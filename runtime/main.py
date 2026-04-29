"""CLI entry: optional HTTP API (FastAPI + Uvicorn) for the Flutter shell."""

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
    lo = logging.getLogger("pecunator.engine")
    if os.environ.get("PECUNATOR_ENGINE_STUB", "").strip().lower() in ("1", "true", "yes"):
        lo.info(
            "PECUNATOR_ENGINE_STUB set: engine exits without HTTP API. "
            "Unset to start the API (default host 127.0.0.1:8765).",
        )
        return
    import uvicorn

    from runtime.api.app import create_app
    from runtime.core.settings import api_bind_host, api_bind_port

    host = api_bind_host()
    port = api_bind_port()
    lo.info("Starting engine HTTP API at http://%s:%s (docs /docs)", host, port)
    uvicorn.run(
        create_app(),
        host=host,
        port=port,
        log_level=os.environ.get("UVICORN_LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
