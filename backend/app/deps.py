"""Injectable external gateways — overridden in tests via app.dependency_overrides."""

from datetime import UTC, datetime
from functools import lru_cache

from app.config import get_config
from app.services.calendar_service import CalendarGateway, GoogleCalendarGateway
from app.services.codex import CodexGateway, LiveCodex
from app.services.email_service import GmailMailer, Mailer
from app.services.fireflies import FirefliesGateway, LiveFireflies
from app.services.stripe_service import LiveStripeGateway, StripeGateway


@lru_cache
def get_calendar() -> CalendarGateway:
    if get_config().fake_integrations:
        from app.dev_fakes import DemoCalendar

        return DemoCalendar()
    return GoogleCalendarGateway()


@lru_cache
def get_mailer() -> Mailer:
    if get_config().fake_integrations:
        from app.dev_fakes import DemoMailer

        return DemoMailer()
    return GmailMailer()


@lru_cache
def get_stripe() -> StripeGateway:
    if get_config().fake_integrations:
        from app.dev_fakes import DemoStripe

        return DemoStripe()
    return LiveStripeGateway()


@lru_cache
def get_fireflies() -> FirefliesGateway:
    if get_config().fake_integrations:
        from app.dev_fakes import DemoFireflies

        return DemoFireflies()
    from app.services.fireflies_account import current_key

    return LiveFireflies(api_key=current_key)


@lru_cache
def get_codex() -> CodexGateway:
    if get_config().fake_integrations:
        from app.dev_fakes import DemoCodex

        return DemoCodex()
    return LiveCodex()


def get_now() -> datetime:
    return datetime.now(UTC)
