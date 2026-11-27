"""Poll pending outbox rows and deliver via SMTP.

Run: ``python -m app.outbox.worker`` (Compose service ``outbox-worker``).
Single-worker deploy: use SKIP LOCKED so a second process would not double-send.
"""

from __future__ import annotations

import logging
import time

from app.config import settings
from app.db import SessionLocal
from app.outbox.services import process_batch
from app.telemetry import configure_telemetry

_log = logging.getLogger(__name__)


def run_once() -> int:
    with SessionLocal() as db:
        delivered = process_batch(db)
    if delivered:
        _log.info("outbox delivered batch_size=%s", delivered)
    return delivered


def run_loop(*, once: bool = False) -> None:
    while True:
        run_once()
        if once:
            return
        time.sleep(settings.outbox_poll_seconds)  # pragma: no cover


def main() -> None:  # pragma: no cover
    configure_telemetry()
    poll = settings.outbox_poll_seconds
    _log.info("outbox worker starting poll_seconds=%s", poll)
    run_loop()


if __name__ == "__main__":  # pragma: no cover
    main()
