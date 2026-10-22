import json
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import requests

from .auth import UpstoxAuth
from .config import CACHE_DIR, settings

BASE_URL = "https://api.upstox.com"

INDICES: dict[str, str] = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "FINNIFTY": "NSE_INDEX|Nifty Fin Service",
    "MIDCPNIFTY": "NSE_INDEX|NIFTY MID SELECT",
    "SENSEX": "BSE_INDEX|SENSEX",
}

EXPIRY_KEYWORDS = (
    "current_week",
    "next_week",
    "far_week",
    "current_month",
    "next_month",
    "far_month",
)


class UpstoxError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _leg(options: dict | None, lot_size: int) -> dict:
    options = options or {}
    market = options.get("market_data") or {}
    greeks = options.get("option_greeks") or {}
    ltp = _num(market.get("ltp"))
    close = _num(market.get("close_price"))
    oi = _num(market.get("oi"))
    prev_oi = _num(market.get("prev_oi"))
    change = ltp - close if close else 0.0
    return {
        "ltp": ltp,
        "chg": round(change, 2),
        "chg_pct": round(change / close * 100, 2) if close else 0.0,
        "oi": oi,
        "doi": oi - prev_oi,
        "prev_oi": prev_oi,
        "vol": _num(market.get("volume")),
        "iv": _num(greeks.get("iv")),
        "bid": _num(market.get("bid_price")),
        "ask": _num(market.get("ask_price")),
        "bid_qty": _num(market.get("bid_qty")),
        "ask_qty": _num(market.get("ask_qty")),
        "delta": _num(greeks.get("delta")),
        "gamma": _num(greeks.get("gamma")),
        "theta": _num(greeks.get("theta")),
        "vega": _num(greeks.get("vega")),
        "oi_contracts": oi / lot_size if lot_size else 0.0,
    }


def normalize_chain(
    data: list[dict], symbol: str = "", lot_size: int = 0
) -> list[dict]:
    rows: list[dict] = []
    for item in data or []:
        call = _leg(item.get("call_options"), lot_size)
        put = _leg(item.get("put_options"), lot_size)
        row: dict = {
            "symbol": symbol,
            "expiry": item.get("expiry", ""),
            "strike": _num(item.get("strike_price")),
            "spot": _num(item.get("underlying_spot_price")),
            "lot_size": lot_size,
        }
        for key, value in call.items():
            row[f"ce_{key}"] = value
        for key, value in put.items():
            row[f"pe_{key}"] = value
        rows.append(row)
    rows.sort(key=lambda r: r["strike"])
    return rows


def parse_expiries(contracts: list[dict]) -> list[str]:
    seen = {str(c.get("expiry")) for c in contracts if c.get("expiry")}
    return sorted(seen)


def resolve_expiry(
    expiries: list[str], keyword: str = "current_week", today: date | None = None
) -> str:
    if keyword not in EXPIRY_KEYWORDS:
        return keyword
    dates = sorted({d for d in expiries if d})
    if not dates:
        raise UpstoxError("No expiries returned for this instrument")
    today = today or date.today()
    upcoming = [date.fromisoformat(d) for d in dates if date.fromisoformat(d) >= today]
    if not upcoming:
        raise UpstoxError(f"No expiry on or after {today.isoformat()}")
    if keyword in ("current_week", "next_week", "far_week"):
        index = ("current_week", "next_week", "far_week").index(keyword)
        if index >= len(upcoming):
            raise UpstoxError(f"Only {len(upcoming)} expiry/expiries available")
        return upcoming[index].isoformat()
    monthly: dict[tuple[int, int], date] = {}
    for moment in upcoming:
        monthly[(moment.year, moment.month)] = max(
            monthly.get((moment.year, moment.month), moment), moment
        )
    months = sorted(monthly)
    index = ("current_month", "next_month", "far_month").index(keyword)
    start = next(
        (
            position
            for position, (year, month) in enumerate(months)
            if (year, month) >= (today.year, today.month)
        ),
        0,
    )
    if start + index >= len(months):
        raise UpstoxError(f"Only {len(months)} month(s) available")
    return monthly[months[start + index]].isoformat()


def pick_lot_size(contracts: list[dict], expiry: str | None = None) -> int:
    for contract in contracts:
        if expiry and str(contract.get("expiry")) != expiry:
            continue
        lot = _num(contract.get("lot_size"))
        if lot:
            return int(lot)
    return 0


def cache_file(symbol: str, expiry: str) -> Path:
    safe = expiry.replace(" ", "_")
    return CACHE_DIR / f"{symbol.upper()}_{safe}.json"


@dataclass
class Snapshot:
    symbol: str
    instrument_key: str
    expiry: str
    spot: float
    lot_size: int
    rows: list[dict] = field(default_factory=list)
    fetched_at: float = field(default_factory=time.time)
    stale: bool = False

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "instrument_key": self.instrument_key,
            "expiry": self.expiry,
            "spot": self.spot,
            "lot_size": self.lot_size,
            "rows": self.rows,
            "fetched_at": self.fetched_at,
            "stale": self.stale,
        }

    def save(self) -> Path:
        path = cache_file(self.symbol, self.expiry)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=1), encoding="utf-8")
        return path


class UpstoxClient:
    def __init__(
        self,
        auth: UpstoxAuth | None = None,
        session: requests.Session | None = None,
        timeout: int | None = None,
        base_url: str = BASE_URL,
    ):
        self.auth = auth or UpstoxAuth()
        self.session = session or requests.Session()
        self.timeout = timeout or settings.request_timeout
        self.base_url = base_url.rstrip("/")

    def _get(
        self, path: str, params: dict | None = None, retries: int = 2
    ) -> list[dict]:
        last_error = ""
        for attempt in range(retries + 1):
            token = self.auth.get_access_token(force_refresh=attempt > 0)
            response = self.session.get(
                f"{self.base_url}{path}",
                params=params,
                headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
                timeout=self.timeout,
            )
            if response.status_code == 200:
                body = response.json()
                if body.get("status") == "success":
                    data = body.get("data")
                    return data if isinstance(data, list) else []
                last_error = json.dumps(body.get("errors") or body)[:300]
            else:
                last_error = response.text[:300]
            if response.status_code in (401, 403):
                continue
            if response.status_code == 429 or response.status_code >= 500:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise UpstoxError(
                f"{path} failed: HTTP {response.status_code} {last_error}",
                response.status_code,
            )
        raise UpstoxError(f"{path} failed after retries: {last_error}")

    def contracts(self, instrument_key: str, expiry: str | None = None) -> list[dict]:
        params: dict = {"instrument_key": instrument_key}
        if expiry:
            params["expiry_date"] = expiry
        return self._get("/v2/option/contract", params)

    def expiries(self, instrument_key: str) -> list[str]:
        return parse_expiries(self.contracts(instrument_key))

    def chain(self, instrument_key: str, expiry: str = "current_week") -> list[dict]:
        return self._get(
            "/v2/option/chain",
            {"instrument_key": instrument_key, "expiry_date": expiry},
        )

    def snapshot(self, symbol: str, expiry: str = "current_week") -> Snapshot:
        key = INDICES.get(symbol.upper())
        if not key:
            raise UpstoxError(f"Unknown index {symbol!r}. Known: {', '.join(INDICES)}")
        contracts: list[dict] | None = None
        resolved = expiry
        if expiry in EXPIRY_KEYWORDS:
            contracts = self.contracts(key)
            resolved = resolve_expiry(parse_expiries(contracts), expiry)
        data = self.chain(key, resolved)
        if not data:
            raise UpstoxError(f"No chain data returned for {symbol} ({expiry})")
        actual_expiry = str(data[0].get("expiry") or resolved)
        lot_size = 0
        try:
            if contracts is None:
                contracts = self.contracts(key, actual_expiry)
            lot_size = pick_lot_size(contracts, actual_expiry)
        except UpstoxError:
            lot_size = 0
        rows = normalize_chain(data, symbol.upper(), lot_size)
        spot = _num(data[0].get("underlying_spot_price"))
        return Snapshot(
            symbol=symbol.upper(),
            instrument_key=key,
            expiry=actual_expiry,
            spot=spot,
            lot_size=lot_size,
            rows=rows,
        )
