"""parse_checkout and LiveStripeGateway — pure, no database."""

import pytest
import stripe

from app.config import Config
from app.services import stripe_service
from app.services.stripe_service import MAX_HOURS, LiveStripeGateway, PaymentInvalid, parse_checkout


def item(hours="5", *, product_id="prod_5h", name="Conseil IA - 5h", quantity=1, description=None, product=None):
    metadata = {} if hours is None else {"hours": hours}
    return {
        "quantity": quantity,
        "description": description,
        "price": {"product": product if product is not None else {"id": product_id, "name": name, "metadata": metadata}},
    }


def session(*items, **over) -> dict:
    base = {
        "id": "cs_test_1",
        "payment_status": "paid",
        "payment_intent": "pi_1",
        "amount_total": 50_000,
        "currency": "EUR",
        "customer_details": {"email": "  Jean.Dupont@Example.COM ", "name": "  Jean Dupont  "},
        "line_items": {"data": list(items) or [item()]},
    }
    base.update(over)
    return base


def test_extracts_and_normalises_every_field():
    info = parse_checkout(session())
    assert info == stripe_service.CheckoutInfo(
        session_id="cs_test_1",
        payment_intent_id="pi_1",
        email="jean.dupont@example.com",
        name="Jean Dupont",
        amount_cents=50_000,
        currency="eur",
        product_id="prod_5h",
        product_name="Conseil IA - 5h",
        hours=5,
        locale="fr",
    )


@pytest.mark.parametrize("over, locale", [({"locale": "en"}, "en"), ({"client_reference_id": "es"}, "es")])
def test_language_chosen_on_the_website_is_kept(over, locale):
    assert parse_checkout(session(**over)).locale == locale


def test_expanded_payment_intent_object_is_reduced_to_its_id():
    assert parse_checkout(session(payment_intent={"id": "pi_obj", "object": "payment_intent"})).payment_intent_id == "pi_obj"


def test_missing_payment_intent_is_allowed():
    assert parse_checkout(session(payment_intent=None)).payment_intent_id is None


@pytest.mark.parametrize("status", ["unpaid", "no_payment_required", None])
def test_refuses_unpaid_sessions(status):
    with pytest.raises(PaymentInvalid, match="payment not completed"):
        parse_checkout(session(payment_status=status))


def test_email_falls_back_to_customer_email():
    info = parse_checkout(session(customer_details=None, customer_email=" Marie@Example.com"))
    assert info.email == "marie@example.com"
    assert info.name == "marie@example.com"  # no name -> email is used


@pytest.mark.parametrize("details", [None, {}, {"email": ""}, {"email": "   "}])
def test_refuses_session_without_email(details):
    with pytest.raises(PaymentInvalid, match="no customer email"):
        parse_checkout(session(customer_details=details))


def test_blank_name_falls_back_to_email():
    assert parse_checkout(session(customer_details={"email": "a@b.fr", "name": "   "})).name == "a@b.fr"


def test_defaults_for_missing_amount_and_currency():
    info = parse_checkout(session(amount_total=None, currency=None))
    assert (info.amount_cents, info.currency) == (0, "eur")


def test_quantity_multiplies_hours_and_missing_quantity_means_one():
    assert parse_checkout(session(item("2", quantity=3))).hours == 6
    assert parse_checkout(session(item("2", quantity=None))).hours == 2


def test_hours_are_summed_across_items_and_first_product_wins():
    info = parse_checkout(session(item("2", product_id="prod_a", name="A"), item("3", product_id="prod_b", name="B")))
    assert (info.hours, info.product_id, info.product_name) == (5, "prod_a", "A")


@pytest.mark.parametrize("bad", ["abc", "", None, "0", "-2", "1.5"])
def test_items_with_invalid_hours_are_ignored(bad):
    info = parse_checkout(session(item(bad, product_id="prod_bad"), item("1", product_id="prod_ok")))
    assert (info.hours, info.product_id) == (1, "prod_ok")
    with pytest.raises(PaymentInvalid, match="no eligible product"):
        parse_checkout(session(item(bad)))


def test_unexpanded_product_is_ignored():
    with pytest.raises(PaymentInvalid, match="no eligible product"):
        parse_checkout(session(item(product="prod_5h")))


@pytest.mark.parametrize("line_items", [None, {}, {"data": []}, {"data": [{"quantity": 1, "price": None}]}])
def test_refuses_session_without_line_items(line_items):
    with pytest.raises(PaymentInvalid, match="no eligible product"):
        parse_checkout(session(line_items=line_items))


def test_product_name_fallbacks():
    assert parse_checkout(session(item(name=None, description="Desc ligne"))).product_name == "Desc ligne"
    assert parse_checkout(session(item(name=None))).product_name == "Conseil IA"


def test_max_hours_boundary():
    assert parse_checkout(session(item(str(MAX_HOURS)))).hours == MAX_HOURS
    with pytest.raises(PaymentInvalid, match="unexpected hours quantity"):
        parse_checkout(session(item(str(MAX_HOURS + 1))))


def test_allowed_product_ids_filter(monkeypatch):
    monkeypatch.setattr(stripe_service, "get_config", lambda: Config(stripe_allowed_product_ids="prod_ok, prod_other"))
    info = parse_checkout(session(item("9", product_id="prod_foreign"), item("2", product_id="prod_ok")))
    assert (info.hours, info.product_id) == (2, "prod_ok")
    with pytest.raises(PaymentInvalid):
        parse_checkout(session(item("9", product_id="prod_foreign")))


def test_config_allowed_product_ids_parsing():
    assert Config(stripe_allowed_product_ids=" a, ,b ,").allowed_product_ids == {"a", "b"}
    assert Config(stripe_allowed_product_ids="").allowed_product_ids == set()


# --- LiveStripeGateway -------------------------------------------------------------


class _StripeObj(dict):
    def to_dict(self):
        return dict(self)


def test_live_gateway_retrieves_expanded_session(monkeypatch):
    calls = []

    def retrieve(session_id, **kw):
        calls.append((session_id, kw))
        return _StripeObj(id=session_id)

    monkeypatch.setattr(stripe_service, "get_config", lambda: Config(stripe_secret_key="rk_test_x"))
    monkeypatch.setattr(stripe.checkout.Session, "retrieve", retrieve)
    assert LiveStripeGateway().retrieve_checkout_session("cs_1") == {"id": "cs_1"}
    assert calls == [("cs_1", {"expand": ["line_items.data.price.product"], "api_key": "rk_test_x"})]


def test_live_gateway_unknown_session_is_payment_invalid(monkeypatch):
    def retrieve(session_id, **kw):
        raise stripe.InvalidRequestError("No such checkout.session", "id")

    monkeypatch.setattr(stripe.checkout.Session, "retrieve", retrieve)
    with pytest.raises(PaymentInvalid, match="^unknown checkout session$"):
        LiveStripeGateway().retrieve_checkout_session("cs_nope")


def test_live_gateway_verifies_webhook_signature_with_secret(monkeypatch):
    calls = []

    def construct_event(payload, signature, secret):
        calls.append((payload, signature, secret))
        return _StripeObj(id="evt_1")

    monkeypatch.setattr(stripe_service, "get_config", lambda: Config(stripe_webhook_secret="whsec_x"))
    monkeypatch.setattr(stripe.Webhook, "construct_event", construct_event)
    assert LiveStripeGateway().construct_event(b"{}", "t=1,v1=abc") == {"id": "evt_1"}
    assert calls == [(b"{}", "t=1,v1=abc", "whsec_x")]
