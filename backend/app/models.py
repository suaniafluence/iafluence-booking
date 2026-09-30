from datetime import datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(320), unique=True)
    # End of session: send the next-session link directly, or leave it as a Gmail draft (default) to add notes.
    auto_send_next_link: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False)
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
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_id: Mapped[int] = mapped_column(ForeignKey("purchases.id"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    start_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    google_event_id: Mapped[str | None] = mapped_column(String(255))
    meet_url: Mapped[str | None] = mapped_column(String(512))
    # confirmed (upcoming) -> completed once it has ended (app.services.follow_up) | cancelled
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    purchase: Mapped[Purchase] = relationship(back_populates="bookings")
    customer: Mapped[Customer] = relationship()

    __table_args__ = (
        CheckConstraint("start_datetime < end_datetime", name="booking_interval_order"),
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
