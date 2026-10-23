import argparse
import sys
import time
from datetime import datetime

from .auth import AuthError, AuthRequired, UpstoxAuth
from .build_live_workbook import LIVE_PATH
from .excel_writer import ExcelWriter
from .feed import MarketFeed
from .live_book import LiveBook
from .upstox import INDICES, UpstoxClient, UpstoxError

SUMMARY_FIELDS = (
    "symbol",
    "expiry",
    "spot",
    "atm",
    "pcr_oi",
    "pcr_vol",
    "max_pain",
    "oi_support",
    "oi_resistance",
    "atm_ce_iv",
    "atm_pe_iv",
    "total_ce_oi",
    "total_pe_oi",
    "total_ce_doi",
    "total_pe_doi",
    "strikes",
    "stale",
    "age_seconds",
)


def _clock() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _summary_row(book: LiveBook, age: int) -> list:
    summary = book.summary()
    if not summary:
        return [book.symbol] + [""] * (len(SUMMARY_FIELDS) - 1)
    summary["stale"] = False
    summary["age_seconds"] = age
    return [summary.get(field, "") for field in SUMMARY_FIELDS]


def run(window: int, interval: float, refresh_after: float, path, open_excel: bool, dry: bool, duration: float = 0.0) -> int:
    auth = UpstoxAuth()
    try:
        token = auth.get_access_token()
    except AuthRequired as exc:
        print(f"Login required: {exc.url}")
        print("Approve it in the browser, then run this again.")
        return 2

    client = UpstoxClient(auth)
    books: dict[str, LiveBook] = {}
    for symbol, key in INDICES.items():
        try:
            snapshot = client.snapshot(symbol)
        except (AuthError, UpstoxError) as exc:
            print(f"{symbol}: {exc}")
            return 2
        book = LiveBook(symbol, key, window)
        book.load(snapshot)
        books[symbol] = book
        print(f"{symbol:<11} {snapshot.expiry}  {len(book.rows):>2} strikes around {book.center:,.0f}")

    keys = [key for book in books.values() for key in book.keys()]
    feed = MarketFeed(token, keys)
    feed.start()
    print(f"Feed subscribed: {len(keys)} keys, mode full")

    writer = None
    if not dry:
        writer = ExcelWriter(path, open_if_missing=open_excel, visible=open_excel)
        if not writer.attach():
            print(f"Could not attach to {path}; writing nothing")
            writer = None
        else:
            print(f"Writing into {path}")

    started = time.monotonic()
    last_refresh = started
    last_report = started
    rest_age = 0
    login_banner = ""
    next_tick = time.monotonic()

    try:
        while True:
            if duration and time.monotonic() - started >= duration:
                print("Duration reached")
                break
            now = time.monotonic()
            rest_age = int(now - last_refresh)
            ticks = feed.ticks()
            for book in books.values():
                book.apply(ticks)

            if any([book.recenter() for book in books.values()]):
                feed.set_keys([key for book in books.values() for key in book.keys()])
                print(f"Recenter: {sum(len(b.rows) for b in books.values())} strikes")

            age = now - feed.last_message if feed.last_message else 999.0
            if age < 5:
                state, label = "ok", "LIVE"
            elif age < 30:
                state, label = "stale", "STALE"
            else:
                state, label = "error", "NO FEED"
            if login_banner:
                state, label = "error", login_banner

            if writer is not None:
                stamp = f"{label} {_clock()} | tick {min(age, 99):.1f}s"
                for symbol, book in books.items():
                    spot = book.spot
                    status = f"{stamp} | {symbol} {spot:,.2f} | {len(book.rows)} strikes"
                    writer.write_chain(symbol, book.frame(), status, state)
                rows = [_summary_row(book, rest_age) for book in books.values()]
                status = f"{label} {_clock()} | summary {rest_age}s old | full chain"
                writer.write_summary(rows, status, state)

            if now - last_refresh >= refresh_after:
                last_refresh = now
                changed = False
                for symbol, book in books.items():
                    try:
                        snapshot = client.snapshot(symbol)
                    except AuthRequired:
                        login_banner = "LOGIN http://127.0.0.1:8765/login"
                        break
                    except (AuthError, UpstoxError) as exc:
                        print(f"refresh {symbol}: {exc}")
                        continue
                    changed = book.set_snapshot(snapshot) or changed
                else:
                    login_banner = ""
                    rest_age = 0
                if changed:
                    feed.set_keys([key for book in books.values() for key in book.keys()])

            if now - last_report >= 30:
                last_report = now
                print(
                    f"{_clock()}  msgs {feed.messages}  ticks {feed.tick_count}  "
                    f"restarts {feed.restarts}  age {age:.1f}s  "
                    f"excel {'ok' if writer and writer.ready else 'off'}"
                )

            next_tick += interval
            sleep_for = next_tick - time.monotonic()
            if sleep_for > 0:
                time.sleep(sleep_for)
            else:
                next_tick = time.monotonic()
    except KeyboardInterrupt:
        print("Stopped")
    finally:
        feed.stop()
        if writer is not None:
            writer.save()
        print(
            f"Session: messages {feed.messages}  ticks {feed.tick_count}  "
            f"restarts {feed.restarts}  last error {feed.last_error or '-'}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.live", description="Live option chain into Excel")
    parser.add_argument("--window", type=int, default=10, help="Strikes each side of ATM (default 10)")
    parser.add_argument("--interval", type=float, default=0.5, help="Excel write interval in seconds")
    parser.add_argument("--refresh", type=float, default=60.0, help="Full chain refresh in seconds")
    parser.add_argument("--path", default=str(LIVE_PATH))
    parser.add_argument("--no-open", action="store_true", help="Do not launch Excel if it is not running")
    parser.add_argument("--dry-run", action="store_true", help="No Excel, console only")
    parser.add_argument("--for", type=float, default=0.0, dest="duration", help="Stop after N seconds")
    args = parser.parse_args(argv)
    return run(
        max(2, args.window),
        max(0.2, args.interval),
        max(10.0, args.refresh),
        args.path,
        not args.no_open,
        args.dry_run,
        args.duration,
    )


if __name__ == "__main__":
    sys.exit(main())
