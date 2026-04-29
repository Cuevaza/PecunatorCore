"""Process configuration from environment (no secrets defaulted here)."""

from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_RUNTIME_DIR = Path(__file__).resolve().parent.parent / "data"


def data_dir() -> Path:
    raw = os.environ.get("PECUNATOR_DATA_DIR", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return _DEFAULT_RUNTIME_DIR.resolve()


def binance_credentials_from_env() -> tuple[str, str] | None:
    """
    Optional non-interactive bootstrap. Keys live in the process environment only.
    Prefer the encrypted vault for daily use.
    """
    key = os.environ.get("PECUNATOR_BINANCE_API_KEY", "").strip()
    sec = os.environ.get("PECUNATOR_BINANCE_API_SECRET", "").strip()
    if key and sec:
        return key, sec
    return None


def vault_unlock_password_from_env() -> str | None:
    """
    Optional master password to decrypt credentials.enc (Flutter will send via API later; env for automation).
    """
    raw = os.environ.get("PECUNATOR_VAULT_PASSWORD", "").strip()
    return raw or None


def account_poll_interval_sec() -> float:
    """
    REST+polling cadence while the gateway runs (balances, open orders).
    Defaults to ~1s for low latency; increase if you hit Binance REST rate limits.
    """
    raw = os.environ.get("PECUNATOR_ACCOUNT_POLL_SEC", "1").strip()
    try:
        v = float(raw)
    except ValueError:
        return 1.0
    return max(0.25, min(v, 300.0))


def my_trades_poll_stride() -> int:
    """How many account poll cycles between myTrades fetches (1 = every cycle). Saves weight vs tickers/orderbook counts."""
    raw = os.environ.get("PECUNATOR_MY_TRADES_POLL_STRIDE", "1").strip()
    try:
        n = int(raw, 10)
    except ValueError:
        return 1
    return max(1, min(n, 1000))
