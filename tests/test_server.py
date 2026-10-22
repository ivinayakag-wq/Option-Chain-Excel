import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import server
from src.auth import AuthRequired
from src.upstox import Snapshot, normalize_chain

FIXTURE = Path(__file__).parent / "fixtures" / "chain_sample.json"


@pytest.fixture()
def sample_snapshot() -> Snapshot:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))["data"]
    return Snapshot(
        symbol="NIFTY",
        instrument_key="NSE_INDEX|Nifty 50",
        expiry="2026-10-27",
        spot=22743.5,
        lot_size=75,
        rows=normalize_chain(data, "NIFTY", 75),
    )


@pytest.fixture()
def client(sample_snapshot, monkeypatch):
    monkeypatch.setattr(server, "_cache", {})
    monkeypatch.setattr(server, "_last_good", {})
    monkeypatch.setattr(server, "_from_disk", lambda symbol: None)
    monkeypatch.setattr(Snapshot, "save", lambda self: Path("cache-disabled"))
    monkeypatch.setattr(
        server.client,
        "snapshot",
        lambda symbol, expiry: replace(sample_snapshot, symbol=symbol),
    )
    return TestClient(server.app)


def test_health_lists_all_symbols(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert set(body["symbols"]) == {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"}


def test_symbols_endpoint(client):
    body = client.get("/symbols").json()
    assert body["keys"]["SENSEX"] == "BSE_INDEX|SENSEX"


def test_chain_returns_rows_and_summary(client):
    response = client.get("/chain/NIFTY")
    assert response.status_code == 200
    body = response.json()
    assert len(body["rows"]) == 4
    assert body["spot"] == 22743.5
    assert body["stale"] is False
    assert body["summary"]["max_pain"] == 22750
    assert body["rows"][0]["ce_oi"] == 1200000


def test_summary_endpoint(client):
    body = client.get("/summary/NIFTY").json()
    assert body["pcr_oi"] == pytest.approx(0.7722)
    assert body["oi_support"] == 22700
    assert body["lot_size"] == 75


def test_summaries_endpoint_returns_one_row_per_symbol(client):
    body = client.get("/summaries").json()
    assert len(body["rows"]) == 5
    assert body["errors"] == {}
    assert {row["symbol"] for row in body["rows"]} == {
        "NIFTY",
        "BANKNIFTY",
        "FINNIFTY",
        "MIDCPNIFTY",
        "SENSEX",
    }


def test_cache_avoids_refetch(client, sample_snapshot, monkeypatch):
    calls = {"n": 0}

    def counting(symbol, expiry):
        calls["n"] += 1
        return sample_snapshot

    monkeypatch.setattr(server.client, "snapshot", counting)
    client.get("/chain/NIFTY")
    client.get("/chain/NIFTY")
    assert calls["n"] == 1


def test_auth_required_returns_503(client, monkeypatch):
    def boom(symbol, expiry):
        raise AuthRequired("No valid token", "http://login")

    monkeypatch.setattr(server.client, "snapshot", boom)
    response = client.get("/chain/NIFTY")
    assert response.status_code == 503
    assert response.json()["detail"]["error"] == "AUTH_REQUIRED"
    assert response.json()["detail"]["login_url"] == "http://login"


def test_stale_fallback_serves_last_good(client, sample_snapshot, monkeypatch):
    monkeypatch.setattr(server.client, "snapshot", lambda symbol, expiry: sample_snapshot)
    client.get("/chain/NIFTY")

    def boom(symbol, expiry):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(server.client, "snapshot", boom)
    monkeypatch.setattr(server, "TTL", 0)
    response = client.get("/chain/NIFTY")
    assert response.status_code == 200
    assert response.json()["stale"] is True


def test_unknown_symbol_404(client):
    assert client.get("/expiries/NOPE").status_code == 404


def test_root_page_renders(client):
    assert "Option Chain service" in client.get("/").text


def test_login_without_credentials_is_clean(monkeypatch):
    monkeypatch.setattr(server.auth, "client_id", "")
    monkeypatch.setattr(server.auth, "client_secret", "")
    assert TestClient(server.app).get("/login").status_code == 500


def test_callback_without_code(client):
    assert client.get("/callback").status_code == 400
    assert client.get("/callback?error=access_denied").status_code == 400
