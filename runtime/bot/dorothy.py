"""ExampleJV-inspired rule set with safe defaults (simulated by default)."""

from __future__ import annotations

import asyncio
import datetime as dt
import time
from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any, Callable, Optional

from binance.client import Client

from runtime.connectors.binance_gateway import normalize_binance_spot_symbol
from runtime.core.security_util import sanitize_log_message


def _dec(x: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(x))
    except Exception:
        return Decimal(default)


def _q(x: Decimal, places: int) -> Decimal:
    if places < 0:
        places = 0
    step = Decimal(10) ** Decimal(-places)
    return x.quantize(step, rounding=ROUND_DOWN)


@dataclass
class DorothyConfig:
    # Preset B (from exampleJV semantics), with safe mode defaults.
    preset_id: str = "B"
    symbol: str = "XRPUSDT"
    loop_interval_sec: int = 450
    quote_order_qty: Decimal = Decimal("8")
    profit_factor: Decimal = Decimal("0.05")
    margin_drop_factor: Decimal = Decimal("0.004")
    qty_decimals: int = 8
    price_decimals: int = 4
    simulated: bool = True
    trading_enabled: bool = False

    def normalize(self) -> None:
        self.symbol = normalize_binance_spot_symbol(self.symbol)
        self.loop_interval_sec = max(1, min(int(self.loop_interval_sec), 86_400))
        self.quote_order_qty = max(_dec(self.quote_order_qty, "0.0001"), Decimal("0.0001"))
        self.profit_factor = max(_dec(self.profit_factor), Decimal("0"))
        self.margin_drop_factor = max(_dec(self.margin_drop_factor), Decimal("0"))
        self.qty_decimals = max(0, min(int(self.qty_decimals), 18))
        self.price_decimals = max(0, min(int(self.price_decimals), 18))

    def as_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["quote_order_qty"] = str(self.quote_order_qty)
        d["profit_factor"] = str(self.profit_factor)
        d["margin_drop_factor"] = str(self.margin_drop_factor)
        d["mode"] = "SIMULATED" if self.simulated else "LIVE"
        return d


class DorothyRunner:
    def __init__(self, log: Callable[[str], None]) -> None:
        self.config = DorothyConfig()
        self.config.normalize()
        self._log = log
        self._task: Optional[asyncio.Task[Any]] = None
        self._stop = asyncio.Event()
        self._last_report: dict[str, Any] = {}
        self._last_error: Optional[str] = None
        self._last_cycle_ts: Optional[str] = None
        self._api_key: Optional[str] = None
        self._api_secret: Optional[str] = None
        self._client: Optional[Client] = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def last_report(self) -> dict[str, Any]:
        return dict(self._last_report)

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    @property
    def last_cycle_ts(self) -> Optional[str]:
        return self._last_cycle_ts

    def apply_config(self, cfg: DorothyConfig) -> None:
        cfg.normalize()
        self.config = cfg

    def set_credentials(self, api_key: str, api_secret: str) -> None:
        self._api_key = api_key.strip()
        self._api_secret = api_secret.strip()

    def _ensure_client(self) -> Client:
        if not self._api_key or not self._api_secret:
            raise RuntimeError("No credentials resolved for bot")
        if self._client is None:
            self._client = Client(
                self._api_key,
                self._api_secret,
                requests_params={"timeout": 30},
            )
        return self._client

    async def _to_thread(self, fn: Callable[[], Any]) -> Any:
        return await asyncio.to_thread(fn)

    async def run_once(self) -> dict[str, Any]:
        c = self.config
        c.normalize()
        if not c.simulated and not c.trading_enabled:
            raise RuntimeError(
                "LIVE mode requires trading_enabled=true (explicit switch).",
            )
        client = self._ensure_client()
        symbol = c.symbol

        open_orders = await self._to_thread(lambda: client.get_open_orders(symbol=symbol))
        if not isinstance(open_orders, list):
            open_orders = []
        sell_limit = [
            o
            for o in open_orders
            if str(o.get("side")) == "SELL" and str(o.get("type")) == "LIMIT"
        ]
        lowest_sell = None
        if sell_limit:
            lowest_sell = min(sell_limit, key=lambda o: _dec(o.get("price", "0"), "0"))

        ticker = await self._to_thread(lambda: client.get_symbol_ticker(symbol=symbol))
        market_price = _dec(ticker.get("price", "0"), "0")
        should_buy = False
        threshold = None
        if lowest_sell is not None:
            trigger = _dec(lowest_sell.get("price", "0"), "0")
            threshold = trigger * (Decimal("1") - (c.profit_factor + c.margin_drop_factor))
            should_buy = market_price <= threshold
        else:
            should_buy = True

        report: dict[str, Any] = {
            "preset_id": c.preset_id,
            "symbol": symbol,
            "simulated": c.simulated,
            "trading_enabled": c.trading_enabled,
            "open_orders_count": len(open_orders),
            "has_sell_limit_anchor": lowest_sell is not None,
            "market_price": str(market_price),
            "entry_threshold_price": str(threshold) if threshold is not None else None,
            "decision": "BUY_AND_SELL" if should_buy else "WAIT",
            "sell_anchor_price": str(_dec(lowest_sell.get("price", "0"), "0")) if lowest_sell else None,
            "loop_interval_sec": c.loop_interval_sec,
        }
        if not should_buy:
            return report

        est_buy = market_price if market_price > 0 else Decimal("1")
        est_qty = c.quote_order_qty / est_buy if est_buy > 0 else Decimal("0")
        est_sell = est_buy * (Decimal("1") + c.profit_factor)
        report["planned_quote_order_qty"] = str(c.quote_order_qty)
        report["planned_buy_price"] = str(est_buy)
        report["planned_sell_price"] = str(est_sell)
        report["planned_qty"] = str(_q(est_qty, c.qty_decimals))

        if c.simulated:
            report["execution"] = "SIMULATED"
            report["message"] = "Dry run only; no orders sent."
            return report

        buy = await self._to_thread(
            lambda: client.create_order(
                symbol=symbol,
                side=client.SIDE_BUY,
                type=client.ORDER_TYPE_MARKET,
                quoteOrderQty=str(c.quote_order_qty),
            )
        )
        fills = buy.get("fills") or []
        if fills:
            buy_price = _dec(fills[0].get("price", "0"), "0")
        else:
            executed = _dec(buy.get("executedQty", "0"), "0")
            quote = _dec(buy.get("cummulativeQuoteQty", "0"), "0")
            buy_price = quote / executed if executed > 0 else est_buy
        qty = _dec(buy.get("executedQty", "0"), "0")
        sell_price = _q(buy_price * (Decimal("1") + c.profit_factor), c.price_decimals)
        sell_qty = _q(qty, c.qty_decimals)
        sell = await self._to_thread(
            lambda: client.create_order(
                symbol=symbol,
                side=client.SIDE_SELL,
                type=client.ORDER_TYPE_LIMIT,
                timeInForce=client.TIME_IN_FORCE_GTC,
                quantity=str(sell_qty),
                price=str(sell_price),
            )
        )
        report["execution"] = "LIVE"
        report["buy_order_id"] = buy.get("orderId")
        report["sell_order_id"] = sell.get("orderId")
        report["filled_qty"] = str(qty)
        report["filled_buy_price"] = str(buy_price)
        report["placed_sell_price"] = str(sell_price)
        return report

    async def sync_time(self) -> dict[str, Any]:
        client = self._ensure_client()
        data = await self._to_thread(lambda: client.get_server_time())
        server_ms = int(data.get("serverTime", 0) or 0)
        local_ms = int(time.time() * 1000)
        offset_ms = server_ms - local_ms
        try:
            client.timestamp_offset = offset_ms
        except Exception:
            pass
        self._log(f"bot:time_sync offset_ms={offset_ms}")
        return {
            "local_time_ms": local_ms,
            "server_time_ms": server_ms,
            "offset_ms": offset_ms,
            "source": "bot",
        }

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                rep = await self.run_once()
                self._last_report = rep
                self._last_error = None
                self._last_cycle_ts = dt.datetime.now(dt.timezone.utc).isoformat()
                self._log(f"bot:{rep.get('decision')} symbol={rep.get('symbol')} simulated={rep.get('simulated')}")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._last_error = sanitize_log_message(str(e))
                self._log(f"bot:error {self._last_error}")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=float(self.config.loop_interval_sec))
            except asyncio.TimeoutError:
                pass

    async def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop.set()
        t = self._task
        if t is not None:
            t.cancel()
            await asyncio.gather(t, return_exceptions=True)
        self._task = None
        if self._client is not None:
            try:
                self._client.session.close()
            except Exception:
                pass
            self._client = None
