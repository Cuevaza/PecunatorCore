"""
[MEJORA] Cálculo de métricas de performance.

Mejora qué da:
- Antes no había forma de saber objetivamente cómo iba el bot. Ahora el
  bot calcula y registra periódicamente:
    * Win rate    : trades cerrados ganadores / total cerrados
    * Sharpe      : mean(returns) / stdev(returns) × sqrt(N), por trade
    * Max DD      : peak-to-trough sobre la curva de equity guardada

Notas:
- El emparejamiento BUY→SELL es FIFO. Lotes parciales se manejan
  consumiendo del inventario hasta agotar la SELL.
- `compute_sharpe` usa retornos por trade (no anualizados); para anualizar
  multiplicar por sqrt(252 / días_promedio_por_trade) externamente.
- Todo se persiste en la tabla `metrics_log` del StateStore.
"""

from __future__ import annotations

import math
from decimal import Decimal


def compute_win_rate_and_pnl(trades: list[dict]):
    """
    Empareja BUY→SELL FIFO. Devuelve:
    (wins, total_closed, total_pnl, returns_pct_list)
    """
    inventory: list[list] = []  # [[qty_restante, precio_compra], ...]
    wins = 0
    total_closed = 0
    total_pnl = Decimal("0")
    returns: list[Decimal] = []

    for t in trades:
        side = t["side"]
        qty = t["qty"]
        price = t["price"]
        if qty <= 0:
            continue
        if side == "BUY":
            inventory.append([qty, price])
        elif side == "SELL":
            qty_to_close = qty
            while qty_to_close > 0 and inventory:
                lot_qty, buy_price = inventory[0]
                taken = lot_qty if lot_qty <= qty_to_close else qty_to_close
                pnl = (price - buy_price) * taken
                total_pnl += pnl
                if buy_price > 0:
                    returns.append((price - buy_price) / buy_price)
                if pnl > 0:
                    wins += 1
                total_closed += 1
                inventory[0][0] -= taken
                qty_to_close -= taken
                if inventory[0][0] <= 0:
                    inventory.pop(0)

    return wins, total_closed, total_pnl, returns


def compute_sharpe(returns: list[Decimal]):
    if not returns or len(returns) < 2:
        return None
    n = len(returns)
    mean = sum(returns) / Decimal(n)
    var = sum((r - mean) ** 2 for r in returns) / Decimal(n - 1)
    std = Decimal(str(math.sqrt(float(var))))
    if std == 0:
        return None
    return (mean / std) * Decimal(str(math.sqrt(n)))


def compute_max_drawdown(equity_curve: list[tuple[str, Decimal]]):
    if not equity_curve:
        return None
    peak = Decimal("0")
    max_dd = Decimal("0")
    for _, eq in equity_curve:
        if eq > peak:
            peak = eq
        if peak > 0:
            dd = (peak - eq) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd


def calcular_y_registrar_metricas(state_store):
    """
    Lee trades + equity_curve del StateStore, calcula las 3 métricas y las
    persiste en `metrics_log`. Devuelve un dict con los valores.
    """
    trades = state_store.get_trades()
    wins, total_closed, total_pnl, returns = compute_win_rate_and_pnl(trades)
    win_rate = (
        (Decimal(wins) / Decimal(total_closed)) if total_closed > 0 else None
    )
    sharpe = compute_sharpe(returns)
    eq_curve = state_store.get_equity_curve()
    max_dd = compute_max_drawdown(eq_curve)

    state_store.record_metrics(
        sharpe=sharpe,
        win_rate=win_rate,
        max_drawdown=max_dd,
        total_trades=total_closed,
        total_pnl=total_pnl,
    )
    return {
        "sharpe": sharpe,
        "win_rate": win_rate,
        "max_drawdown": max_dd,
        "total_trades": total_closed,
        "total_pnl": total_pnl,
    }
