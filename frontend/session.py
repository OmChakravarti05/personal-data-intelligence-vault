import streamlit as st

from client import ApiError


def require_login() -> tuple[str, dict]:
    """Stop the page unless the user is signed in. Returns (token, user)."""
    if "token" not in st.session_state:
        st.warning("Please sign in first.")
        st.page_link("app.py", label="Go to sign in")
        st.stop()
    user = st.session_state["user"]
    with st.sidebar:
        st.write(f"Signed in as **{user['email']}**")
        if st.button("Sign out"):
            st.session_state.clear()
            st.rerun()
    return st.session_state["token"], user


def show_error(error: ApiError) -> None:
    """An expired or invalid token signs the user out; other errors are shown."""
    if error.status_code == 401:
        st.session_state.clear()
        st.warning("Your session expired. Please sign in again.")
        st.page_link("app.py", label="Go to sign in")
    else:
        st.error(str(error))