"""API-level singleton hub service for Dorothy bots."""

from __future__ import annotations

from dataclasses import dataclass, replace
import datetime as dt
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import threading
import uuid
from typing import Any, Callable, Optional

from runtime.bot.dorothy import DorothyConfig, DorothyRunner


@dataclass
class _BotRecord:
    bot_id: str
    tag: str
    runner: DorothyRunner
    created_at: str


class BotService:
    def __init__(self) -> None:
        self._bots: dict[str, _BotRecord] = {}
        self._default_bot_id: Optional[str] = None
        self._db_path: Optional[Path] = None
        self._db_lock = threading.Lock()

    def attach_data_dir(self, data_dir: Path) -> None:
        db_path = Path(data_dir) / "dorothy_hub.sqlite"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        if self._db_path is None:
            return
        with self._db_lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS dorothy_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts_utc TEXT NOT NULL,
                        bot_id TEXT NOT NULL,
                        tag TEXT NOT NULL,
                        level TEXT NOT NULL,
                        message TEXT NOT NULL,
                        payload_json TEXT
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def _write_log(
        self,
        bot_id: str,
        tag: str,
        level: str,
        message: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> None:
        if self._db_path is None:
            return
        with self._db_lock:
            conn = sqlite3.connect(str(self._db_path))
            try:
                conn.execute(
                    """
                    INSERT INTO dorothy_logs (ts_utc, bot_id, tag, level, message, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        dt.datetime.now(dt.timezone.utc).isoformat(),
                        bot_id,
                        tag,
                        level,
                        message,
                        json.dumps(payload) if payload is not None else None,
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def _runner_log_sink(self, bot_id: str) -> Callable[[str], None]:
        def _sink(msg: str) -> None:
            rec = self._bots.get(bot_id)
            tag = rec.tag if rec is not None else "-"
            self._write_log(bot_id, tag, "INFO", msg)

        return _sink

    def _record_payload(self, rec: _BotRecord) -> dict[str, Any]:
        cfg = rec.runner.config
        return {
            "bot_id": rec.bot_id,
            "tag": rec.tag,
            "created_at": rec.created_at,
            "running": rec.runner.running,
            "preset_id": cfg.preset_id,
            "symbol": cfg.symbol,
            "simulated": cfg.simulated,
            "trading_enabled": cfg.trading_enabled,
            "loop_interval_sec": cfg.loop_interval_sec,
            "quote_order_qty": str(cfg.quote_order_qty),
            "profit_factor": str(cfg.profit_factor),
            "margin_drop_factor": str(cfg.margin_drop_factor),
            "qty_decimals": cfg.qty_decimals,
            "price_decimals": cfg.price_decimals,
            "last_cycle_ts": rec.runner.last_cycle_ts,
            "last_error": rec.runner.last_error,
            "last_report": rec.runner.last_report,
        }

    def _default_bot(self) -> _BotRecord:
        if self._default_bot_id and self._default_bot_id in self._bots:
            return self._bots[self._default_bot_id]
        payload = self.create_instance(tag="Dorothy default")
        self._default_bot_id = payload["bot_id"]
        return self._bots[self._default_bot_id]

    @property
    def runner(self) -> DorothyRunner:
        return self._default_bot().runner

    def create_instance(
        self,
        *,
        tag: str,
        bot_id: Optional[str] = None,
        symbol: str = "XRPUSDT",
        loop_interval_sec: int = 450,
        quote_order_qty: str = "8",
        profit_factor: str = "0.05",
        margin_drop_factor: str = "0.004",
        qty_decimals: int = 8,
        price_decimals: int = 4,
        simulated: bool = True,
        trading_enabled: bool = False,
    ) -> dict[str, Any]:
        bot_id_norm = (bot_id or "").strip() or f"dorothy-{uuid.uuid4().hex[:8]}"
        if bot_id_norm in self._bots:
            raise ValueError(f"Bot id already exists: {bot_id_norm}")
        cfg = DorothyConfig(
            preset_id="B",
            symbol=symbol,
            loop_interval_sec=loop_interval_sec,
            quote_order_qty=Decimal(str(quote_order_qty)),
            profit_factor=Decimal(str(profit_factor)),
            margin_drop_factor=Decimal(str(margin_drop_factor)),
            qty_decimals=qty_decimals,
            price_decimals=price_decimals,
            simulated=simulated,
            trading_enabled=trading_enabled,
        )
        cfg.normalize()
        runner = DorothyRunner(self._runner_log_sink(bot_id_norm))
        runner.apply_config(cfg)
        rec = _BotRecord(
            bot_id=bot_id_norm,
            tag=(tag or "Dorothy").strip(),
            runner=runner,
            created_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        )
        self._bots[bot_id_norm] = rec
        if self._default_bot_id is None:
            self._default_bot_id = bot_id_norm
        payload = self._record_payload(rec)
        self._write_log(bot_id_norm, rec.tag, "SYSTEM", "bot_created", payload)
        return payload

    def list_instances(self) -> list[dict[str, Any]]:
        rows = [self._record_payload(v) for _, v in sorted(self._bots.items(), key=lambda x: x[1].created_at)]
        return rows

    def status_instance(self, bot_id: str) -> dict[str, Any]:
        rec = self._bots.get(bot_id)
        if rec is None:
            raise KeyError(bot_id)
        return self._record_payload(rec)

    def update_instance(
        self,
        bot_id: str,
        *,
        tag: Optional[str] = None,
        symbol: Optional[str] = None,
        loop_interval_sec: Optional[int] = None,
        quote_order_qty: Optional[str] = None,
        profit_factor: Optional[str] = None,
        margin_drop_factor: Optional[str] = None,
        qty_decimals: Optional[int] = None,
        price_decimals: Optional[int] = None,
        simulated: Optional[bool] = None,
        trading_enabled: Optional[bool] = None,
    ) -> dict[str, Any]:
        rec = self._bots.get(bot_id)
        if rec is None:
            raise KeyError(bot_id)
        cfg = replace(rec.runner.config)
        if symbol is not None:
            cfg.symbol = symbol
        if loop_interval_sec is not None:
            cfg.loop_interval_sec = loop_interval_sec
        if quote_order_qty is not None:
            cfg.quote_order_qty = Decimal(str(quote_order_qty))
        if profit_factor is not None:
            cfg.profit_factor = Decimal(str(profit_factor))
        if margin_drop_factor is not None:
            cfg.margin_drop_factor = Decimal(str(margin_drop_factor))
        if qty_decimals is not None:
            cfg.qty_decimals = qty_decimals
        if price_decimals is not None:
            cfg.price_decimals = price_decimals
        if simulated is not None:
            cfg.simulated = simulated
        if trading_enabled is not None:
            cfg.trading_enabled = trading_enabled
        cfg.normalize()
        rec.runner.apply_config(cfg)
        if tag is not None and tag.strip():
            rec.tag = tag.strip()
        payload = self._record_payload(rec)
        self._write_log(bot_id, rec.tag, "SYSTEM", "bot_updated", payload)
        return payload

    async def start_instance(self, bot_id: str, api_key: str, api_secret: str) -> dict[str, Any]:
        rec = self._bots.get(bot_id)
        if rec is None:
            raise KeyError(bot_id)
        rec.runner.set_credentials(api_key, api_secret)
        await rec.runner.sync_time()
        await rec.runner.start()
        payload = self._record_payload(rec)
        self._write_log(bot_id, rec.tag, "SYSTEM", "bot_started", payload)
        return payload

    async def run_once_instance(self, bot_id: str, api_key: str, api_secret: str) -> dict[str, Any]:
        rec = self._bots.get(bot_id)
        if rec is None:
            raise KeyError(bot_id)
        rec.runner.set_credentials(api_key, api_secret)
        await rec.runner.sync_time()
        rep = await rec.runner.run_once()
        self.mark_run_once(bot_id, rep, error=None)
        payload = self._record_payload(rec)
        self._write_log(bot_id, rec.tag, "SYSTEM", "bot_run_once", payload)
        return payload

    async def stop_instance(self, bot_id: str) -> dict[str, Any]:
        rec = self._bots.get(bot_id)
        if rec is None:
            raise KeyError(bot_id)
        await rec.runner.stop()
        payload = self._record_payload(rec)
        self._write_log(bot_id, rec.tag, "SYSTEM", "bot_stopped", payload)
        return payload

    async def delete_instance(self, bot_id: str) -> None:
        rec = self._bots.get(bot_id)
        if rec is None:
            raise KeyError(bot_id)
        await rec.runner.stop()
        self._write_log(bot_id, rec.tag, "SYSTEM", "bot_deleted")
        del self._bots[bot_id]
        if self._default_bot_id == bot_id:
            self._default_bot_id = next(iter(self._bots.keys()), None)

    async def stop_all(self) -> None:
        for bot_id in list(self._bots.keys()):
            try:
                await self.stop_instance(bot_id)
            except Exception:
                pass

    def get_logs(self, bot_id: str, limit: int = 200) -> list[dict[str, Any]]:
        if self._db_path is None:
            return []
        if bot_id not in self._bots:
            raise KeyError(bot_id)
        n = max(1, min(int(limit), 1000))
        with self._db_lock:
            conn = sqlite3.connect(str(self._db_path))
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    """
                    SELECT ts_utc, bot_id, tag, level, message, payload_json
                    FROM dorothy_logs
                    WHERE bot_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (bot_id, n),
                ).fetchall()
            finally:
                conn.close()
        out: list[dict[str, Any]] = []
        for row in reversed(rows):
            payload_raw = row["payload_json"]
            out.append(
                {
                    "ts_utc": row["ts_utc"],
                    "bot_id": row["bot_id"],
                    "tag": row["tag"],
                    "level": row["level"],
                    "message": row["message"],
                    "payload": json.loads(payload_raw) if payload_raw else None,
                }
            )
        return out

    # Compatibility layer for pre-hub API endpoints
    def get_config(self) -> DorothyConfig:
        return replace(self._default_bot().runner.config)

    def set_config(
        self,
        *,
        symbol: str,
        loop_interval_sec: int,
        quote_order_qty: str,
        profit_factor: str,
        margin_drop_factor: str,
        qty_decimals: int,
        price_decimals: int,
        simulated: bool,
        trading_enabled: bool,
    ) -> DorothyConfig:
        rec = self._default_bot()
        payload = self.update_instance(
            rec.bot_id,
            symbol=symbol,
            loop_interval_sec=loop_interval_sec,
            quote_order_qty=quote_order_qty,
            profit_factor=profit_factor,
            margin_drop_factor=margin_drop_factor,
            qty_decimals=qty_decimals,
            price_decimals=price_decimals,
            simulated=simulated,
            trading_enabled=trading_enabled,
        )
        cfg = DorothyConfig(
            preset_id=payload["preset_id"],
            symbol=payload["symbol"],
            loop_interval_sec=payload["loop_interval_sec"],
            quote_order_qty=Decimal(payload["quote_order_qty"]),
            profit_factor=Decimal(payload["profit_factor"]),
            margin_drop_factor=Decimal(payload["margin_drop_factor"]),
            qty_decimals=payload["qty_decimals"],
            price_decimals=payload["price_decimals"],
            simulated=payload["simulated"],
            trading_enabled=payload["trading_enabled"],
        )
        return replace(cfg)

    def status_payload(self) -> dict[str, Any]:
        rec = self._default_bot()
        p = self._record_payload(rec)
        return {
            "running": p["running"],
            "preset_id": p["preset_id"],
            "symbol": p["symbol"],
            "simulated": p["simulated"],
            "trading_enabled": p["trading_enabled"],
            "loop_interval_sec": p["loop_interval_sec"],
            "last_cycle_ts": p["last_cycle_ts"],
            "last_error": p["last_error"],
            "last_report": p["last_report"],
        }

    def mark_run_once(self, report: dict[str, Any], error: str | None = None, bot_id: str | None = None) -> None:
        rec = self._bots.get(bot_id) if bot_id else None
        if rec is None:
            rec = self._default_bot()
        rec.runner._last_report = dict(report)  # noqa: SLF001
        rec.runner._last_error = error  # noqa: SLF001
        rec.runner._last_cycle_ts = dt.datetime.now(dt.timezone.utc).isoformat()  # noqa: SLF001
