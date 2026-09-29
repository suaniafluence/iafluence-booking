from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Environment-level configuration (secrets, URLs). Business settings live in the DB."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://iafluence:iafluence@localhost:5432/iafluence"
    public_base_url: str = "http://localhost:5173"

    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    # Comma-separated list of Stripe product IDs accepted for booking. Empty = any product with metadata `hours`.
    stripe_allowed_product_ids: str = ""

    google_client_id: str = ""
    google_client_secret: str = ""
    google_refresh_token: str = ""
    # Sender address for Gmail API emails (the authorised Gmail account).
    mail_from: str = ""
    mail_from_name: str = "Suan Tay — IAfluence"

    admin_password_hash: str = ""
    session_secret: str = "change-me"
    cookie_secure: bool = True

    # Local demo only: replace Google/Stripe/Gmail with in-memory fakes (see app/dev_fakes.py).
    fake_integrations: bool = False

    @property
    def allowed_product_ids(self) -> set[str]:
        return {p.strip() for p in self.stripe_allowed_product_ids.split(",") if p.strip()}


@lru_cache
def get_config() -> Config:
    return Config()
