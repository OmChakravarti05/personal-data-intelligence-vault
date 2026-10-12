import pandas as pd
import streamlit as st

from client import ApiError, get_stats
from session import require_login, show_error

st.set_page_config(page_title="Overview", page_icon="📊", layout="wide")
token, user = require_login()


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


st.title("Overview")
if st.button("Refresh"):
    st.rerun()

try:
    stats = get_stats(token)
except ApiError as error:
    show_error(error)
    st.stop()

by_status = stats["documents_by_status"]

row1 = st.columns(3)
row1[0].metric("Documents", stats["documents_total"])
row1[1].metric("Indexed and searchable", by_status["indexed"])
row1[2].metric("Text chunks", stats["chunks_total"])

row2 = st.columns(3)
row2[0].metric("Possible PII findings", stats["pii_findings_total"])
row2[1].metric("Documents with PII", stats["documents_with_pii"])
row2[2].metric("Storage used", human_size(stats["storage_bytes"]))

row3 = st.columns(3)
row3[0].metric("Conversations", stats["conversations_total"])
row3[1].metric("Chat messages", stats["messages_total"])

if stats["documents_total"] == 0:
    st.info("No documents yet. Upload your first file on the Files page.")

if by_status["failed"]:
    st.warning(f"{by_status['failed']} document(s) failed processing. See the Files page.")
if by_status["uploaded"] or by_status["processing"]:
    st.info("Some documents are still being indexed. Use Refresh in a moment.")

left, right = st.columns(2)
with left:
    st.subheader("Documents by status")
    status_df = pd.DataFrame({"documents": by_status})
    st.bar_chart(status_df)
with right:
    st.subheader("PII by category")
    if stats["pii_by_category"]:
        pii_df = pd.DataFrame(stats["pii_by_category"]).set_index("category")
        st.bar_chart(pii_df)
    else:
        st.caption("No PII detected in your documents.")