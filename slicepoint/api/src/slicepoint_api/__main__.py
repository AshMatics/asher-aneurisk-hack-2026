"""``slicepoint-api`` / ``python -m slicepoint_api``: run the service with uvicorn.

One process, one worker: job state is in memory (plus JSON on disk). Binds to
127.0.0.1 unless ``SLICEPOINT_API_HOST`` says otherwise.
"""

from __future__ import annotations

import logging
import sys

from .settings import Settings, SettingsError


def main() -> None:
    import uvicorn

    from .app import create_app

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        settings = Settings.from_env()
        app = create_app(settings)
    except SettingsError as exc:
        sys.stderr.write(f"slicepoint-api: {exc}\n")
        raise SystemExit(2) from None
    uvicorn.run(app, host=settings.host, port=settings.port, workers=1, access_log=False,
                proxy_headers=False, server_header=False)


if __name__ == "__main__":
    main()
