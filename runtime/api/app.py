"""FastAPI application: vault session, gateway lifecycle, read-only snapshot."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from runtime.api import deps
from runtime.api.schemas import (
    GatewaySnapshotOut,
    GatewayStartBody,
    VaultSessionBody,
    VaultStatusOut,
)
from runtime.app import AppContext
from runtime.connectors.binance_gateway import BinanceGateway
from runtime.core.security_util import sanitize_log_message
from runtime.core.settings import (
    api_bind_host_for_cors_regex,
    binance_credentials_from_env,
    vault_unlock_password_from_env,
)

_LOG = logging.getLogger("pecunator.api")


def _mask_pk(pk: str) -> str:
    s = pk.strip()
    return s if len(s) <= 24 else f"{s[:14]}…{s[-6:]}"


@asynccontextmanager
async def _lifespan(app: FastAPI):
    deps.init_context()
    mp = vault_unlock_password_from_env()
    if mp:
        ctx = deps.get_ctx()
        ctx.cached_master_password = mp
        _LOG.info("Cached master password loaded from PECUNATOR_VAULT_PASSWORD env")
    yield
    ctx = deps.peek_ctx()
    if ctx and ctx.gateway:
        try:
            await ctx.gateway.stop()
        except Exception as e:
            _LOG.warning("gateway stop on shutdown: %s", e)
        ctx.gateway = None


def create_app() -> FastAPI:
    app = FastAPI(
        title="PecunatorCore Engine API",
        description="Local HTTP API for the Flutter shell. Bind loopback only unless you know the risk.",
        version="0.2.0",
        lifespan=_lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=api_bind_host_for_cors_regex(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        ctx = deps.get_ctx()
        return {"status": "ok", "data_dir": str(ctx.config.data_dir)}

    @app.get("/api/v1/vault/status", response_model=VaultStatusOut)
    async def vault_status(ctx: AppContext = Depends(deps.get_ctx)) -> Any:
        pubs = ctx.config.list_public_credentials()
        return VaultStatusOut(
            vault_file_exists=ctx.config.exists(),
            credential_rows=len(pubs),
            active_credential_id=ctx.config.get_active_credential_id(),
            session_cached=bool(ctx.cached_master_password),
        )

    @app.get("/api/v1/vault/credentials")
    async def vault_credentials(ctx: AppContext = Depends(deps.get_ctx)) -> list[dict[str, str]]:
        return [
            {"id": p["id"], "public_key": p["public_key"], "public_key_short": _mask_pk(p["public_key"])}
            for p in ctx.config.list_public_credentials()
        ]

    @app.post("/api/v1/vault/session")
    async def vault_session(body: VaultSessionBody, ctx: AppContext = Depends(deps.get_ctx)) -> dict[str, bool]:
        if not ctx.config.exists():
            raise HTTPException(status_code=400, detail="No vault file; add credentials first.")
        try:
            pair = ctx.config.get_pair_for_active(body.master_password)
        except ValueError as e:
            raise HTTPException(status_code=401, detail=str(e)) from None
        if not pair:
            raise HTTPException(status_code=401, detail="Vault empty or invalid password")
        ctx.cached_master_password = body.master_password
        return {"unlocked": True}

    @app.delete("/api/v1/vault/session")
    async def vault_session_clear(ctx: AppContext = Depends(deps.get_ctx)) -> dict[str, bool]:
        ctx.cached_master_password = None
        return {"unlocked": False}

    @app.post("/api/v1/gateway/start")
    async def gateway_start(
        body: GatewayStartBody = GatewayStartBody(),
        ctx: AppContext = Depends(deps.get_ctx),
    ) -> GatewaySnapshotOut:
        mp = (body.master_password or "") or ctx.cached_master_password or ""
        mp = (mp or "").strip()
        pair = binance_credentials_from_env()
        if not pair:
            if not mp:
                raise HTTPException(status_code=400, detail="Provide vault session or master_password, or set env keys.")
            try:
                pair = ctx.config.get_pair_for_active(mp)
            except ValueError as e:
                raise HTTPException(status_code=401, detail=str(e)) from None
            if pair:
                ctx.cached_master_password = mp
        if not pair:
            raise HTTPException(status_code=400, detail="No API credentials available")
        if ctx.gateway:
            await ctx.gateway.stop()
            ctx.gateway = None
        ak, sec = pair
        gw = BinanceGateway(ak, sec, ctx.bus, ctx.state, ctx.log_line)
        try:
            await gw.start()
            await gw.fetch_account()
        except Exception as e:
            try:
                await gw.stop()
            except Exception:
                pass
            ctx.state.last_error = sanitize_log_message(str(e))
            raise HTTPException(status_code=502, detail=ctx.state.last_error) from None
        ctx.gateway = gw
        ctx.state.last_error = None
        return _snapshot(ctx)

    @app.post("/api/v1/gateway/stop")
    async def gateway_stop(ctx: AppContext = Depends(deps.get_ctx)) -> dict[str, bool]:
        if ctx.gateway:
            await ctx.gateway.stop()
            ctx.gateway = None
            ctx.state.connected = False
        return {"stopped": True}

    @app.post("/api/v1/gateway/fetch_account")
    async def gateway_fetch(ctx: AppContext = Depends(deps.get_ctx)) -> GatewaySnapshotOut:
        if not ctx.gateway:
            raise HTTPException(status_code=400, detail="Gateway not running")
        await ctx.gateway.fetch_account()
        return _snapshot(ctx)

    @app.get("/api/v1/gateway/snapshot", response_model=GatewaySnapshotOut)
    async def gateway_snapshot(ctx: AppContext = Depends(deps.get_ctx)) -> Any:
        return _snapshot(ctx)

    return app


def _snapshot(ctx: AppContext) -> GatewaySnapshotOut:
    return GatewaySnapshotOut(
        gateway_running=ctx.gateway is not None,
        last_error=ctx.state.last_error,
        account_summary=dict(ctx.state.account_summary or {}),
        balances=list(ctx.state.balances),
        balances_total_assets_in_response=int(getattr(ctx.state, "balances_total_assets_in_response", 0) or 0),
        ws_connected=bool(ctx.state.connected),
        selected_symbol=ctx.state.selected_symbol,
    )
