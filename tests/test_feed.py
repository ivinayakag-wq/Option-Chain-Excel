from src.feed import parse_feeds


def _market_message(oi=125000, ltp=142.5, cp=150.0, iv=0.1512):
    return {
        "type": "live_feed",
        "feeds": {
            "NSE_FO|123": {
                "fullFeed": {
                    "marketFF": {
                        "ltpc": {"ltp": ltp, "cp": cp},
                        "marketLevel": {
                            "bidAskQuote": [{"bidP": 142.4, "askP": 142.6, "bidQ": "750", "askQ": "300"}]
                        },
                        "optionGreeks": {"delta": 0.51, "gamma": 0.0008, "theta": -8.5, "vega": 16.7},
                        "oi": oi,
                        "vtt": "98765",
                        "iv": iv,
                    }
                },
                "requestMode": "full",
            }
        },
        "currentTs": "1740727891739",
    }


def test_parse_full_feed_option():
    ticks = parse_feeds(_market_message())
    tick = ticks["NSE_FO|123"]
    assert tick.ltp == 142.5
    assert tick.oi == 125000
    assert tick.vol == 98765
    assert tick.bid == 142.4
    assert tick.ask == 142.6
    assert tick.bid_qty == 750
    assert tick.delta == 0.51
    assert round(tick.iv, 2) == 15.12
    assert tick.chg_pct == -5.0


def test_parse_full_feed_index():
    message = {
        "type": "live_feed",
        "feeds": {"NSE_INDEX|Nifty 50": {"fullFeed": {"indexFF": {"ltpc": {"ltp": 22500.5, "cp": 22400.0}}}}},
    }
    ticks = parse_feeds(message)
    assert ticks["NSE_INDEX|Nifty 50"].ltp == 22500.5
    assert ticks["NSE_INDEX|Nifty 50"].oi == 0


def test_parse_ignores_other_messages():
    assert parse_feeds({"type": "market_info"}) == {}
    assert parse_feeds({}) == {}


def test_parse_missing_fields_defaults():
    message = {"type": "live_feed", "feeds": {"K": {"fullFeed": {"marketFF": {"ltpc": {"ltp": 10}}}}}}
    tick = parse_feeds(message)["K"]
    assert tick.oi == 0
    assert tick.iv == 0
    assert tick.chg_pct == 0.0
