"""Shared FastAPI dependencies and process-wide `AppContext`."""

from __future__ import annotations

from typing import Optional

from runtime.api.bot_service import BotService
from runtime.app import AppContext, build_context

_ctx: Optional[AppContext] = None
_bot: BotService = BotService()


def init_context() -> AppContext:
    global _ctx
    if _ctx is None:
        _ctx = build_context()
        _bot.attach_data_dir(_ctx.config.data_dir)
    return _ctx


def get_ctx() -> AppContext:
    if _ctx is None:
        raise RuntimeError("AppContext not initialized (lifespan did not run)")
    return _ctx


def peek_ctx() -> Optional[AppContext]:
    return _ctx


def get_bot() -> BotService:
    return _bot
