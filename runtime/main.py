"""Single entrypoint: logging + NiceGUI bootstrap (dashboard and gateway lifecycle)."""

from __future__ import annotations

import logging
import os
import sys


def _configure_logging() -> None:
    level_name = os.environ.get("PECUNATOR_LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    fmt = os.environ.get(
        "PECUNATOR_LOG_FMT",
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt=os.environ.get("PECUNATOR_LOG_DATEFMT", "%Y-%m-%d %H:%M:%S"),
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )


def main() -> None:
    _configure_logging()
    logging.getLogger("pecunator").info("starting PecunatorCore (%s)", __name__)
    from runtime.app import main as run_dashboard  # noqa: PLC0415

    run_dashboard()


if __name__ == "__main__":
    main()
