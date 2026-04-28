"""Map Binance `get_account` payload to dashboard-friendly general account summary (no balances)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def summarize_binance_account_rest(data: dict[str, Any]) -> dict[str, Any]:
    """
    Non-sensitive general fields from REST `/api/v3/account` compatible response.
    Balances excluded (handled separately).
    """

    def _pct(raw: Any) -> str:
        try:
            z = float(raw)
        except (TypeError, ValueError):
            return "—"
        return f"{z * 0.01:.4f}%"

    update_ms = data.get("updateTime") or data.get("update_time")
    update_str = "—"
    if isinstance(update_ms, int) and update_ms > 0:
        try:
            dt = datetime.fromtimestamp(update_ms / 1000.0, tz=UTC)
            update_str = dt.isoformat()
        except (ValueError, OSError):
            update_str = str(update_ms)

    return {
        "accountType": str(data.get("accountType") or data.get("account_type") or "—"),
        "canTrade": bool(data.get("canTrade")),
        "canWithdraw": bool(data.get("canWithdraw")),
        "canDeposit": bool(data.get("canDeposit")),
        "makerCommission": _pct(data.get("makerCommission")),
        "takerCommission": _pct(data.get("takerCommission")),
        "buyerCommission": _pct(data.get("buyerCommission")),
        "sellerCommission": _pct(data.get("sellerCommission")),
        "updateTime": update_str,
    }
