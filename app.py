import streamlit as st
import requests
import os
from dotenv import load_dotenv
import json
import uuid
from datetime import datetime, timedelta
import holidays

load_dotenv()
MIDDLEWARE_BASE_URL = os.getenv("MIDDLEWARE_BASE_URL", "http://localhost:8000")
VALID_USER = os.getenv("sap_sign_in_user")
VALID_PASS = os.getenv("sap_sign_log_password")

st.set_page_config(page_title="SAP B1 Copilot", layout="centered")

# --- Auth ---
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "login_attempts" not in st.session_state:
    st.session_state.login_attempts = 0
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

if not st.session_state.authenticated:
    st.title("🔐 SAP B1 Endpoint Login")
    
    if st.session_state.login_attempts >= 3:
        st.error("Account locked due to 3 failed attempts. Please contact administrator.")
        st.stop()
        
    with st.form("login"):
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        
        if st.form_submit_button("Sign In"):
            if u == VALID_USER and p == VALID_PASS:
                st.session_state.authenticated = True
                st.session_state.login_attempts = 0  
                st.rerun()
            else:
                st.session_state.login_attempts += 1
                if st.session_state.login_attempts >= 3:
                    st.error("Account locked due to 3 failed attempts. Please contact administrator.")
                else:
                    st.error(f"Invalid credentials. Attempt {st.session_state.login_attempts} of 3.")
    st.stop()

# --- App UI ---
st.title("💬 SAP Business One Copilot")

def handle_logout():
    """Clears conversation cache on the backend, then resets local session."""
    try:
        requests.post(f"{MIDDLEWARE_BASE_URL}/api/v1/clear_conversation", json={"session_id": st.session_state.session_id}, timeout=5)
    except Exception:
        pass
    st.session_state.update(authenticated=False, login_attempts=0, messages=[], session_id=str(uuid.uuid4()))

st.sidebar.button("Logout", on_click=handle_logout)


st.sidebar.divider()
st.sidebar.markdown("### 🛠️ Admin Controls")
if st.sidebar.button("🔄 Refresh Schema Cache"):
 #   with st.spinner("Wiping server memory..."):
        try:
            res = requests.post(f"{MIDDLEWARE_BASE_URL}/api/v1/clear_cache")
            res.raise_for_status()
            st.sidebar.success("Cache cleared! New custom fields will be detected.")
        except requests.exceptions.RequestException as e:
            st.sidebar.error(f"Failed to clear cache: {e}")

st.sidebar.divider()
@st.cache_data
def load_festival_map():
    current_year = datetime.now().year
    dynamic_years = list(range(current_year - 2, current_year + 1))
    states = [
        "TN", "KA", "MH", "DL", "GJ", "UP", "RJ", "WB", "PB",
        "HR", "JK", "CH", "TG", "AP", "KL", "OD", "MP", "BR"
    ]

    in_holidays = holidays.India(years=dynamic_years)
    for state in states:
        try:
            in_holidays.update(holidays.India(years=dynamic_years, subdiv=state))
        except NotImplementedError:
            pass

    f_map = {}
    for dt, names in sorted(in_holidays.items()):
        for name in names.split("; "):
            f_map.setdefault(name, set()).add(dt)

    return {name: sorted(dates) for name, dates in f_map.items()}

# Ensure chat history exists before sidebar buttons append to it
if "messages" not in st.session_state:
    st.session_state.messages = []

festival_map = load_festival_map()

with st.sidebar:
    st.markdown("### 🎉 Festival Analysis")
    selected_festival = st.selectbox("Select Festival", sorted(festival_map.keys()))

    dates = festival_map[selected_festival]
    selected_date = st.selectbox(
        "Select Year",
        dates,
        index=len(dates) - 1,
        format_func=lambda d: f"{d.year} ({d})"
    )

    col_before, col_after = st.columns(2)
    with col_before:
        days_before = st.number_input("Days before", min_value=0, max_value=31, value=0)
    with col_after:
        days_after = st.number_input("Days after", min_value=0, max_value=31, value=0)

    start_dt = selected_date - timedelta(days=days_before)
    end_dt = selected_date + timedelta(days=days_after)
    st.caption(f"Range: {start_dt} to {end_dt}")

    if st.button("Get Festival Sales", use_container_width=True):
        question = f"Show total sales for {selected_festival} {selected_date.year} from {start_dt} to {end_dt}."
        st.session_state.messages.append({"role": "user", "content": question})
        st.rerun()


#st.sidebar.markdown("### Architecture Flow\n1. AI natively routes intent to standard tables.\n2. Fetch exact standard & custom schema dynamically.\n3. Generate hallucination-free SQL.\n4. Analyze live database JSON.")

# --- UI Helper ---
def render_assistant_content(m, is_latest=True):
    if m.get("is_clarification"):
        st.warning(m["content"])
    else:
        if m.get("sql"):
            # FIX: Prevents the Streamlit "Shadow" glitch by removing nested expanders
            if is_latest:
                with st.expander("🔍 View AI Generated SQL & Routing"):
                    st.write(f"**Tables Routed:** {', '.join(m.get('tables', []))}")
                    st.code(m["sql"], language="sql")
                    if m.get("udfs"):
                        st.write(f"**Custom UDFs Interacted:** {', '.join(m['udfs'])}")
                    else:
                        st.write("**Custom UDFs Interacted:** None")
            else:
                st.markdown("**🔍 AI Generated SQL & Routing:**")
                st.code(m["sql"], language="sql")
        
        st.markdown(f"### 📊 Business Insight:\n{m['content']}")
        
        if m.get("time_seconds"):
            st.divider()
            col1, col2, col3 = st.columns(3)
            col1.metric("Execution Time", f"{m['time_seconds']} sec")
            col2.metric("Input Tokens", m.get("input_tokens", 0))
            col3.metric("Output Tokens", m.get("output_tokens", 0))

# --- Chat Logic ---
if "messages" not in st.session_state:
    st.session_state.messages = []

for i, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"]):
        is_latest = (i == len(st.session_state.messages) - 1)
        
        if msg["role"] == "assistant" and not is_latest:
            with st.expander("Show Previous Response (SQL & Insight)", expanded=False):
                render_assistant_content(msg, is_latest=False)
        else:
            if msg["role"] == "assistant":
                render_assistant_content(msg, is_latest=True)
            else:
                st.write(msg["content"])
        
        if is_latest and msg["role"] == "assistant":
            if msg.get("is_clarification"):
                cols = st.columns(len(msg.get("options", [])))
                for idx, opt in enumerate(msg.get("options", [])):
                    if cols[idx].button(opt, key=f"clarify_{i}_{idx}"):
                        original_query = st.session_state.messages[-2]["content"]
                        st.session_state.messages.append({"role": "user", "content": f"{original_query} (Use exactly: {opt})"})
                        st.rerun()
                        
            elif msg.get("follow_ups"):
                st.write("**Suggested Follow-ups:**")
                for idx, q in enumerate(msg["follow_ups"]):
                    if st.button(q, key=f"followup_{i}_{idx}"):
                        st.session_state.messages.append({"role": "user", "content": q})
                        st.rerun()

prompt = st.chat_input("Ask about sales, stock, HR, or performance...")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.rerun() 

if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
    user_input = st.session_state.messages[-1]["content"]
    
    with st.chat_message("assistant"):
        sql_placeholder = st.empty()
        insight_placeholder = st.empty()
        metrics_placeholder = st.empty()
        
        full_response = ""
        is_clarification = False
        options = []
        captured_sql = None
        captured_tables = []
        captured_udfs = []
        captured_time = None
        captured_in_tokens = None
        captured_out_tokens = None
        has_backend_error = False 
        
        with st.spinner("Analyzing intent and generating SQL..."):
            try:
                res = requests.post(f"{MIDDLEWARE_BASE_URL}/api/v1/ask", json={"question": user_input, "session_id": st.session_state.session_id}, stream=True, timeout=120)
                res.raise_for_status()
                
                for line in res.iter_lines():
                    if line:
                        try:
                            # Safely attempt to parse the JSON
                            chunk = json.loads(line.decode("utf-8"))
                        except json.JSONDecodeError:
                            # If the server sends bad data (like an HTML error page), skip it or break
                            has_backend_error = True
                            st.error("Received an invalid response format from the server.")
                            break
                        
                        if chunk["type"] == "metadata":
                            captured_sql = chunk.get("sql")
                            captured_tables = chunk.get("tables", [])
                            captured_udfs = chunk.get("udfs", [])
                            with sql_placeholder.expander("🔍 View AI Generated SQL & Routing"):
                                st.write(f"**Tables Routed:** {', '.join(captured_tables)}")
                                st.code(captured_sql, language="sql")
                                if captured_udfs:
                                    st.write(f"**Custom UDFs Interacted:** {', '.join(captured_udfs)}")
                                else:
                                    st.write("**Custom UDFs Interacted:** None")
                                    
                        elif chunk["type"] == "clarification_menu":
                            is_clarification = True
                            full_response = chunk.get("message", "Please clarify:")
                            options = chunk.get("options", [])
                            insight_placeholder.warning(full_response)
                            break 
                            
                        elif chunk["type"] == "chunk":
                            full_response += chunk["text"]
                            insight_placeholder.markdown(f"### 📊 Business Insight:\n{full_response}▌")
                            
                        elif chunk["type"] == "metrics":
                            captured_time = chunk.get("time_seconds")
                            captured_in_tokens = chunk.get("input_tokens")
                            captured_out_tokens = chunk.get("output_tokens")
                            with metrics_placeholder.container():
                                st.divider()
                                col1, col2, col3 = st.columns(3)
                                col1.metric("Execution Time", f"{captured_time} sec")
                                col2.metric("Input Tokens", captured_in_tokens)
                                col3.metric("Output Tokens", captured_out_tokens)
                                
                        elif chunk["type"] == "error":
                            st.error(chunk["text"])
                            has_backend_error = True
                            break 

                if has_backend_error:
                    st.stop()

                follow_ups = []
                if not is_clarification:
                    raw_lines = full_response.split("\n")
                    clean_lines = []
                    for line in raw_lines:
                        if "[BUTTON]" in line:
                            follow_ups.append(line.replace("[BUTTON]", "").strip())
                        else:
                            clean_lines.append(line)
                            
                    full_response = "\n".join(clean_lines).strip()
                    insight_placeholder.markdown(f"### 📊 Business Insight:\n{full_response}")
                
                msg_data = {
                    "role": "assistant", 
                    "content": full_response,
                    "sql": captured_sql,
                    "tables": captured_tables,
                    "udfs": captured_udfs,
                    "time_seconds": captured_time,
                    "input_tokens": captured_in_tokens,
                    "output_tokens": captured_out_tokens
                }
                if is_clarification:
                    msg_data["is_clarification"] = True
                    msg_data["options"] = options
                elif follow_ups:
                    msg_data["follow_ups"] = follow_ups
                    
                st.session_state.messages.append(msg_data)
                st.rerun() 
                
            except requests.exceptions.RequestException as e:
                st.error(f"Backend Connection Error: {e}")