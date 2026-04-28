"""Entry point: PecunatorCore dashboard + runtime."""

from __future__ import annotations

import os
import secrets
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Optional

from nicegui import ui

from runtime.connectors.binance_gateway import BinanceGateway
from runtime.core.browser_launch import print_dashboard_banner, should_auto_open_browser
from runtime.core.config_manager import ConfigManager
from runtime.core.event_bus import EventBus
from runtime.core.settings import data_dir, http_host, http_port
from runtime.core.state_store import StateStore
from runtime.ui.terminal import TerminalContext


@dataclass
class AppContext:
    bus: EventBus
    state: StateStore
    config: ConfigManager
    gateway: Optional[BinanceGateway] = None
    logs: Deque[str] = field(default_factory=lambda: deque(maxlen=500))
    auto_connect_attempted: bool = False
    """Last successful master password in process memory after unlock (volatile)."""
    cached_master_password: Optional[str] = None

    def log_line(self, msg: str) -> None:
        self.logs.append(msg)

    @property
    def terminal_ctx(self) -> TerminalContext:
        return TerminalContext(self.state, self.gateway, self.logs)


def build_context() -> AppContext:
    return AppContext(
        bus=EventBus(),
        state=StateStore(),
        config=ConfigManager(data_dir()),
    )


def main() -> None:
    from runtime.ui.dashboard import mount  # noqa: PLC0415 — avoid import cycle

    ctx = build_context()
    mount(ctx)
    storage_secret = os.environ.get("PECUNATOR_STORAGE_SECRET") or secrets.token_hex(32)

    bind_host = http_host()
    port = http_port()
    print_dashboard_banner(bind_host, port)

    # NiceGUI's show= uses a background thread that waits for the port — do not open the browser
    # from app.on_startup: Uvicorn does not accept connections until startup hooks finish, so a
    # connect loop there would block or race and cause ERR_CONNECTION_REFUSED.
    open_browser = should_auto_open_browser()

    _dark: bool | None
    _dark_raw = os.environ.get("PECUNATOR_DARK", "1").strip().lower()
    if _dark_raw in ("0", "false", "no", "off", "light"):
        _dark = False
    elif _dark_raw in ("auto",):
        _dark = None
    else:
        _dark = True

    ui.run(
        title="PecunatorCore",
        host=bind_host,
        port=port,
        reload=False,
        show="/" if open_browser else False,
        storage_secret=storage_secret,
        dark=_dark,
    )


if __name__ == "__main__":
    main()
