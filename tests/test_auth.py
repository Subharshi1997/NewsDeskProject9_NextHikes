from unittest.mock import patch

import auth


def test_get_configured_password_returns_value_when_set():
    with patch.object(auth.st, "secrets", {"app_password": "hunter2"}):
        assert auth.get_configured_password() == "hunter2"


def test_get_configured_password_returns_none_when_unset():
    with patch.object(auth.st, "secrets", {}):
        assert auth.get_configured_password() is None


def test_get_configured_password_returns_none_when_secrets_unavailable():
    class ExplodingSecrets:
        def get(self, key):
            raise FileNotFoundError("no secrets.toml")

    with patch.object(auth.st, "secrets", ExplodingSecrets()):
        assert auth.get_configured_password() is None


def test_check_password_matches():
    assert auth.check_password("hunter2", "hunter2") is True


def test_check_password_mismatch():
    assert auth.check_password("wrong", "hunter2") is False


def test_check_password_no_configured_password_always_fails():
    assert auth.check_password("anything", None) is False
    assert auth.check_password("", "") is False


def test_is_authenticated_true_when_no_password_configured():
    with patch.object(auth, "get_configured_password", return_value=None):
        assert auth.is_authenticated({}) is True
        assert auth.is_authenticated({"authenticated": False}) is True


def test_is_authenticated_requires_session_flag_when_password_configured():
    with patch.object(auth, "get_configured_password", return_value="hunter2"):
        assert auth.is_authenticated({}) is False
        assert auth.is_authenticated({"authenticated": False}) is False
        assert auth.is_authenticated({"authenticated": True}) is True
