from types import SimpleNamespace

from src.feed import Tick
from src.live_book import LiveBook


def _rows(count=40, start=1000, step=50, spot=2000):
    rows = []
    for index in range(count):
        strike = start + index * step
        rows.append(
            {
                "symbol": "NIFTY",
                "expiry": "2026-10-27",
                "strike": strike,
                "spot": spot,
                "lot_size": 75,
                "ce_key": f"CE{strike}",
                "pe_key": f"PE{strike}",
                "ce_ltp": 100.0,
                "ce_chg": 2.0,
                "ce_chg_pct": 2.0,
                "ce_oi": 1000,
                "ce_prev_oi": 800,
                "ce_doi": 200,
                "ce_vol": 5000,
                "ce_iv": 12.0,
                "ce_bid": 99.5,
                "ce_ask": 100.5,
                "ce_bid_qty": 75,
                "ce_ask_qty": 150,
                "ce_delta": 0.5,
                "ce_gamma": 0.001,
                "ce_theta": -5.0,
                "ce_vega": 10.0,
                "pe_ltp": 90.0,
                "pe_chg": -1.0,
                "pe_chg_pct": -1.1,
                "pe_oi": 700,
                "pe_prev_oi": 650,
                "pe_doi": 50,
                "pe_vol": 3000,
                "pe_iv": 13.0,
                "pe_bid": 89.5,
                "pe_ask": 90.5,
                "pe_bid_qty": 150,
                "pe_ask_qty": 75,
                "pe_delta": -0.5,
                "pe_gamma": 0.001,
                "pe_theta": -4.0,
                "pe_vega": 9.0,
            }
        )
    return rows


def _snapshot(rows, spot=2000, expiry="2026-10-27"):
    return SimpleNamespace(
        symbol="NIFTY",
        expiry=expiry,
        lot_size=75,
        spot=spot,
        rows=rows,
    )


def test_window_centers_on_atm():
    book = LiveBook("NIFTY", "NSE_INDEX|Nifty 50", 10)
    book.load(_snapshot(_rows(), spot=2010))
    assert len(book.rows) == 21
    assert book.center == 2000
    assert book.rows[10].strike == 2000
    assert book.rows[0].strike == 1500
    assert book.rows[-1].strike == 2500


def test_keys_include_index_and_both_legs():
    book = LiveBook("NIFTY", "NSE_INDEX|Nifty 50", 10)
    book.load(_snapshot(_rows()))
    keys = book.keys()
    assert len(keys) == 43
    assert keys[0] == "NSE_INDEX|Nifty 50"
    assert "CE2000" in keys and "PE2000" in keys
    assert "CE1000" not in keys


def test_apply_tick_updates_leg_and_doi():
    book = LiveBook("NIFTY", "NSE_INDEX|Nifty 50", 10)
    book.load(_snapshot(_rows()))
    book.apply(
        {
            "NSE_INDEX|Nifty 50": Tick(ltp=2025.0),
            "CE2000": Tick(ltp=150.0, cp=100.0, oi=1500, vol=9000, iv=18.5, bid=149.0, ask=151.0),
        }
    )
    row = next(r for r in book.rows if r.strike == 2000)
    assert book.spot == 2025.0
    assert row.ce.ltp == 150.0
    assert row.ce.chg_pct == 50.0
    assert row.ce.oi == 1500
    assert row.ce.doi == 700
    assert row.ce.iv == 18.5


def test_apply_keeps_previous_values_when_tick_is_empty():
    book = LiveBook("NIFTY", "NSE_INDEX|Nifty 50", 10)
    book.load(_snapshot(_rows()))
    book.apply({"CE2000": Tick()})
    row = next(r for r in book.rows if r.strike == 2000)
    assert row.ce.ltp == 100.0
    assert row.ce.oi == 1000


def test_frame_matches_column_order():
    book = LiveBook("NIFTY", "NSE_INDEX|Nifty 50", 10)
    book.load(_snapshot(_rows(), spot=2010))
    frame = book.frame()
    assert len(frame) == 21
    assert len(frame[0]) == 21
    row = frame[10]
    assert row[0] == "NIFTY"
    assert row[1] == "2026-10-27"
    assert row[2] == 2010
    assert row[11] == 2000
    assert row[20] == 75


def test_recenter_when_spot_drifts():
    book = LiveBook("NIFTY", "NSE_INDEX|Nifty 50", 10)
    book.load(_snapshot(_rows(), spot=2000))
    assert book.recenter() is False
    book.apply({"NSE_INDEX|Nifty 50": Tick(ltp=2450.0)})
    assert book.recenter() is True
    assert book.center == 2450
    assert book.rows[10].strike == 2450
    assert book.rows[0].strike == 1950


def test_summary_uses_full_chain():
    book = LiveBook("NIFTY", "NSE_INDEX|Nifty 50", 10)
    book.load(_snapshot(_rows(), spot=2000))
    book.apply({"CE2000": Tick(ltp=150.0, cp=100.0, oi=5000, vol=1000, iv=18.0)})
    summary = book.summary()
    assert summary["strikes"] == 40
    assert summary["atm"] == 2000
    assert summary["total_ce_oi"] == 39 * 1000 + 5000
    assert summary["spot"] == 2000


def test_set_snapshot_reports_window_change():
    book = LiveBook("NIFTY", "NSE_INDEX|Nifty 50", 10)
    book.load(_snapshot(_rows(), spot=2000))
    assert book.set_snapshot(_snapshot(_rows(), spot=2000)) is False
    assert book.set_snapshot(_snapshot(_rows(), spot=2100)) is True
