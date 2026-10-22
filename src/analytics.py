from typing import Iterable


def _rows(rows: Iterable[dict]) -> list[dict]:
    return [r for r in rows if r.get("strike")]


def totals(rows: list[dict]) -> dict:
    return {
        "ce_oi": sum(r.get("ce_oi", 0) for r in rows),
        "pe_oi": sum(r.get("pe_oi", 0) for r in rows),
        "ce_doi": sum(r.get("ce_doi", 0) for r in rows),
        "pe_doi": sum(r.get("pe_doi", 0) for r in rows),
        "ce_vol": sum(r.get("ce_vol", 0) for r in rows),
        "pe_vol": sum(r.get("pe_vol", 0) for r in rows),
    }


def pcr(rows: list[dict], basis: str = "oi") -> float:
    t = totals(rows)
    numerator = t["pe_oi"] if basis == "oi" else t["pe_vol"]
    denominator = t["ce_oi"] if basis == "oi" else t["ce_vol"]
    if not denominator:
        return 0.0
    return round(numerator / denominator, 4)


def atm_strike(rows: list[dict], spot: float | None = None) -> float:
    if not rows:
        return 0.0
    spot = spot if spot else rows[0].get("spot", 0)
    return min((r["strike"] for r in rows), key=lambda k: abs(k - spot))


def pain_at(rows: list[dict], settlement: float) -> float:
    pain = 0.0
    for row in rows:
        strike = row["strike"]
        if settlement > strike:
            pain += row.get("ce_oi", 0) * (settlement - strike)
        elif settlement < strike:
            pain += row.get("pe_oi", 0) * (strike - settlement)
    return pain


def max_pain_profile(rows: list[dict]) -> list[dict]:
    strikes = sorted({r["strike"] for r in rows})
    return [{"strike": s, "pain": pain_at(rows, s)} for s in strikes]


def max_pain(rows: list[dict]) -> tuple[float, float]:
    profile = max_pain_profile(rows)
    if not profile:
        return 0.0, 0.0
    best = min(profile, key=lambda item: item["pain"])
    return best["strike"], best["pain"]


def oi_levels(rows: list[dict]) -> dict:
    if not rows:
        return {"support": 0.0, "support_oi": 0.0, "resistance": 0.0, "resistance_oi": 0.0}
    support = max(rows, key=lambda r: r.get("pe_oi", 0))
    resistance = max(rows, key=lambda r: r.get("ce_oi", 0))
    return {
        "support": support["strike"],
        "support_oi": support.get("pe_oi", 0),
        "resistance": resistance["strike"],
        "resistance_oi": resistance.get("ce_oi", 0),
    }


def atm_iv(rows: list[dict], strike: float) -> tuple[float, float]:
    for row in rows:
        if row["strike"] == strike:
            return row.get("ce_iv", 0.0), row.get("pe_iv", 0.0)
    return 0.0, 0.0


def summarize(rows: list[dict], stale: bool = False) -> dict:
    rows = _rows(rows)
    if not rows:
        raise ValueError("Cannot summarize an empty chain")
    spot = rows[0].get("spot", 0.0)
    atm = atm_strike(rows, spot)
    pain_strike, pain_value = max_pain(rows)
    levels = oi_levels(rows)
    t = totals(rows)
    ce_iv, pe_iv = atm_iv(rows, atm)
    return {
        "symbol": rows[0].get("symbol", ""),
        "expiry": rows[0].get("expiry", ""),
        "spot": round(spot, 2),
        "atm": atm,
        "pcr_oi": pcr(rows, "oi"),
        "pcr_vol": pcr(rows, "vol"),
        "max_pain": pain_strike,
        "max_pain_value": pain_value,
        "oi_support": levels["support"],
        "oi_support_oi": levels["support_oi"],
        "oi_resistance": levels["resistance"],
        "oi_resistance_oi": levels["resistance_oi"],
        "atm_ce_iv": ce_iv,
        "atm_pe_iv": pe_iv,
        "total_ce_oi": t["ce_oi"],
        "total_pe_oi": t["pe_oi"],
        "total_ce_doi": t["ce_doi"],
        "total_pe_doi": t["pe_doi"],
        "total_ce_vol": t["ce_vol"],
        "total_pe_vol": t["pe_vol"],
        "strikes": len(rows),
        "stale": stale,
    }
