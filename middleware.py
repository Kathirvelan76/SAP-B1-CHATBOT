from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import anthropic
import os
import json
import requests
import re
import time
import logging
import threading
import hashlib
from dotenv import load_dotenv
from fastapi.responses import StreamingResponse
from datetime import datetime
from entity_cache import smart_spell_check, refresh_ram_dictionary
from sqlite_cache import init_db, get_cached_sql, save_cached_sql
from conversation_cache import (
    init_conversation_db,
    save_turn,
    get_conversation_history,
    build_context_messages,
    get_last_sql,
    clear_session,
)

init_db()
init_conversation_db()

load_dotenv()

current_date = datetime.now().strftime("%Y-%m-%d")
current_year = datetime.now().strftime("%Y")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Sonnet 5.5 has adaptive thinking ON by default at effort "high", which is where most output tokens go.
# "between_tools" removes up-front thinking (thinking: "disabled" returns a 400 on this model).
# Effort can be tuned from .env: low / medium / high.
EFFORT_SQL = os.getenv("CLAUDE_EFFORT_SQL", "medium")      # calls that write SQL
EFFORT_ANSWER = os.getenv("CLAUDE_EFFORT_ANSWER", "low")   # calls that only write the answer


def llm_options(effort: str) -> dict:
    """Extra request options for Sonnet 5.5 (sent via extra_body so any SDK version accepts them)."""
    if "sonnet-5-5" not in CLAUDE_MODEL:
        return {}
    return {"extra_body": {"thinking": {"type": "between_tools"}, "output_config": {"effort": effort}}}

COMPANY_API_URL = os.getenv("COMPANY_API_URL")
HANA_SCHEMA = os.getenv("HANA_SCHEMA_NAME")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

hana_session = requests.Session()

refresh_ram_dictionary()
app = FastAPI()


@app.on_event("startup")
def startup_event():
    logger.info("Starting background RAM dictionary fetch...")
    thread = threading.Thread(target=refresh_ram_dictionary, daemon=True)
    thread.start()


class AskRequest(BaseModel):
    question: str
    session_id: str = "default"


def generate_session_id(question: str) -> str:
    """Generates a simple session hash. The frontend can also send one."""
    return "default"


def execute_via_company_api(sql_query: str):
    clean_sql = sql_query.replace("```sql", "").replace("```", "").strip()
    check_query = clean_sql.upper()

    if not check_query.startswith("SELECT") or any(
        keyword in check_query
        for keyword in ["DROP ", "DELETE ", "UPDATE ", "INSERT ", "ALTER ", "EXEC ", "CREATE "]
    ):
        return [{"error": "Security Alert: Only SELECT queries are permitted."}]

    try:
        headers = {
            "QIKCHAT-API-KEY": "YOUR_API_KEY",
            "Content-Type": "text/plain",
        }

        response = hana_session.post(
            COMPANY_API_URL,
            headers=headers,
            data=clean_sql.encode("utf-8"),
            timeout=120,
        )

        response.raise_for_status()

        data = response.json()
        if isinstance(data, dict) and any(k.lower() in ["error", "message", "errormessage"] for k in data.keys()):
            return [{"error": str(data)}]
        data_list = data if isinstance(data, list) else data.get("value", data.get("results", []))

        is_aggregate = any(k in check_query for k in ["SUM(", "COUNT(", "GROUP BY"])

        if not is_aggregate and isinstance(data_list, list) and len(data_list) > 100:
            logger.warning(f"Large data dump intercepted: {len(data_list)} rows. Truncating to 100.")
            return {
                "system_message": f"Data was too large ({len(data_list)} rows). Here are the first 100 items.",
                "data": data_list[:100],
            }
        return data_list

    except requests.exceptions.RequestException as e:
        print(f"CONNECTION ERROR: {str(e)}")
        return [{"error": f"API Request Failed: {str(e)}"}]


# ──────────────────────────────────────────────────────────────
#  Business Rules Loader
# ──────────────────────────────────────────────────────────────
RULES_FILE_PATH = os.path.join(os.path.dirname(__file__), "business_rules.md")


def load_business_rules() -> str:
    """Reads business_rules.md to inject into the LLM prompt."""
    try:
        with open(RULES_FILE_PATH, "r", encoding="utf-8") as file:
            return file.read()
    except FileNotFoundError:
        print("Warning: business_rules.md not found. Proceeding without business rules.")
        return ""


def log_field_usage(sql_query: str) -> list[str]:
    custom_fields = list(set(re.findall(r'"?(U_[A-Za-z0-9_]+)"?', sql_query, re.IGNORECASE)))
    if custom_fields:
        logger.info(f"UDFs Detected in SQL: {', '.join(custom_fields)}")
    return custom_fields


def joined_sql(executed):
    """All successful SQL statements of this turn (a question can run several queries in parallel)."""
    return "\n\n".join(q for q, _ in executed) or None


def joined_preview(executed):
    parts = [p for _, p in executed if p]
    return " | ".join(parts)[:2000] if parts else None


def clean_summary(text: str) -> str:
    """Final answer text without the [BUTTON] follow-up lines, for the conversation summary column."""
    lines = [ln for ln in (text or "").split("\n") if "[BUTTON]" not in ln]
    return "\n".join(lines).strip()[:1500]


def compact_rows(data):
    """
    Compact form of a database result for the model: column names once, rows as arrays,
    SAP 6-decimal strings ("19337.000000") turned into plain numbers. Errors and anything
    that is not a list of row dicts are returned unchanged.
    """
    payload, extra = data, {}
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        extra = {k: v for k, v in data.items() if k != "data"}
        payload = data["data"]
    if (
        not isinstance(payload, list)
        or not payload
        or not all(isinstance(r, dict) for r in payload)
        or any("error" in str(k).lower() for r in payload for k in r)
    ):
        return data

    cols = list(payload[0].keys())

    def clean(v):
        if v is None:
            return ""
        if isinstance(v, str) and re.fullmatch(r"-?\d+\.\d{6}", v):
            t = v.rstrip("0").rstrip(".")
            return int(t) if "." not in t else float(t)
        return v

    out = {"columns": cols, "rows": [[clean(r.get(c)) for c in cols] for r in payload], "row_count": len(payload)}
    out.update(extra)
    return out


def to_model_json(data) -> str:
    """Compact JSON text (no spaces) sent to the model."""
    return json.dumps(compact_rows(data), ensure_ascii=False, separators=(",", ":"), default=str)


def make_result_preview(raw_data, max_rows: int = 10, max_chars: int = 1200):
    """
    Compact JSON of the first rows returned by the database. Stored with the turn so follow-up
    questions can use keys such as ItemCode, CardCode and DocEntry without re-running the query.
    """
    rows = raw_data.get("data") if isinstance(raw_data, dict) else raw_data
    if not isinstance(rows, list) or not rows:
        return None
    text = to_model_json(rows[:max_rows])
    return text if len(text) <= max_chars else text[:max_chars] + "..."


# ──────────────────────────────────────────────────────────────
#  Terminal SQL Logger
# ──────────────────────────────────────────────────────────────
def log_sql_to_terminal(sql: str, source: str = "AI Generated"):
    """Prints the SQL query prominently in the terminal."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print("\n" + "=" * 60)
    print(f"  [{timestamp}] SQL QUERY ({source})")
    print("=" * 60)
    print(sql)
    print("-" * 60 + "\n")


# ──────────────────────────────────────────────────────────────
#  API Endpoints
# ──────────────────────────────────────────────────────────────
@app.post("/api/v1/clear_cache")
def clear_schema_cache():
    try:
        logger.info("Manual schema cache refresh triggered via UI.")
        thread = threading.Thread(target=refresh_ram_dictionary, daemon=True)
        thread.start()
        return {"status": "success", "message": "Cache refresh started in background."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class ClearConversationRequest(BaseModel):
    session_id: str = "default"


@app.post("/api/v1/clear_conversation")
def clear_conversation_history(request: ClearConversationRequest):
    """Clears conversation cache on sign-out so the next session starts fresh."""
    try:
        clear_session(request.session_id)
        logger.info(f"Conversation history cleared for session: {request.session_id}")
        return {"status": "success", "message": "Conversation history cleared."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/ask")
def ask_copilot(request: AskRequest):
    def generate_stream():
        start_time = time.time()
        current_date = datetime.now().strftime("%Y-%m-%d")
        normalized_q = request.question.strip().lower()
        session_id = request.session_id or "default"

        total_in_tokens = 0
        total_out_tokens = 0
        

        try:
            
            # ==========================================
            # PHASE 1: AI GENERATION FLOW
            # ==========================================
            business_rules = load_business_rules()

            system_prompt = f"""You are an SAP Business One AI Assistant.

IDENTITY
You are a business data assistant for SAP Business One. You help users by answering questions.
DATA QUESTIONS (Administration, Financials, CRM, Opportunities, Sales - A/R, Purchasing - A/P, Business Partners, Banking, Inventory, Resources, Production, MRP, Service, Human Resources, Project Management, Reports, etc.): Generate a SQL query, execute it, and summarize the results in business language.

TODAY'S DATE: {current_date}
CURRENT YEAR: {current_year}
DATABASE SCHEMA: {HANA_SCHEMA}

BUSINESS RULES (authoritative, follow literally):
These rules describe this company's data, custom fields, definitions and relationships. They are authoritative and override general SAP knowledge. Follow them literally.
{business_rules}

HOW TO USE THE BUSINESS RULES AND SAP KNOWLEDGE
- Authority order: (1) the business rules above (custom fields, company definitions, join paths and the STANDARD SAP B1 REFERENCE) always win. (2) For standard tables not listed there, use your SAP B1 knowledge, but only tables and columns you are certain exist.
- Never invent a table, column, custom field or join. If you are not sure a column exists, write a simpler query that avoids it, or ask one focused question. There is no metadata tool.
- Use a custom field only when the question needs it for a filter, condition, grouping or classification. A default named in the rules only decides which field to use once one is needed.
- If something required is not covered, or the rules conflict, say so or ask one focused question. Never guess.

SAP B1 ARCHITECTURE PRINCIPLES
- Respect SAP B1 table separation: always join the relevant master and transaction tables properly instead of assuming all requested fields exist on a single header table.
- Follow SAP B1 document flow: when a question spans linked documents, join the related tables directly rather than relying on header default fields.
- Self-verify results: after executing SQL, inspect the returned JSON. If a query errors or a key requested field is NULL/empty, automatically run a corrected query using the appropriate linked SAP B1 table before answering.

QUERY PLANNING (think internally, never print)
1. Type: METRIC (sales, purchases, stock, counts, totals, trends) or LOOKUP (a specific document, item, vendor, customer, barcode, contact, latest or first record, details).
2. Documents: map the user's words using WORD MEANINGS below.
3. Tables and joins: take them only from the JOIN MAP and the STANDARD SAP B1 REFERENCE in the business rules. Join only what the question needs. A header joins to its own lines on "DocEntry". Never join the lines of two different documents to each other, and never join OITB directly to a line table.
4. Filters: dates, "CANCELED" = 'N', entity keys, and a custom field only if the question needs it.
5. Follow-up? Apply the follow-up rules below.
6. Check before executing: every table, column and join comes from the business rules or is certain; no join can duplicate amounts; dates, cancellation and filters are identical on every part of the query.
Priority: Accuracy > Simplicity > Performance.

WORD MEANINGS (use these defaults, do not ask)
- bought / purchased = A/P invoice (OPCH/PCH1). ordered = purchase order (OPOR/POR1). received = goods receipt PO (OPDN/PDN1). sold = A/R invoice (OINV/INV1).
- vendor / supplier = OCRD with "CardType" = 'S'. customer = OCRD with "CardType" = 'C'.
- last / latest = ORDER BY "DocDate" DESC, "DocEntry" DESC with LIMIT 1 (or the number asked). first / earliest = ASC.
- Dates with slashes are DD/MM/YYYY (11/10/2026 = 11 October 2026). Convert them to 'YYYYMMDD'. A single date with no range means "DocDate" = that day.

METRIC vs LOOKUP
- METRIC (sales, purchases, stock): follow the invoice-minus-return pattern and amount rules in the business rules.
- LOOKUP: do not net returns. Query the relevant document or master table directly, with "CANCELED" = 'N' on document headers. Return the requested rows, not a grand total.
- Count documents with COUNT(DISTINCT "DocEntry"). Identify documents by "DocEntry" and show "DocNum" to the user.

MINIMAL COLUMNS (applies to every query)
- SELECT only the columns the answer needs. Do not add columns "for context": status codes, totals, dates, party codes or names, extra amounts or line details, unless the question asks for them or they are needed to compute the answer.
- Identifier columns for follow-ups are allowed in addition, and nothing else: a document's "DocNum" and "DocEntry"; an item's "ItemCode"; a vendor's or customer's "CardCode" only when the question is about a specific vendor or customer or the answer lists them.
- Compute in SQL instead of returning raw material: CASE for a status text (for example 'Paid' / 'Outstanding'), SUM or COUNT for totals and counts, and the outstanding amount instead of its component amounts when only the outstanding is asked.
- Return the fewest rows needed. Counts and totals return aggregates, not documents.
- Example: "which POs created on 11 May are fully paid and which are outstanding" needs the PO number ("DocNum"), "DocEntry", the PO total, the outstanding amount and a status text. It does not need the vendor, the PO status code, the invoiced total or the paid amount.
- Do not mention identifier columns in the answer unless useful.

CONVERSATIONAL MEMORY & FOLLOW-UP RULES (CRITICAL)
- Earlier turns are in the messages. Each earlier answer shows the SQL used, the key rows the database returned, and the answer given. Read them before writing any SQL.
- Words such as "that item", "it", "its", "that vendor", "the same", "them", "that invoice" refer to the entities in the most recent relevant earlier answer. Take their keys ("ItemCode", "CardCode", "DocEntry") from the key rows or the SQL used, and filter by KEY, never by name. Do not call search_dictionary again for an entity that was already resolved.
- A follow-up such as barcode, vendor details, payment details or items on that invoice is a NEW query on the right table filtered by that key. Do not re-run the earlier query unless asked.
- Keep earlier filters (period, branch, brand, category) unless the user changes them.
- If the reference could mean several earlier results, call request_user_clarification with the options. If the earlier result was empty, say so and do not invent an entity.

SYNTAX
1. Write SAP HANA SQL. Double-quote all table and column names. Use aliases T0, T1, T2...
2. Output ONLY a SELECT statement. No comments, no markdown, no data-changing statements.
3. Multi-line format: SELECT, FROM, JOIN, WHERE, GROUP BY, ORDER BY on separate lines.
4. No SELECT *. Name every column with a meaningful alias.
5. ONE query per part of the question. Use joins, subqueries or derived tables as needed. If the question has independent parts (for example a total and a top 3 breakdown), call execute_hana_sql once per part in the same response.

DATE HANDLING
6. Use "DocDate" for date filters unless the question implies another date column.
7. Write dates as 'YYYYMMDD' format (e.g., '20261120'). Filter with "DocDate" >= start AND "DocDate" <= end.
8. METRIC questions with no period given → current year to date (LOOKUP questions such as "last" or "latest" with no date get NO date filter): "DocDate" >= '{current_year}0101' AND "DocDate" <= CURRENT_DATE
9. "Today" → "DocDate" = CURRENT_DATE
10. "Last N days" → "DocDate" >= ADD_DAYS(CURRENT_DATE, -N) AND "DocDate" <= CURRENT_DATE
11. Month/quarter/year/festival → compute exact first and last day as 'YYYYMMDD' from today's date.
12. YEAR() and MONTH() are allowed in SELECT and GROUP BY for trends, but NOT in WHERE clauses.

AGGREGATION
13. For METRIC questions return a single grand total row by default. LOOKUP questions return the requested rows.
14. Use GROUP BY only when the user asks for a breakdown ("by", "wise", "each", "top N", "trend", "compare").
15. Never ask the user how to group.
16. Use COALESCE for NULLs and NULLIF to avoid division by zero.
17. Detailed or document-level queries: add LIMIT 100 (or the smaller number the user asked for) unless the user asks for everything.
18. Never let a join duplicate amounts or quantities.

DICTIONARY LOOKUP
19. Never guess database values (brands, branches, categories, items, sizes, states, colors, vendors, customers).
20. Call search_dictionary with an array of likely synonyms/abbreviations.
21. "exact_match" or "corrected" → use that value. "ambiguous" → call request_user_clarification with options.
22. Branch/warehouse names from search_dictionary are ALWAYS OWHS."WhsName", never "WhsCode".
23. After a clarification, keep every original filter.
24. Festival or date-period comparisons: filter by "DocDate" only. Do NOT search the dictionary for the festival name.
25. Vendor or customer names: after search_dictionary, join OCRD and filter on the exact "CardName" with the right "CardType" (see the business rules). Use "CardCode" for every later step.

EXECUTION RULES
26. Never claim a query ran or state any figure unless the tool returned data. Never fabricate results.
27. On error, read it. If the cause is identifiable, fix the SQL and retry (max 2 retries). Never resend the same failing query. If unresolved, explain the limitation in business language.

RESPONSE FORMAT

RESPONSE STYLE: Answer the user's question directly in simple, clear sentences. Do NOT write long summaries or elaborate reports.

FOR DATA ANSWERS (after successful SQL execution):
- State the answer in 1-2 simple sentences with the number and period (e.g., "Total sales for October 2026 were ₹12.5 L (₹12,50,000).").
- For breakdowns: show a compact Markdown table (name, value, % share). Max 10 rows; mention how many more exist.
- Keep it short and to the point. No lengthy analysis, no "snapshot", no "worth a look" sections.

FOR LOOKUPS (a specific item, vendor, document, barcode, details):
- Answer directly in 1-3 sentences or a small table (for example item name, quantity, date, vendor). No headline or analysis sections.

FOR GENERAL SAP B1 QUESTIONS:
- Answer clearly in 2-4 simple sentences. Use bullet points only if listing steps or multiple items.

FORMATTING RULES (all answers):
- Currency in ₹. Large amounts in K, L, or Cr with full Indian-grouped value in brackets (e.g., ₹12.5 L (₹12,50,000)).
- Call tax-inclusive figures "Sales" or "Total Sales". Use "Net Sales" only if user asked for without-tax.
- Never explain the SQL, tables, or calculation methodology.
- Never show raw column names or table names.
- Use only numbers from actual results. Never invent comparisons, growth, or causes.
- End with exactly 3 follow-up questions that are natural next steps for this answer (for example barcode, vendor details, payment details), each on a new line starting with '[BUTTON]'.
"""
            cached_system = [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"}
                }
            ]

            # ==========================================
            # PHASE 1: SQLITE CACHE CHECK
            # (Only check static cache if there is NO prior conversation context,
            # so follow-up questions always take conversation history into account!)
            # ==========================================
            conversation_history = get_conversation_history(session_id)
            cached_sql = get_cached_sql(normalized_q) if not conversation_history else None

            if cached_sql:
                logger.info("🚀 SQLite Cache Hit! Skipping SQL Generation.")

                yield json.dumps({
                    "type": "metadata",
                    "sql": cached_sql,
                    "tables": ["Served from SQLite Cache"],
                    "udfs": log_field_usage(cached_sql)
                }) + "\n"

                db_start_time = time.time()
                raw_data = execute_via_company_api(cached_sql)
                cache_db_exec_sec = round(time.time() - db_start_time, 2)
                cache_preview = make_result_preview(raw_data)

                cache_prompt = f"""Here is the database JSON: {to_model_json(raw_data)}
                If it is empty ([]), reply exactly with 'No records found for this criteria.' and stop.
                Otherwise answer the user's question following the RESPONSE FORMAT rules in your instructions."""

                messages = [
                    {"role": "user", "content": request.question},
                    {"role": "assistant", "content": f"I have run this SQL query: {cached_sql}"},
                    {"role": "user", "content": cache_prompt}
                ]

                summary_start_time = time.time()
                full_cached_resp = ""
                with client.messages.stream(
                    model=CLAUDE_MODEL,
                    max_tokens=4000,
                    system=cached_system,
                    messages=messages,
                    **llm_options(EFFORT_ANSWER)
                ) as stream:
                    for text in stream.text_stream:
                        full_cached_resp += text
                        yield json.dumps({"type": "chunk", "text": text}) + "\n"

                # Persist turn to conversation cache
                save_turn(session_id, "user", request.question)
                save_turn(
                    session_id, "assistant", full_cached_resp[:600],
                    sql_query=cached_sql,
                    summary=clean_summary(full_cached_resp),
                    result_preview=cache_preview,
                )

                execution_time = round(time.time() - start_time, 2)
                summary_generation_time = round(time.time() - summary_start_time, 2)
                yield json.dumps({
                    "type": "metrics",
                    "time_seconds": execution_time,
                    "sql_gen_sec": 0.0,
                    "db_exec_sec": cache_db_exec_sec,
                    "summary_sec": summary_generation_time,
                    "input_tokens": stream.get_final_message().usage.input_tokens,
                    "output_tokens": stream.get_final_message().usage.output_tokens
                }) + "\n"
                return

            # ==========================================
            # PHASE 2: STANDARD GENERATION FLOW
            # ==========================================
            tools = [
                {
                    "name": "execute_hana_sql",
                    "description": "Executes a HANA SQL query via the company API.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"sql_query": {"type": "string"}},
                        "required": ["sql_query"]
                    }
                },
                {
                    "name": "search_dictionary",
                    "description": "Spell-checks and verifies brands, branches, categories, items, sizes, states, colors, accounts, vendors and customers against the SAP database RAM cache.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "entity_type": {
                                "type": "string",
                                "enum": ["brand", "branch", "category", "item", "size", "state", "color", "account", "vendor", "customer"],
                                "description": "The type of entity you are looking for."
                            },
                            "search_terms": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "An array of search terms. Provide up to 4 likely database synonyms, abbreviations, or state codes."
                            }
                        },
                        "required": ["entity_type", "search_terms"]
                    }
                },
                {
                    "name": "request_user_clarification",
                    "description": "Use ONLY if a dictionary search returned multiple ambiguous matches, or a follow-up reference such as 'that item' could mean several earlier results. Do NOT use if the user's intent is clear.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "message": {"type": "string", "description": "Short question asking the user to pick one."},
                            "options": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "The exact database IDs or names for the user to click."
                            }
                        },
                        "required": ["message", "options"]
                    }
                }
            ]

            # Build messages WITH full prior conversation context for continuous conversation flow
            messages = build_context_messages(session_id, request.question)

            max_loops = 6
            last_result_preview = None
            executed = []
            loop_count = 0
            final_analytical_sql = None
            is_analytical_run = False
            sql_generation_time = 0.0
            db_execution_time = 0.0

            while loop_count < max_loops:
                sql_start_time = time.time()
                response = client.messages.create(
                    model=CLAUDE_MODEL,
                    max_tokens=4000,
                    system=cached_system,
                    tools=tools,
                    messages=messages,
                    **llm_options(EFFORT_SQL)
                )
                sql_generation_time += round(time.time() - sql_start_time, 2)

                total_in_tokens += response.usage.input_tokens
                total_out_tokens += response.usage.output_tokens

                clean_content = [block for block in response.content if block.type != "thinking"]
                messages.append({"role": "assistant", "content": clean_content})

                if response.stop_reason == "tool_use":
                    tool_results_list = []

                    for block in response.content:
                        if block.type == "tool_use":
                            if block.name == "request_user_clarification":
                                yield json.dumps({
                                    "type": "clarification_menu",
                                    "message": block.input.get("message", "Please clarify your request:"),
                                    "options": block.input.get("options", [])
                                }) + "\n"

                                execution_time = round(time.time() - start_time, 2)
                                yield json.dumps({
                                    "type": "metrics",
                                    "time_seconds": execution_time,
                                    "sql_gen_sec": sql_generation_time,
                                    "db_exec_sec": db_execution_time,
                                    "summary_sec": 0.0,
                                    "input_tokens": total_in_tokens,
                                    "output_tokens": total_out_tokens
                                }) + "\n"
                                return

                            elif block.name == "search_dictionary":
                                ent_type = block.input.get("entity_type")
                                s_terms = block.input.get("search_terms")
                                dictionary_result = smart_spell_check(ent_type, s_terms)

                                tool_results_list.append({
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": json.dumps(dictionary_result)
                                })

                            elif block.name == "execute_hana_sql":
                                generated_sql = block.input.get("sql_query", "")
                                sql_upper = generated_sql.upper()
                                is_discovery = "LIKE" in sql_upper and "JOIN" not in sql_upper and "SUM(" not in sql_upper

                                db_start_time = time.time()
                                raw_data = execute_via_company_api(generated_sql)
                                print("\n--- RAW HANA JSON PAYLOAD ---")
                                print(raw_data)
                                print("-----------------------------\n")
                                db_execution_time += round(time.time() - db_start_time, 2)

                                raw_str = json.dumps(raw_data).lower()
                                has_error = any(
                                    err in raw_str
                                    for err in ['"error"', '"errormessage"', '"message":', 'invalid column', 'sql syntax', 'api request failed']
                                )

                                if not is_discovery and not has_error:
                                    is_analytical_run = True
                                    final_analytical_sql = generated_sql
                                    last_result_preview = make_result_preview(raw_data)
                                    executed.append((generated_sql, last_result_preview))
                                    yield json.dumps({
                                        "type": "metadata",
                                        "sql": joined_sql(executed),
                                        "tables": ["Automatically Routed"],
                                        "udfs": log_field_usage(generated_sql)
                                    }) + "\n"

                                tool_results_list.append({
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": to_model_json(raw_data)
                                })

                    # Always feed tool results back so Claude can verify data or self-correct
                    messages.append({"role": "user", "content": tool_results_list})
                    loop_count += 1
                else:
                    if final_analytical_sql and len(executed) == 1:
                        save_cached_sql(normalized_q, final_analytical_sql)
                        logger.info("Saved new query to SQLite Cache.")

                    response_text = ""
                    if any(b.type == "text" for b in response.content):
                        response_text = "".join(b.text for b in response.content if b.type == "text")
                        yield json.dumps({"type": "chunk", "text": response_text}) + "\n"

                    # Save turns into conversation cache so future follow-up questions retain context
                    save_turn(session_id, "user", request.question)
                    save_turn(
                        session_id, "assistant", response_text[:600],
                        sql_query=joined_sql(executed),
                        summary=clean_summary(response_text),
                        result_preview=joined_preview(executed),
                    )

                    execution_time = round(time.time() - start_time, 2)
                    yield json.dumps({
                        "type": "metrics",
                        "time_seconds": execution_time,
                        "sql_gen_sec": sql_generation_time,
                        "db_exec_sec": db_execution_time,
                        "summary_sec": 0.0,
                        "input_tokens": total_in_tokens,
                        "output_tokens": total_out_tokens
                    }) + "\n"
                    return

            # ==========================================
            # PHASE 3: FALLBACK IF MAX LOOPS REACHED
            # ==========================================
            if not final_analytical_sql and not is_analytical_run:
                fallback_msg = "I tried to find the data but encountered an error or too many ambiguous matches. Please rephrase or be more specific."
                yield json.dumps({
                    "type": "chunk",
                    "text": fallback_msg
                }) + "\n"
                save_turn(session_id, "user", request.question)
                save_turn(session_id, "assistant", fallback_msg)
                execution_time = round(time.time() - start_time, 2)
                yield json.dumps({
                    "type": "metrics",
                    "time_seconds": execution_time,
                    "sql_gen_sec": sql_generation_time,
                    "db_exec_sec": db_execution_time,
                    "summary_sec": 0.0,
                    "input_tokens": total_in_tokens,
                    "output_tokens": total_out_tokens
                }) + "\n"
                return

            if final_analytical_sql and len(executed) == 1:
                save_cached_sql(normalized_q, final_analytical_sql)
                logger.info("Saved new query to SQLite Cache.")

            summary_start_time = time.time()
            full_final_resp = ""
            with client.messages.stream(
                model=CLAUDE_MODEL,
                max_tokens=4000,
                system=cached_system,
                messages=messages,
                **llm_options(EFFORT_ANSWER)
            ) as stream:
                for text in stream.text_stream:
                    full_final_resp += text
                    yield json.dumps({"type": "chunk", "text": text}) + "\n"

            # Save completed analytical turn to conversation cache
            save_turn(session_id, "user", request.question)
            save_turn(
                session_id, "assistant", full_final_resp[:600],
                sql_query=joined_sql(executed),
                summary=clean_summary(full_final_resp),
                result_preview=joined_preview(executed),
            )

            summary_generation_time = round(time.time() - summary_start_time, 2)
            execution_time = round(time.time() - start_time, 2)

            yield json.dumps({
                "type": "metrics",
                "time_seconds": execution_time,
                "sql_gen_sec": sql_generation_time,
                "db_exec_sec": db_execution_time,
                "summary_sec": summary_generation_time,
                "input_tokens": total_in_tokens + stream.get_final_message().usage.input_tokens,
                "output_tokens": total_out_tokens + stream.get_final_message().usage.output_tokens
            }) + "\n"

        except Exception as e:
            logger.error(f"System Error: {str(e)}")
            yield json.dumps({"type": "error", "text": f"System Error: {str(e)}"}) + "\n"

    return StreamingResponse(generate_stream(), media_type="application/x-ndjson")