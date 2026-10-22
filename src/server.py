import glob
import json
import os
import threading
import time
from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from .analytics import summarize
from .auth import AuthError, AuthRequired, UpstoxAuth
from .config import settings
from .upstox import INDICES, Snapshot, UpstoxClient, cache_file

TTL = int(os.environ.get("OC_TTL", "10"))

app = FastAPI(title="Option Chain", version="0.1.0")
auth = UpstoxAuth()
client = UpstoxClient(auth=auth)

_cache: dict[tuple[str, str], tuple[Snapshot, float]] = {}
_last_good: dict[tuple[str, str], Snapshot] = {}
_lock = threading.Lock()


def _key(symbol: str, expiry: str) -> tuple[str, str]:
    return symbol.upper(), expiry


def _peek(symbol: str, expiry: str) -> tuple[Snapshot | None, float]:
    with _lock:
        hit = _cache.get(_key(symbol, expiry))
        if hit:
            return hit[0], hit[1]
        return _last_good.get(_key(symbol, expiry)), 0.0


def _from_disk(symbol: str) -> Snapshot | None:
    matches = sorted(glob.glob(str(cache_file(symbol, "*"))))
    if not matches:
        return None
    try:
        data = json.loads(Path(matches[-1]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return Snapshot(
        symbol=data.get("symbol", symbol),
        instrument_key=data.get("instrument_key", ""),
        expiry=data.get("expiry", ""),
        spot=data.get("spot", 0.0),
        lot_size=data.get("lot_size", 0),
        rows=data.get("rows", []),
        fetched_at=data.get("fetched_at", 0.0),
        stale=True,
    )


def get_snapshot(symbol: str, expiry: str = "current_week", force: bool = False) -> Snapshot:
    key = _key(symbol, expiry)
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and not force and now - hit[1] < TTL:
            return hit[0]
    try:
        snapshot = client.snapshot(symbol, expiry)
    except Exception as exc:
        with _lock:
            fallback = _last_good.get(key)
            if fallback is None and not expiry.replace("_", "").isdigit():
                fallback = _from_disk(symbol)
        if fallback is not None:
            return replace(fallback, stale=True)
        if isinstance(exc, AuthRequired):
            raise HTTPException(
                status_code=503,
                detail={"error": "AUTH_REQUIRED", "login_url": exc.url, "message": str(exc)},
            ) from exc
        if isinstance(exc, AuthError):
            raise HTTPException(
                status_code=503,
                detail={"error": "AUTH_ERROR", "message": str(exc)},
            ) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    with _lock:
        _cache[key] = (snapshot, now)
        _last_good[key] = snapshot
    try:
        snapshot.save()
    except OSError:
        pass
    return snapshot


def _summary_payload(symbol: str, expiry: str, force: bool = False) -> dict:
    snapshot = get_snapshot(symbol, expiry, force)
    data = summarize(snapshot.rows, stale=snapshot.stale)
    data["symbol"] = snapshot.symbol
    data["fetched_at"] = snapshot.fetched_at
    data["age_seconds"] = max(0, int(time.time() - snapshot.fetched_at))
    data["lot_size"] = snapshot.lot_size
    return data


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    status = auth.status()
    rows = "".join(
        f"<tr><td><a href='/summary/{sym}'>{sym}</a></td>"
        f"<td><a href='/chain/{sym}'>chain</a></td>"
        f"<td><code>{key}</code></td></tr>"
        for sym, key in INDICES.items()
    )
    token = (
        "<p style='color:#0a0'>Token valid</p>"
        if status["valid"]
        else "<p style='color:#c00'>No valid token. <a href='/login'>Log in</a></p>"
    )
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Option Chain</title>
<style>body{{font-family:Segoe UI,sans-serif;margin:2rem;max-width:820px}}
table{{border-collapse:collapse}}td,th{{padding:6px 12px;border-bottom:1px solid #ddd;text-align:left}}
code{{background:#f4f4f4;padding:2px 4px}}</style></head><body>
<h1>Option Chain service</h1>{token}
<table><tr><th>Index</th><th>Data</th><th>Instrument key</th></tr>{rows}</table>
<p>Summary: <a href="/summary/NIFTY">/summary/NIFTY</a> ·
<a href="/health">/health</a> · <a href="/refresh">/refresh</a> (all)</p>
</body></html>"""


@app.get("/health")
def health() -> dict:
    symbols: dict[str, dict] = {}
    for symbol in INDICES:
        snapshot, ts = _peek(symbol, "current_week")
        symbols[symbol] = {
            "cached": snapshot is not None,
            "stale": snapshot.stale if snapshot else None,
            "expiry": snapshot.expiry if snapshot else None,
            "rows": len(snapshot.rows) if snapshot else 0,
            "age_seconds": max(0, int(time.time() - ts)) if ts else None,
        }
    return {
        "status": "ok",
        "auth": auth.status(),
        "ttl_seconds": TTL,
        "symbols": symbols,
    }


@app.get("/symbols")
def symbols() -> dict:
    return {"symbols": list(INDICES), "keys": INDICES}


@app.get("/expiries/{symbol}")
def expiries(symbol: str) -> dict:
    key = INDICES.get(symbol.upper())
    if not key:
        raise HTTPException(status_code=404, detail=f"Unknown symbol {symbol}")
    try:
        return {"symbol": symbol.upper(), "expiries": client.expiries(key)}
    except AuthError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/chain/{symbol}")
def chain(symbol: str, expiry: str = Query("current_week")) -> dict:
    snapshot = get_snapshot(symbol, expiry)
    summary = summarize(snapshot.rows, stale=snapshot.stale)
    return {
        "symbol": snapshot.symbol,
        "expiry": snapshot.expiry,
        "spot": snapshot.spot,
        "lot_size": snapshot.lot_size,
        "fetched_at": snapshot.fetched_at,
        "stale": snapshot.stale,
        "summary": summary,
        "rows": snapshot.rows,
    }


@app.get("/summary/{symbol}")
def summary(symbol: str, expiry: str = Query("current_week")) -> dict:
    return _summary_payload(symbol, expiry)


@app.get("/summaries")
def summaries(expiry: str = Query("current_week")) -> dict:
    rows: list[dict] = []
    errors: dict[str, str] = {}
    for sym in INDICES:
        try:
            rows.append(_summary_payload(sym, expiry))
        except HTTPException as exc:
            errors[sym] = str(exc.detail)
    return {"rows": rows, "errors": errors}


@app.get("/refresh")
def refresh(symbol: str | None = None) -> dict:
    targets = [symbol] if symbol else list(INDICES)
    results: dict[str, dict] = {}
    for sym in targets:
        try:
            data = _summary_payload(sym, "current_week", force=True)
            results[sym.upper()] = {
                "ok": True,
                "expiry": data["expiry"],
                "spot": data["spot"],
                "rows": data["strikes"],
                "stale": data["stale"],
            }
        except HTTPException as exc:
            results[sym.upper()] = {"ok": False, "detail": exc.detail}
    return {"refreshed": results}


@app.get("/login")
def login() -> RedirectResponse:
    try:
        return RedirectResponse(auth.login_url())
    except AuthError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/callback", response_class=HTMLResponse)
def callback(code: str | None = None, error: str | None = None) -> HTMLResponse:
    if error:
        return HTMLResponse(f"<h2>Upstox returned an error</h2><p>{error}</p>", status_code=400)
    if not code:
        return HTMLResponse("<h2>No code in callback</h2>", status_code=400)
    try:
        tokens = auth.exchange_code(code)
    except AuthError as exc:
        return HTMLResponse(f"<h2>Token exchange failed</h2><p>{exc}</p>", status_code=400)
    until = time.strftime("%Y-%m-%d %H:%M", time.localtime(tokens.expires_at))
    return HTMLResponse(
        f"<h2>Token saved</h2><p>Valid until {until}.</p><p><a href='/'>Back</a></p>"
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")
