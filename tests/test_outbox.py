from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from app.config import settings
from app.outbox.mailer import send_smtp
from app.outbox.models import OutboxEvent, OutboxStatus
from app.outbox.services import (
    process_batch,
    render_decision_notice_body,
    render_decision_notice_subject,
)
from app.outbox.worker import main, run_loop, run_once
from app.prior_auth.models import PriorAuthRequest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.conftest import (
    TWO_PROCEDURES,
    approve_all_outcomes,
    decide_as,
    submit_and_claim,
)


def _decide_denied(client: TestClient) -> dict:
    data = submit_and_claim(client, procedures=TWO_PROCEDURES, clinical_note="secret note")
    outcomes = [
        {"procedure_id": data["procedures"][0]["uuid"], "decision": "approved"},
        {
            "procedure_id": data["procedures"][1]["uuid"],
            "decision": "denied",
            "denial_reason": "Not medically necessary",
        },
    ]
    decided = decide_as(client, data["uuid"], outcomes)
    assert decided.status_code == 200, decided.text
    return decided.json()


def test_decide_enqueues_pending_outbox(client: TestClient, db: Session):
    body = _decide_denied(client)
    events = list(
        db.scalars(select(OutboxEvent).where(OutboxEvent.request_id == body["uuid"])).all()
    )
    assert len(events) == 1
    event = events[0]
    assert event.status == OutboxStatus.pending
    assert event.attempts == 0
    assert event.payload["to"] == client.seed["practice"].notification_email
    member = client.seed["member"]
    assert "Prior authorization decided" in event.payload["subject"]
    assert member.full_name in event.payload["subject"]
    assert member.external_id in event.payload["subject"]
    assert str(body["uuid"]) not in event.payload["subject"]
    email_body = event.payload["body"]
    assert "secret note" not in email_body
    assert "Not medically necessary" not in email_body
    assert "clinical_note" not in email_body
    assert "denial_reason" not in email_body
    assert "Approved" in email_body
    assert "Denied" in email_body
    assert member.full_name in email_body
    assert member.external_id in email_body
    assert str(body["uuid"]) in email_body
    assert "nurse or physician has decided" in email_body
    assert f"Patient: {member.full_name} ({member.external_id})" in email_body
    assert "Member:" not in email_body


def test_worker_mocked_send_marks_sent(client: TestClient, db: Session):
    body = _decide_denied(client)
    sent: list[tuple[str, str, str]] = []

    def fake_send(to: str, subject: str, text: str) -> None:
        sent.append((to, subject, text))

    n = process_batch(db, send_fn=fake_send)
    assert n == 1
    assert len(sent) == 1
    event = db.scalars(select(OutboxEvent).where(OutboxEvent.request_id == body["uuid"])).one()
    assert event.status == OutboxStatus.sent
    assert event.attempts == 1
    assert event.sent_at is not None
    assert event.last_error is None


def test_worker_send_failure_bumps_attempts(client: TestClient, db: Session):
    body = _decide_denied(client)

    def boom(_to: str, _subject: str, _text: str) -> None:
        raise RuntimeError("smtp down")

    n = process_batch(db, send_fn=boom)
    assert n == 1
    event = db.scalars(select(OutboxEvent).where(OutboxEvent.request_id == body["uuid"])).one()
    assert event.status == OutboxStatus.failed
    assert event.attempts == 1
    assert "smtp down" in (event.last_error or "")


def test_send_smtp_noop_without_host(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "smtp_host", "")
    send_smtp("a@b.c", "s", "body")


def test_send_smtp_uses_stdlib(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "smtp_host", "maildev")
    monkeypatch.setattr(settings, "smtp_port", 1025)
    monkeypatch.setattr(settings, "smtp_from", "noreply@prior-auth.local")
    captured: list = []

    class FakeSMTP:
        def __init__(self, host: str, port: int):
            captured.append(("init", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def send_message(self, msg):
            captured.append(("send", msg["To"], msg["Subject"], msg.get_content()))

    monkeypatch.setattr("app.outbox.mailer.smtplib.SMTP", FakeSMTP)
    send_smtp("office@ex.com", "Prior auth decision — x", "hello")
    assert captured[0] == ("init", "maildev", 1025)
    assert captured[1][0] == "send"
    assert captured[1][1] == "office@ex.com"


def test_send_smtp_records_error_on_span(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "smtp_host", "maildev")
    monkeypatch.setattr(settings, "smtp_port", 1025)
    monkeypatch.setattr(settings, "smtp_from", "noreply@prior-auth.local")

    class BoomSMTP:
        def __init__(self, host: str, port: int):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def send_message(self, _msg):
            raise RuntimeError("smtp boom")

    monkeypatch.setattr("app.outbox.mailer.smtplib.SMTP", BoomSMTP)
    with pytest.raises(RuntimeError, match="smtp boom"):
        send_smtp("office@ex.com", "subj", "body")


def test_render_body_uses_member_id_when_no_member():
    request = MagicMock(spec=PriorAuthRequest)
    request.uuid = "rid"
    request.member_id = "mid"
    request.date_of_service.isoformat.return_value = "2026-01-01"
    proc = MagicMock()
    proc.sequence = 1
    proc.code = "99213"
    proc.decision.value = "approved"
    request.procedures = [proc]
    subject = render_decision_notice_subject(request, None)
    text = render_decision_notice_body(request, None)
    assert subject == "Prior authorization decided for patient mid"
    assert "Patient: mid" in text
    assert "nurse or physician has decided" in text
    assert "doctors' office" in text
    assert "• 99213 — Approved" in text
    assert "Clinical notes and denial reasons are not included" in text


def test_run_loop_once(monkeypatch: pytest.MonkeyPatch):
    calls: list[int] = []

    def fake_once() -> int:
        calls.append(1)
        return 0

    monkeypatch.setattr("app.outbox.worker.run_once", fake_once)
    run_loop(once=True)
    assert calls == [1]


def test_run_loop_sleeps_then_stops(monkeypatch: pytest.MonkeyPatch):
    def noop_once() -> int:
        return 0

    monkeypatch.setattr("app.outbox.worker.run_once", noop_once)
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        raise StopIteration

    monkeypatch.setattr("app.outbox.worker.time.sleep", fake_sleep)
    with pytest.raises(StopIteration):
        run_loop(once=False)
    assert sleeps == [settings.outbox_poll_seconds]


def test_main_delegates(monkeypatch: pytest.MonkeyPatch):
    calls: list[int] = []
    configured: list[int] = []

    def fake_configure() -> None:
        configured.append(1)

    def fake_loop() -> None:
        calls.append(1)

    monkeypatch.setattr("app.outbox.worker.configure_telemetry", fake_configure)
    monkeypatch.setattr("app.outbox.worker.run_loop", fake_loop)
    main()
    assert configured == [1]
    assert calls == [1]


def test_run_once_calls_process_batch(monkeypatch: pytest.MonkeyPatch):
    class FakeSession:
        def __enter__(self):
            return "db"

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr("app.outbox.worker.SessionLocal", FakeSession)
    seen: list = []

    def fake_process(db, **_kwargs):
        seen.append(db)
        return 0

    monkeypatch.setattr("app.outbox.worker.process_batch", fake_process)
    assert run_once() == 0
    assert seen == ["db"]


def test_process_batch_empty(db: Session):
    assert process_batch(db, limit=5) == 0


def test_approve_all_still_enqueues(client: TestClient, db: Session):
    data = submit_and_claim(client)
    decided = decide_as(client, data["uuid"], approve_all_outcomes(data["procedures"]))
    assert decided.status_code == 200
    events = list(
        db.scalars(
            select(OutboxEvent).where(OutboxEvent.request_id == decided.json()["uuid"])
        ).all()
    )
    assert len(events) == 1
    assert events[0].status == OutboxStatus.pending
