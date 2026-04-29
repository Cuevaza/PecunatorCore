"""FastAPI application: vault session, gateway lifecycle, read-only snapshot."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from binance.client import Client
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from runtime.api import deps
from runtime.api.schemas import (
    BotConfigBody,
    BotConfigOut,
    BotStatusOut,
    GatewaySnapshotOut,
    GatewayStartBody,
    TerminalExecBody,
    TerminalExecOut,
    TimeSyncBody,
    TimeSyncOut,
    VaultSessionBody,
    VaultStatusOut,
)
from runtime.app import AppContext
from runtime.connectors.binance_gateway import BinanceGateway
from runtime.core.master_remember import load_remembered_master, save_remembered_master
from runtime.core.security_util import sanitize_log_message
from runtime.core.settings import (
    api_bind_host_for_cors_regex,
    binance_credentials_from_env,
    remember_master_password_enabled,
    vault_unlock_password_from_env,
)

_LOG = logging.getLogger("pecunator.api")


def _mask_pk(pk: str) -> str:
    s = pk.strip()
    return s if len(s) <= 24 else f"{s[:14]}…{s[-6:]}"


@asynccontextmanager
async def _lifespan(app: FastAPI):
    deps.init_context()
    ctx = deps.get_ctx()
    mp = vault_unlock_password_from_env()
    if mp:
        ctx.cached_master_password = mp
        _LOG.info("Cached master password loaded from PECUNATOR_VAULT_PASSWORD env")
    elif remember_master_password_enabled():
        remembered = load_remembered_master(ctx.config.data_dir)
        if remembered:
            ctx.cached_master_password = remembered
            _LOG.info("Cached master password loaded from device remember store")
    yield
    ctx = deps.peek_ctx()
    bot = deps.get_bot()
    await bot.runner.stop()
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
        version="0.3.0",
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

    @app.get("/api/v1/bot/presets")
    async def bot_presets() -> list[dict[str, Any]]:
        return [
            {
                "preset_id": "B",
                "name": "Dorothy7 preset B (exampleJV)",
                "symbol": "XRPUSDT",
                "loop_interval_sec": 450,
                "quote_order_qty": "8",
                "profit_factor": "0.05",
                "margin_drop_factor": "0.004",
                "qty_decimals": 8,
                "price_decimals": 4,
                "simulated": True,
                "trading_enabled": False,
            }
        ]

    @app.get("/api/v1/bot/config", response_model=BotConfigOut)
    async def bot_config_get() -> Any:
        cfg = deps.get_bot().get_config()
        return BotConfigOut(**cfg.as_json())

    @app.put("/api/v1/bot/config", response_model=BotConfigOut)
    async def bot_config_set(body: BotConfigBody) -> Any:
        svc = deps.get_bot()
        cfg = svc.set_config(
            symbol=body.symbol,
            loop_interval_sec=body.loop_interval_sec,
            quote_order_qty=body.quote_order_qty,
            profit_factor=body.profit_factor,
            margin_drop_factor=body.margin_drop_factor,
            qty_decimals=body.qty_decimals,
            price_decimals=body.price_decimals,
            simulated=body.simulated,
            trading_enabled=body.trading_enabled,
        )
        return BotConfigOut(**cfg.as_json())

    @app.get("/api/v1/bot/status", response_model=BotStatusOut)
    async def bot_status() -> Any:
        return BotStatusOut(**deps.get_bot().status_payload())

    @app.post("/api/v1/terminal/execute", response_model=TerminalExecOut)
    async def terminal_execute(
        body: TerminalExecBody,
        ctx: AppContext = Depends(deps.get_ctx),
    ) -> Any:
        output = await _execute_terminal_command(ctx, body.command, body.master_password)
        return TerminalExecOut(ok=True, command=body.command, output=output)

    @app.post("/api/v1/time/sync", response_model=TimeSyncOut)
    async def time_sync(
        body: TimeSyncBody = TimeSyncBody(),
        ctx: AppContext = Depends(deps.get_ctx),
    ) -> Any:
        payload = await _sync_binance_time(ctx, body.master_password)
        return TimeSyncOut(ok=True, **payload)

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
        if remember_master_password_enabled():
            save_remembered_master(ctx.config.data_dir, body.master_password)
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
        pair = _resolve_pair(ctx, body.master_password)
        if not pair:
            raise HTTPException(status_code=400, detail="No API credentials available")
        if ctx.gateway:
            await ctx.gateway.stop()
            ctx.gateway = None
        ak, sec = pair
        gw = BinanceGateway(ak, sec, ctx.bus, ctx.state, ctx.log_line)
        try:
            await gw.start()
            await gw.sync_time()
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

    @app.post("/api/v1/bot/start", response_model=BotStatusOut)
    async def bot_start(
        body: GatewayStartBody = GatewayStartBody(),
        ctx: AppContext = Depends(deps.get_ctx),
    ) -> Any:
        svc = deps.get_bot()
        pair = _resolve_pair(ctx, body.master_password)
        if not pair:
            raise HTTPException(status_code=400, detail="No API credentials available")
        svc.runner.set_credentials(pair[0], pair[1])
        try:
            await svc.runner.sync_time()
            await svc.runner.start()
        except Exception as e:
            raise HTTPException(status_code=502, detail=sanitize_log_message(str(e))) from None
        return BotStatusOut(**svc.status_payload())

    @app.post("/api/v1/bot/stop", response_model=BotStatusOut)
    async def bot_stop() -> Any:
        svc = deps.get_bot()
        await svc.runner.stop()
        return BotStatusOut(**svc.status_payload())

    @app.post("/api/v1/bot/run_once", response_model=BotStatusOut)
    async def bot_run_once(
        body: GatewayStartBody = GatewayStartBody(),
        ctx: AppContext = Depends(deps.get_ctx),
    ) -> Any:
        svc = deps.get_bot()
        pair = _resolve_pair(ctx, body.master_password)
        if not pair:
            raise HTTPException(status_code=400, detail="No API credentials available")
        svc.runner.set_credentials(pair[0], pair[1])
        try:
            await svc.runner.sync_time()
            rep = await svc.runner.run_once()
            svc.mark_run_once(rep, error=None)
        except Exception as e:
            msg = sanitize_log_message(str(e))
            svc.mark_run_once({}, error=msg)
            raise HTTPException(status_code=502, detail=msg) from None
        return BotStatusOut(**svc.status_payload())

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


def _resolve_pair(ctx: AppContext, master_password: str | None) -> tuple[str, str] | None:
    mp = (master_password or "") or ctx.cached_master_password or ""
    mp = (mp or "").strip()
    pair = binance_credentials_from_env()
    if pair:
        return pair
    if not mp:
        return None
    try:
        pair = ctx.config.get_pair_for_active(mp)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from None
    if pair:
        ctx.cached_master_password = mp
        if remember_master_password_enabled():
            save_remembered_master(ctx.config.data_dir, mp)
    return pair


async def _execute_terminal_command(
    ctx: AppContext,
    command: str,
    master_password: str | None,
) -> str:
    cmd = " ".join((command or "").strip().split())
    if not cmd:
        return ""
    parts = cmd.split()
    key = parts[0].lower()
    rest = parts[1:]
    bot = deps.get_bot()

    if key in ("help", "?"):
        return (
            "Commands:\n"
            "  help\n"
            "  health\n"
            "  time sync [master]\n"
            "  vault status\n"
            "  vault unlock <master>\n"
            "  gateway start|stop|snapshot|fetch [master]\n"
            "  bot status|start|stop|run_once [master]\n"
            "  account\n"
            "  balances\n"
            "  open_orders\n"
            "  my_trades [SYMBOL]\n"
            "  price SYMBOL"
        )

    if key == "health":
        return "ok"

    if key == "time":
        if not rest or rest[0].lower() != "sync":
            return "usage: time sync [master]"
        mp = (rest[1] if len(rest) > 1 else None) or master_password
        payload = await _sync_binance_time(ctx, mp)
        return (
            f"time synced ({payload['source']}): local={payload['local_time_ms']} "
            f"server={payload['server_time_ms']} offset_ms={payload['offset_ms']}"
        )

    if key == "vault":
        if not rest:
            return "usage: vault status | vault unlock <master>"
        sub = rest[0].lower()
        if sub == "status":
            pubs = ctx.config.list_public_credentials()
            return (
                f"vault_exists={ctx.config.exists()} rows={len(pubs)} "
                f"active={ctx.config.get_active_credential_id() or '-'} "
                f"session_cached={bool(ctx.cached_master_password)}"
            )
        if sub == "unlock":
            mp = " ".join(rest[1:]).strip() if len(rest) > 1 else (master_password or "").strip()
            if not mp:
                return "master password required"
            try:
                pair = ctx.config.get_pair_for_active(mp)
            except ValueError as e:
                return sanitize_log_message(str(e))
            if not pair:
                return "vault unlocked but no active credential"
            ctx.cached_master_password = mp
            return "vault unlocked"
        return "usage: vault status | vault unlock <master>"

    if key == "gateway":
        if not rest:
            return "usage: gateway start|stop|snapshot|fetch [master]"
        sub = rest[0].lower()
        if sub == "start":
            mp = (rest[1] if len(rest) > 1 else None) or master_password
            pair = _resolve_pair(ctx, mp)
            if not pair:
                return "no credentials available"
            if ctx.gateway:
                await ctx.gateway.stop()
                ctx.gateway = None
            gw = BinanceGateway(pair[0], pair[1], ctx.bus, ctx.state, ctx.log_line)
            try:
                await gw.start()
                await gw.sync_time()
                await gw.fetch_account()
            except Exception as e:
                try:
                    await gw.stop()
                except Exception:
                    pass
                return sanitize_log_message(str(e))
            ctx.gateway = gw
            return "gateway started"
        if sub == "stop":
            if ctx.gateway:
                await ctx.gateway.stop()
                ctx.gateway = None
            return "gateway stopped"
        if sub == "snapshot":
            s = _snapshot(ctx)
            return (
                f"running={s.gateway_running} ws={s.ws_connected} "
                f"balances={len(s.balances)} last_error={s.last_error or '-'}"
            )
        if sub == "fetch":
            if not ctx.gateway:
                return "gateway not running"
            await ctx.gateway.fetch_account()
            return f"account refreshed; balances={len(ctx.state.balances)}"
        return "usage: gateway start|stop|snapshot|fetch [master]"

    if key == "bot":
        if not rest:
            return "usage: bot status|start|stop|run_once [master]"
        sub = rest[0].lower()
        if sub == "status":
            st = bot.status_payload()
            return (
                f"running={st['running']} simulated={st['simulated']} "
                f"trading_enabled={st['trading_enabled']} symbol={st['symbol']}"
            )
        if sub in ("start", "run_once"):
            mp = (rest[1] if len(rest) > 1 else None) or master_password
            pair = _resolve_pair(ctx, mp)
            if not pair:
                return "no credentials available"
            bot.runner.set_credentials(pair[0], pair[1])
            try:
                if sub == "start":
                    await bot.runner.sync_time()
                    await bot.runner.start()
                    return "bot loop started"
                await bot.runner.sync_time()
                rep = await bot.runner.run_once()
                bot.mark_run_once(rep, error=None)
                return f"run_once: {rep.get('decision', '-')}"
            except Exception as e:
                msg = sanitize_log_message(str(e))
                bot.mark_run_once({}, error=msg)
                return msg
        if sub == "stop":
            await bot.runner.stop()
            return "bot loop stopped"
        return "usage: bot status|start|stop|run_once [master]"

    if key == "account":
        if not ctx.gateway:
            return "gateway not running"
        await ctx.gateway.fetch_account()
        s = ctx.state.account_summary or {}
        return (
            f"accountType={s.get('accountType', '-')} "
            f"canTrade={s.get('canTrade', '-')} "
            f"balances_non_zero={len(ctx.state.balances)}"
        )

    if key == "balances":
        if not ctx.gateway:
            return "gateway not running"
        await ctx.gateway.fetch_account()
        if not ctx.state.balances:
            return "(empty)"
        lines = [
            f"{b.get('asset','?'):6} free={b.get('free','0'):>14} locked={b.get('locked','0'):>14}"
            for b in ctx.state.balances
        ]
        return "\n".join(lines)

    if key == "open_orders":
        if not ctx.gateway:
            return "gateway not running"
        await ctx.gateway.fetch_open_orders()
        ods = ctx.state.open_orders
        if not ods:
            return "(no open orders)"
        return "\n".join(
            f"{o.get('symbol')} {o.get('side')} {o.get('type')} qty={o.get('origQty')} price={o.get('price')}"
            for o in ods
        )

    if key == "my_trades":
        if not ctx.gateway:
            return "gateway not running"
        sym = rest[0] if rest else ctx.state.selected_symbol
        try:
            await ctx.gateway.fetch_my_trades(sym)
        except Exception as e:
            return sanitize_log_message(str(e))
        mts = ctx.state.my_trades
        if not mts:
            return "(no trades)"
        lines = [
            f"{t.get('time')} {'BUY' if t.get('isBuyer') else 'SELL'} qty={t.get('qty')} price={t.get('price')}"
            for t in mts[-20:]
        ]
        return "\n".join(lines)

    if key == "price":
        if len(rest) < 1:
            return "usage: price SYMBOL"
        if not ctx.gateway:
            return "gateway not running"
        bk = await ctx.gateway.fetch_book_ticker(rest[0])
        if not bk:
            return "could not fetch bookTicker"
        return f"{rest[0].upper()} bid={bk.get('bidPrice')} ask={bk.get('askPrice')}"

    return f"unknown command: {key}. type 'help'."


async def _sync_binance_time(ctx: AppContext, master_password: str | None) -> dict[str, Any]:
    bot = deps.get_bot()
    if ctx.gateway:
        payload = await ctx.gateway.sync_time()
        if bot.runner.running:
            try:
                await bot.runner.sync_time()
            except Exception:
                pass
        return payload

    pair = _resolve_pair(ctx, master_password)
    if not pair:
        raise HTTPException(status_code=400, detail="No API credentials available")

    client = Client(pair[0], pair[1], requests_params={"timeout": 10})
    try:
        data = await asyncio.to_thread(client.get_server_time)
        server_ms = int(data.get("serverTime", 0) or 0)
        local_ms = int(time.time() * 1000)
        offset_ms = server_ms - local_ms
        try:
            client.timestamp_offset = offset_ms
        except Exception:
            pass
        if bot.runner.running:
            try:
                await bot.runner.sync_time()
            except Exception:
                pass
        return {
            "source": "one_shot",
            "local_time_ms": local_ms,
            "server_time_ms": server_ms,
            "offset_ms": offset_ms,
        }
    except Exception as e:
        msg = sanitize_log_message(str(e))
        raise HTTPException(status_code=502, detail=msg) from None
    finally:
        try:
            await asyncio.to_thread(client.close_connection)
        except Exception:
            pass
