from datetime import datetime
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, EmailStr, Field, StringConstraints


class Slot(BaseModel):
    start: datetime
    end: datetime


class AvailabilityOut(BaseModel):
    slots: list[Slot]


class CustomerOut(BaseModel):
    name: str
    email: str


class PurchaseOut(BaseModel):
    product_name: str
    hours_purchased: int
    hours_booked: int
    hours_remaining: int


class BookingOut(BaseModel):
    start: datetime
    end: datetime
    meet_url: str | None


class BookingContextOut(BaseModel):
    customer: CustomerOut
    purchase: PurchaseOut
    booking: BookingOut | None
    consultant_name: str
    timezone: str
    booking_duration_min: int
    locale: str


class CheckoutOut(BaseModel):
    token: str
    locale: str


class BookingIn(BaseModel):
    token: str
    start: AwareDatetime
    # Language of the page and IANA time zone of the browser; unknown values are ignored.
    locale: str | None = Field(None, max_length=16)
    timezone: str | None = Field(None, max_length=64)


class BookingConfirmedOut(BaseModel):
    status: str
    start: datetime
    end: datetime
    meet_url: str | None
    hours_purchased: int
    hours_booked: int
    hours_remaining: int


class LoginIn(BaseModel):
    password: str


# Stripped before the length check, so whitespace-only values are rejected.
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class ManualClientIn(BaseModel):
    name: Label
    email: EmailStr
    hours: int = Field(ge=1, le=100)
    product_name: Label = "Conseil IA"
    amount_cents: int = Field(0, ge=0)
    send_link: bool = True


class ManualClientOut(BaseModel):
    purchase_id: int
    booking_url: str


class CustomerPatchIn(BaseModel):
    auto_send_next_link: bool


class CancelBookingIn(BaseModel):
    notify: bool = True


class PurchaseHoursIn(BaseModel):
    hours_purchased: int = Field(ge=0, le=100)


class ReportSettingsIn(BaseModel):
    send_without_review: bool


class FirefliesConnectIn(BaseModel):
    api_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]
