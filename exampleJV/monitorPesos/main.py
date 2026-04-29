# -*- coding: utf-8 -*-
"""Console occupancy bar + CSV log for Binance REST weight (same header as Pecunator gateway)."""

from __future__ import annotations

import csv
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from binance.client import Client

# Allow `from accesoAPI import ...` when run from exampleJV/monitorPesos/
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from accesoAPI import inicializar_cliente  # noqa: E402


def _weight_total_default() -> int:
    raw = os.environ.get(
        "MONITOR_PESOS_WEIGHT_TOTAL",
        os.environ.get("PECUNATOR_API_WEIGHT_LIMIT_1M", "6000"),
    ).strip()
    try:
        return max(1, int(raw, 10))
    except ValueError:
        return 6000


def print_occupation_bar(now: datetime, weight: str | int, total: int) -> None:
    """Text bar (the historical 'grafiquita' — no PNG; console + CSV only)."""
    try:
        w = int(weight)
    except (TypeError, ValueError):
        w = 0
    percentage = min(100.0, (w / total) * 100)
    bar_length = 30
    filled_length = int(bar_length * percentage / 100)
    bar = "\u2593" * filled_length + "-" * (bar_length - filled_length)
    print(
        f"Ocupación: [{bar}] {percentage:.2f}%",
        f"{now}: PESO CONSUMIDO EN EL ULTIMO MINUTO: {weight}",
        f"(De {total} disponible — ajusta MONITOR_PESOS_WEIGHT_TOTAL o PECUNATOR_API_WEIGHT_LIMIT_1M)",
    )


def read_used_weight_1m(client: Client) -> str:
    client.ping()
    time.sleep(1)
    resp = getattr(client, "response", None)
    if resp is None:
        raise RuntimeError("python-binance did not set client.response after ping()")
    headers = getattr(resp, "headers", {}) or {}
    for k, v in headers.items():
        if str(k).upper() == "X-MBX-USED-WEIGHT-1M":
            return str(v)
    raise KeyError("X-MBX-USED-WEIGHT-1M not in response headers")


def main() -> None:
    total = _weight_total_default()
    client = inicializar_cliente()
    filename = "api_weight_MULTISYMBOL_log.csv"
    if not os.path.exists(filename):
        with open(filename, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(["Fecha y Hora", "Peso Consumido"])

    while True:
        try:
            weight = read_used_weight_1m(client)
            now = datetime.now()
            print_occupation_bar(now, weight, total)
            with open(filename, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([now.isoformat(), weight])
            time.sleep(2)
        except Exception as e:
            print(f"Ocurrió un error: {e}")


if __name__ == "__main__":
    main()
