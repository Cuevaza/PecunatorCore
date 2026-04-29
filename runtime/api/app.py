"""FastAPI application: vault session, gateway lifecycle, read-only snapshot."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from decimal import Decimal, InvalidOperation
from typing import Any

from binance.client import Client
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from runtime.api import deps
from runtime.api.schemas import (
    ActiveCredentialOut,
    BotConfigBody,
    BotConfigOut,
    BotStatusOut,
    GatewaySnapshotOut,
    GatewayStartBody,
    HubBotCreateBody,
    HubBotLogsOut,
    HubBotOut,
    HubBotsOut,
    HubBotUpdateBody,
    TerminalExecBody,
    TerminalExecOut,
    TimeSyncBody,
    TimeSyncOut,
    VaultSessionBody,
    VaultCredentialDeleteBody,
    VaultCredentialLabelBody,
    VaultCredentialUpsertBody,
    VaultStatusOut,
)
from runtime.app import AppContext
from runtime.connectors.binance_gateway import BinanceGateway
from runtime.core.master_remember import load_remembered_master, save_remembered_master
from runtime.core.security_util import sanitize_log_message
from runtime.core.settings import (
    api_bind_host_for_cors_regex,
    api_weight_limit_1m_display,
    binance_credentials_from_env,
    remember_master_password_enabled,
    vault_unlock_password_from_env,
)

_LOG = logging.getLogger("pecunator.api")


def _mask_pk(pk: str) -> str:
    s = pk.strip()
    return s if len(s) <= 24 else f"{s[:14]}…{s[-6:]}"


def _pk_last4(pk: str) -> str:
    s = (pk or "").strip()
    return s[-4:] if len(s) >= 4 else s


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
    await _autostart_gateway_if_possible(ctx)
    yield
    ctx = deps.peek_ctx()
    bot = deps.get_bot()
    await bot.stop_all()
    if ctx and ctx.gateway:
        try:
            await ctx.gateway.stop()
        except Exception as e:
            _LOG.warning("gateway stop on shutdown: %s", e)
        ctx.gateway = None


async def _autostart_gateway_if_possible(ctx: AppContext) -> None:
    if ctx.gateway is not None:
        return
    try:
        pair = _resolve_pair(ctx, None)
    except HTTPException:
        pair = None
    except Exception as e:
        _LOG.warning("Gateway auto-start resolve skipped: %s", sanitize_log_message(str(e)))
        pair = None
    if not pair:
        _LOG.info("Gateway auto-start skipped: no credentials resolved")
        return
    gw = BinanceGateway(pair[0], pair[1], ctx.bus, ctx.state, ctx.log_line)
    try:
        await gw.start()
        await gw.sync_time()
        await gw.fetch_account()
        ctx.gateway = gw
        ctx.state.last_error = None
        _LOG.info("Gateway auto-started on API startup")
    except Exception as e:
        try:
            await gw.stop()
        except Exception:
            pass
        ctx.state.last_error = sanitize_log_message(str(e))
        _LOG.warning("Gateway auto-start failed: %s", ctx.state.last_error)


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
            {
                "id": p["id"],
                "public_key": p["public_key"],
                "public_key_short": _mask_pk(p["public_key"]),
                "label": p.get("label", ""),
            }
            for p in ctx.config.list_public_credentials()
        ]

    @app.post("/api/v1/vault/credentials")
    async def vault_credentials_add(
        body: VaultCredentialUpsertBody,
        ctx: AppContext = Depends(deps.get_ctx),
    ) -> dict[str, Any]:
        mp = _resolve_master_for_vault(ctx, body.master_password)
        try:
            cid, updated = ctx.config.add_credential(
                body.api_key,
                body.api_secret,
                mp,
                label=body.label or "",
            )
        except ValueError as e:
            raise HTTPException(status_code=401, detail=str(e)) from None
        pubs = ctx.config.list_public_credentials()
        row = next((p for p in pubs if p.get("id") == cid), None)
        return {
            "id": cid,
            "updated_existing": bool(updated),
            "label": (row or {}).get("label", body.label or ""),
        }

    @app.patch("/api/v1/vault/credentials/{credential_id}")
    async def vault_credentials_update_label(
        credential_id: str,
        body: VaultCredentialLabelBody,
        ctx: AppContext = Depends(deps.get_ctx),
    ) -> dict[str, Any]:
        mp = _resolve_master_for_vault(ctx, body.master_password)
        ok = ctx.config.update_credential_label(credential_id, body.label or "", mp)
        if not ok:
            raise HTTPException(status_code=404, detail="Credential not found")
        return {"updated": True}

    @app.post("/api/v1/vault/credentials/{credential_id}/activate")
    async def vault_credentials_activate(
        credential_id: str,
        ctx: AppContext = Depends(deps.get_ctx),
    ) -> dict[str, Any]:
        pubs = ctx.config.list_public_credentials()
        exists = any(str(p.get("id")) == credential_id for p in pubs)
        if not exists:
            raise HTTPException(status_code=404, detail="Credential not found")
        ctx.config.set_active_credential_id(credential_id)
        return {"active": True, "active_credential_id": credential_id}

    @app.post("/api/v1/vault/credentials/{credential_id}/delete")
    async def vault_credentials_delete(
        credential_id: str,
        body: VaultCredentialDeleteBody = VaultCredentialDeleteBody(),
        ctx: AppContext = Depends(deps.get_ctx),
    ) -> dict[str, Any]:
        mp = _resolve_master_for_vault(ctx, body.master_password)
        try:
            ok = ctx.config.remove_credential(credential_id, mp)
        except ValueError as e:
            raise HTTPException(status_code=401, detail=str(e)) from None
        if not ok:
            raise HTTPException(status_code=404, detail="Credential not found")
        return {"deleted": True}

    @app.get("/api/v1/credentials/active", response_model=ActiveCredentialOut)
    async def active_credential(ctx: AppContext = Depends(deps.get_ctx)) -> Any:
        active_id = ctx.config.get_active_credential_id()
        pubs = ctx.config.list_public_credentials()
        active_pub = next((p for p in pubs if p.get("id") == active_id), None)
        active_label = (active_pub or {}).get("label", "") or None
        if ctx.active_api_key_hint:
            return ActiveCredentialOut(
                source=ctx.active_api_key_source or "runtime",
                public_key_hint=ctx.active_api_key_hint,
                public_key_last4=ctx.active_api_key_last4 or _pk_last4(ctx.active_api_key_hint),
                active_credential_id=active_id,
                label=active_label,
            )
        env_pair = binance_credentials_from_env()
        if env_pair:
            return ActiveCredentialOut(
                source="env",
                public_key_hint=_mask_pk(env_pair[0]),
                public_key_last4=_pk_last4(env_pair[0]),
                active_credential_id=active_id,
                label=active_label,
            )
        mp = (ctx.cached_master_password or "").strip()
        if mp:
            try:
                pair = ctx.config.get_pair_for_active(mp)
            except ValueError:
                pair = None
            if pair:
                return ActiveCredentialOut(
                    source="vault",
                    public_key_hint=_mask_pk(pair[0]),
                    public_key_last4=_pk_last4(pair[0]),
                    active_credential_id=active_id,
                    label=active_label,
                )
        return ActiveCredentialOut(
            source="none",
            public_key_hint="-",
            public_key_last4="-",
            active_credential_id=active_id,
            label=active_label,
        )

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
            note=body.note,
            simulated=body.simulated,
            trading_enabled=body.trading_enabled,
        )
        return BotConfigOut(**cfg.as_json())

    @app.get("/api/v1/bot/status", response_model=BotStatusOut)
    async def bot_status() -> Any:
        return BotStatusOut(**deps.get_bot().status_payload())

    @app.get("/api/v1/hub/bots", response_model=HubBotsOut)
    async def hub_bots_list() -> Any:
        return HubBotsOut(bots=[HubBotOut(**row) for row in deps.get_bot().list_instances()])

    @app.post("/api/v1/hub/bots", response_model=HubBotOut)
    async def hub_bots_create(body: HubBotCreateBody) -> Any:
        svc = deps.get_bot()
        try:
            row = svc.create_instance(
                bot_id=body.bot_id,
                tag=body.tag,
                symbol=body.symbol,
                loop_interval_sec=body.loop_interval_sec,
                quote_order_qty=body.quote_order_qty,
                profit_factor=body.profit_factor,
                margin_drop_factor=body.margin_drop_factor,
                qty_decimals=body.qty_decimals,
                price_decimals=body.price_decimals,
                note=body.note,
                simulated=body.simulated,
                trading_enabled=body.trading_enabled,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=sanitize_log_message(str(e))) from None
        return HubBotOut(**row)

    @app.patch("/api/v1/hub/bots/{bot_id}", response_model=HubBotOut)
    async def hub_bots_update(bot_id: str, body: HubBotUpdateBody) -> Any:
        svc = deps.get_bot()
        try:
            row = svc.update_instance(
                bot_id,
                tag=body.tag,
                symbol=body.symbol,
                loop_interval_sec=body.loop_interval_sec,
                quote_order_qty=body.quote_order_qty,
                profit_factor=body.profit_factor,
                margin_drop_factor=body.margin_drop_factor,
                qty_decimals=body.qty_decimals,
                price_decimals=body.price_decimals,
                note=body.note,
                simulated=body.simulated,
                trading_enabled=body.trading_enabled,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="Bot not found") from None
        except Exception as e:
            raise HTTPException(status_code=400, detail=sanitize_log_message(str(e))) from None
        return HubBotOut(**row)

    @app.delete("/api/v1/hub/bots/{bot_id}")
    async def hub_bots_delete(bot_id: str) -> dict[str, bool]:
        svc = deps.get_bot()
        try:
            await svc.delete_instance(bot_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Bot not found") from None
        return {"deleted": True}

    @app.post("/api/v1/hub/bots/{bot_id}/start", response_model=HubBotOut)
    async def hub_bots_start(
        bot_id: str,
        body: GatewayStartBody = GatewayStartBody(),
        ctx: AppContext = Depends(deps.get_ctx),
    ) -> Any:
        pair = _resolve_pair(ctx, body.master_password, body.api_key, body.api_secret)
        if not pair:
            raise HTTPException(status_code=400, detail="No API credentials available")
        try:
            row = await deps.get_bot().start_instance(bot_id, pair[0], pair[1])
        except KeyError:
            raise HTTPException(status_code=404, detail="Bot not found") from None
        except Exception as e:
            raise HTTPException(status_code=502, detail=sanitize_log_message(str(e))) from None
        return HubBotOut(**row)

    @app.post("/api/v1/hub/bots/{bot_id}/stop", response_model=HubBotOut)
    async def hub_bots_stop(bot_id: str) -> Any:
        try:
            row = await deps.get_bot().stop_instance(bot_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Bot not found") from None
        return HubBotOut(**row)

    @app.post("/api/v1/hub/bots/{bot_id}/run_once", response_model=HubBotOut)
    async def hub_bots_run_once(
        bot_id: str,
        body: GatewayStartBody = GatewayStartBody(),
        ctx: AppContext = Depends(deps.get_ctx),
    ) -> Any:
        pair = _resolve_pair(ctx, body.master_password, body.api_key, body.api_secret)
        if not pair:
            raise HTTPException(status_code=400, detail="No API credentials available")
        try:
            row = await deps.get_bot().run_once_instance(bot_id, pair[0], pair[1])
        except KeyError:
            raise HTTPException(status_code=404, detail="Bot not found") from None
        except Exception as e:
            raise HTTPException(status_code=502, detail=sanitize_log_message(str(e))) from None
        return HubBotOut(**row)

    @app.get("/api/v1/hub/bots/{bot_id}/logs", response_model=HubBotLogsOut)
    async def hub_bots_logs(bot_id: str, limit: int = 200) -> Any:
        try:
            rows = deps.get_bot().get_logs(bot_id, limit=limit)
        except KeyError:
            raise HTTPException(status_code=404, detail="Bot not found") from None
        return HubBotLogsOut(logs=rows)

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
        payload = await _sync_binance_time(ctx, body.master_password, body.api_key, body.api_secret)
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
        pair = _resolve_pair(ctx, body.master_password, body.api_key, body.api_secret)
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
        pair = _resolve_pair(ctx, body.master_password, body.api_key, body.api_secret)
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
        pair = _resolve_pair(ctx, body.master_password, body.api_key, body.api_secret)
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

    @app.get("/api/v1/account/wallets")
    async def account_wallets(
        base_asset: str = "USDT",
        ctx: AppContext = Depends(deps.get_ctx),
    ) -> dict[str, Any]:
        return await _fetch_wallet_buckets(ctx, base_asset=base_asset)

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
        used_weight_1m=getattr(ctx.state, "api_weight_used_1m", None),
        weight_limit_1m=api_weight_limit_1m_display(),
    )


def _to_decimal_str(value: Any) -> str:
    try:
        dec = Decimal(str(value or "0"))
        text = format(dec, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        if text in ("", "-0"):
            return "0"
        return text
    except (InvalidOperation, ValueError, TypeError):
        return "0"


def _is_non_zero(value: str) -> bool:
    try:
        return Decimal(value) != 0
    except (InvalidOperation, ValueError, TypeError):
        return False


def _bucket_sum(rows: list[dict[str, Any]], key: str) -> str:
    total = Decimal("0")
    for row in rows:
        try:
            total += Decimal(str(row.get(key, "0")))
        except (InvalidOperation, ValueError, TypeError):
            pass
    return str(total)


async def _fetch_wallet_buckets(ctx: AppContext, base_asset: str = "USDT") -> dict[str, Any]:
    pair = _resolve_pair(ctx, None)
    if not pair:
        raise HTTPException(status_code=400, detail="No API credentials available")

    client = Client(pair[0], pair[1], requests_params={"timeout": 15})
    base = (base_asset or "USDT").strip().upper() or "USDT"
    warnings: list[str] = []
    spot_rows: list[dict[str, Any]] = []
    futures_rows: list[dict[str, Any]] = []
    earn_rows: list[dict[str, Any]] = []
    external_rows: list[dict[str, Any]] = []
    try:
        account = await asyncio.to_thread(client.get_account)
        raw_balances = account.get("balances", []) if isinstance(account, dict) else []
        if not isinstance(raw_balances, list):
            raw_balances = []
        for b in raw_balances:
            asset = str((b or {}).get("asset", "")).upper()
            free = _to_decimal_str((b or {}).get("free", "0"))
            locked = _to_decimal_str((b or {}).get("locked", "0"))
            total = _to_decimal_str(Decimal(free) + Decimal(locked))
            if not _is_non_zero(total):
                continue
            row = {"asset": asset, "free": free, "locked": locked, "total": total}
            if asset.startswith("LD"):
                earn_rows.append(row)
            else:
                spot_rows.append(row)

        if hasattr(client, "futures_account_balance"):
            try:
                fut = await asyncio.to_thread(client.futures_account_balance)
                if isinstance(fut, list):
                    for r in fut:
                        asset = str((r or {}).get("asset", "")).upper()
                        wb = _to_decimal_str((r or {}).get("balance", "0"))
                        cw = _to_decimal_str((r or {}).get("crossWalletBalance", "0"))
                        if not (_is_non_zero(wb) or _is_non_zero(cw)):
                            continue
                        futures_rows.append(
                            {
                                "asset": asset,
                                "wallet_balance": wb,
                                "cross_wallet_balance": cw,
                                "total": wb,
                            }
                        )
            except Exception as e:
                warnings.append(f"futures unavailable: {sanitize_log_message(str(e))}")
        else:
            warnings.append("futures endpoint not available in this client build")

        if hasattr(client, "get_funding_wallet"):
            try:
                ext = await asyncio.to_thread(client.get_funding_wallet)
                if isinstance(ext, list):
                    for r in ext:
                        asset = str((r or {}).get("asset", "")).upper()
                        free = _to_decimal_str((r or {}).get("free", "0"))
                        locked = _to_decimal_str((r or {}).get("locked", "0"))
                        freeze = _to_decimal_str((r or {}).get("freeze", "0"))
                        total = _to_decimal_str(Decimal(free) + Decimal(locked) + Decimal(freeze))
                        if not _is_non_zero(total):
                            continue
                        external_rows.append(
                            {
                                "asset": asset,
                                "free": free,
                                "locked": locked,
                                "freeze": freeze,
                                "total": total,
                            }
                        )
            except Exception as e:
                warnings.append(f"external wallet unavailable: {sanitize_log_message(str(e))}")
        else:
            warnings.append("external wallet endpoint not available in this client build")

        spot_rows.sort(key=lambda r: r.get("asset", ""))
        futures_rows.sort(key=lambda r: r.get("asset", ""))
        earn_rows.sort(key=lambda r: r.get("asset", ""))
        external_rows.sort(key=lambda r: r.get("asset", ""))

        return {
            "base_asset": base,
            "spot": spot_rows,
            "futures": futures_rows,
            "stake_earn": earn_rows,
            "external": external_rows,
            "base_asset_totals": {
                "spot": next((r for r in spot_rows if r.get("asset") == base), {"total": "0"}),
                "futures": next((r for r in futures_rows if r.get("asset") == base), {"total": "0"}),
                "stake_earn": next((r for r in earn_rows if r.get("asset") == f"LD{base}"), {"total": "0"}),
                "external": next((r for r in external_rows if r.get("asset") == base), {"total": "0"}),
            },
            "summary": {
                "spot_assets": len(spot_rows),
                "futures_assets": len(futures_rows),
                "stake_earn_assets": len(earn_rows),
                "external_assets": len(external_rows),
                "spot_total_sum": _bucket_sum(spot_rows, "total"),
                "futures_total_sum": _bucket_sum(futures_rows, "total"),
                "stake_earn_total_sum": _bucket_sum(earn_rows, "total"),
                "external_total_sum": _bucket_sum(external_rows, "total"),
            },
            "warnings": warnings,
        }
    finally:
        try:
            await asyncio.to_thread(client.close_connection)
        except Exception:
            pass


def _resolve_pair(
    ctx: AppContext,
    master_password: str | None,
    api_key: str | None = None,
    api_secret: str | None = None,
) -> tuple[str, str] | None:
    ak = (api_key or "").strip()
    sec = (api_secret or "").strip()
    if ak and sec:
        ctx.active_api_key_hint = _mask_pk(ak)
        ctx.active_api_key_last4 = _pk_last4(ak)
        ctx.active_api_key_source = "inline"
        return ak, sec
    mp = (master_password or "") or ctx.cached_master_password or ""
    mp = (mp or "").strip()
    pair = binance_credentials_from_env()
    if pair:
        ctx.active_api_key_hint = _mask_pk(pair[0])
        ctx.active_api_key_last4 = _pk_last4(pair[0])
        ctx.active_api_key_source = "env"
        return pair
    if not mp:
        return None
    try:
        pair = ctx.config.get_pair_for_active(mp)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from None
    if pair:
        ctx.cached_master_password = mp
        ctx.active_api_key_hint = _mask_pk(pair[0])
        ctx.active_api_key_last4 = _pk_last4(pair[0])
        ctx.active_api_key_source = "vault"
        if remember_master_password_enabled():
            save_remembered_master(ctx.config.data_dir, mp)
    return pair


def _resolve_master_for_vault(ctx: AppContext, master_password: str | None) -> str:
    mp = (master_password or "").strip() or (ctx.cached_master_password or "").strip()
    if not mp:
        raise HTTPException(
            status_code=400,
            detail="Master password required (no cached vault session)",
        )
    ctx.cached_master_password = mp
    if remember_master_password_enabled():
        save_remembered_master(ctx.config.data_dir, mp)
    return mp


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


async def _sync_binance_time(
    ctx: AppContext,
    master_password: str | None,
    api_key: str | None = None,
    api_secret: str | None = None,
) -> dict[str, Any]:
    bot = deps.get_bot()
    if ctx.gateway:
        payload = await ctx.gateway.sync_time()
        if bot.runner.running:
            try:
                await bot.runner.sync_time()
            except Exception:
                pass
        return payload

    pair = _resolve_pair(ctx, master_password, api_key, api_secret)
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
