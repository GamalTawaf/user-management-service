from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://prior:prior@localhost:5432/prior_auth"
    jwt_secret: str = "dev-only-change-me-32bytes-min!!"
    jwt_algorithm: str = "HS256"
    otel_service_name: str = "prior-auth-api"
    # In-app body cap (set the same limit on any reverse proxy in front).
    max_request_body_bytes: int = 262_144
    # Empty SMTP_HOST → mailer no-op (pytest); Compose sets maildev for the worker.
    smtp_host: str = ""
    smtp_port: int = 1025
    smtp_from: str = "noreply@prior-auth.local"
    outbox_poll_seconds: float = 2.0
    outbox_batch_size: int = 20


settings = Settings()
