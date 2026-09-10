"""heren-core entrypoint:  python -m heren_core  (reads HEREN_CONFIG / HEREN_* env)."""
from __future__ import annotations

import logging

import uvicorn

from heren_core.app import create_app
from heren_core.config import Settings


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    settings = Settings.load()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
