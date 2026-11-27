"""stdlib SMTP send; no-op when SMTP_HOST is empty (tests / local without MailDev)."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.config import settings

_tracer = trace.get_tracer("prior-auth-api.smtp")


def send_smtp(to: str, subject: str, body: str) -> None:
    if not settings.smtp_host:
        return
    with _tracer.start_as_current_span("smtp.send") as span:
        host = settings.smtp_host
        port = settings.smtp_port
        span.set_attribute("server.address", host)
        span.set_attribute("server.port", port)
        span.set_attribute("mail.to_count", 1)
        msg = EmailMessage()
        msg["From"] = settings.smtp_from
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        try:
            with smtplib.SMTP(host, port) as client:
                client.send_message(msg)
        except Exception as exc:
            error_message = str(exc)
            error_status = Status(StatusCode.ERROR, error_message)
            span.set_status(error_status)
            span.record_exception(exc)
            raise
