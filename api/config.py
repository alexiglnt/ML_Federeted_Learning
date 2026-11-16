"""Runtime configuration, read from the environment.

Everything is overridable by an environment variable so that the same image
runs locally and on a server without a code change. Defaults are chosen to make
`docker compose up` work with no `.env` at all — but see `secret_key`, which
deliberately refuses to keep its default outside development.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent

DEV_SECRET = "dev-only-insecure-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_prefix="MLFL_", extra="ignore"
    )

    # "development" relaxes a few guards (see check()); anything else is
    # treated as a real deployment.
    environment: str = "development"

    database_url: str = "postgresql+psycopg://mlfl:mlfl@db:5432/mlfl"

    # Signs the session cookie. Rotating it logs everybody out, which is the
    # intended emergency lever.
    secret_key: str = DEV_SECRET
    session_cookie: str = "mlfl_session"
    session_max_age_days: int = 30

    # Uploaded files live on disk, never in the database and never under a
    # directory the web server will serve. Mounted as a volume in
    # docker-compose so uploads survive a rebuild.
    data_dir: Path = ROOT / "var" / "data"

    # Refuses anything larger, before reading the body into memory.
    max_upload_bytes: int = 16 * 1024 * 1024

    # Minimum rows for a contribution. Not a statistical threshold — a privacy
    # one. Sufficient statistics are not anonymous on very few rows, and on a
    # single row they reproduce it exactly. See ARCHITECTURE.md §5.1.
    min_contribution_rows: int = 5

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def artefact_dir(self) -> Path:
        return self.data_dir / "artefacts"

    def check(self) -> None:
        """Fail loudly at startup rather than quietly in production."""
        if not self.is_development and self.secret_key == DEV_SECRET:
            raise RuntimeError(
                "MLFL_SECRET_KEY is still the development default. Set it to a "
                "random value before running outside development."
            )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.check()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.artefact_dir.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()
