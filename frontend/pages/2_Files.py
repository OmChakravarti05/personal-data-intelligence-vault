from collections import Counter

import pandas as pd
import streamlit as st

from client import (
    ApiError,
    delete_document,
    list_documents,
    pii_findings,
    pii_preview,
    reprocess_document,
    upload_document,
)
from formatting import human_size, local_time
from session import require_login, show_error

PAGE_SIZE = 20
STATUS_LABELS = {
    "uploaded": "⏳ uploaded",
    "processing": "⏳ processing",
    "indexed": "✅ indexed",
    "failed": "❌ failed",
}

st.set_page_config(page_title="Files", page_icon="📁", layout="wide")
token, user = require_login()
st.title("Files")

st.session_state.setdefault("uploader_key", 0)
if "flash" in st.session_state:
    st.success(st.session_state.pop("flash"))

with st.expander("Upload a document"):
    file = st.file_uploader("Choose a file", key=f"uploader_{st.session_state['uploader_key']}")
    if file is not None and st.button("Upload"):
        try:
            with st.spinner("Uploading..."):
                upload_document(
                    token, file.name, file.getvalue(), file.type or "application/octet-stream"
                )
        except ApiError as error:
            show_error(error)
        else:
            st.session_state["uploader_key"] += 1
            st.session_state["flash"] = f"Uploaded {file.name}. Indexing runs in the background."
            st.rerun()

f1, f2, f3, f4 = st.columns([3, 2, 1, 1])
search = f1.text_input("Search by name")
status_filter = f2.selectbox("Status", ["all", "uploaded", "processing", "indexed", "failed"])
page = f3.number_input("Page", min_value=1, value=1, step=1)
f4.write("")
if f4.button("Refresh"):
    st.rerun()

try:
    data = list_documents(
        token,
        q=search.strip() or None,
        status=None if status_filter == "all" else status_filter,
        limit=PAGE_SIZE,
        offset=(page - 1) * PAGE_SIZE,
    )
except ApiError as error:
    show_error(error)
    st.stop()

items, total = data["items"], data["total"]
st.caption(f"{total} document(s)")
if not items:
    st.info("No documents match. Upload a file above to get started.")
    st.stop()
if any(d["status"] in ("uploaded", "processing") for d in items):
    st.info("Some documents are still being indexed. Use Refresh in a moment.")

frame = pd.DataFrame(
    {
        "Name": [d["original_filename"] for d in items],
        "Status": [STATUS_LABELS.get(d["status"], d["status"]) for d in items],
        "Size": [human_size(d["size_bytes"]) for d in items],
        "Pages": [str(d["page_count"]) if d["page_count"] else "—" for d in items],
        "Uploaded": [local_time(d["created_at"]) for d in items],
        "Indexed": [local_time(d["indexed_at"]) for d in items],
    }
)
event = st.dataframe(
    frame, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row"
)
selected = event.selection.rows
if not selected:
    st.caption("Select a row to see details and actions.")
    st.stop()

doc = items[selected[0]]
doc_id = doc["id"]
st.divider()
st.subheader(doc["original_filename"])
st.write(f"Status: **{doc['status']}** · {human_size(doc['size_bytes'])} · {doc['mime_type']}")

if doc["status"] == "failed":
    st.error(doc["error_message"] or "Processing failed.")
if doc["status"] in ("failed", "uploaded"):
    if st.button("Retry indexing"):
        try:
            with st.spinner("Indexing... this can take a minute."):
                reprocess_document(token, doc_id)
        except ApiError as error:
            show_error(error)
        else:
            st.session_state["flash"] = "Indexing finished. Check the status above."
            st.rerun()

if doc["status"] == "indexed":
    st.markdown("**Possible PII**")
    try:
        findings = pii_findings(token, doc_id)
    except ApiError as error:
        show_error(error)
    else:
        if findings["total"] == 0:
            st.caption("No PII detected.")
        else:
            counts = Counter(item["category"] for item in findings["items"])
            st.dataframe(
                pd.DataFrame({"Category": list(counts), "Count": list(counts.values())}),
                hide_index=True,
            )
            if findings["total"] > len(findings["items"]):
                st.caption(f"Counts cover the first {len(findings['items'])} of {findings['total']} findings.")

    if st.button("Show redacted preview"):
        try:
            st.session_state["preview"] = (doc_id, pii_preview(token, doc_id))
        except ApiError as error:
            show_error(error)
    preview = st.session_state.get("preview")
    if preview and preview[0] == doc_id:
        body = preview[1]
        for segment in body["segments"]:
            if segment["page_number"]:
                st.caption(f"Page {segment['page_number']}")
            st.text(segment["text"])
        if body["truncated"]:
            st.caption("Preview truncated.")
        st.caption(body["disclaimer"])

st.divider()
confirm = st.checkbox("I understand this permanently deletes the file and its search data")
if st.button("Delete document", disabled=not confirm):
    try:
        delete_document(token, doc_id)
    except ApiError as error:
        show_error(error)
    else:
        st.session_state.pop("preview", None)
        st.session_state["flash"] = f"Deleted {doc['original_filename']}."
        st.rerun()