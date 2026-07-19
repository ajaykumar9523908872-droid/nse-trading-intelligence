"""Configuration foundation (M18).

Layered config: defaults -> environment -> local overrides.
Secrets come from the environment only, never from source control (MASTER_PLAN §21.4).
"""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Paths — L0 archive is the disaster-recovery floor (MASTER_PLAN §10.1)
    data_dir: Path = Field(default=PROJECT_ROOT / "data")

    # Network behaviour for M01a. NSE applies bot mitigation, so a browser-like
    # session is required rather than a bare request (Appendix B, MN-2).
    http_timeout_seconds: int = 30
    http_max_retries: int = 3
    http_backoff_seconds: float = 2.0
    # Politeness delay between requests to a public source we do not pay for.
    http_delay_seconds: float = 1.0

    # Database (M05). Credentials come from the environment, never from source
    # control (§21.4). The default password is a local development value only.
    db_host: str = "127.0.0.1"
    db_port: int = 5432
    db_name: str = "nse_ti"
    db_user: str = "nse"
    db_password: str = "nse_local_dev"

    @property
    def archive_dir(self) -> Path:
        return self.data_dir / "archive"

    @property
    def db_dsn(self) -> str:
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def db_dsn_display(self) -> str:
        """DSN with the password redacted — safe to log (§21.4)."""
        return f"postgresql://{self.db_user}:***@{self.db_host}:{self.db_port}/{self.db_name}"


settings = Settings()
