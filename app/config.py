from pydantic_settings import BaseSettings, SettingsConfigDict

_JWT_SECRET_MIN_LEN = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://ums:ums@localhost:5433/user_mgmt"
    jwt_secret: str = "dev-only-change-me-32bytes-min!!"
    jwt_algorithm: str = "HS256"
    allow_insecure_defaults: bool = False
    otel_service_name: str = "user-management-api"
    log_level: str = "INFO"
    max_request_body_bytes: int = 262_144
    smtp_host: str = ""
    smtp_port: int = 1025
    smtp_from: str = "noreply@user-mgmt.local"
    outbox_poll_seconds: float = 2.0
    outbox_batch_size: int = 20
    outbox_max_attempts: int = 5
    redis_url: str = ""
    rate_limit_enabled: bool = True
    rate_limit_capacity: int = 120
    rate_limit_refill_per_second: float = 2.0
    rate_limit_key_prefix: str = "rl:"

    def validate_security(self) -> None:
        """Refuse short JWT secrets unless explicitly opted into insecure mode."""
        if len(self.jwt_secret) >= _JWT_SECRET_MIN_LEN:
            return
        if self.allow_insecure_defaults:
            return
        raise RuntimeError(
            f"JWT_SECRET must be at least {_JWT_SECRET_MIN_LEN} characters "
            "(set ALLOW_INSECURE_DEFAULTS=true only for local demos)"
        )


settings = Settings()
