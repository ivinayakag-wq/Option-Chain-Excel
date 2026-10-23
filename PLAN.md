# Indian Index Option Chain → Excel

**Document type:** Build plan / scope statement  
**Status:** Approved architecture — data source finalised (Upstox). Auth, client, analytics, service and workbook shell built; live data verification pending an Upstox login.  
**Target environment verified:** Windows, Office 365 Excel 16.0.20524, Python 3.14.6, network in Bengaluru (Jio)

---

## 1. What we are building

A local Excel workbook showing live option chains for five Indian indices, refreshed with **Data ▸ Refresh All** — no macros, no add-ins, no cloud account.

Two cooperating parts:

1. **A small Python service** on `127.0.0.1:8765` that authenticates to Upstox, pulls one chain per index, normalises the rows, computes derived metrics, and serves clean JSON.
2. **An `.xlsx` workbook** where each index has its own Power Query table bound to that service, plus a Summary sheet.

```
Upstox API ──► Python service (localhost:8765) ──► Excel Power Query tables
                     ▲                                     │
                     └───────── Refresh All (1 click) ──────┘
```

The workbook never calls Upstox directly. Credentials, token refresh, caching and normalisation stay in Python, and Excel only ever sees `http://127.0.0.1:8765/...`.

---

## 2. Why Upstox, and why not scraping

Verified during planning:

| Candidate | Option chain | Sensex (BSE) | IV + Greeks | Cost | Verdict |
|---|---|---|---|---|---|
| **Upstox** | `GET /v2/option/chain` — full chain in one call | `BSE_INDEX\|SENSEX` | included | **Free** | **Chosen** |
| Fyers | `/data/options-chain` with greeks | yes | included | Free (Standard tier) | Documented fallback |
| Angel One | no chain endpoint; assemble from quotes (50 tokens/call) | yes | build yourself | Free | Rejected — too many calls |
| Dhan | excellent | yes | yes | **₹499 + GST / month** | Rejected — needless cost |
| ICICI Breeze | clunky | partial | partial | Free | Rejected — auth friction |
| Flattrade | quotes-oriented | unclear | unclear | Free | Rejected — unproven |
| NSE scrape | v3 works today | **blocked (Akamai 403)** | IV only, no greeks | Free | Optional phase-2 fallback |
| BSE scrape | blocked at TLS/edge | — | — | — | Dead end |
| `MrChartist/india-s-best-option-hub` | NSE proxy, React app | needs Dhan keys | yes | Free (personal licence) | Rejected as a base |

**Decision:** build from scratch on Upstox. Option Hub's only value was bypassing NSE's bot protection, which Upstox makes unnecessary. It is a 1,965-file React app under a personal-use-only licence with no Excel output — more surface area, not less. The generated `upstox-python` SDK is also not needed; we use three plain REST calls via `requests`.

### Verified instrument keys (public instrument master, no credentials)

| Index | `instrument_key` |
|---|---|
| NIFTY | `NSE_INDEX\|Nifty 50` |
| BANKNIFTY | `NSE_INDEX\|Nifty Bank` |
| FINNIFTY | `NSE_INDEX\|Nifty Fin Service` |
| MIDCPNIFTY | `NSE_INDEX\|NIFTY MID SELECT` |
| SENSEX | `BSE_INDEX\|SENSEX` |

The same master file supplies lot sizes, so nothing is hardcoded and no IV needs computing.

### API surface used

| Purpose | Call |
|---|---|
| Login dialog | `GET https://api.upstox.com/v2/login/authorization/dialog?client_id=&redirect_uri=&response_type=code&state=` |
| Code → token | `POST https://api.upstox.com/v2/login/authorization/token` (`grant_type=authorization_code`) |
| Renew | Not available — re-run the login dialog (one click) |
| Expiries / contracts | `GET /v2/option/contract?instrument_key=` |
| Chain | `GET /v2/option/chain?instrument_key=&expiry_date=YYYY-MM-DD` |
| Lot sizes | `https://assets.upstox.com/market-quote/instruments/exchange/{NSE,BSE}.json.gz` |

`expiry_date` also accepts `current_week`, `next_week`, `current_month`, but in practice those keywords can resolve to an already-expired contract (NSE weeklies expire on Tuesday, BSE on Thursday). The service therefore resolves the keyword against `/option/contract` and always calls the chain with an explicit date.

**Fields per strike:** LTP, volume, OI, previous OI, close, bid/ask price, bid/ask qty, IV, delta, gamma, theta, vega, PoP, underlying spot.

---

## 3. Scope

### In scope (v1)

- Five chains: NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, SENSEX (all from the same shape).
- Nearest expiry only (`current_week`, auto-rolls after expiry).
- Classic split layout: calls left, strike centre, puts right —
  `CE OI | CE ΔOI | CE Vol | CE IV | CE LTP | CE Chg% | CE Bid | CE Ask ‖ STRIKE ‖ PE Bid | PE Ask | PE Chg% | PE LTP | PE IV | PE Vol | PE ΔOI | PE OI`
- **Summary** sheet: spot, snapshot time, PCR (PE OI ÷ CE OI), max pain, OI support (highest PE OI), OI resistance (highest CE OI), ATM strike, stale flag.
- Workbook polish: data bars on OI, ITM shading, max-pain row highlight, frozen strike column, autofilter, Indian number formats, Read Me sheet.
- Auth that gives an obvious "re-authenticate" state instead of stale numbers, and a one-click login each trading day.
- FastAPI service: `/health`, `/expiries/{symbol}`, `/chain/{symbol}`, `/summary/{symbol}`, `/refresh`.
- 10-second cache per symbol; last-good snapshot served with `"stale": true` when a fetch fails.
- `fetch_once.py` one-shot CLI writing `data/cache/*.json` for pre-warming and offline use.
- `Start Option Chain Server.bat` launcher.

### Out of scope (v1)

- Equity/stock options — index options only.
- Multiple expiries side by side, historical OI, charts, backtesting.
- Google Sheets (the service would work, but Google's egress IPs are the ones NSE blocks).
- Order placement — data only. This also keeps us clear of SEBI's algo-registration rules, which apply to order automation.
- Timer auto-refresh (manual one-click is v1; the cache is already built for it).
- Multi-user hosting. Single machine, single account.

---

## 4. Components

| Component | File | Responsibility |
|---|---|---|
| Auth | `src/auth.py` | Login URL, code exchange, token store, expiry detection |
| Upstox client | `src/upstox.py` | Chain, contracts, instrument master (lot sizes), retries, timeouts |
| Analytics | `src/analytics.py` | PCR, max pain, ATM, OI support/resistance — pure functions, unit-testable |
| Service | `src/server.py` | FastAPI, TTL cache, stale fallback, `/health` |
| Cache writer | `src/fetch_once.py` | One-shot fetch → `data/cache/*.json` |
| Workbook builder | `src/build_workbook.py` | openpyxl styling, then COM pass to add queries and tables |

### Auth design

- Access token expires at 03:30 IST every day. Upstox's current API returns no refresh token, so there is no silent renewal.
- `data/tokens.json` (outside git) stores the token plus its expiry.
- On 401: surface `AUTH_REQUIRED` with the login URL; never show stale data as if it were live.
- One browser login per trading day (~2 minutes). For unattended use, Upstox also offers a semi-automated token request delivered to a notifier URL; not implemented in v1.
- No headless browser, no TOTP secret, no PIN stored.

### Why Power Query, not VBA

`Workbook.Queries.Add` and list-object binding were tested successfully via COM on this machine. Native refresh, real tables, no `.xlsm`, no macro trust prompt.

### Why a localhost service, not `Web.Contents` direct

Credentials must never be pasted into an Excel query, and tokens must be refreshable in one place. The service also normalises five different-looking chains into one row shape, so the workbook has no per-index special cases.

---

## 5. Advantages

1. **Free and official.** No ₹499/month, no scraping, no Akamai fight, no Dhan account.
2. **Sensex included** — the one index that was unsolvable by scraping now costs nothing.
3. **Richer data than NSE scraping** — greeks, PoP, previous OI, bid/ask quantities.
4. **One call per index.** Five HTTP requests per refresh; refreshes in seconds.
5. **Genuinely one-click.** Native Power Query refresh, no macro warnings.
6. **Real Excel tables** — sortable, filterable, pivot-friendly.
7. **Contractual, not scraped.** Stable JSON shape instead of HTML/endpoint roulette.
8. **Graceful degradation.** Last-good snapshot with a visible timestamp rather than an error wall.
9. **Small footprint.** ~600 lines, pure Python, one `.xlsx`, no database, no Node, no Docker.
10. **Portable.** Code and workbook are shareable; we own the licence (see §8).

---

## 6. Disadvantages and limitations

1. **Daily-token tax.** SEBI mandates short-lived tokens at every broker, and Upstox currently issues no refresh token. The access token dies at 03:30 IST, so one browser login per trading day is unavoidable. Forgetting it is the most likely cause of "it stopped working".
2. **Needs an Upstox account** (free, KYC) and an API app. That is a hard prerequisite; no account means no data.
3. **Personal-use data licence.** Upstox supplies data for the account holder's own use, not for redistribution. Fine for your own analysis; not a basis for reselling or feeding a public service.
4. **Single-machine.** The service must be running while you use the workbook.
5. **Snapshots, not streaming.** Fresh on each refresh, not tick-by-tick. Streaming means their WebSocket plus a long-running process — a later phase.
6. **One expiry per sheet.** Changing expiry is a query parameter or a Settings cell, not a dropdown.
7. **First-run friction.** Excel may prompt once for `127.0.0.1` credentials — answer **Anonymous**.
8. **Vendor concentration.** One broker's API. Mitigated by isolating it in `src/upstox.py`; Fyers is a drop-in swap.
9. **No history.** Nothing accumulates, so no OI trend analysis until we add SQLite/CSV append.

---

## 7. Risks and fallbacks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Token expired (daily, 03:30 IST) | Certain | Clear `AUTH_REQUIRED` state + one-click login URL in `/health` |
| Upstox changes response shape | Low | Field mapping in one module; contract test against a recorded payload |
| Sensex weekly chain unavailable via API | Low | Verify on day one; fallback is Fyers, or monthly expiry |
| Rate limiting | Very low | 5 calls per refresh; cache 10s |
| Account/KYC delay | Certain, short | Build against recorded fixtures; go live the moment credentials exist |

**Fallback broker:** Fyers free Standard tier (option chain with greeks, NSE + BSE, 5 req/s). Same normalised row shape, one file swapped.

**Optional phase 2:** NSE `option-chain-v3` fallback for the four NSE indices, so the workbook still shows something if the Upstox token is dead. Deliberately not in v1 — two data paths means two things to maintain.

---

## 8. Sharing, licensing and secrets

Separate the three things being shared:

| What | Shareable? | Notes |
|---|---|---|
| **Code + workbook** | **Yes, freely** | Ours. No credentials embedded. We choose the licence (MIT recommended). |
| **Your credentials / token files** | **Never** | `data/tokens.json`, `.env`, client secret stay local and are git-ignored. |
| **The market data itself** | Personal use only | Exchange data via Upstox is licensed to the account holder. Sharing a snapshot with a friend is normal use; feeding a public site, a paid group or a resold product is not. |

Anyone you share the code with needs their **own** Upstox app and their own daily login. The service is single-user by design — there is no multi-tenant auth in v1.

Concretely, the repo will contain:

```
.gitignore        ← data/tokens.json, .env, data/cache/, __pycache__
.env.example      ← UPSTOX_CLIENT_ID=, UPSTOX_CLIENT_SECRET=, UPSTOX_REDIRECT_URI=
```

---

## 9. Deliverables

```
F:\option chain in excel\
  PLAN.md
  README.md
  requirements.txt
  .gitignore
  .env.example
  src\auth.py
  src\upstox.py
  src\analytics.py
  src\server.py
  src\fetch_once.py
  src\build_workbook.py
  scripts\mock_server.py
  scripts\verify_workbook.py
  tests\test_analytics.py
  data\cache\*.json          (git-ignored)
  data\tokens.json           (git-ignored)
  Start Option Chain Server.bat
  OptionChain.xlsx
```

---

## 10. Build order, timing, verification

| # | Step | Est. |
|---|---|---|
| 1 | `auth.py` + `upstox.py` (against fixtures until credentials exist) | 90 min |
| 2 | `analytics.py` + unit tests | 30 min |
| 3 | `server.py`, cache, stale path | 30 min |
| 4 | Workbook: styling, COM queries, Summary, Read Me | 60–90 min |
| 5 | Live verification + failure test | 30 min |
| | **Total** | **~4–5 h ≈ one working day with review** |

User-side critical path (runs in parallel): Upstox account + KYC (same day to ~48 h) → create app in the developer console (~5 min) → one browser login (~2 min).

Verification gates:
1. All five symbols return >20 rows with non-null OI, LTP and IV.
2. PCR and max pain recomputed independently from raw JSON match the workbook.
3. Refresh All completes under 5 s for all five sheets.
4. Kill the server → refresh shows last-good data plus a stale timestamp, not an error wall.
5. Delete/expire the token → workbook shows `AUTH_REQUIRED` and a working login URL.

Nothing is committed to git unless you ask.

---

## 11. Live mode (v2)

The v1 workbook is a snapshot: it updates when you press Refresh All. v2 pushes data into a second workbook, `OptionChain Live.xlsx`, every half second while the market is open. `OptionChain.xlsx` stays as it is and remains the fallback.

### What forced the design

Measured against the live API on 2026-10-23:

| Fact | Number | Consequence |
|---|---|---|
| Option keys in one expiry, five indices | 1,632 | Full chain cannot be polled cheaply |
| Keys per market-quote call | 500 (601 → HTTP 400) | Four calls per full pass |
| Latency of a 500-key quote call | ~1.6 s | REST cannot serve 1–3 s refresh |
| Standard API budget | 2,000 / 30 min = 1.1 req/s | Four calls per 1 s cycle is 4× over |
| V3 feed, `full` mode | LTP, OI, IV, Greeks, depth, prev close | One socket replaces every quote call |
| Full-mode key limit | 2,000 individual | 1,632 fits, but only if not mixed with other modes |

REST polling is therefore architecturally unable to meet a one-second target. The WebSocket feed is not an optimisation; it is the only transport that fits.

### Subscriptions

The live workbook shows ATM ± 10 strikes (21 rows) per index, so only 215 keys are needed: 5 index keys plus 210 option keys. That is 11% of the feed, leaves the connection far below the 2,000 limit, and keeps decode cost negligible. Everything outside the window is still in memory from the REST chain and is used for PCR and max pain.

### Transport

`src/feed.py` opens a raw `wss://api.upstox.com/v3/feed/market-data-feed` socket with `websocket-client`, sends the `sub` request as a binary frame, and decodes with the protobuf classes bundled in `upstox-python-sdk`. The SDK's own `MarketDataStreamerV3` wrapper was tested and abandoned: it opened connections but never delivered frames through `WebSocketApp`, while the raw socket worked first time. The SDK is still a dependency, but only for `MarketDataFeedV3_pb2`.

Message flow: `FeedResponse` → `MessageToDict` → one `Tick` per instrument key, held in a dict under a lock. Reconnects use exponential backoff (1 s to 10 s), and the subscriber is marked stale after 30 s without a message. Re-subscription after a reconnect sends the full key set again; key changes mid-session are sent as `sub`/`unsub` diffs from the receive loop.

### Excel delivery

`src/excel_writer.py` attaches to the running Excel via `GetActiveObject`, or launches it with `--open`. It writes a 21×21 `Value2` block per sheet, plus a 5×18 Summary block, and refreshes the A2 heartbeat line. Measured cost on the target machine: **~30 ms per sheet**, so five sheets plus Summary is ~180 ms of a 500 ms budget.

Two details that matter:

- Chain sheets have no ListObjects or Power Query connections. Tables fight external writes and add refresh bookkeeping for no benefit.
- Conditional formatting and data bars are scoped to rows 5–25, not rows 5–2000 as in the v1 workbook. Excel re-evaluates those rules on every write, and the original range was 40× larger than needed.

### Cadence and recentering

- Chain sheets: every 0.5 s. Worst-case staleness on screen is ~0.6 s.
- Summary: recomputed every 0.5 s from memory, but the full-chain snapshot behind it refreshes over REST every 60 s (five calls per minute, 150 per 30 min). The Age column states that lag.
- The window is anchored when the service starts. Rows are never inserted or deleted; if spot drifts more than 5 strikes from the anchor, the window is re-sliced, the feed subscription is diffed, and the new edges fill in on the next tick.

### Verification

- 40-second live run: 273 messages, 9,914 ticks, zero reconnects, Excel writes acknowledged every cycle.
- Workbook read back after save: all five spot values live, 21 strikes per sheet, Summary expiry stored as text, heartbeat line showing tick age.
- `python -m pytest -q`: 59 tests, covering feed parsing, window math, DOI, recentering, and existing snapshot behaviour.

### Known limits

- Writing replaces cell contents: manual edits in the live workbook are lost within half a second, and the undo stack is cleared.
- IV and Greeks arrive over the socket but are only as good as Upstox's server-side computation; they are not recomputed locally.
- If Excel is closed mid-session the service stops writing rather than reopening the file; restart the launcher.
- The daily 03:30 IST token expiry still applies. The heartbeat line turns red with the login URL when a REST refresh is refused.

