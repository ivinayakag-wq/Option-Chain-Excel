import json
from datetime import date
from pathlib import Path

import pytest

from src.upstox import (
    INDICES,
    Snapshot,
    UpstoxClient,
    UpstoxError,
    normalize_chain,
    parse_expiries,
    pick_lot_size,
    resolve_expiry,
)

FIXTURE = Path(__file__).parent / "fixtures" / "chain_sample.json"


@pytest.fixture()
def chain_data():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["data"]


def test_index_keys_are_exact():
    assert INDICES["NIFTY"] == "NSE_INDEX|Nifty 50"
    assert INDICES["BANKNIFTY"] == "NSE_INDEX|Nifty Bank"
    assert INDICES["FINNIFTY"] == "NSE_INDEX|Nifty Fin Service"
    assert INDICES["MIDCPNIFTY"] == "NSE_INDEX|NIFTY MID SELECT"
    assert INDICES["SENSEX"] == "BSE_INDEX|SENSEX"


def test_normalize_sorts_and_computes(chain_data):
    rows = normalize_chain(chain_data, "NIFTY", 75)
    assert [r["strike"] for r in rows] == [22700, 22750, 22800, 22850]
    first = rows[0]
    assert first["symbol"] == "NIFTY"
    assert first["expiry"] == "2026-10-27"
    assert first["spot"] == 22743.5
    assert first["lot_size"] == 75
    assert first["ce_chg"] == pytest.approx(20.5)
    assert first["ce_chg_pct"] == pytest.approx(20.5)
    assert first["ce_doi"] == 50000
    assert first["ce_iv"] == pytest.approx(11.2)
    assert first["ce_delta"] == pytest.approx(0.52)
    assert first["pe_chg"] == pytest.approx(-6.75)
    assert first["pe_delta"] == pytest.approx(-0.47)
    assert first["ce_oi_contracts"] == pytest.approx(16000)


def test_normalize_handles_missing_leg(chain_data):
    rows = normalize_chain(chain_data, "NIFTY", 75)
    last = rows[-1]
    assert last["ce_ltp"] == 51.3
    assert last["pe_ltp"] == 0
    assert last["pe_oi"] == 0
    assert last["pe_iv"] == 0


def test_normalize_empty():
    assert normalize_chain([], "NIFTY", 75) == []


def test_parse_expiries_sorted_unique():
    contracts = [
        {"expiry": "2026-11-03"},
        {"expiry": "2026-10-27"},
        {"expiry": "2026-10-27"},
        {"expiry": None},
    ]
    assert parse_expiries(contracts) == ["2026-10-27", "2026-11-03"]


def test_pick_lot_size_prefers_matching_expiry():
    contracts = [
        {"expiry": "2026-10-27", "lot_size": 75},
        {"expiry": "2026-11-03", "lot_size": 120},
    ]
    assert pick_lot_size(contracts, "2026-11-03") == 120
    assert pick_lot_size(contracts) == 75
    assert pick_lot_size([]) == 0


class FakeAuth:
    def __init__(self):
        self.calls = []

    def get_access_token(self, force_refresh=False, min_valid=0):
        self.calls.append(force_refresh)
        return "test-token"


class FakeResponse:
    def __init__(self, payload, status=200):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, chain_payload, contracts_payload=None):
        self.chain_payload = chain_payload
        self.contracts_payload = contracts_payload or []
        self.urls = []
        self.headers = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.urls.append((url, params))
        self.headers.append(headers or {})
        if url.endswith("/v2/option/chain"):
            return FakeResponse({"status": "success", "data": self.chain_payload})
        if url.endswith("/v2/option/contract"):
            return FakeResponse({"status": "success", "data": self.contracts_payload})
        return FakeResponse({"status": "error"}, 404)


def test_snapshot_pipeline(chain_data):
    contracts = [{"expiry": "2026-10-27", "lot_size": 75}]
    session = FakeSession(chain_data, contracts)
    auth = FakeAuth()
    client = UpstoxClient(auth=auth, session=session, base_url="http://fake")

    snap = client.snapshot("NIFTY")

    assert isinstance(snap, Snapshot)
    assert snap.expiry == "2026-10-27"
    assert snap.lot_size == 75
    assert snap.spot == 22743.5
    assert len(snap.rows) == 4
    assert session.headers[0]["Authorization"] == "Bearer test-token"
    assert session.urls[0][0].endswith("/v2/option/contract")
    assert session.urls[1][0].endswith("/v2/option/chain")
    assert session.urls[1][1]["expiry_date"] == "2026-10-27"


def test_resolve_expiry_week_keywords():
    expiries = ["2026-10-27", "2026-11-03", "2026-11-09", "2026-11-17"]
    today = date(2026, 10, 22)
    assert resolve_expiry(expiries, "current_week", today) == "2026-10-27"
    assert resolve_expiry(expiries, "next_week", today) == "2026-11-03"
    assert resolve_expiry(expiries, "far_week", today) == "2026-11-09"


def test_resolve_expiry_skips_past_dates():
    expiries = ["2026-10-20", "2026-10-27", "2026-11-03"]
    today = date(2026, 10, 22)
    assert resolve_expiry(expiries, "current_week", today) == "2026-10-27"


def test_resolve_expiry_month_keywords():
    expiries = [
        "2026-10-27",
        "2026-11-03",
        "2026-11-10",
        "2026-11-17",
        "2026-11-24",
        "2026-12-01",
        "2026-12-29",
    ]
    today = date(2026, 10, 22)
    assert resolve_expiry(expiries, "current_month", today) == "2026-10-27"
    assert resolve_expiry(expiries, "next_month", today) == "2026-11-24"
    assert resolve_expiry(expiries, "far_month", today) == "2026-12-29"


def test_resolve_expiry_passes_dates_through():
    assert resolve_expiry(["2026-10-27"], "2026-11-03") == "2026-11-03"


def test_unknown_symbol(chain_data):
    client = UpstoxClient(auth=FakeAuth(), session=FakeSession(chain_data))
    with pytest.raises(UpstoxError):
        client.snapshot("NIFTYBANK")


def test_http_error_surfaces_status():
    class ErrorSession(FakeSession):
        def get(self, url, params=None, headers=None, timeout=None):
            return FakeResponse({"status": "error", "message": "boom"}, 400)

    client = UpstoxClient(auth=FakeAuth(), session=ErrorSession([]))
    with pytest.raises(UpstoxError) as exc:
        client.chain("NSE_INDEX|Nifty 50")
    assert exc.value.status == 400
