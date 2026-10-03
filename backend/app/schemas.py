from datetime import datetime
from typing import Annotated, Literal

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
    # Confidentiality agreement: offered when its PDF is uploaded and this customer has not received it yet.
    nda_available: bool
    nda_sent: bool


class CheckoutOut(BaseModel):
    token: str
    locale: str


class BookingIn(BaseModel):
    token: str
    start: AwareDatetime
    # Language of the page and IANA time zone of the browser; unknown values are ignored.
    locale: str | None = Field(None, max_length=16)
    timezone: str | None = Field(None, max_length=64)
    # Box ticked: email the confidentiality agreement (app.services.nda).
    nda: bool = False


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


# How a customer came. 'site' is set by the website itself; the others are chosen for a client added by hand.
AcquisitionSource = Literal["site", "whatsapp", "recommandation", "linkedin", "reseau", "email_telephone", "autre"]
OptionalText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)]


class ManualClientIn(BaseModel):
    name: Label
    email: EmailStr
    acquisition_source: AcquisitionSource
    acquisition_detail: OptionalText | None = None
    # No hours: the client is only added to the follow-up (a prospect), without a purchase or booking link.
    hours: int | None = Field(None, ge=1, le=100)
    product_name: OptionalText | None = None
    amount_cents: int = Field(0, ge=0)
    send_link: bool = True


class ManualClientOut(BaseModel):
    customer_id: int
    purchase_id: int | None
    booking_url: str | None


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


class DiscoveryInfoOut(BaseModel):
    consultant_name: str
    timezone: str
    duration_min: int
    nda_available: bool


class DiscoveryIn(BaseModel):
    name: Label
    email: EmailStr
    start: AwareDatetime
    # What the visitor would like to talk about (optional), shown in the Google event and the admin email.
    message: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] = ""
    locale: str | None = Field(None, max_length=16)
    timezone: str | None = Field(None, max_length=64)
    nda: bool = False
    # Honeypot: hidden from people, filled in by bots.
    website: str = Field("", max_length=255)


class DiscoveryOut(BaseModel):
    start: datetime
    end: datetime
    meet_url: str | None


class MeetingReportIn(BaseModel):
    transcript_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    title: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] | None = None
    start: AwareDatetime
    end: AwareDatetime
    name: Label
    email: EmailStr
    locale: Literal["fr", "en", "es"] = "fr"


class NdaSendIn(BaseModel):
    name: Label
    email: EmailStr
    locale: Literal["fr", "en", "es"] = "fr"


class NdaSignedIn(BaseModel):
    signed: bool


# --- V3: staff accounts, settings, consultant cockpit ---------------------------------------------------------


class StaffUserIn(BaseModel):
    email: EmailStr
    name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] = ""
    is_admin: bool = False
    is_consultant: bool = True


class StaffUserPatchIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] | None = None
    is_admin: bool | None = None
    is_consultant: bool | None = None
    active: bool | None = None
    unlink_google: bool = False


class PlatformSettingsIn(BaseModel):
    reminder_enabled: bool | None = None
    reminder_after_days: int | None = Field(None, ge=1, le=365)
    reminder_auto_send: bool | None = None
    hide_after_days: int | None = Field(None, ge=2, le=730)


class LearnerPatchIn(BaseModel):
    company_name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] | None = None
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=10_000)] | None = None
    acquisition_source: AcquisitionSource | None = None
    acquisition_detail: OptionalText | None = None


class CompanyAttachIn(BaseModel):
    siren: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^\d{9}$")]


class PlanMessageIn(BaseModel):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class PlanValidateIn(BaseModel):
    validated: bool
