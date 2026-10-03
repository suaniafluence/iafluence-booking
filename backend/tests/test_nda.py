"""Confidentiality agreement (NDA): PDF uploaded by the admin, asked for by the customer, returned signed."""

from email import message_from_bytes

import pytest
from sqlalchemy import select, update

from app.db import SessionLocal
from app.models import Booking, Customer
from app.routers import public
from app.services import nda
from app.services.email_service import build_message
from tests.conftest import staff_login, ADMIN_PASSWORD, NOW, paris

pytestmark = pytest.mark.usefixtures("db_clean")

PDF = b"%PDF-1.7\n% NDA signe par Suan Tay\n%%EOF\n"
PDF_EN = b"%PDF-1.7\n% NDA signed by Suan Tay\n%%EOF\n"
SLOT = paris(2026, 10, 6, 14)


@pytest.fixture(autouse=True)
def fresh_limiter():
    public.discovery_limiter.reset()


def login(client):
    staff_login(client)


def upload(client, locale="fr", pdf=PDF, filename="NDA IAfluence - signé.pdf"):
    return client.put(
        f"/api/consultant/nda/documents/{locale}",
        params={"filename": filename},
        content=pdf,
        headers={"Content-Type": "application/pdf"},
    )


def nda_mails(fakes) -> list[dict]:
    return [m for m in fakes["mailer"].sent if m.get("attachments")]


def customer(email: str) -> Customer:
    with SessionLocal() as db:
        return db.scalar(select(Customer).where(Customer.email == email))


def book_discovery(client, email="paul@example.com", start=paris(2026, 10, 6, 9, 30), **kw):
    body = {"name": "Paul Prospect", "email": email, "start": start.isoformat(), **kw}
    return client.post("/api/discovery", json=body)


# --- admin: the signed PDF ---------------------------------------------------------------------------------------


def test_endpoints_require_the_admin_session(client):
    assert client.get("/api/consultant/nda").status_code == 401
    assert upload(client).status_code == 401
    assert client.get("/api/consultant/nda/documents/fr.pdf").status_code == 401
    assert client.delete("/api/consultant/nda/documents/fr").status_code == 401
    assert client.post("/api/consultant/nda/send", json={"name": "A", "email": "a@example.com"}).status_code == 401
    assert client.patch("/api/consultant/customers/1/nda", json={"signed": True}).status_code == 401


def test_upload_replace_download_and_delete_the_pdf(client):
    login(client)
    assert client.get("/api/consultant/nda").json() == {"documents": [], "customers": []}
    r = upload(client)
    assert r.status_code == 200, r.text
    assert r.json() == {"locale": "fr", "filename": "NDA IAfluence - signé.pdf", "size": len(PDF)}

    assert upload(client, pdf=PDF + b"v2", filename="nda-v2.pdf").json()["filename"] == "nda-v2.pdf"
    r = client.get("/api/consultant/nda/documents/fr.pdf")
    assert (r.status_code, r.content, r.headers["content-type"]) == (200, PDF + b"v2", "application/pdf")
    assert r.headers["cache-control"] == "private, no-store"
    assert client.get("/api/consultant/nda").json()["documents"] == [
        {"locale": "fr", "filename": "nda-v2.pdf", "size": len(PDF) + 2, "uploaded_at": NOW.isoformat()}
    ]

    assert client.delete("/api/consultant/nda/documents/fr").json() == {"status": "deleted"}
    assert client.get("/api/consultant/nda/documents/fr.pdf").status_code == 404
    assert client.delete("/api/consultant/nda/documents/fr").status_code == 404


def test_upload_refuses_what_is_not_a_pdf_too_big_or_an_unknown_language(client, monkeypatch):
    login(client)
    r = upload(client, pdf=b"<html>not a pdf</html>")
    assert (r.status_code, r.json()["detail"]) == (422, "Ce fichier n'est pas un PDF.")
    assert upload(client, locale="de").status_code == 404
    assert upload(client, locale="FR").status_code == 404
    monkeypatch.setattr(nda, "MAX_PDF_BYTES", len(PDF) - 1)
    assert upload(client).status_code == 413
    assert client.get("/api/consultant/nda").json()["documents"] == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, "NDA-IAfluence.pdf"),
        ("", "NDA-IAfluence.pdf"),
        ("C:\\Users\\suan\\NDA.pdf", "NDA.pdf"),
        ("../../etc/accord", "accord.pdf"),
        ('nda"\r\n<x>.PDF', "ndax.PDF"),
        ("???", "NDA-IAfluence.pdf"),
    ],
)
def test_clean_filename(raw, expected):
    assert nda.clean_filename(raw) == expected


# --- the box on the public pages ---------------------------------------------------------------------------------


def test_box_is_offered_once_the_french_pdf_is_uploaded(client, token_for):
    token = token_for()
    assert client.get("/api/discovery").json()["nda_available"] is False
    login(client)
    upload(client, locale="en", pdf=PDF_EN)
    # English alone is not enough: French is the fallback of every language.
    assert client.get(f"/api/booking/{token}").json()["nda_available"] is False
    upload(client)
    assert client.get("/api/discovery").json()["nda_available"] is True
    ctx = client.get(f"/api/booking/{token}").json()
    assert (ctx["nda_available"], ctx["nda_sent"]) == (True, False)


def test_first_session_with_the_box_ticked_emails_the_signed_pdf(client, fakes, token_for):
    login(client)
    upload(client)
    token = token_for(email="jean@example.com", name="Jean Dupont")
    r = client.post("/api/bookings", json={"token": token, "start": SLOT.isoformat(), "nda": True})
    assert r.status_code == 201, r.text

    [mail] = nda_mails(fakes)
    assert mail["to"] == "jean@example.com"
    assert mail["subject"] == "Accord de confidentialité (NDA) — IAfluence"
    assert mail["attachments"] == [("NDA IAfluence - signé.pdf", PDF)]
    assert mail["body"].startswith("Bonjour Jean Dupont,\n")
    assert "renvoyez-le en réponse à cet email" in mail["body"]
    assert mail["body"].endswith("Suan Tay\nIAfluence\n")
    [admin] = [m for m in fakes["mailer"].sent if m["to"] == "admin@iafluence.test"]
    assert "NDA :\nDemandé par le client" in admin["body"]

    assert customer("jean@example.com").nda_sent_at is not None
    assert client.get(f"/api/booking/{token}").json()["nda_sent"] is True
    listed = client.get("/api/consultant/nda").json()["customers"]
    assert [(c["email"], c["signed_at"]) for c in listed] == [("jean@example.com", None)]


def test_without_the_box_nothing_is_sent(client, fakes, token_for):
    login(client)
    upload(client)
    token = token_for()
    assert client.post("/api/bookings", json={"token": token, "start": SLOT.isoformat()}).status_code == 201
    assert nda_mails(fakes) == []
    [admin] = [m for m in fakes["mailer"].sent if m["to"] == "admin@iafluence.test"]
    assert "NDA" not in admin["body"]
    assert customer("jean@example.com").nda_sent_at is None


def test_discovery_with_the_box_sends_the_pdf_of_the_visitor_language(client, fakes):
    login(client)
    upload(client)
    upload(client, locale="en", pdf=PDF_EN, filename="NDA-EN.pdf")
    r = book_discovery(client, nda=True, locale="en")
    assert r.status_code == 201, r.text
    [mail] = nda_mails(fakes)
    assert (mail["subject"], mail["attachments"]) == ("Non-disclosure agreement (NDA) — IAfluence", [("NDA-EN.pdf", PDF_EN)])
    assert mail["body"].startswith("Hello Paul Prospect,\n")
    admin = next(m for m in fakes["mailer"].sent if m["subject"] == "NOUVEL APPEL DÉCOUVERTE")
    assert "NDA :" in admin["body"]


def test_a_language_without_its_own_pdf_gets_the_french_one(client, fakes):
    login(client)
    upload(client)
    assert book_discovery(client, nda=True, locale="es").status_code == 201
    [mail] = nda_mails(fakes)
    assert mail["subject"] == "Acuerdo de confidencialidad (NDA) — IAfluence"
    assert mail["body"].startswith("Hola, Paul Prospect:\n")
    assert mail["attachments"] == [("NDA IAfluence - signé.pdf", PDF)]


def test_the_public_form_sends_it_once_per_address(client, fakes):
    login(client)
    upload(client)
    assert book_discovery(client, nda=True).status_code == 201
    with SessionLocal() as db:  # the call is over: the same person books another one
        db.execute(update(Booking).values(status="completed"))
        db.commit()
    assert book_discovery(client, nda=True, start=paris(2026, 10, 7, 9, 30)).status_code == 201
    assert len(nda_mails(fakes)) == 1


def test_box_ticked_but_no_pdf_sends_nothing(client, fakes):
    assert book_discovery(client, nda=True).status_code == 201
    assert nda_mails(fakes) == []
    assert customer("paul@example.com").nda_sent_at is None


def test_gmail_failure_leaves_it_unsent(client, fakes):
    login(client)
    upload(client)
    fakes["mailer"].fail = True
    assert book_discovery(client, nda=True).status_code == 201
    assert customer("paul@example.com").nda_sent_at is None


# --- admin: sending by hand and « Signé reçu » -------------------------------------------------------------------


def test_admin_sends_it_to_a_new_contact_and_again_to_a_known_one(client, fakes):
    login(client)
    r = client.post("/api/consultant/nda/send", json={"name": "Claire", "email": "claire@example.com"})
    assert (r.status_code, r.json()["detail"]) == (409, "Téléversez d'abord le NDA signé (PDF).")
    assert customer("claire@example.com") is None

    upload(client)
    r = client.post("/api/consultant/nda/send", json={"name": " Claire Durand ", "email": "Claire@Example.com"})
    assert r.status_code == 200, r.text
    assert r.json()["sent_at"] == NOW.isoformat()
    c = customer("claire@example.com")
    assert (c.name, r.json()["customer_id"]) == ("Claire Durand", c.id)

    # Resent on demand, even though she already received it; she keeps her name.
    r = client.post("/api/consultant/nda/send", json={"name": "Autre nom", "email": "claire@example.com", "locale": "en"})
    assert r.status_code == 200
    assert customer("claire@example.com").name == "Claire Durand"
    assert [m["to"] for m in nda_mails(fakes)] == ["claire@example.com", "claire@example.com"]
    assert nda_mails(fakes)[1]["subject"].startswith("Non-disclosure agreement")


def test_admin_send_reports_a_gmail_failure(client, fakes):
    login(client)
    upload(client)
    fakes["mailer"].fail = True
    r = client.post("/api/consultant/nda/send", json={"name": "Claire", "email": "claire@example.com"})
    assert (r.status_code, r.json()["detail"]) == (502, "Gmail a refusé l'email du NDA (voir les logs de l'API).")
    assert customer("claire@example.com") is None


def test_signed_received_is_ticked_and_unticked(client, fakes):
    login(client)
    upload(client)
    cid = client.post("/api/consultant/nda/send", json={"name": "Claire", "email": "claire@example.com"}).json()["customer_id"]

    r = client.patch(f"/api/consultant/customers/{cid}/nda", json={"signed": True})
    assert r.json() == {"customer_id": cid, "signed_at": NOW.isoformat()}
    assert client.get("/api/consultant/nda").json()["customers"] == [
        {
            "customer_id": cid,
            "name": "Claire",
            "email": "claire@example.com",
            "sent_at": NOW.isoformat(),
            "signed_at": NOW.isoformat(),
        }
    ]
    assert client.patch(f"/api/consultant/customers/{cid}/nda", json={"signed": False}).json()["signed_at"] is None


def test_signed_needs_a_sent_agreement_and_a_known_customer(client, token_for):
    login(client)
    token_for()
    cid = customer("jean@example.com").id
    r = client.patch(f"/api/consultant/customers/{cid}/nda", json={"signed": True})
    assert (r.status_code, r.json()["detail"]) == (409, "Le NDA n'a pas encore été envoyé à ce client.")
    assert client.patch("/api/consultant/customers/999/nda", json={"signed": True}).status_code == 404


# --- the email itself --------------------------------------------------------------------------------------------


def test_built_message_attaches_the_pdf():
    msg = message_from_bytes(build_message("a@example.com", "NDA", "Bonjour", attachments=[("NDA.pdf", PDF)]).as_bytes())
    assert msg.get_content_type() == "multipart/mixed"
    body, pdf = msg.get_payload()
    plain, html = body.get_payload()
    assert plain.get_payload(decode=True).decode().strip() == "Bonjour"
    assert html.get_content_type() == "text/html"
    assert (pdf.get_content_type(), pdf.get_filename(), pdf.get_payload(decode=True)) == ("application/pdf", "NDA.pdf", PDF)
