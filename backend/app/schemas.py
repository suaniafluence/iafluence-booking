from datetime import datetime

from pydantic import AwareDatetime, BaseModel, EmailStr, Field


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


class CheckoutOut(BaseModel):
    token: str


class BookingIn(BaseModel):
    token: str
    start: AwareDatetime


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


class ManualClientIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    hours: int = Field(ge=1, le=100)
    product_name: str = Field("Conseil IA", min_length=1, max_length=255)
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
