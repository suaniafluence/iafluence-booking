from datetime import datetime

from pydantic import AwareDatetime, BaseModel


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
