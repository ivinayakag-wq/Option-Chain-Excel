import json
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from src.analytics import summarize
from src.upstox import INDICES, normalize_chain

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "chain_sample.json"
PORT = 8765


def _data():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["data"]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        parts = [p for p in path.split("/") if p]
        if path == "/health":
            self._send({"status": "mock", "symbols": {s: {"rows": 4} for s in INDICES}})
            return
        if path == "/summaries":
            rows = []
            for symbol in INDICES:
                data = normalize_chain(_data(), symbol, 75)
                summary = summarize(data)
                summary["fetched_at"] = time.time()
                summary["age_seconds"] = 0
                summary["lot_size"] = 75
                rows.append(summary)
            self._send({"rows": rows, "errors": {}})
            return
        if len(parts) == 2 and parts[0] in ("chain", "summary"):
            symbol = parts[1].upper()
            if symbol not in INDICES:
                self._send({"detail": "unknown"}, 404)
                return
            rows = normalize_chain(_data(), symbol, 75)
            summary = summarize(rows)
            if parts[0] == "chain":
                self._send(
                    {
                        "symbol": symbol,
                        "expiry": "2026-10-27",
                        "spot": 22743.5,
                        "lot_size": 75,
                        "fetched_at": time.time(),
                        "stale": False,
                        "summary": summary,
                        "rows": rows,
                    }
                )
            else:
                summary["fetched_at"] = time.time()
                summary["age_seconds"] = 0
                summary["lot_size"] = 75
                self._send(summary)
            return
        self._send({"detail": "not found"}, 404)


if __name__ == "__main__":
    print(f"Mock option-chain server on http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
