"""
Conversation Cache for SAP B1 AI Assistant
-------------------------------------------
Stores per-session conversation history so Claude can follow the user's
continuous interaction flow. All turns are kept until the user signs out,
which triggers clear_session() to wipe the history.

Each assistant turn stores:
  - content         : the answer text (kept as before, for backward compatibility)
  - sql_query       : the SQL that produced the answer
  - summary         : the model's final summary-style answer (follow-up buttons removed)
  - result_preview  : the first rows returned by the database (JSON text), so follow-ups
                      like "barcode of that item" can use ItemCode / CardCode / DocEntry

Storage: SQLite (same DB as query cache). No auto-expiry, cleared on sign-out only.
"""

import sqlite3
import time
import logging

logger = logging.getLogger(__name__)

DB_PATH = "copilot_cache.db"

# ── Context size controls (keeps the token cost of long chats under control) ──
RECENT_TURNS_WITH_DETAIL = 3     # last N answers include SQL + data preview + summary
SQL_MAX_CHARS = 2400
PREVIEW_MAX_CHARS = 2000
RECENT_SUMMARY_MAX_CHARS = 900
OLD_SUMMARY_MAX_CHARS = 300      # older answers are reduced to a short summary


def _ensure_column(cursor, table: str, column: str, ddl: str):
    """Adds a column to an existing table if it is missing (safe migration)."""
    cursor.execute(f"PRAGMA table_info({table})")
    existing = [row[1] for row in cursor.fetchall()]
    if column not in existing:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        logger.info(f"Added column {column} to {table}")


def init_conversation_db():
    """Creates the conversation history table and adds new columns to older databases."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Conversation_History (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            sql_query TEXT DEFAULT NULL,
            summary TEXT DEFAULT NULL,
            result_preview TEXT DEFAULT NULL,
            created_at REAL NOT NULL
        )
    """)
    # Migration for databases created before these columns existed
    _ensure_column(cursor, "Conversation_History", "summary", "TEXT DEFAULT NULL")
    _ensure_column(cursor, "Conversation_History", "result_preview", "TEXT DEFAULT NULL")
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_session_id
        ON Conversation_History(session_id)
    """)
    conn.commit()
    conn.close()


def save_turn(
    session_id: str,
    role: str,
    content: str,
    sql_query: str = None,
    summary: str = None,
    result_preview: str = None,
):
    """Saves a single conversation turn. All turns are kept until sign-out."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO Conversation_History
            (session_id, role, content, sql_query, summary, result_preview, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (session_id, role, content, sql_query, summary, result_preview, time.time()))
    conn.commit()
    conn.close()


def get_conversation_history(session_id: str) -> list[dict]:
    """
    Returns the full conversation history for a session, oldest first, as dicts with
    role, content, sql_query, summary and result_preview.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT role, content, sql_query, summary, result_preview
        FROM Conversation_History
        WHERE session_id = ?
        ORDER BY created_at ASC, id ASC
    """, (session_id,))
    rows = cursor.fetchall()
    conn.close()

    return [
        {
            "role": r[0],
            "content": r[1],
            "sql_query": r[2],
            "summary": r[3],
            "result_preview": r[4],
        }
        for r in rows
    ]


def get_last_sql(session_id: str) -> str | None:
    """Returns the most recent SQL query from this session, or None."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sql_query FROM Conversation_History
        WHERE session_id = ? AND sql_query IS NOT NULL
        ORDER BY created_at DESC, id DESC
        LIMIT 1
    """, (session_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None


def clear_session(session_id: str):
    """Clears all conversation history for a session."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM Conversation_History WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()
    logger.info(f"Cleared conversation history for session: {session_id}")


def _clip(text: str | None, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def build_context_messages(session_id: str, current_question: str) -> list[dict]:
    """
    Builds the messages array for Claude.

    - The last RECENT_TURNS_WITH_DETAIL answers carry the SQL used, the first rows the
      database returned (so keys like ItemCode / CardCode / DocEntry are available for
      follow-ups) and the summary answer.
    - Older answers are reduced to a short summary to save tokens.
    - The current question is always last.
    """
    history = get_conversation_history(session_id)

    assistant_positions = [i for i, t in enumerate(history) if t["role"] == "assistant"]
    recent_positions = set(assistant_positions[-RECENT_TURNS_WITH_DETAIL:])

    messages = []
    for i, turn in enumerate(history):
        if turn["role"] != "assistant":
            messages.append({"role": "user", "content": turn["content"]})
            continue

        # Prefer the full summary column; fall back to content for rows saved before the migration
        answer = turn.get("summary") or turn["content"]

        if i in recent_positions:
            parts = []
            if turn.get("sql_query"):
                parts.append("SQL used:\n" + _clip(turn["sql_query"], SQL_MAX_CHARS))
            if turn.get("result_preview"):
                parts.append("Key rows returned (first rows, JSON):\n" + _clip(turn["result_preview"], PREVIEW_MAX_CHARS))
            parts.append("Answer given:\n" + _clip(answer, RECENT_SUMMARY_MAX_CHARS))
            text = "\n\n".join(parts)
        else:
            text = "Answer given: " + _clip(answer, OLD_SUMMARY_MAX_CHARS)

        messages.append({"role": "assistant", "content": text})

    messages.append({"role": "user", "content": current_question})
    return messages