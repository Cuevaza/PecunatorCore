"""Fetch Spot exchangeInfo rateLimits snapshot into docs/binance-limits-snapshots/."""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

URL = "https://api.binance.com/api/v3/exchangeInfo"


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    out_dir = root / "docs" / "binance-limits-snapshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = out_dir / f"exchangeInfo-rateLimits-{day}.json"

    with urllib.request.urlopen(URL, timeout=60) as resp:
        data = json.load(resp)

    payload = {
        "snapshot_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_url": URL,
        "serverTime": data.get("serverTime"),
        "timezone": data.get("timezone"),
        "rateLimits": data.get("rateLimits"),
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
