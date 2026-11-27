from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://ums:ums@localhost:5433/user_mgmt"
    jwt_secret: str = "dev-only-change-me-32bytes-min!!"
    jwt_algorithm: str = "HS256"
    otel_service_name: str = "user-management-api"
    log_level: str = "INFO"
    max_request_body_bytes: int = 262_144
    smtp_host: str = ""
    smtp_port: int = 1025
    smtp_from: str = "noreply@user-mgmt.local"
    outbox_poll_seconds: float = 2.0
    outbox_batch_size: int = 20
    redis_url: str = ""
    rate_limit_enabled: bool = True
    rate_limit_capacity: int = 120
    rate_limit_refill_per_second: float = 2.0
    rate_limit_key_prefix: str = "rl:"


settings = Settings()
