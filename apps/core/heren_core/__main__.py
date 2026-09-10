"""heren-core entrypoint:  python -m heren_core  (reads HEREN_CONFIG / HEREN_* env)."""
from __future__ import annotations

import logging
from pathlib import Path

import uvicorn

from heren_core.app import create_app
from heren_core.config import Settings
from heren_core.netaccess import access_urls, ensure_self_signed


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    settings = Settings.load()
    log = logging.getLogger("heren")
    cert: Path | None = None
    key: Path | None = None
    if settings.tls:
        if settings.tls_cert and settings.tls_key:
            cert, key = settings.tls_cert, settings.tls_key
        else:
            cert, key = ensure_self_signed(settings.tls_dir)
            log.info("tls: self-signed certificate at %s (accept it once on each phone)", cert)
    urls = access_urls(settings)
    if urls:
        log.info("phone/tablet access: %s", "  ".join(urls))
    elif settings.host in ("127.0.0.1", "localhost"):
        log.info("bound to %s only — set HEREN_HOST=0.0.0.0 HEREN_TLS=true for phone access", settings.host)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info",
                ssl_certfile=str(cert) if cert else None, ssl_keyfile=str(key) if key else None)


if __name__ == "__main__":
    main()
