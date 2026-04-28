"""Allow `python -m runtime` alongside `python -m runtime.app` / `python main.py`."""

from __future__ import annotations

from runtime.main import main

if __name__ == "__main__":
    main()
