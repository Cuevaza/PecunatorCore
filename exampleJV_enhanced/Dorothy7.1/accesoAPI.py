"""Binance client bootstrap — compatible with PecunatorCore credential sources."""

from __future__ import annotations

import os

from binance.client import Client


def _credentials_from_config_module() -> tuple[str, str] | None:
    try:
        import config  # type: ignore[import-not-found]
    except ImportError:
        return None
    ak = str(getattr(config, "api_key", "") or "").strip()
    sec = str(getattr(config, "api_secret", "") or "").strip()
    if ak and sec:
        return ak, sec
    return None


def _credentials_from_env() -> tuple[str, str] | None:
    # Same variable names as `runtime/core/settings.py` for PecunatorCore.
    ak = os.environ.get("PECUNATOR_BINANCE_API_KEY", "").strip()
    sec = os.environ.get("PECUNATOR_BINANCE_API_SECRET", "").strip()
    if ak and sec:
        return ak, sec
    return None


def inicializar_cliente() -> Client:
    """
    Return a configured Binance client.

    Resolution order:
    1. `exampleJV/config.py` (`api_key`, `api_secret`) if present and non-empty
    2. Environment: `PECUNATOR_BINANCE_API_SECRET` + `PECUNATOR_BINANCE_API_KEY`
    """
    pair = _credentials_from_config_module() or _credentials_from_env()
    if not pair:
        raise RuntimeError(
            "No API credentials: create exampleJV/config.py from config.example.py "
            "or set PECUNATOR_BINANCE_API_KEY and PECUNATOR_BINANCE_API_SECRET.",
        )
    api_key, api_secret = pair
    return Client(api_key, api_secret)
