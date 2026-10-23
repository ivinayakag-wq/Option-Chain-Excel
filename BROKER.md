# Adding another broker

The app is built around two seams. Everything else — PCR, max pain, the ATM window, the Excel push loop, the cadence — is broker-neutral.

| Seam | Upstox implementation | Contract |
|---|---|---|
| Chain snapshot (REST) | `src/upstox.py` → `UpstoxClient.snapshot()` | `Snapshot` with `symbol`, `expiry`, `lot_size`, `spot`, `rows` |
| Live ticks (WebSocket) | `src/feed.py` → `MarketFeed` | `start()`, `stop()`, `set_keys()`, `ticks()`, `tick(key)`, `stale` |

`src/live.py` is the only file that knows both, and it only calls those methods. Replace one side, or both.

## What a snapshot must contain

One row per strike, sorted by strike, with these keys. `ce_*` and `pe_*` are identical in shape.

| Field | Meaning |
|---|---|
| `strike`, `spot`, `expiry`, `lot_size` | Contract identity |
| `ce_key`, `pe_key` | Opaque instrument id used to subscribe the feed |
| `<leg>_ltp`, `<leg>_chg`, `<leg>_oi`, `<leg>_prev_oi` | Price and open interest |
| `<leg>_vol`, `<leg>_iv`, `<leg>_bid`, `<leg>_ask` | Volume, implied volatility (percent), top of book |
| `<leg>_delta`, `_gamma`, `_theta`, `_vega` | Greeks, optional but expected |

`prev_oi` is what makes DOI work, so it must be the previous session's OI, not zero.

## What a tick feed must contain

`MarketFeed.ticks()` returns `dict[instrument_key, Tick]`. `Tick` lives in `src/feed.py`:

`ltp`, `cp`, `oi`, `vol`, `iv` (percent), `bid`, `ask`, `bid_qty`, `ask_qty`, `delta`, `gamma`, `theta`, `vega`.

`set_keys()` must reconcile subscriptions at runtime — the window moves as spot moves — and `ticks()` must be safe to call from another thread.

## Canonical mapping (how Upstox fills it)

| Canonical | Upstox V3 source |
|---|---|
| `ltp`, `cp` | `fullFeed.marketFF.ltpc.ltp` / `.cp` |
| `oi`, `vol` | `.oi` / `.vtt` |
| `iv` | `.iv` × 100 (Upstox sends a fraction; the workbook shows percent) |
| `bid`, `ask` | `.marketLevel.bidAskQuote[0].bidP` / `.askP` |
| Greeks | `.optionGreeks` |
| Chain fields | `/v2/option/chain` → `market_data` and `option_greeks` per leg |

The units matter more than the names: OI is often quoted in contracts by one broker and in quantity by another, and IV is a fraction on Upstox but a percentage on some others. Normalise at the adapter, not downstream.

## Recipe

1. **Copy the feed skeleton.** `src/feed.py` is ~260 lines: connect, subscribe, decode, reconnect with backoff, stale detection. Keep the class surface, replace the transport and decoder.
2. **Write the snapshot adapter.** Wrap the vendor's chain endpoint. Resolve expiry keywords yourself — Upstox's own `current_week` pointed at expired contracts because NSE weeklies expire Tuesday and BSE Thursday.
3. **Register the symbols.** `INDICES` in `src/upstox.py` maps display name to instrument id. A different broker means a different id scheme, e.g. Kite tokens or Angel symbols.
4. **Replace the auth call.** `live.py` calls `UpstoxAuth.get_access_token()`. Every Indian broker has its own flavour: Kite `request_token` → `access_token`, Angel JWT plus TOTP, Fyers app id plus daily token.
5. **Wire a flag.** Add `--broker` to `src/live.py` and construct the pair (`snapshot_provider`, `feed`) from it. Ten lines.
6. **Test offline.** `tests/test_feed.py` parses recorded payloads without a network. Record one frame per vendor and assert the mapped `Tick`.

## Broker notes

None of these were implemented or tested here. Treat the numbers as starting points to verify against current vendor documentation.

| Broker | Chain data | Streaming | Watch out for |
|---|---|---|---|
| Upstox (this repo) | `/v2/option/chain` incl. IV + Greeks | V3 `full` feed, 2,000 keys, 2 connections | 2,000 REST calls / 30 min; token dies 03:30 IST |
| Zerodha Kite | `/quote/ohlc` + `/quote` for OI | KiteTicker `full` mode | 3 req/s quote limit; instrument dump refresh |
| Angel One | `optionGreek` + `marketData` | SmartAPI WebSocket v2 | TOTP login, JWT refresh, per-exchange tokens |
| Fyers | `/data/quotes` (OI included) | Socket v3 | App id + daily access token, symbol format differs |
| Dhan | `/v2/marketfeed/ltp` and `/v2/marketfeed/quote` | Market feed WebSocket | 1,000 instruments per request; segment ids |
| ICICI Breeze | `quotes` with `expiry` | Breeze WebSocket | Daily session token, 100 keys per quote call |

## Porting checklist

- [ ] Chain snapshot returns > 20 strikes with non-null OI, LTP and IV.
- [ ] `prev_oi` matches the vendor's previous close OI, so DOI is not equal to OI.
- [ ] Tick adapter yields both legs and the index level under the same key scheme.
- [ ] Subscription size stays under the vendor's per-connection cap for 21 strikes × 5 indices.
- [ ] Reconnect restores subscriptions, and `stale` flips after 30 s of silence.
- [ ] IV and Greeks are in the units the workbook expects.
- [ ] Token expiry path puts the login URL in the A2 heartbeat instead of crashing.
