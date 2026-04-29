"""CLI entry: logging only. No web server."""

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
    log = logging.getLogger("pecunator.engine")
    log.info(
        "PecunatorCore Python engine (no HTTP UI). Flutter desktop shell: scaffold with "
        "scripts/init_flutter_desktop.ps1; HTTP API layer not implemented yet.",
    )


if __name__ == "__main__":
    main()
