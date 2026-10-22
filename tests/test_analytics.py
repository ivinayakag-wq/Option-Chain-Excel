import json
from pathlib import Path

import pytest

from src.analytics import (
    atm_strike,
    max_pain,
    max_pain_profile,
    oi_levels,
    pain_at,
    pcr,
    summarize,
    totals,
)
from src.upstox import normalize_chain

FIXTURE = Path(__file__).parent / "fixtures" / "chain_sample.json"


@pytest.fixture()
def rows():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))["data"]
    return normalize_chain(data, "NIFTY", 75)


def test_totals(rows):
    t = totals(rows)
    assert t["ce_oi"] == 4390000
    assert t["pe_oi"] == 3390000
    assert t["ce_doi"] == 50000 + 50000 + 70000 + 30000
    assert t["pe_vol"] == 210000 + 180000 + 265000


def test_pcr_oi_and_volume(rows):
    assert pcr(rows, "oi") == pytest.approx(0.7722)
    assert pcr(rows, "vol") == pytest.approx(655000 / 978000, rel=1e-4)


def test_atm_picks_nearest(rows):
    assert atm_strike(rows, 22743.5) == 22750
    assert atm_strike(rows, 22680) == 22700
    assert atm_strike(rows, 22990) == 22850


def test_pain_at_matches_manual(rows):
    assert pain_at(rows, 22750) == pytest.approx(119_000_000)
    assert pain_at(rows, 22700) == pytest.approx(156_000_000)


def test_max_pain(rows):
    strike, pain = max_pain(rows)
    assert strike == 22750
    assert pain == pytest.approx(119_000_000)


def test_max_pain_profile_is_sorted(rows):
    profile = max_pain_profile(rows)
    assert [p["strike"] for p in profile] == [22700, 22750, 22800, 22850]


def test_oi_levels(rows):
    levels = oi_levels(rows)
    assert levels["support"] == 22700
    assert levels["support_oi"] == 1450000
    assert levels["resistance"] == 22800
    assert levels["resistance_oi"] == 1650000


def test_summarize(rows):
    summary = summarize(rows)
    assert summary["symbol"] == "NIFTY"
    assert summary["spot"] == 22743.5
    assert summary["atm"] == 22750
    assert summary["max_pain"] == 22750
    assert summary["pcr_oi"] == pytest.approx(0.7722)
    assert summary["strikes"] == 4
    assert summary["stale"] is False
    assert summary["atm_ce_iv"] == pytest.approx(10.9)
    assert summary["atm_pe_iv"] == pytest.approx(10.4)


def test_summarize_marks_stale(rows):
    assert summarize(rows, stale=True)["stale"] is True


def test_summarize_rejects_empty():
    with pytest.raises(ValueError):
        summarize([])


def test_zero_oi_does_not_divide_by_zero():
    rows = [{"strike": 100, "ce_oi": 0, "pe_oi": 0, "ce_vol": 0, "pe_vol": 0, "spot": 100}]
    assert pcr(rows) == 0.0
    assert max_pain(rows) == (100, 0.0)
