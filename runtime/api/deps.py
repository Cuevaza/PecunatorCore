"""Shared FastAPI dependencies and process-wide `AppContext`."""

from __future__ import annotations

from typing import Optional

from runtime.app import AppContext, build_context

_ctx: Optional[AppContext] = None


def init_context() -> AppContext:
    global _ctx
    if _ctx is None:
        _ctx = build_context()
    return _ctx


def get_ctx() -> AppContext:
    if _ctx is None:
        raise RuntimeError("AppContext not initialized (lifespan did not run)")
    return _ctx


def peek_ctx() -> Optional[AppContext]:
    return _ctx
