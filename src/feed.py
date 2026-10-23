import json
import threading
import time
import uuid
from dataclasses import dataclass, field

import websocket
from google.protobuf import json_format
from upstox_client.feeder.proto import MarketDataFeedV3_pb2

URL = "wss://api.upstox.com/v3/feed/market-data-feed"
FULL = "full"
STALE_AFTER = 30.0
RECV_TIMEOUT = 0.5


class FeedError(Exception):
    pass


def _f(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass
class Tick:
    ltp: float = 0.0
    cp: float = 0.0
    oi: float = 0.0
    prev_oi: float = 0.0
    vol: float = 0.0
    iv: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    bid_qty: float = 0.0
    ask_qty: float = 0.0
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    ts: float = field(default_factory=time.time)

    @property
    def chg_pct(self) -> float:
        if not self.cp:
            return 0.0
        return round((self.ltp - self.cp) / self.cp * 100, 2)


def parse_feeds(message: dict) -> dict[str, Tick]:
    if message.get("type") != "live_feed":
        return {}
    out: dict[str, Tick] = {}
    for key, feed in (message.get("feeds") or {}).items():
        full = feed.get("fullFeed") or {}
        market = full.get("marketFF") or full.get("indexFF") or {}
        if not market:
            continue
        ltpc = market.get("ltpc") or {}
        levels = (market.get("marketLevel") or {}).get("bidAskQuote") or [{}]
        depth = levels[0] or {}
        greeks = market.get("optionGreeks") or {}
        out[key] = Tick(
            ltp=_f(ltpc.get("ltp")),
            cp=_f(ltpc.get("cp")),
            oi=_f(market.get("oi")),
            prev_oi=_f(market.get("prev_oi")),
            vol=_f(market.get("vtt")),
            iv=round(_f(market.get("iv")) * 100, 2),
            bid=_f(depth.get("bidP")),
            ask=_f(depth.get("askP")),
            bid_qty=_f(depth.get("bidQ")),
            ask_qty=_f(depth.get("askQ")),
            delta=_f(greeks.get("delta")),
            gamma=_f(greeks.get("gamma")),
            theta=_f(greeks.get("theta")),
            vega=_f(greeks.get("vega")),
        )
    return out


def decode(buffer: bytes) -> dict:
    message = MarketDataFeedV3_pb2.FeedResponse.FromString(buffer)
    return json_format.MessageToDict(message)


class MarketFeed:
    def __init__(self, token: str, keys: list[str], mode: str = FULL):
        self.token = token
        self.mode = mode
        self._keys: set[str] = set(keys)
        self._sent: set[str] = set()
        self._ticks: dict[str, Tick] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ws = None
        self.last_message = 0.0
        self.last_error = ""
        self.connected = False
        self.messages = 0
        self.tick_count = 0
        self.restarts = 0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    def set_keys(self, keys: list[str]) -> None:
        with self._lock:
            self._keys = set(keys)

    def ticks(self) -> dict[str, Tick]:
        with self._lock:
            return dict(self._ticks)

    def tick(self, key: str) -> Tick | None:
        with self._lock:
            return self._ticks.get(key)

    @property
    def stale(self) -> bool:
        return (time.monotonic() - self.last_message) > STALE_AFTER if self.last_message else True

    def _subscribe_message(self, keys: list[str], method: str = "sub") -> bytes:
        request = {
            "guid": str(uuid.uuid4()),
            "method": method,
            "data": {"mode": self.mode, "instrumentKeys": keys},
        }
        return json.dumps(request).encode("utf-8")

    def _sync(self, ws) -> None:
        with self._lock:
            wanted = set(self._keys)
        added = sorted(wanted - self._sent)
        removed = sorted(self._sent - wanted)
        if added:
            ws.send(self._subscribe_message(added), opcode=websocket.ABNF.OPCODE_BINARY)
            self._sent |= set(added)
        if removed:
            ws.send(self._subscribe_message(removed, "unsub"), opcode=websocket.ABNF.OPCODE_BINARY)
            self._sent -= set(removed)
            with self._lock:
                for key in removed:
                    self._ticks.pop(key, None)

    def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            ws = None
            try:
                ws = websocket.create_connection(
                    URL,
                    header=[f"Authorization: Bearer {self.token}", "Accept: */*"],
                    timeout=15,
                )
                ws.settimeout(RECV_TIMEOUT)
                self._ws = ws
                self._sent = set()
                with self._lock:
                    self._sent = set(self._keys)
                ws.send(
                    self._subscribe_message(sorted(self._sent)),
                    opcode=websocket.ABNF.OPCODE_BINARY,
                )
                self.connected = True
                self.last_message = time.monotonic()
                self.last_error = ""
                backoff = 1.0
                while not self._stop.is_set():
                    try:
                        frame = ws.recv()
                    except websocket.WebSocketTimeoutException:
                        self._sync(ws)
                        if time.monotonic() - self.last_message > STALE_AFTER:
                            self.last_error = "no data for 30s"
                            break
                        continue
                    if not frame:
                        self.last_error = "connection closed"
                        break
                    if isinstance(frame, str):
                        continue
                    self._handle(frame)
                    self._sync(ws)
            except Exception as exc:
                if not self._stop.is_set():
                    self.last_error = f"{type(exc).__name__}: {str(exc)[:160]}"
            finally:
                self.connected = False
                self._ws = None
                try:
                    ws.close()
                except Exception:
                    pass
            if self._stop.is_set():
                return
            self.restarts += 1
            time.sleep(backoff)
            backoff = min(backoff * 2, 10.0)

    def _handle(self, frame: bytes) -> None:
        self.messages += 1
        self.last_message = time.monotonic()
        try:
            message = decode(frame)
        except Exception as exc:
            self.last_error = f"decode: {exc}"
            return
        parsed = parse_feeds(message)
        if not parsed:
            return
        with self._lock:
            self._ticks.update(parsed)
            self.tick_count += len(parsed)
