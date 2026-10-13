import pandas as pd
import streamlit as st

import client
from client import ApiError
from formatting import local_time
from session import require_login, show_error

st.set_page_config(page_title="Audit Log", layout="wide")
st.title("Audit Log")
st.caption("Security-relevant actions on your account. Document contents and questions are never logged.")

token, user = require_login()

PAGE_SIZE = 20

col1, col2 = st.columns(2)
event_type = col1.text_input("Event type", placeholder="e.g. auth.login, document.upload")
result = col2.selectbox("Result", ["all", "success", "failure"])

filter_key = (event_type, result)
if st.session_state.get("audit_filter") != filter_key:
    st.session_state["audit_filter"] = filter_key
    st.session_state["audit_page"] = 0
page = st.session_state.setdefault("audit_page", 0)

try:
    data = client.list_audit_events(
        token,
        event_type=event_type.strip() or None,
        result=None if result == "all" else result,
        limit=PAGE_SIZE,
        offset=page * PAGE_SIZE,
    )
except ApiError as e:
    show_error(e)
    st.stop()

events = data["items"]
total = data["total"]

if not events:
    st.info("No events found.")
else:
    rows = [
        {
            "When": local_time(e["created_at"]),
            "Event": e["event_type"],
            "Result": e["result"],
            "Resource": e["resource_type"] or "",
            "Details": ", ".join(f"{k}={v}" for k, v in (e.get("metadata") or {}).items()),
        }
        for e in events
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

pages = max(1, -(-total // PAGE_SIZE))
prev_col, label_col, next_col = st.columns([1, 2, 1])
if prev_col.button("Previous", disabled=page == 0):
    st.session_state["audit_page"] -= 1
    st.rerun()
label_col.write(f"Page {page + 1} of {pages} · {total} events")
if next_col.button("Next", disabled=page + 1 >= pages):
    st.session_state["audit_page"] += 1
    st.rerun()