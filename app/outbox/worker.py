"""Poll pending outbox rows and deliver via SMTP.

Run: ``python -m app.outbox.worker`` (Compose service ``outbox-worker``).
Single-worker take-home: use SKIP LOCKED so a second process would not double-send.
"""

from __future__ import annotations

import time

from app.config import settings
from app.db import SessionLocal
from app.outbox.services import process_batch
from app.telemetry import configure_telemetry


def run_once() -> int:
    with SessionLocal() as db:
        return process_batch(db)


def run_loop(*, once: bool = False) -> None:
    while True:
        run_once()
        if once:
            return
        time.sleep(settings.outbox_poll_seconds)  # pragma: no cover


def main() -> None:  # pragma: no cover
    configure_telemetry()
    run_loop()


if __name__ == "__main__":  # pragma: no cover
    main()
