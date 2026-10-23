from dataclasses import dataclass

from . import analytics


@dataclass
class Leg:
    key: str = ""
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

    @classmethod
    def from_row(cls, row: dict, prefix: str) -> "Leg":
        return cls(
            key=str(row.get(f"{prefix}_key") or ""),
            ltp=float(row.get(f"{prefix}_ltp") or 0),
            cp=float(row.get(f"{prefix}_chg") or 0) + float(row.get(f"{prefix}_ltp") or 0),
            oi=float(row.get(f"{prefix}_oi") or 0),
            prev_oi=float(row.get(f"{prefix}_prev_oi") or 0),
            vol=float(row.get(f"{prefix}_vol") or 0),
            iv=float(row.get(f"{prefix}_iv") or 0),
            bid=float(row.get(f"{prefix}_bid") or 0),
            ask=float(row.get(f"{prefix}_ask") or 0),
            bid_qty=float(row.get(f"{prefix}_bid_qty") or 0),
            ask_qty=float(row.get(f"{prefix}_ask_qty") or 0),
            delta=float(row.get(f"{prefix}_delta") or 0),
            gamma=float(row.get(f"{prefix}_gamma") or 0),
            theta=float(row.get(f"{prefix}_theta") or 0),
            vega=float(row.get(f"{prefix}_vega") or 0),
        )

    def apply(self, tick) -> None:
        if tick.ltp:
            self.ltp = tick.ltp
        if tick.cp:
            self.cp = tick.cp
        if tick.oi:
            self.oi = tick.oi
        if tick.vol:
            self.vol = tick.vol
        if tick.iv:
            self.iv = tick.iv
        if tick.bid:
            self.bid = tick.bid
        if tick.ask:
            self.ask = tick.ask
        if tick.bid_qty:
            self.bid_qty = tick.bid_qty
        if tick.ask_qty:
            self.ask_qty = tick.ask_qty
        if tick.delta:
            self.delta = tick.delta
        if tick.gamma:
            self.gamma = tick.gamma
        if tick.theta:
            self.theta = tick.theta
        if tick.vega:
            self.vega = tick.vega

    @property
    def doi(self) -> float:
        return self.oi - self.prev_oi

    @property
    def chg_pct(self) -> float:
        if not self.cp:
            return 0.0
        return round((self.ltp - self.cp) / self.cp * 100, 2)

    def fields(self, prefix: str) -> dict:
        return {
            f"{prefix}_ltp": self.ltp,
            f"{prefix}_chg_pct": self.chg_pct,
            f"{prefix}_oi": self.oi,
            f"{prefix}_doi": self.doi,
            f"{prefix}_vol": self.vol,
            f"{prefix}_iv": self.iv,
            f"{prefix}_bid": self.bid,
            f"{prefix}_ask": self.ask,
            f"{prefix}_bid_qty": self.bid_qty,
            f"{prefix}_ask_qty": self.ask_qty,
            f"{prefix}_delta": self.delta,
            f"{prefix}_gamma": self.gamma,
            f"{prefix}_theta": self.theta,
            f"{prefix}_vega": self.vega,
        }


@dataclass
class WindowRow:
    strike: float
    ce: Leg
    pe: Leg


class LiveBook:
    def __init__(self, symbol: str, index_key: str, window: int = 10):
        self.symbol = symbol.upper()
        self.index_key = index_key
        self.window = window
        self.expiry = ""
        self.lot_size = 0
        self.base_spot = 0.0
        self.index_ltp = 0.0
        self.rows: list[WindowRow] = []
        self._base: list[dict] = []
        self.center = 0.0

    def load(self, snapshot, spot: float | None = None) -> None:
        self.expiry = snapshot.expiry
        self.lot_size = snapshot.lot_size
        self.base_spot = snapshot.spot
        self._base = list(snapshot.rows)
        self._rebuild(spot if spot else self.base_spot)

    def set_snapshot(self, snapshot) -> bool:
        self.expiry = snapshot.expiry
        self.lot_size = snapshot.lot_size
        if snapshot.spot:
            self.base_spot = snapshot.spot
        previous = {(r.strike, r.ce.key, r.pe.key) for r in self.rows}
        self._base = list(snapshot.rows)
        self._rebuild(self._spot())
        current = {(r.strike, r.ce.key, r.pe.key) for r in self.rows}
        return previous != current

    @property
    def spot(self) -> float:
        return self.index_ltp or self.base_spot

    def _spot(self) -> float:
        return self.spot

    def keys(self) -> list[str]:
        keys = [self.index_key]
        for row in self.rows:
            if row.ce.key:
                keys.append(row.ce.key)
            if row.pe.key:
                keys.append(row.pe.key)
        return keys

    def _rebuild(self, spot: float) -> None:
        if not self._base:
            self.rows = []
            return
        strikes = sorted({float(r["strike"]) for r in self._base if r.get("strike")})
        if not strikes:
            self.rows = []
            return
        atm = min(strikes, key=lambda k: abs(k - spot))
        self.center = atm
        index = strikes.index(atm)
        low = max(0, index - self.window)
        high = min(len(strikes), index + self.window + 1)
        by_strike = {}
        for raw in self._base:
            if not raw.get("strike"):
                continue
            row = WindowRow(
                strike=float(raw["strike"]),
                ce=Leg.from_row(raw, "ce"),
                pe=Leg.from_row(raw, "pe"),
            )
            by_strike[row.strike] = row
        self.rows = [by_strike[s] for s in strikes[low:high] if s in by_strike]

    def recenter(self) -> bool:
        if not self.rows:
            return False
        strikes = sorted({float(r["strike"]) for r in self._base if r.get("strike")})
        if not strikes:
            return False
        atm = min(strikes, key=lambda k: abs(k - self.spot))
        center_index = strikes.index(self.center) if self.center in strikes else 0
        atm_index = strikes.index(atm)
        threshold = max(2, self.window // 2)
        if abs(atm_index - center_index) <= threshold:
            return False
        previous = [r.strike for r in self.rows]
        self._rebuild(self.spot)
        return [r.strike for r in self.rows] != previous

    def apply(self, ticks: dict) -> None:
        index_tick = ticks.get(self.index_key)
        if index_tick is not None and index_tick.ltp:
            self.index_ltp = index_tick.ltp
        for row in self.rows:
            tick = ticks.get(row.ce.key)
            if tick is not None:
                row.ce.apply(tick)
            tick = ticks.get(row.pe.key)
            if tick is not None:
                row.pe.apply(tick)

    def merged_rows(self) -> list[dict]:
        spot = self.spot
        overlay = {}
        for row in self.rows:
            overlay[row.strike] = row
        rows: list[dict] = []
        for raw in self._base:
            strike = float(raw.get("strike") or 0)
            if not strike:
                continue
            live = overlay.get(strike)
            if live is None:
                merged = dict(raw)
                merged["spot"] = spot
            else:
                merged = {
                    "symbol": self.symbol,
                    "expiry": self.expiry,
                    "strike": strike,
                    "spot": spot,
                    "lot_size": self.lot_size,
                }
                merged.update(live.ce.fields("ce"))
                merged.update(live.pe.fields("pe"))
            rows.append(merged)
        if not rows:
            for row in self.rows:
                merged = {
                    "symbol": self.symbol,
                    "expiry": self.expiry,
                    "strike": row.strike,
                    "spot": spot,
                    "lot_size": self.lot_size,
                }
                merged.update(row.ce.fields("ce"))
                merged.update(row.pe.fields("pe"))
                rows.append(merged)
        return rows

    def summary(self) -> dict:
        rows = self.merged_rows()
        if not rows:
            return {}
        return analytics.summarize(rows, stale=False)

    def frame(self) -> list[list]:
        spot = self.spot
        out: list[list] = []
        for row in self.rows:
            out.append(
                [
                    self.symbol,
                    self.expiry,
                    spot,
                    row.ce.oi,
                    row.ce.doi,
                    row.ce.vol,
                    row.ce.iv,
                    row.ce.ltp,
                    row.ce.chg_pct,
                    row.ce.bid,
                    row.ce.ask,
                    row.strike,
                    row.pe.bid,
                    row.pe.ask,
                    row.pe.chg_pct,
                    row.pe.ltp,
                    row.pe.iv,
                    row.pe.vol,
                    row.pe.doi,
                    row.pe.oi,
                    self.lot_size,
                ]
            )
        return out
