from app.db import APP_SCHEMA


def test_app_schema_name():
    assert APP_SCHEMA == "user_mgmt"
