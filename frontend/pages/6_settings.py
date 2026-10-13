import streamlit as st

import client
from client import ApiError
from formatting import human_size, local_time
from session import require_login, show_error

st.set_page_config(page_title="Settings", layout="wide")
st.title("Settings")

token, user = require_login()

try:
    me = client.me(token)
    stats = client.get_stats(token)
    info = client.system_info(token)
except ApiError as e:
    show_error(e)
    st.stop()

st.subheader("Account")
st.write(f"**Email:** {me.get('email', '')}")
if me.get("full_name"):
    st.write(f"**Name:** {me['full_name']}")
if me.get("created_at"):
    st.write(f"**Member since:** {local_time(me['created_at'])}")

st.subheader("Your vault")
c1, c2, c3 = st.columns(3)
c1.metric("Documents", stats["documents_total"])
c2.metric("Storage used", human_size(stats["storage_bytes"]))
c3.metric("Conversations", stats["conversations_total"])

st.subheader("Privacy")
if info["external_llm"]:
    st.warning(
        f"Answers use an external service ({info['llm_provider']}, model `{info['llm_model']}`). "
        "Your questions and the document passages retrieved for them are sent to that service. "
        "Your stored files and search index stay on this system."
    )
else:
    st.success(
        f"Answers use a local model (`{info['llm_model']}`). "
        "Your questions and document text are not sent to any outside service."
    )
st.markdown(
    "- Files are encrypted at rest with AES-256-GCM.\n"
    "- The audit log never records document text or your questions.\n"
    "- Shared documents are read-only for the people you share with."
)

st.subheader("Session")
if st.button("Sign out"):
    st.session_state.clear()
    st.rerun()