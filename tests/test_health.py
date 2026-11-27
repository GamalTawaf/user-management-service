from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.main import app
from fastapi.testclient import TestClient


def test_health_ok():
    client = TestClient(app)
    response = client.get("/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_today_is_new_york_date():
    from app.clock import get_today

    today = get_today()
    assert isinstance(today, date)
    assert today == datetime.now(ZoneInfo("America/New_York")).date()
