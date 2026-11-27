from __future__ import annotations

import logging

from app.log_pii import (
    REDACTED,
    PiiRedactingFilter,
    ScrubbingSpanExporter,
    _redact_value,
    install_pii_log_filter,
    redact_text,
    scrub_db_statement,
    scrub_span_attributes,
)
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExportResult
from opentelemetry.trace import SpanContext, SpanKind, TraceFlags
from opentelemetry.trace.status import Status, StatusCode


def test_redact_text_masks_email_jwt_bearer_and_fields():
    raw = (
        "user=office@riverside.example.com "
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.e30.sig "
        'clinical_note="patient has diabetes" '
        "denial_reason=Not medically necessary "
        "member_id=22222222-2222-2222-2222-222222222222"
    )
    out = redact_text(raw)
    assert "office@riverside.example.com" not in out
    assert "eyJhbGciOiJIUzI1NiJ9" not in out
    assert "patient has diabetes" not in out
    assert "Not medically necessary" not in out
    assert "22222222-2222-2222-2222-222222222222" not in out
    assert REDACTED in out


def test_filter_redacts_msg_and_args(caplog):
    logger = logging.getLogger("test.pii.filter")
    logger.addFilter(PiiRedactingFilter())
    logger.setLevel(logging.INFO)
    with caplog.at_level(logging.INFO, logger="test.pii.filter"):
        logger.info("note=%s email=%s", 'clinical_note="secret chart"', "a@b.co")
        logger.info("payload %s", {"denial_reason": "too expensive", "ok": "keep"})
        logger.info("list %s", ["user@example.com"])
        logger.info("tuple %s", ("password=hunter2",))
    text = caplog.text
    assert "secret chart" not in text
    assert "a@b.co" not in text
    assert "too expensive" not in text
    assert "hunter2" not in text
    assert "user@example.com" not in text
    assert "keep" in text
    assert REDACTED in text


def test_filter_non_string_msg_and_empty_args():
    record = logging.LogRecord(
        name="test.pii",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=42,
        args=(),
        exc_info=None,
    )
    assert PiiRedactingFilter().filter(record) is True
    assert record.msg == 42


def test_redact_value_passthrough_and_containers():
    assert _redact_value(7) == 7
    assert _redact_value(("a@b.co",)) == (REDACTED,)
    assert _redact_value(["a@b.co"]) == [REDACTED]


def test_install_pii_log_filter_idempotent():
    install_pii_log_filter()
    root = logging.getLogger()
    before = sum(1 for f in root.filters if isinstance(f, PiiRedactingFilter))
    install_pii_log_filter()
    after = sum(1 for f in root.filters if isinstance(f, PiiRedactingFilter))
    assert after == before
    assert before >= 1


def test_scrub_db_statement_masks_sql_literals_and_fields():
    sql = (
        "INSERT INTO prior_auth.prior_auth_requests (clinical_note) VALUES ('patient has diabetes')"
    )
    out = scrub_db_statement(sql)
    assert "patient has diabetes" not in out
    assert f"'{REDACTED}'" in out


def test_scrub_span_attributes_targets_statement_keys_only():
    assert scrub_span_attributes(None) == {}
    attrs = scrub_span_attributes(
        {
            "db.statement": "UPDATE t SET n='secret note'",
            "db.query.text": "SELECT 'ssn-value' FROM t",
            "db.system": "postgresql",
            "http.method": "GET",
        }
    )
    assert "secret note" not in attrs["db.statement"]
    assert "ssn-value" not in attrs["db.query.text"]
    assert attrs["db.system"] == "postgresql"
    assert attrs["http.method"] == "GET"


def test_scrubbing_span_exporter_delegates():
    captured: list = []

    class FakeExporter:
        def export(self, spans):
            captured.extend(spans)
            return SpanExportResult.SUCCESS

        def shutdown(self):
            captured.append("shutdown")

        def force_flush(self, timeout_millis: int = 30000):
            captured.append(("flush", timeout_millis))
            return True

    ctx = SpanContext(
        trace_id=1,
        span_id=2,
        is_remote=False,
        trace_flags=TraceFlags(0x01),
    )
    status = Status(StatusCode.UNSET)
    span = ReadableSpan(
        name="SELECT",
        context=ctx,
        attributes={"db.statement": "SELECT 'phi-here'"},
        kind=SpanKind.CLIENT,
        status=status,
    )
    exporter = ScrubbingSpanExporter(FakeExporter())
    result = exporter.export([span])
    assert result is SpanExportResult.SUCCESS
    assert len(captured) == 1
    assert "phi-here" not in captured[0].attributes["db.statement"]
    assert f"'{REDACTED}'" in captured[0].attributes["db.statement"]
    exporter.force_flush(1000)
    exporter.shutdown()
    assert ("flush", 1000) in captured
    assert "shutdown" in captured
