import streamlit as st

# PDF Task 7.1: "Implement authentication to restrict access to authorized
# users only." For a single-local-user tool, a full account system would
# be overkill -- this is a shared-password gate (st.secrets), not a user
# database. See .streamlit/secrets.toml.example.


def get_configured_password():
    """Reads app_password from st.secrets. Returns None if unset, or if
    no secrets.toml exists at all -- both are treated as "no gate
    configured" rather than an error, so a fresh local setup is never
    locked out before the user has had a chance to configure one.
    """
    try:
        return st.secrets.get("app_password") or None
    except Exception:
        return None


def check_password(entered, configured):
    return bool(configured) and entered == configured


def is_authenticated(session_state):
    """True if no password is configured (unprotected by choice) or this
    session has already unlocked it.
    """
    if not get_configured_password():
        return True
    return bool(session_state.get("authenticated"))
