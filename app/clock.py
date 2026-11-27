from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")


def get_today() -> date:
    return datetime.now(TZ).date()


def utc_now() -> datetime:
    return datetime.now(UTC)
