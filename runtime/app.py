"""Process context: engine state (connectors, vault, event bus). Web UI removed; Flutter is the shell."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Optional

from runtime.connectors.binance_gateway import BinanceGateway
from runtime.core.config_manager import ConfigManager
from runtime.core.event_bus import EventBus
from runtime.core.settings import data_dir
from runtime.core.state_store import StateStore


@dataclass
class AppContext:
    bus: EventBus
    state: StateStore
    config: ConfigManager
    gateway: Optional[BinanceGateway] = None
    logs: Deque[str] = field(default_factory=lambda: deque(maxlen=500))
    auto_connect_attempted: bool = False
    """Volatile: last master password used successfully in this process, if any."""
    cached_master_password: Optional[str] = None

    def log_line(self, msg: str) -> None:
        self.logs.append(msg)


def build_context() -> AppContext:
    return AppContext(
        bus=EventBus(),
        state=StateStore(),
        config=ConfigManager(data_dir()),
    )
