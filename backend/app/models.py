from datetime import datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    Time,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(320), unique=True)
    # End of session: send the next-session link directly, or leave it as a Gmail draft (default) to add notes.
    auto_send_next_link: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False)
    # Confidentiality agreement (app.services.nda): emailed signed by the consultant, returned signed by the
    # customer in reply (the admin ticks it off).
    nda_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    nda_signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    purchases: Mapped[list["Purchase"]] = relationship(back_populates="customer")


class Purchase(Base):
    __tablename__ = "purchases"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    stripe_checkout_session_id: Mapped[str] = mapped_column(String(255), unique=True)
    stripe_payment_id: Mapped[str | None] = mapped_column(String(255), index=True)
    product_id: Mapped[str] = mapped_column(String(255))
    product_name: Mapped[str] = mapped_column(String(255))
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8))
    hours_purchased: Mapped[int] = mapped_column(Integer)
    hours_booked: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    payment_status: Mapped[str] = mapped_column(String(32))  # paid | refunded
    # Customer-facing language (fr | en | es) and the IANA time zone of the browser used to book.
    locale: Mapped[str] = mapped_column(String(5), server_default="fr", default="fr")
    customer_timezone: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    customer: Mapped[Customer] = relationship(back_populates="purchases")
    bookings: Mapped[list["Booking"]] = relationship(back_populates="purchase")

    __table_args__ = (
        CheckConstraint("hours_booked >= 0 AND hours_booked <= hours_purchased", name="hours_booked_range"),
    )

    @property
    def hours_remaining(self) -> int:
        return self.hours_purchased - self.hours_booked


class BookingToken(Base):
    __tablename__ = "booking_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_id: Mapped[int] = mapped_column(ForeignKey("purchases.id"), index=True)
    token: Mapped[str] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    purchase: Mapped[Purchase] = relationship()


class Booking(Base):
    """A paid consulting session (`session`), a free discovery call booked on /decouverte (`discovery`), or a
    meeting booked elsewhere whose Fireflies recording the admin chose to summarize (`meeting`).

    Only sessions belong to a purchase. The others carry the customer's language and time zone themselves.
    """

    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), server_default="session", default="session")
    purchase_id: Mapped[int | None] = mapped_column(ForeignKey("purchases.id"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    start_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    google_event_id: Mapped[str | None] = mapped_column(String(255))
    meet_url: Mapped[str | None] = mapped_column(String(512))
    # confirmed (upcoming) -> completed once it has ended (app.services.follow_up) | cancelled
    status: Mapped[str] = mapped_column(String(32))
    # Meeting: its Fireflies title. Discovery and meeting: the customer's language and browser time zone.
    title: Mapped[str | None] = mapped_column(String(255))
    locale: Mapped[str | None] = mapped_column(String(5))
    customer_timezone: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    purchase: Mapped[Purchase | None] = relationship(back_populates="bookings")
    customer: Mapped[Customer] = relationship()

    @property
    def client_locale(self) -> str:
        return self.purchase.locale if self.purchase else (self.locale or "fr")

    @property
    def client_timezone(self) -> str | None:
        return self.purchase.customer_timezone if self.purchase else self.customer_timezone

    __table_args__ = (
        CheckConstraint("start_datetime < end_datetime", name="booking_interval_order"),
        CheckConstraint("kind IN ('session', 'discovery', 'meeting')", name="booking_kind"),
        CheckConstraint("(kind = 'session') = (purchase_id IS NOT NULL)", name="booking_purchase_iff_session"),
        # One upcoming discovery call per person (email).
        Index(
            "uq_bookings_one_discovery_per_customer",
            "customer_id",
            unique=True,
            postgresql_where=text("kind = 'discovery' AND status = 'confirmed'"),
        ),
        # R03 — one upcoming session per purchase: finished ones move to 'completed', freeing the next.
        Index(
            "uq_bookings_one_confirmed_per_purchase",
            "purchase_id",
            unique=True,
            postgresql_where=text("status = 'confirmed'"),
        ),
        # R10 — no two confirmed bookings may overlap.
        ExcludeConstraint(
            (func.tstzrange(text("start_datetime"), text("end_datetime")), "&&"),
            name="ex_bookings_no_overlap",
            using="gist",
            where=text("status = 'confirmed'"),
        ),
    )


class SessionReport(Base):
    """Summary of a finished session, written by the Codex agent from the Fireflies transcript.

    waiting_transcript -> summarizing -> ready -> drafted | failed (app.services.session_reports).
    The transcript itself is never stored: only its Fireflies id, the summary and the infographic.
    """

    __tablename__ = "session_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), unique=True)
    status: Mapped[str] = mapped_column(String(32))
    # Start of the Fireflies wait window (end of the session, or the last « Relancer »).
    waiting_since: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    transcript_attempts: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    summary_attempts: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    # A process summarizing the report holds it until then (Codex turns take minutes: no row lock meanwhile).
    claimed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fireflies_transcript_id: Mapped[str | None] = mapped_column(String(128))
    summary: Mapped[dict | None] = mapped_column(JSONB)
    image_png: Mapped[bytes | None] = mapped_column(LargeBinary)
    # Short reason shown in the admin — never transcript content.
    error: Mapped[str | None] = mapped_column(Text)
    # How the client email went out: draft | sent | failed (Gmail refused it); with_summary tells whether it
    # carried the summary.
    delivery: Mapped[str | None] = mapped_column(String(16))
    with_summary: Mapped[bool | None] = mapped_column(Boolean)
    drafted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Summary and image erased after REPORT_RETENTION_DAYS.
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    booking: Mapped[Booking] = relationship()

    __table_args__ = (
        CheckConstraint(
            "status IN ('waiting_transcript', 'summarizing', 'ready', 'drafted', 'failed')", name="report_status"
        ),
        Index("ix_session_reports_status_next_attempt", "status", "next_attempt_at"),
        # A recording is summarized once, whether matched to a session or picked by the admin.
        Index(
            "uq_session_reports_transcript",
            "fireflies_transcript_id",
            unique=True,
            postgresql_where=text("fireflies_transcript_id IS NOT NULL"),
        ),
    )


class CodexLogin(Base):
    """Device authorization of the codex app-server with the ChatGPT plan (OAuth 2.0, RFC 8628).

    Only what the admin needs to see is stored: the OAuth tokens stay inside the codex container.
    PENDING -> COMPLETED | EXPIRED | DENIED | CANCELLED | ERROR
    """

    __tablename__ = "codex_logins"

    id: Mapped[int] = mapped_column(primary_key=True)
    login_id: Mapped[str] = mapped_column(String(128))
    verification_url: Mapped[str] = mapped_column(String(512))
    # One-time code the admin types on the OpenAI page; blanked once the login is over.
    user_code: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    error: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # « Déconnecter » ends the session this login opened.
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'COMPLETED', 'EXPIRED', 'DENIED', 'CANCELLED', 'ERROR')", name="codex_login_status"
        ),
    )


class CalendarSource(Base):
    __tablename__ = "calendar_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    google_calendar_id: Mapped[str] = mapped_column(String(512), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true", default=True)


class Settings(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_duration_min: Mapped[int] = mapped_column(Integer, default=60)
    slot_step_min: Mapped[int] = mapped_column(Integer, default=60)
    minimum_notice_min: Mapped[int] = mapped_column(Integer, default=24 * 60)
    maximum_window_days: Mapped[int] = mapped_column(Integer, default=30)
    buffer_before_min: Mapped[int] = mapped_column(Integer, default=15)
    buffer_after_min: Mapped[int] = mapped_column(Integer, default=15)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Paris")
    booking_calendar_id: Mapped[str] = mapped_column(String(512), default="primary")
    meet_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    admin_email: Mapped[str] = mapped_column(String(320), default="")
    consultant_name: Mapped[str] = mapped_column(String(255), default="Suan Tay")
    # Customers on « Envoi auto »: an email carrying a generated summary is still left as a draft for review,
    # unless this is on.
    send_reports_without_review: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False)
    # « Connexion Fireflies » (app.services.fireflies_account): API key encrypted with a key derived from
    # SESSION_SECRET, and the account it belongs to, for display. Empty = FIREFLIES_API_KEY of the server, if any.
    fireflies_api_key_enc: Mapped[str | None] = mapped_column(Text)
    fireflies_email: Mapped[str | None] = mapped_column(String(320))
    fireflies_name: Mapped[str | None] = mapped_column(String(255))
    fireflies_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Free discovery call (/decouverte): same weekly hours, notice and buffers as the sessions.
    discovery_enabled: Mapped[bool] = mapped_column(Boolean, server_default="true", default=True)
    discovery_duration_min: Mapped[int] = mapped_column(Integer, server_default="30", default=30)


class NdaDocument(Base):
    """The confidentiality agreement already signed by the consultant, one PDF per customer language.

    French is the reference: a customer whose language has no PDF of its own receives it."""

    __tablename__ = "nda_documents"

    locale: Mapped[str] = mapped_column(String(5), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    pdf: Mapped[bytes] = mapped_column(LargeBinary)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (CheckConstraint("locale IN ('fr', 'en', 'es')", name="nda_locale"),)


class AvailabilityRule(Base):
    __tablename__ = "availability_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    weekday: Mapped[int] = mapped_column(SmallInteger)  # 0 = lundi … 6 = dimanche
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)

    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint("start_time < end_time", name="rule_interval_order"),
    )


class StripeEvent(Base):
    __tablename__ = "stripe_events"

    event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    type: Mapped[str] = mapped_column(String(128))
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    note: Mapped[str | None] = mapped_column(Text)
