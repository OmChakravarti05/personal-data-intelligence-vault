import streamlit as st

from client import ApiError, login, me, register

st.set_page_config(page_title="Personal Data Intelligence Vault", page_icon="🔐")


def sign_in(email: str, password: str) -> None:
    token = login(email, password)
    st.session_state["token"] = token
    st.session_state["user"] = me(token)


def login_view() -> None:
    st.title("🔐 Personal Data Intelligence Vault")
    st.caption("Search and ask questions about your own documents. Everything runs on this machine.")
    tab_in, tab_up = st.tabs(["Sign in", "Create account"])

    with tab_in:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in")
        if submitted:
            try:
                sign_in(email.strip(), password)
            except ApiError as error:
                st.error(str(error))
            else:
                st.rerun()

    with tab_up:
        with st.form("register_form"):
            full_name = st.text_input("Full name")
            new_email = st.text_input("Email", key="reg_email")
            new_password = st.text_input("Password", type="password", key="reg_password")
            created = st.form_submit_button("Create account")
        if created:
            try:
                register(new_email.strip(), full_name.strip(), new_password)
                sign_in(new_email.strip(), new_password)
            except ApiError as error:
                st.error(str(error))
            else:
                st.rerun()


def home_view() -> None:
    user = st.session_state["user"]
    with st.sidebar:
        st.write(f"Signed in as **{user['email']}**")
        if st.button("Sign out"):
            st.session_state.clear()
            st.rerun()
    st.title("Welcome back")
    st.write(f"Hello, {user['full_name']}. The Overview, Files and AI Assistant pages are coming next.")


if "token" in st.session_state:
    home_view()
else:
    login_view()
    