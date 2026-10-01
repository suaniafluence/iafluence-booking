"""Customer language and time zone handling — pure, no database."""

import pytest

from app import i18n


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("en", "en"),
        ("en-GB", "en"),
        ("es-419", "es"),
        (" FR ", "fr"),
        ("auto", None),
        ("de", None),
        ("", None),
        (None, None),
        (42, None),
    ],
)
def test_normalize_locale(raw, expected):
    assert i18n.normalize_locale(raw) == expected


@pytest.mark.parametrize(
    "session, expected",
    [
        ({"locale": "en"}, "en"),
        # Stripe "auto" (browser language) -> fall back to the reference set by iafluence.fr.
        ({"locale": "auto", "client_reference_id": "es"}, "es"),
        ({"locale": None, "client_reference_id": None, "metadata": {"lang": "en"}}, "en"),
        ({"locale": "es", "client_reference_id": "en"}, "es"),
        ({"client_reference_id": "order_123"}, "fr"),
        ({}, "fr"),
        ({"metadata": None}, "fr"),
    ],
)
def test_checkout_locale(session, expected):
    assert i18n.checkout_locale(session) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Australia/Sydney", "Australia/Sydney"),
        ("America/Santiago", "America/Santiago"),
        ("UTC", "UTC"),
        ("Mars/Olympus", None),
        ("../../etc/passwd", None),
        ("/absolute", None),
        ("", None),
        (None, None),
        ("A" * 65, None),
    ],
)
def test_valid_timezone(raw, expected):
    assert i18n.valid_timezone(raw) == expected


def test_every_language_has_every_text():
    keys = set(i18n.TEXTS[i18n.DEFAULT_LOCALE])
    assert set(i18n.TEXTS) == set(i18n.LOCALES)
    for locale in i18n.LOCALES:
        assert set(i18n.TEXTS[locale]) == keys, locale


def test_text_formats_and_falls_back_to_french():
    assert i18n.text("en", "event_summary", name="Ana") == "AI consulting - Ana"
    assert i18n.text("es", "event_summary", name="Ana") == "Asesoría en IA - Ana"
    assert i18n.text("de", "event_summary", name="Ana") == "Conseil IA - Ana"
