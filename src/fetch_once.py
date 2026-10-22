import argparse
import sys

from .analytics import summarize
from .upstox import INDICES, UpstoxClient


def run(symbols: list[str], expiry: str) -> int:
    client = UpstoxClient()
    failures = 0
    print(f"{'SYMBOL':<12}{'EXPIRY':<14}{'SPOT':>10}{'STRIKES':>9}{'PCR':>8}{'MAXPAIN':>10}  CACHE")
    for symbol in symbols:
        try:
            snapshot = client.snapshot(symbol, expiry)
            summary = summarize(snapshot.rows, stale=snapshot.stale)
            path = snapshot.save()
            print(
                f"{snapshot.symbol:<12}{snapshot.expiry:<14}{snapshot.spot:>10.2f}"
                f"{len(snapshot.rows):>9}{summary['pcr_oi']:>8.3f}"
                f"{summary['max_pain']:>10.0f}  {path.name}"
            )
        except Exception as exc:
            failures += 1
            print(f"{symbol:<12}{'-':<14}{'-':>10}{'-':>9}{'-':>8}{'-':>10}  FAILED: {exc}")
    return 0 if failures == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch option chains once into data/cache")
    parser.add_argument("symbols", nargs="*", default=None, help="Default: all five indices")
    parser.add_argument("--expiry", default="current_week", help="Keyword or YYYY-MM-DD")
    args = parser.parse_args(argv)
    symbols = [s.upper() for s in args.symbols] or list(INDICES)
    unknown = [s for s in symbols if s not in INDICES]
    if unknown:
        print(f"Unknown symbols: {', '.join(unknown)}. Known: {', '.join(INDICES)}")
        return 2
    return run(symbols, args.expiry)


if __name__ == "__main__":
    sys.exit(main())
