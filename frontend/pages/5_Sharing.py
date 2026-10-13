import streamlit as st

import client
from client import ApiError
from formatting import human_size, local_time
from session import require_login, show_error

st.set_page_config(page_title="Sharing", layout="wide")
st.title("Sharing")
st.caption("Share documents read-only. People you share with can search and ask questions over them, but cannot download, change or delete them.")

token, user = require_login()

tab_mine, tab_with_me = st.tabs(["Share my documents", "Shared with me"])

with tab_mine:
    try:
        docs = client.list_documents(token, limit=100)["items"]
    except ApiError as e:
        show_error(e)
        st.stop()

    if not docs:
        st.info("Upload a document on the Files page first.")
    else:
        by_id = {d["id"]: d for d in docs}
        doc_id = st.selectbox(
            "Document",
            options=list(by_id),
            format_func=lambda i: f"{by_id[i]['original_filename']} ({by_id[i]['status']})",
        )

        with st.form("share_form", clear_on_submit=True):
            email = st.text_input("Share with (email)")
            submitted = st.form_submit_button("Share")
        if submitted:
            if not email.strip():
                st.warning("Enter an email address.")
            else:
                try:
                    client.share_document(token, doc_id, email.strip())
                    st.success(f"Shared with {email.strip()}.")
                except ApiError as e:
                    show_error(e)

        st.subheader("Currently shared with")
        try:
            shares = client.list_shares(token, doc_id)
        except ApiError as e:
            show_error(e)
            shares = []
        if not shares:
            st.caption("Not shared with anyone.")
        for s in shares:
            c1, c2, c3 = st.columns([3, 2, 1])
            c1.write(s.get("grantee_email", s.get("email", "")))
            c2.caption(local_time(s["created_at"]))
            if c3.button("Revoke", key=f"revoke_{s['id']}"):
                try:
                    client.revoke_share(token, s["id"])
                    st.rerun()
                except ApiError as e:
                    show_error(e)

with tab_with_me:
    try:
        incoming = client.shared_with_me(token)
    except ApiError as e:
        show_error(e)
        st.stop()
    if not incoming:
        st.info("Nobody has shared a document with you yet.")
    for s in incoming:
        c1, c2, c3 = st.columns([3, 3, 1])
        c1.write(f"**{s['filename']}** · {human_size(s['size_bytes'])} · {s['status']}")
        c2.caption(f"From {s['shared_by_email']} · {local_time(s['shared_at'])}")
        if c3.button("Leave", key=f"leave_{s['share_id']}"):
            try:
                client.revoke_share(token, s["share_id"])
                st.rerun()
            except ApiError as e:
                show_error(e)