import time
from datetime import datetime

import pytest

from src.auth import IST, AuthError, AuthRequired, Tokens, UpstoxAuth, session_end


def test_tokens_validity_window():
    tokens = Tokens(access_token="abc", expires_at=time.time() + 600)
    assert tokens.is_valid()
    assert tokens.is_valid(300)
    assert not tokens.is_valid(900)


def test_expired_tokens_are_not_valid():
    tokens = Tokens(access_token="abc", expires_at=time.time() - 1)
    assert not tokens.is_valid()
    assert not Tokens(access_token="").is_valid()


def test_from_response_uses_expires_in():
    tokens = Tokens.from_response({"access_token": "a", "refresh_token": "r", "expires_in": 3600})
    assert tokens.access_token == "a"
    assert tokens.refresh_token == "r"
    assert 3500 < tokens.expires_at - time.time() <= 3600


def test_from_response_without_expires_in_uses_0330_ist():
    tokens = Tokens.from_response({"access_token": "a"})
    assert tokens.access_token == "a"
    assert tokens.expires_at == pytest.approx(session_end(), abs=2)


def test_session_end_rolls_to_next_morning():
    evening = datetime(2026, 10, 22, 19, 45, tzinfo=IST)
    assert session_end(evening) == datetime(2026, 10, 23, 3, 30, tzinfo=IST).timestamp()
    early = datetime(2026, 10, 22, 1, 0, tzinfo=IST)
    assert session_end(early) == datetime(2026, 10, 22, 3, 30, tzinfo=IST).timestamp()


def test_token_store_roundtrip(tmp_path):
    path = tmp_path / "nested" / "tokens.json"
    auth = UpstoxAuth(client_id="cid", client_secret="secret", token_path=path)
    auth.save(Tokens(access_token="a", refresh_token="r", expires_at=time.time() + 100))

    loaded = auth.load()
    assert loaded.access_token == "a"
    assert loaded.refresh_token == "r"
    assert auth.status()["has_refresh_token"] is True


def test_get_access_token_returns_valid_token(tmp_path):
    path = tmp_path / "tokens.json"
    auth = UpstoxAuth(client_id="cid", client_secret="secret", token_path=path)
    auth.save(Tokens(access_token="good", expires_at=time.time() + 600))
    assert auth.get_access_token() == "good"


def test_expired_without_refresh_requires_login(tmp_path):
    path = tmp_path / "tokens.json"
    auth = UpstoxAuth(
        client_id="cid",
        client_secret="secret",
        redirect_uri="http://127.0.0.1:8765/callback",
        token_path=path,
    )
    auth.save(Tokens(access_token="old", expires_at=time.time() - 10))
    with pytest.raises(AuthRequired) as exc:
        auth.get_access_token()
    assert "127.0.0.1" in exc.value.url


def test_login_url_encodes_redirect(tmp_path):
    auth = UpstoxAuth(
        client_id="cid",
        client_secret="secret",
        redirect_uri="http://127.0.0.1:8765/callback",
        token_path=tmp_path / "tokens.json",
    )
    url = auth.login_url(state="xyz")
    assert url.startswith("https://api.upstox.com/v2/login/authorization/dialog?")
    assert "response_type=code" in url
    assert "state=xyz" in url
    assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A8765%2Fcallback" in url


def test_login_url_requires_client_id(tmp_path):
    auth = UpstoxAuth(client_id="", client_secret="", token_path=tmp_path / "t.json")
    with pytest.raises(AuthError):
        auth.login_url()


def test_logout_is_idempotent(tmp_path):
    auth = UpstoxAuth(token_path=tmp_path / "t.json")
    auth.logout()
    auth.logout()
    assert auth.load().access_token == ""
