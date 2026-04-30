"""
[MEJORA] Persistencia de estado robusta con SQLite.

Mejora qué da:
- Antes los bots reconstruían su estado desde las órdenes vivas en Binance
  (frágil ante reinicios, cancelaciones manuales o fallos de red).
- Ahora el bot tiene memoria propia: trades históricos, snapshots de equity,
  peak histórico para drawdown y registro de métricas. Permite reanudar
  operación sin perder contexto y analizar performance offline.

Tablas:
- bot_state         : pares clave/valor por bot (p. ej. peak_equity)
- trades            : cada BUY/SELL ejecutado (MARKET o LIMIT)
- equity_snapshots  : serie temporal de equity en USDT
- metrics_log       : histórico de Sharpe / win-rate / max-DD
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path


_SCHEMA = """
CREATE TABLE IF NOT EXISTS bot_state (
    bot_name   TEXT NOT NULL,
    key        TEXT NOT NULL,
    value      TEXT,
    updated_at TEXT,
    PRIMARY KEY (bot_name, key)
);
CREATE TABLE IF NOT EXISTS trades (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_name  TEXT NOT NULL,
    ts_utc    TEXT NOT NULL,
    symbol    TEXT NOT NULL,
    side      TEXT NOT NULL,        -- BUY | SELL
    type      TEXT NOT NULL,        -- MARKET | LIMIT
    qty       TEXT NOT NULL,
    price     TEXT NOT NULL,
    cost      TEXT NOT NULL,
    ref       TEXT
);
CREATE TABLE IF NOT EXISTS equity_snapshots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_name            TEXT NOT NULL,
    ts_utc              TEXT NOT NULL,
    equity_usdt         TEXT NOT NULL,
    capital_disponible  TEXT
);
CREATE TABLE IF NOT EXISTS metrics_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_name      TEXT NOT NULL,
    ts_utc        TEXT NOT NULL,
    sharpe        TEXT,
    win_rate      TEXT,
    max_drawdown  TEXT,
    total_trades  INTEGER,
    total_pnl     TEXT
);
CREATE INDEX IF NOT EXISTS idx_trades_bot ON trades(bot_name, ts_utc);
CREATE INDEX IF NOT EXISTS idx_equity_bot ON equity_snapshots(bot_name, ts_utc);
"""


class StateStore:
    """Wrapper minimalista sobre SQLite para los bots de exampleJV."""

    def __init__(self, db_path: str, bot_name: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.bot_name = bot_name
        with self._conn() as cx:
            cx.executescript(_SCHEMA)

    @contextmanager
    def _conn(self):
        cx = sqlite3.connect(str(self.db_path))
        try:
            yield cx
            cx.commit()
        finally:
            cx.close()

    # ---- estado clave/valor ----
    def set_state(self, key: str, value) -> None:
        with self._conn() as cx:
            cx.execute(
                "INSERT OR REPLACE INTO bot_state (bot_name, key, value, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (self.bot_name, key, str(value), datetime.utcnow().isoformat()),
            )

    def get_state(self, key: str, default=None):
        with self._conn() as cx:
            row = cx.execute(
                "SELECT value FROM bot_state WHERE bot_name=? AND key=?",
                (self.bot_name, key),
            ).fetchone()
        return row[0] if row else default

    # ---- trades ----
    def record_trade(self, symbol: str, side: str, type_: str, qty, price, ref: str = "") -> None:
        qty_d = Decimal(str(qty))
        price_d = Decimal(str(price))
        cost = qty_d * price_d
        with self._conn() as cx:
            cx.execute(
                "INSERT INTO trades (bot_name, ts_utc, symbol, side, type, qty, price, cost, ref) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    self.bot_name,
                    datetime.utcnow().isoformat(),
                    symbol,
                    side,
                    type_,
                    str(qty_d),
                    str(price_d),
                    str(cost),
                    ref,
                ),
            )

    def get_trades(self, symbol: str | None = None) -> list[dict]:
        sql = "SELECT ts_utc, symbol, side, qty, price, cost FROM trades WHERE bot_name=?"
        params: list = [self.bot_name]
        if symbol:
            sql += " AND symbol=?"
            params.append(symbol)
        sql += " ORDER BY id"
        with self._conn() as cx:
            rows = cx.execute(sql, params).fetchall()
        return [
            {
                "ts": r[0],
                "symbol": r[1],
                "side": r[2],
                "qty": Decimal(r[3]),
                "price": Decimal(r[4]),
                "cost": Decimal(r[5]),
            }
            for r in rows
        ]

    # ---- equity ----
    def record_equity(self, equity_usdt, capital_disponible=None) -> None:
        with self._conn() as cx:
            cx.execute(
                "INSERT INTO equity_snapshots (bot_name, ts_utc, equity_usdt, capital_disponible) "
                "VALUES (?,?,?,?)",
                (
                    self.bot_name,
                    datetime.utcnow().isoformat(),
                    str(equity_usdt),
                    str(capital_disponible) if capital_disponible is not None else None,
                ),
            )

    def get_equity_curve(self) -> list[tuple[str, Decimal]]:
        with self._conn() as cx:
            rows = cx.execute(
                "SELECT ts_utc, equity_usdt FROM equity_snapshots WHERE bot_name=? ORDER BY id",
                (self.bot_name,),
            ).fetchall()
        return [(r[0], Decimal(r[1])) for r in rows]

    # ---- metrics ----
    def record_metrics(self, sharpe, win_rate, max_drawdown, total_trades: int, total_pnl) -> None:
        with self._conn() as cx:
            cx.execute(
                "INSERT INTO metrics_log "
                "(bot_name, ts_utc, sharpe, win_rate, max_drawdown, total_trades, total_pnl) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    self.bot_name,
                    datetime.utcnow().isoformat(),
                    str(sharpe) if sharpe is not None else None,
                    str(win_rate) if win_rate is not None else None,
                    str(max_drawdown) if max_drawdown is not None else None,
                    int(total_trades),
                    str(total_pnl),
                ),
            )
