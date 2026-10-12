import streamlit as st

from client import ApiError, ask, delete_conversation, get_conversation, list_conversations
from session import require_login, show_error

st.set_page_config(page_title="AI Assistant", page_icon="💬", layout="wide")
token, user = require_login()

st.title("AI Assistant")
st.caption(
    "Answers come only from your own documents and cite their sources. "
    "The model runs locally, so the first answer can take a while."
)

st.session_state.setdefault("conversation_id", None)
current_id = st.session_state["conversation_id"]

try:
    conversations = list_conversations(token)
except ApiError as error:
    show_error(error)
    st.stop()

with st.sidebar:
    st.divider()
    if st.button("➕ New conversation"):
        st.session_state["conversation_id"] = None
        st.rerun()
    for conversation in conversations:
        marker = "▶ " if conversation["id"] == current_id else ""
        if st.button(marker + conversation["title"][:40], key=f"open_{conversation['id']}"):
            st.session_state["conversation_id"] = conversation["id"]
            st.rerun()
    if current_id and st.button("🗑 Delete this conversation"):
        try:
            delete_conversation(token, current_id)
        except ApiError as error:
            show_error(error)
        else:
            st.session_state["conversation_id"] = None
            st.rerun()

messages: list[dict] = []
if current_id:
    try:
        messages = get_conversation(token, current_id)["messages"]
    except ApiError as error:
        if error.status_code == 404:
            st.session_state["conversation_id"] = None
            st.rerun()
        show_error(error)
        st.stop()


def render_sources(sources: list[dict]) -> None:
    with st.expander(f"Sources ({len(sources)})"):
        for source in sources:
            page = f", page {source['page_number']}" if source["page_number"] else ""
            cited = " · cited in the answer" if source["cited"] else ""
            st.markdown(f"**[{source['number']}] {source['filename']}**{page}{cited}")
            st.caption(f"Distance {source['distance']} (lower is more similar)")
            st.text(source["excerpt"])


if not messages:
    st.info(
        "Ask a question about your uploaded documents. If nothing relevant is found, "
        "the assistant says so instead of guessing."
    )

for message in messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message["role"] == "assistant" and message.get("sources"):
            render_sources(message["sources"])

question = st.chat_input("Ask a question about your documents")
if question:
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("Searching your documents and thinking..."):
            try:
                result = ask(token, question, current_id)
            except ApiError as error:
                show_error(error)
            else:
                st.session_state["conversation_id"] = result["conversation_id"]
                st.rerun()