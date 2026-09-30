from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Environment-level configuration (secrets, URLs). Business settings live in the DB."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://iafluence:iafluence@localhost:5432/iafluence"
    public_base_url: str = "http://localhost:5173"
    # Where clients buy more hours (thank-you email after their last session).
    shop_url: str = "https://iafluence.fr"

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

    # End-of-session job: how often finished sessions are closed and the next-session link emailed. 0 = off.
    follow_up_poll_seconds: int = 60

    # Session reports (app.services.session_reports): Fireflies transcript -> Codex summary -> Gmail draft.
    # Off unless both the Fireflies key and the codex app-server URL are set.
    fireflies_api_key: str = ""
    fireflies_api_url: str = "https://api.fireflies.ai/graphql"
    # One Fireflies request per poll for all waiting sessions. Free plan (50 requests/day): raise to 1800.
    fireflies_poll_seconds: int = 300
    # No transcript after this long: the email is prepared without a summary and the admin is alerted.
    fireflies_max_wait_hours: int = 6
    # codex app-server (deploy/codex), reached over the internal Docker network with a shared capability token.
    codex_app_server_url: str = ""
    codex_ws_token: str = ""
    codex_model: str = ""  # empty = the default model of the ChatGPT plan
    codex_turn_timeout_seconds: int = 600
    # Summaries and infographics are personal data: erased from the database after this many days. 0 = kept.
    report_retention_days: int = 90

    # Local demo only: replace Google/Stripe/Gmail/Fireflies/Codex with in-memory fakes (see app/dev_fakes.py).
    fake_integrations: bool = False
    # Demo only: also write every email as a .eml file in this directory (E2E checks, example drafts).
    demo_outbox_dir: str = ""

    @property
    def session_reports_enabled(self) -> bool:
        return self.fake_integrations or bool(self.fireflies_api_key and self.codex_app_server_url)

    @property
    def allowed_product_ids(self) -> set[str]:
        return {p.strip() for p in self.stripe_allowed_product_ids.split(",") if p.strip()}


@lru_cache
def get_config() -> Config:
    return Config()
