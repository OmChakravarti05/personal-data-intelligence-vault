import streamlit as st

import client
from client import ApiError
from formatting import human_size, local_time
from session import require_login, show_error

st.set_page_config(page_title="Settings", layout="wide")
st.title("Settings")

token, user = require_login()

st.subheader("Account")
try:
    me = client.me(token)
    stats = client.get_stats(token)
except ApiError as e:
    show_error(e)
    st.stop()

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
st.markdown(
    "- Files are encrypted at rest with AES-256-GCM.\n"
    "- Questions are answered by a local model; nothing is sent to an outside AI service.\n"
    "- The audit log never records document text or your questions.\n"
    "- Shared documents are read-only for the people you share with."
)

st.subheader("Session")
if st.button("Sign out"):
    st.session_state.clear()
    st.rerun()