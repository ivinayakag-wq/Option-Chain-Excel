import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
TOKEN_PATH = DATA_DIR / "tokens.json"


def load_env(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


load_env()


@dataclass(frozen=True)
class Settings:
    client_id: str = os.environ.get("UPSTOX_CLIENT_ID", "")
    client_secret: str = os.environ.get("UPSTOX_CLIENT_SECRET", "")
    redirect_uri: str = os.environ.get(
        "UPSTOX_REDIRECT_URI", "http://127.0.0.1:8765/callback"
    )
    host: str = os.environ.get("OC_HOST", "127.0.0.1")
    port: int = int(os.environ.get("OC_PORT", "8765"))
    request_timeout: int = int(os.environ.get("OC_TIMEOUT", "20"))


settings = Settings()
