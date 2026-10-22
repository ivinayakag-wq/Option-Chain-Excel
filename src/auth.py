import argparse
import json
import os
import secrets
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests

from .config import TOKEN_PATH, settings

DIALOG_URL = "https://api.upstox.com/v2/login/authorization/dialog"
TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"
IST = timezone(timedelta(hours=5, minutes=30))


def session_end(now: datetime | None = None) -> float:
    moment = now or datetime.now(IST)
    end = moment.replace(hour=3, minute=30, second=0, microsecond=0)
    if end <= moment:
        end += timedelta(days=1)
    return end.timestamp()


class AuthError(Exception):
    pass


class AuthRequired(AuthError):
    def __init__(self, message="Upstox login required", url=""):
        super().__init__(message)
        self.url = url


@dataclass
class Tokens:
    access_token: str
    refresh_token: str = ""
    expires_at: float = 0.0
    raw: dict = field(default_factory=dict)

    def is_valid(self, min_seconds: int = 0) -> bool:
        return bool(self.access_token) and (self.expires_at - time.time()) > min_seconds

    @classmethod
    def from_response(cls, data: dict) -> "Tokens":
        ttl = data.get("expires_in")
        expires_at = time.time() + float(ttl) if ttl else session_end()
        return cls(
            access_token=data.get("access_token", ""),
            refresh_token=data.get("refresh_token", "") or "",
            expires_at=expires_at,
            raw=data,
        )

    def to_dict(self) -> dict:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "updated_at": time.time(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Tokens":
        return cls(
            access_token=data.get("access_token", ""),
            refresh_token=data.get("refresh_token", "") or "",
            expires_at=float(data.get("expires_at") or 0),
            raw=data,
        )


def _error_text(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}: {response.text[:300]}"
    errors = body.get("errors")
    if isinstance(errors, list) and errors:
        parts = [
            f"{e.get('errorCode', '')}: {e.get('message', '')}".strip(": ")
            for e in errors
            if isinstance(e, dict)
        ]
        if parts:
            return f"HTTP {response.status_code}: " + "; ".join(parts)
    message = body.get("message") or body.get("error") or response.text[:300]
    return f"HTTP {response.status_code}: {message}"


class UpstoxAuth:
    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        redirect_uri: str | None = None,
        token_path: Path | None = None,
        timeout: int | None = None,
        session: requests.Session | None = None,
    ):
        self.client_id = client_id if client_id is not None else settings.client_id
        self.client_secret = (
            client_secret if client_secret is not None else settings.client_secret
        )
        self.redirect_uri = (
            redirect_uri if redirect_uri is not None else settings.redirect_uri
        )
        self.token_path = Path(token_path) if token_path else TOKEN_PATH
        self.timeout = timeout or settings.request_timeout
        self.session = session or requests.Session()

    def login_url(self, state: str | None = None) -> str:
        if not self.client_id:
            raise AuthError("UPSTOX_CLIENT_ID is not set (see .env.example)")
        query = urllib.parse.urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "state": state or secrets.token_urlsafe(8),
            }
        )
        return f"{DIALOG_URL}?{query}"

    def _require_credentials(self) -> None:
        if not self.client_id or not self.client_secret:
            raise AuthError(
                "UPSTOX_CLIENT_ID and UPSTOX_CLIENT_SECRET must be set (see .env.example)"
            )

    def _post_token(self, payload: dict) -> Tokens:
        self._require_credentials()
        response = self.session.post(
            TOKEN_URL,
            data=payload,
            headers={"Accept": "application/json"},
            timeout=self.timeout,
        )
        if response.status_code != 200:
            raise AuthError(_error_text(response))
        data = response.json()
        tokens = Tokens.from_response(data)
        self.save(tokens)
        return tokens

    def exchange_code(self, code: str) -> Tokens:
        return self._post_token(
            {
                "code": code.strip(),
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": self.redirect_uri,
                "grant_type": "authorization_code",
            }
        )

    def refresh(self, current: Tokens | None = None) -> Tokens:
        current = current or self.load()
        if not current.refresh_token:
            raise AuthRequired("No refresh token stored", self.login_url())
        payload = {
            "refresh_token": current.refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
        }
        try:
            tokens = self._post_token(payload)
        except AuthError as exc:
            raise AuthRequired(f"Refresh failed: {exc}", self.login_url()) from exc
        if not tokens.refresh_token:
            tokens.refresh_token = current.refresh_token
            self.save(tokens)
        return tokens

    def get_access_token(self, min_valid: int = 300, force_refresh: bool = False) -> str:
        tokens = self.load()
        if not force_refresh and tokens.is_valid(min_valid):
            return tokens.access_token
        if tokens.refresh_token:
            return self.refresh(tokens).access_token
        raise AuthRequired("No valid token", self.login_url())

    def load(self) -> Tokens:
        try:
            data = json.loads(self.token_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return Tokens(access_token="")
        return Tokens.from_dict(data)

    def save(self, tokens: Tokens) -> None:
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.token_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(tokens.to_dict(), indent=2), encoding="utf-8")
        os.replace(tmp, self.token_path)

    def logout(self) -> None:
        try:
            self.token_path.unlink()
        except FileNotFoundError:
            pass

    def status(self) -> dict:
        tokens = self.load()
        return {
            "has_access_token": bool(tokens.access_token),
            "has_refresh_token": bool(tokens.refresh_token),
            "expires_at": tokens.expires_at,
            "expires_in_seconds": max(0, int(tokens.expires_at - time.time())),
            "valid": tokens.is_valid(),
            "credentials_configured": bool(self.client_id and self.client_secret),
            "login_url": self.login_url() if self.client_id else "",
        }


class _CallbackHandler(BaseHTTPRequestHandler):
    result: dict = {}
    expected_path: str = "/callback"

    def log_message(self, *args) -> None:
        pass

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != self.expected_path:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
            return
        params = urllib.parse.parse_qs(parsed.query)
        code = (params.get("code") or [""])[0]
        error = (params.get("error") or [""])[0]
        _CallbackHandler.result = {"code": code, "error": error}
        body = (
            b"<h2>Authorised</h2><p>You can close this tab.</p>"
            if code
            else b"<h2>Authorisation failed</h2><p>Check the terminal.</p>"
        )
        self.send_response(200 if code else 400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)
        threading.Thread(target=self.server.shutdown, daemon=True).start()


def wait_for_code(redirect_uri: str, timeout: int = 300) -> str:
    parsed = urllib.parse.urlparse(redirect_uri)
    if parsed.hostname not in ("127.0.0.1", "localhost"):
        raise AuthError("--serve requires a loopback redirect_uri")
    if not parsed.port:
        raise AuthError("redirect_uri must include an explicit port")
    _CallbackHandler.expected_path = parsed.path or "/callback"
    server = ThreadingHTTPServer((parsed.hostname, parsed.port), _CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        deadline = time.time() + timeout
        while not _CallbackHandler.result and time.time() < deadline:
            time.sleep(0.2)
    finally:
        server.shutdown()
        server.server_close()
    result = _CallbackHandler.result
    if not result:
        raise AuthError(f"Timed out after {timeout}s waiting for the callback")
    if result.get("error"):
        raise AuthError(f"Upstox returned error: {result['error']}")
    code = result.get("code", "")
    if not code:
        raise AuthError("Callback did not contain a code")
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.auth")
    sub = parser.add_subparsers(dest="command", required=True)

    login = sub.add_parser("login", help="Print or open the Upstox login URL")
    login.add_argument("--open", action="store_true", help="Open it in the browser")
    login.add_argument("--serve", action="store_true", help="Capture the callback and save tokens")
    login.add_argument("--timeout", type=int, default=300)

    exchange = sub.add_parser("exchange", help="Exchange a pasted authorisation code")
    exchange.add_argument("code")

    sub.add_parser("status", help="Show stored token status")
    sub.add_parser("logout", help="Delete stored tokens")

    args = parser.parse_args(argv)
    auth = UpstoxAuth()

    if args.command == "login":
        url = auth.login_url()
        print(url)
        if args.serve:
            webbrowser.open(url)
            print("Waiting for the browser callback...", flush=True)
            code = wait_for_code(auth.redirect_uri, args.timeout)
            tokens = auth.exchange_code(code)
            print(f"Saved access token, valid until {time.strftime('%Y-%m-%d %H:%M', time.localtime(tokens.expires_at))}")
        elif args.open:
            webbrowser.open(url)
            print("After approving, copy the code from the redirect URL and run:")
            print("  python -m src.auth exchange <code>")
        else:
            print("After approving, copy the code from the redirect URL and run:")
            print("  python -m src.auth exchange <code>")
        return 0

    if args.command == "exchange":
        tokens = auth.exchange_code(args.code)
        print(f"Saved access token, valid until {time.strftime('%Y-%m-%d %H:%M', time.localtime(tokens.expires_at))}")
        return 0

    if args.command == "status":
        info = auth.status()
        print(json.dumps(info, indent=2))
        return 0

    if args.command == "logout":
        auth.logout()
        print("Tokens deleted")
        return 0

    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AuthError as exc:
        print(f"Error: {exc}")
        print("Set credentials in .env (copy .env.example first):")
        print("  UPSTOX_CLIENT_ID=...")
        print("  UPSTOX_CLIENT_SECRET=...")
        raise SystemExit(2)
