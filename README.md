# Option Chain in Excel

Live NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY and SENSEX option chains inside Excel.

Two workbooks come out of this repo:

- **`OptionChain Live.xlsx`** — pushed every 0.5 s over Upstox's WebSocket feed while the market is open. Nothing to press.
- **`OptionChain.xlsx`** — the snapshot workbook. Press **Data ▸ Refresh All**. Keep it as the fallback.

Data comes from the free Upstox API. No scraping, no subscription, no macros.

## Status

| Phase | State |
|---|---|
| Auth (`src/auth.py`) | Done |
| Upstox client (`src/upstox.py`) | Done |
| Analytics (PCR, max pain) | Done |
| Local service on `127.0.0.1:8765` | Done |
| `OptionChain.xlsx` shell | Done — verified with live data (all five chains) |
| Live feed (`src/feed.py`) | Done — V3 WebSocket, 215 keys, verified live |
| `OptionChain Live.xlsx` push | Done — 0.5 s cadence, verified writing into Excel |

See `PLAN.md` for the full design, scope and rationale.

## Requirements

- Python 3.10+
- An Upstox account (free, KYC) and an API app
- Excel 2016+ with Power Query

## Setup

1. Install dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

2. Create an API app at <https://account.upstox.com/developer/apps>:
   - Redirect URI: `http://127.0.0.1:8765/callback`
   - Copy the Client ID and Client Secret

3. Create your local config:

   ```powershell
   Copy-Item .env.example .env
   ```

   Fill in `UPSTOX_CLIENT_ID` and `UPSTOX_CLIENT_SECRET`.

4. Log in. Easiest is with the service running (`Start Option Chain Server.bat`),
   then open <http://127.0.0.1:8765/login>. Or use the CLI. The login flow binds port 8765 itself, so stop the service first:

   ```powershell
   python -m src.auth login --serve
   ```

5. Check the token:

   ```powershell
   python -m src.auth status
   ```

   Do this once each trading day, before you need the workbook.

## Service

Run `Start Option Chain Server.bat` (or `python -m src.server`) and open
<http://127.0.0.1:8765> for a status page.

| Endpoint | Purpose |
|---|---|
| `/health` | Service, token and per-symbol cache state |
| `/symbols` | Index names and instrument keys |
| `/expiries/{symbol}` | Available expiries |
| `/chain/{symbol}` | Full normalised chain plus summary |
| `/summary/{symbol}` | PCR, max pain, ATM, OI levels |
| `/refresh` | Force-refresh all five (add `?symbol=NIFTY` for one) |
| `/login`, `/callback` | Upstox OAuth |
| `/docs` | FastAPI's generated reference |

Cached 10 s (`OC_TTL`). If a fetch fails, the last good snapshot is served with
`"stale": true` instead of an error.

## Live mode

```powershell
python -m src.live
```

or double-click `Start Live Option Chain.bat`. It opens `OptionChain Live.xlsx` if
Excel is not already running, subscribes 215 instrument keys over a WebSocket, and
writes ATM ± 10 strikes for all five indices every 0.5 seconds.

| Detail | Value |
|---|---|
| Transport | `wss://api.upstox.com/v3/feed/market-data-feed`, `full` mode |
| Keys | 5 index keys + 210 option keys (21 strikes × 2 legs × 5 indices) |
| Fields per tick | LTP, change, OI, volume, IV, Greeks, best bid/ask, previous close |
| Sheet refresh | 0.5 s |
| Summary refresh | full chain over REST every 60 s (PCR, max pain, OI levels) |
| Heartbeat | A2 on every sheet: state, time, tick age, spot |

Why not just refresh faster? Upstox allows 2,000 REST calls per 30 minutes (~1.1/s),
and a full chain is 1,632 keys at 500 keys per call. Polling cannot meet a
one-second target; the socket can.

The window follows the market: when spot drifts more than 5 strikes from the
anchor, the rows are re-sliced and the subscription is updated. Rows are never
inserted or deleted.

Stop with Ctrl+C. The workbook is saved on exit.

## Commands

| Command | Purpose |
|---|---|
| `python -m src.live` | Start the live feed into `OptionChain Live.xlsx` |
| `python -m src.live --dry-run --for 20` | Feed only, console stats, no Excel |
| `python -m src.live --window 15 --interval 0.5` | Wider window, slower or faster writes |
| `python -m src.auth login [--open] [--serve]` | Start the Upstox login flow |
| `python -m src.auth exchange <code>` | Manually exchange a pasted code |
| `python -m src.auth status` | Show token state, never prints the token |
| `python -m src.auth logout` | Delete stored tokens |
| `python -m pytest -q` | Run the tests (no network needed) |

## Workbook

Two builders, two files.

**`OptionChain Live.xlsx`** — no queries, no tables; a display surface for the push loop:

```powershell
python -m src.build_live_workbook
```

**`OptionChain.xlsx`** — built from Python and then finished through Excel COM, which is
what adds the Power Query connections:

```powershell
python -m src.build_workbook
```

| Sheet | Contents |
|---|---|
| Read Me | Setup, column guide, definitions, troubleshooting |
| Summary | One row per index: PCR, max pain, OI support/resistance, ATM IV, freshness |
| NIFTY … SENSEX | Calls left, strike centre, puts right; ITM shading, OI data bars |

The workbook starts empty (headers only) until a token exists. Press
**Data ▸ Refresh All** after logging in. `--no-refresh` skips the initial pull.

Build or verify against sample data without a broker account:

```powershell
python -m scripts.mock_server        # fixtures on 8765, no auth
python -m src.build_workbook
python -m scripts.verify_workbook    # tables, headers, freeze panes, formats
```

## Tokens

- The access token expires at **03:30 IST every day**. Upstox's current API returns no refresh token, so there is no silent renewal — log in once each trading day (~2 minutes).
- Expiry keywords (`current_week`, `next_week`, …) are resolved against `/v2/option/contract` before the chain call. Upstox's own keywords can point at a contract that has already expired, since NSE weeklies expire on Tuesday and BSE on Thursday.
- Stored in `data/tokens.json`, which is git-ignored. Never commit or share it.

## Sharing

The code and the workbook are yours to share. Two things are not:

- `data/tokens.json`, `.env`, and your Client Secret.
- The data feed itself: Upstox licenses it to the account holder for personal use. Passing a snapshot to a friend is normal; feeding a public service or reselling it is not.

Anyone running this needs their own Upstox app and their own daily login.
