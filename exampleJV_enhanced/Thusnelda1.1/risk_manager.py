"""
[MEJORA] Gestor de riesgo: stop-loss por posición y protección por drawdown.

Mejora qué da:
- Antes los bots NO tenían defensa contra bear markets prolongados ni contra
  posiciones que entraban en pérdida fuerte. El capital se acumulaba sin
  límite y sin salida.
- Ahora:
  * Drawdown global: si el equity cae bajo `peak * (1 - max_drawdown_pct)`,
    bloquea la apertura de nuevas posiciones hasta que el equity recupere.
  * Stop-loss por posición: marca cuándo conviene liquidar a mercado una
    compra que está demasiado en pérdida frente a su precio de referencia.

Persistencia:
- `peak_equity` se guarda en `bot_state` para sobrevivir reinicios.
"""

from __future__ import annotations

from decimal import Decimal


class RiskManager:
    def __init__(self, max_drawdown_pct, stop_loss_pct=None, state_store=None):
        # max_drawdown_pct: 0.20 = bloquea trading si drawdown ≥ 20%
        self.max_drawdown_pct = Decimal(str(max_drawdown_pct))
        # stop_loss_pct: 0.10 = liquida si precio cae 10% bajo referencia
        # (None desactiva el stop-loss por posición)
        self.stop_loss_pct = (
            Decimal(str(stop_loss_pct)) if stop_loss_pct is not None else None
        )
        self.state_store = state_store
        self.peak_equity = self._load_peak()

    def _load_peak(self) -> Decimal:
        if self.state_store is None:
            return Decimal("0")
        v = self.state_store.get_state("peak_equity", "0")
        try:
            return Decimal(str(v))
        except Exception:
            return Decimal("0")

    def register_equity(self, equity) -> Decimal:
        """Actualiza el peak histórico si el equity es nuevo máximo."""
        eq = Decimal(str(equity))
        if eq > self.peak_equity:
            self.peak_equity = eq
            if self.state_store is not None:
                self.state_store.set_state("peak_equity", str(eq))
        return eq

    def current_drawdown(self, current_equity) -> Decimal:
        cur = Decimal(str(current_equity))
        if self.peak_equity <= 0:
            return Decimal("0")
        return (self.peak_equity - cur) / self.peak_equity

    def is_trading_blocked(self, current_equity) -> bool:
        """True si el drawdown supera el umbral configurado."""
        dd = self.current_drawdown(current_equity)
        return dd >= self.max_drawdown_pct

    def should_stop_loss(self, reference_price, current_price) -> bool:
        """
        True si conviene liquidar a mercado.
        `reference_price` puede ser precio de compra individual, DCA o promedio.
        """
        if self.stop_loss_pct is None or reference_price is None:
            return False
        rp = Decimal(str(reference_price))
        cp = Decimal(str(current_price))
        if rp <= 0:
            return False
        loss_threshold = rp * (Decimal("1") - self.stop_loss_pct)
        return cp <= loss_threshold
