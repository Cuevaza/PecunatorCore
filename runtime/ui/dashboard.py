"""NiceGUI dashboard: vault (public keys), REST connection, balances & account summary."""

from __future__ import annotations

import asyncio
from typing import Any

from nicegui import ui

from runtime.app import AppContext
from runtime.connectors.binance_gateway import BinanceGateway
from runtime.core.master_remember import (
    clear_remembered_master,
    load_remembered_master,
    save_remembered_master,
)
from runtime.core.security_util import sanitize_log_message
from runtime.core.settings import (
    binance_credentials_from_env,
    vault_unlock_password_from_env,
)

_MAIN = ("BTC", "ETH", "BNB", "SOL", "USDT", "USDC", "XRP", "ADA")


def _tot(b: dict[str, Any]) -> float:
    return float(b.get("free", 0) or 0) + float(b.get("locked", 0) or 0)


def _primary(balances: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pos = [b for b in balances if _tot(b) > 0]
    by = {b["asset"]: b for b in pos}
    head = [by[a] for a in _MAIN if a in by]
    tail = sorted(
        (x for x in pos if x["asset"] not in _MAIN),
        key=lambda b: (-_tot(b), b["asset"]),
    )[:20]
    out: list[dict[str, Any]] = []
    for b in head + tail:
        t = _tot(b)
        out.append(
            {
                "asset": b.get("asset", ""),
                "free": str(b.get("free", "0")),
                "locked": str(b.get("locked", "0")),
                "total": f"{t:.12g}".rstrip("0").rstrip("."),
            }
        )
    return out


def _short(pk: str) -> str:
    s = pk.strip()
    return s if len(s) <= 24 else f"{s[:14]}…{s[-6:]}"


async def _auto_start(ctx: AppContext) -> None:
    if ctx.auto_connect_attempted:
        return
    ctx.auto_connect_attempted = True
    pair = binance_credentials_from_env()
    if not pair:
        mp = ctx.cached_master_password or vault_unlock_password_from_env()
        if mp and ctx.config.exists():
            pair = ctx.config.get_pair_for_active(mp)
            if pair:
                ctx.cached_master_password = mp
    if not pair:
        return
    ak, sec = pair
    try:
        if ctx.gateway:
            await ctx.gateway.stop()
        ctx.gateway = BinanceGateway(ak, sec, ctx.bus, ctx.state, ctx.log_line)
        await ctx.gateway.start()
        await ctx.gateway.fetch_account()
        ctx.state.last_error = None
    except Exception as e:
        ctx.gateway = None
        ctx.state.connected = False
        ctx.state.last_error = sanitize_log_message(str(e))


def mount(ctx: AppContext) -> None:
    ui.add_head_html(
        "<style>html,body{margin:0;min-height:100%;background:#12151c;color:#e6e6e6}</style>",
        shared=True,
    )

    @ui.page("/", title="PecunatorCore", dark=True)
    async def page() -> None:
        ui.dark_mode().enable()
        remembered = load_remembered_master(ctx.config.data_dir)
        if remembered:
            ctx.cached_master_password = remembered

        rf: dict[str, Any] = {}

        def sync_sel() -> None:
            sel = rf.get("sel")
            if not sel:
                return
            pubs = ctx.config.list_public_credentials()
            m = {p["id"]: _short(p["public_key"]) for p in pubs}
            sel.options = m
            if m:
                cur = ctx.config.get_active_credential_id()
                pick = cur if cur in m else next(iter(m))
                sel.value = pick
                ctx.config.set_active_credential_id(str(pick))
            else:
                sel.value = None
                ctx.config.set_active_credential_id(None)

        def fill_public(col: ui.column) -> None:
            col.clear()
            with col:
                pubs = ctx.config.list_public_credentials()
                if not pubs:
                    ui.label("No credentials stored.").classes("text-caption text-grey-6")
                    return

                async def drop(cid: str) -> None:
                    mi = rf.get("mp")
                    mp = (mi.value or "").strip() if mi else ""
                    mp = mp or (ctx.cached_master_password or "").strip()
                    if not mp:
                        ui.notify("Enter master password in Vault first.", type="warning")
                        return
                    if ctx.gateway:
                        await ctx.gateway.stop()
                        ctx.gateway = None
                        ctx.state.connected = False
                    if ctx.config.remove_credential(cid, mp):
                        sync_sel()
                        fill_public(col)
                        ui.notify("Removed.", type="positive")
                    else:
                        ui.notify("Delete failed.", type="negative")

                for p in pubs:
                    cid = p["id"]
                    pub = p["public_key"]
                    with ui.row().classes("w-full items-center gap-sm py-xs border-b border-grey-9"):
                        ui.label(pub).classes("grow text-caption break-all")
                        ui.button(
                            icon="delete",
                            on_click=lambda c=cid: asyncio.create_task(drop(c)),
                        ).props("dense flat color=warning")

        wipe = ui.dialog()
        add = ui.dialog()
        vault = ui.dialog()

        with wipe, ui.card().classes("w-full max-w-sm"):
            ui.label("Erase entire vault?").classes("text-subtitle1")

            async def do_wipe() -> None:
                if ctx.gateway:
                    await ctx.gateway.stop()
                    ctx.gateway = None
                    ctx.state.connected = False
                ctx.config.clear_credentials()
                clear_remembered_master(ctx.config.data_dir)
                ctx.cached_master_password = None
                wipe.close()
                ph = rf.get("ph")
                if ph:
                    fill_public(ph)
                sync_sel()
                ui.notify("Vault cleared.", type="warning")

            with ui.row().classes("gap-sm justify-end"):
                ui.button("Cancel", on_click=wipe.close).props("flat dense")
                ui.button("Erase", color="negative", on_click=lambda: asyncio.create_task(do_wipe())).props(
                    "dense"
                )

        with add, ui.card().classes("w-full max-w-md"):
            ui.label("Add Binance credential").classes("text-h6")
            inp_ak = ui.input("Public API key").props("dense outlined").classes("w-full")
            inp_sk = ui.input("Secret key", password=True).props("dense outlined").classes("w-full")

            async def save_pair() -> None:
                mi = rf.get("mp")
                mp = (mi.value or "").strip() if mi else ""
                mp = mp or (ctx.cached_master_password or "").strip()
                ak = (inp_ak.value or "").strip()
                sk = (inp_sk.value or "").strip()
                if len(mp) < 12:
                    ui.notify("Master password (≥12 chars) required.", type="warning")
                    return
                if len(ak) < 16 or len(sk) < 16:
                    ui.notify("API key / secret look incomplete.", type="warning")
                    return
                try:
                    ctx.config.add_credential(ak, sk, mp)
                    ctx.cached_master_password = mp
                    rb = rf.get("rb")
                    if rb and rb.value:
                        save_remembered_master(ctx.config.data_dir, mp)
                except ValueError as e:
                    ui.notify(str(e), type="warning")
                    return
                inp_ak.value = ""
                inp_sk.value = ""
                add.close()
                ph = rf.get("ph")
                if ph:
                    fill_public(ph)
                sync_sel()
                ui.notify("Saved.", type="positive")

            with ui.row().classes("justify-end gap-sm"):
                ui.button("Cancel", on_click=add.close).props("dense flat")
                ui.button("Save credential", color="primary", on_click=save_pair).props("dense")

        with vault, ui.card().classes("w-full max-w-2xl"):
            ui.markdown("##### Vault · public keys only")
            rf["mp"] = inp_mp = ui.input(
                label="Master password",
                password=True,
                value=remembered or "",
            ).props("dense outlined").classes("w-full")
            rf["rb"] = cb_rm = ui.checkbox(
                "Remember master password locally (encrypted blob)",
                value=bool(remembered),
            )

            def on_chk() -> None:
                s = (inp_mp.value or "").strip()
                if cb_rm.value:
                    if len(s) >= 12:
                        save_remembered_master(ctx.config.data_dir, s)
                        ctx.cached_master_password = s
                else:
                    clear_remembered_master(ctx.config.data_dir)

            cb_rm.on_value_change(lambda _: on_chk())

            pubs0 = ctx.config.list_public_credentials()
            opt_map = {x["id"]: _short(x["public_key"]) for x in pubs0}
            av0 = ctx.config.get_active_credential_id()
            v0 = av0 if av0 and av0 in opt_map else (next(iter(opt_map)) if opt_map else None)
            rf["sel"] = sel_pick = ui.select(
                opt_map,
                label="Active credential",
                value=v0,
            ).props("dense outlined emit-value maps-options").classes("w-full")

            def sel_upd(_evt: dict[str, Any]) -> None:
                v = sel_pick.value
                if v:
                    ctx.config.set_active_credential_id(str(v))

            sel_pick.on_value_change(sel_upd)

            ph_col = ui.column().classes("w-full pec-public-slot mb-sm mt-sm").style(
                "max-height:220px;overflow:auto;border:1px solid #2a3344;border-radius:6px;"
            )
            rf["ph"] = ph_col
            fill_public(ph_col)

            with ui.row().classes("gap-sm flex-wrap mt-sm"):
                ui.button(
                    icon="add",
                    label="New credential…",
                    on_click=add.open,
                    color="primary",
                ).props("dense outline")
                ui.button(
                    icon="delete_forever",
                    label="Erase vault",
                    color="warning",
                    on_click=wipe.open,
                ).props("dense outline")
            ui.button("Close", on_click=vault.close).props("flat dense")

        tbl_acc = ui.table(
            columns=[
                {"name": "k", "label": "Field", "field": "k"},
                {"name": "v", "label": "", "field": "v"},
            ],
            rows=[],
        ).props("dense flat bordered")

        tbl_bal = ui.table(
            columns=[
                {"name": "asset", "label": "Asset", "field": "asset"},
                {"name": "free", "label": "Free", "field": "free"},
                {"name": "locked", "label": "Locked", "field": "locked"},
                {"name": "total", "label": "Total", "field": "total"},
            ],
            rows=[],
            row_key="asset",
        ).props("dense flat bordered")

        conn_lbl = ui.label("REST: OFF · WS idle").classes("text-subtitle2 text-grey-5")
        ui.separator().classes("my-md")

        with ui.row().classes("items-center gap-md mb-md"):
            ui.label("REST + WebSocket gateway").classes("text-h5 text-bold grow")

            async def toggle() -> None:
                if ctx.gateway:
                    await ctx.gateway.stop()
                    ctx.gateway = None
                    ctx.state.connected = False
                    ui.notify("Stopped.", type="info")
                    return
                blob = binance_credentials_from_env()
                if blob is None:
                    mp_in = inp_mp.value if inp_mp.value else ""
                    mp_in = (mp_in or "").strip() or (ctx.cached_master_password or "").strip()
                    if not mp_in:
                        ui.notify("Open Vault — enter master password.", type="warning")
                        vault.open()
                        return
                    blob = ctx.config.get_pair_for_active(mp_in)
                    ctx.cached_master_password = mp_in
                if not blob:
                    ui.notify("No keys.", type="warning")
                    vault.open()
                    return
                ak_, sec_ = blob
                try:
                    ctx.gateway = BinanceGateway(ak_, sec_, ctx.bus, ctx.state, ctx.log_line)
                    await ctx.gateway.start()
                    await ctx.gateway.fetch_account()
                    ctx.state.last_error = None
                    ui.notify("REST online.", type="positive")
                except Exception as ex:
                    ctx.gateway = None
                    ui.notify(sanitize_log_message(str(ex)), type="negative")

            ui.button("Connection toggle", icon="bolt", on_click=toggle).props(
                "dense rounded-borders"
            ).classes("px-md")
            ui.button("Vault…", icon="vpn_key", on_click=vault.open).props("dense flat rounded-borders")

        async def reload_balances() -> None:
            if ctx.gateway:
                await ctx.gateway.fetch_account()

        ui.button("Refresh REST snapshot", icon="refresh", on_click=reload_balances).props("dense outline mb-md")

        def repaint() -> None:
            gw = ctx.gateway is not None
            conn_lbl.set_text(
                f"REST: {'ON' if gw else 'OFF'} · WS: {'streaming' if ctx.state.connected else 'idle'}",
            )
            s = ctx.state.account_summary or {}
            tbl_acc.rows = [
                {"k": "accountType", "v": str(s.get("accountType", "—"))},
                {"k": "canTrade", "v": "yes" if s.get("canTrade") else ("no" if gw else "—")},
                {"k": "canWithdraw", "v": "yes" if s.get("canWithdraw") else ("no" if gw else "—")},
                {"k": "canDeposit", "v": "yes" if s.get("canDeposit") else ("no" if gw else "—")},
                {"k": "makerCommission", "v": str(s.get("makerCommission", "—"))},
                {"k": "takerCommission", "v": str(s.get("takerCommission", "—"))},
                {"k": "updateTime", "v": str(s.get("updateTime", "—"))},
            ]
            tbl_bal.rows = _primary(ctx.state.balances)

        ui.timer(0.4, repaint)

        await _auto_start(ctx)

