"""Consultant cockpit: learners and their time, company profile, web research, action plans (real PostgreSQL)."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.config import get_config
from app.db import SessionLocal
from app.models import (
    ActionPlan,
    Booking,
    BookingToken,
    Customer,
    CustomerProfile,
    Purchase,
    SessionReport,
    StaffUser,
)
from app.services import action_plans, company, learners
from app.services.codex import CodexNotConnected, CodexUnavailable
from tests.conftest import NOW, SYNTHESE, paris, staff_login

pytestmark = pytest.mark.usefixtures("db_clean")


@pytest.fixture
def cockpit(client):
    staff_login(client)
    return client


@pytest.fixture
def codex_on(monkeypatch):
    monkeypatch.setattr(get_config(), "codex_app_server_url", "ws://codex:4500")


def add_customer(name, email, consultant_id=1, **kw) -> int:
    with SessionLocal() as db:
        c = Customer(name=name, email=email, consultant_id=consultant_id, **kw)
        db.add(c)
        db.commit()
        return c.id


def add_purchase(customer_id, hours, created=paris(2026, 9, 1, 10), status="paid", token="tok") -> int:
    with SessionLocal() as db:
        p = Purchase(
            customer_id=customer_id, stripe_checkout_session_id=f"cs_{customer_id}_{hours}_{created:%m%d}",
            product_id="prod", product_name=f"Conseil IA - {hours}h", amount_cents=hours * 100_00, currency="eur",
            hours_purchased=hours, hours_booked=0, payment_status=status, created_at=created,
        )
        db.add(p)
        db.flush()
        if token:
            db.add(BookingToken(purchase_id=p.id, token=f"{token}-{p.id}"))
        db.commit()
        return p.id


def add_booking(customer_id, start, kind="session", purchase_id=None, status="completed", minutes=60, message=None) -> int:
    with SessionLocal() as db:
        b = Booking(
            kind=kind, purchase_id=purchase_id, customer_id=customer_id, start_datetime=start,
            end_datetime=start + timedelta(minutes=minutes), status=status, message=message,
            meet_url="https://meet.google.com/x" if status == "confirmed" else None,
        )
        db.add(b)
        if purchase_id:
            db.execute(update(Purchase).where(Purchase.id == purchase_id).values(hours_booked=Purchase.hours_booked + 1))
        db.commit()
        return b.id


def add_report(booking_id, status="drafted", summary=SYNTHESE):
    with SessionLocal() as db:
        db.add(SessionReport(booking_id=booking_id, status=status, waiting_since=NOW, summary=summary))
        db.commit()


def plan_answer(sessions=3, minutes=60, reponse="Plan rédigé.", objectif="Diviser par trois le temps des devis") -> str:
    def seance(n):
        return {
            "numero": n, "titre": f"Séance {n}", "objectif": "Un livrable", "duree_min": minutes,
            "deroule": [{"minutes": 10, "activite": "Point"}, {"minutes": minutes - 10, "activite": "Atelier"}],
            "livrable": "Prototype", "preparation_client": ["Dix devis"],
        }

    return json.dumps(
        {
            "reponse": reponse,
            "plan": {
                "resume": "Premier cas d'usage : les devis.",
                "objectif": objectif,
                "diagnostic": ["Devis à la main (appel)"],
                "priorites": [{"titre": "Devis", "pourquoi": "Cité en premier", "gain_attendu": "4 h/semaine", "effort": "faible"}],
                "seances": [seance(n) for n in range(1, sessions + 1)],
                "entre_les_seances": ["Tester sur trois devis"],
                "indicateurs": ["Temps par devis"],
                "risques": [{"risque": "RGPD", "parade": "Compte pro"}],
                "outils": [{"nom": "ChatGPT Team", "usage": "Rédaction", "cout": "30 €/mois"}],
                "hypotheses_a_verifier": [],
                "questions_ouvertes": ["Qui valide ?"],
            },
        },
        ensure_ascii=False,
    )


@pytest.fixture
def jean():
    """5 h bought on 1 September: sessions on 14 and 28 September, the next one on 8 October."""
    cid = add_customer("Jean Dupont", "jean@dupont-conseil.fr")
    pid = add_purchase(cid, 5)
    add_booking(cid, paris(2026, 9, 14, 10), purchase_id=pid)
    add_booking(cid, paris(2026, 9, 28, 10), purchase_id=pid)
    add_booking(cid, paris(2026, 10, 8, 14), purchase_id=pid, status="confirmed")
    return cid


# --- learners -----------------------------------------------------------------------------------------------------


def test_learner_time_management(cockpit, jean):
    data = cockpit.get("/api/consultant/learners").json()
    [row] = data["learners"]
    assert data["settings"] == {"reminder_after_days": 21, "hide_after_days": 60, "session_duration_min": 60}
    assert row | {"alerts": None} == {
        "customer_id": jean, "name": "Jean Dupont", "email": "jean@dupont-conseil.fr", "company": None,
        "status": "en_cours", "hours_purchased": 5, "sessions_done": 2, "sessions_to_deliver": 3,
        "hours_to_schedule": 2, "next_session": {
            "id": 3, "kind": "session", "start": "2026-10-08T14:00:00+02:00", "end": "2026-10-08T15:00:00+02:00",
            "meet_url": "https://meet.google.com/x",
        },
        "last_session": {"id": 2, "kind": "session", "start": "2026-09-28T10:00:00+02:00", "end": "2026-09-28T11:00:00+02:00", "meet_url": None},
        "idle_days": None, "hidden": False, "pace_days": 14.0,
        # 3 sessions left at one every 14 days, from today.
        "projected_end": "2026-11-16T08:00:00+01:00",
        "plan_status": None, "reminder_sent_at": None, "alerts": None,
    }
    assert row["alerts"] == [{"niveau": "info", "texte": "Pas encore de plan d'action"}]


def test_idle_learners_leave_the_list_and_come_back(cockpit):
    gone = add_customer("Marie Martin", "marie@example.com")
    pid = add_purchase(gone, 2, created=paris(2026, 7, 1, 10))
    add_booking(gone, paris(2026, 8, 1, 10), purchase_id=pid)  # 64 days ago
    data = cockpit.get("/api/consultant/learners").json()
    assert data["learners"] == [] and data["hidden_count"] == 1
    [row] = cockpit.get("/api/consultant/learners?hidden=true").json()["learners"]
    assert (row["hidden"], row["idle_days"]) == (True, 64)
    assert {"niveau": "attention", "texte": "Aucune séance prévue depuis 64 jours"} in row["alerts"]
    add_booking(gone, paris(2026, 10, 12, 10), purchase_id=pid, status="confirmed")
    [row] = cockpit.get("/api/consultant/learners").json()["learners"]
    assert row["hidden"] is False and row["idle_days"] is None


def test_statuses(cockpit):
    prospect = add_customer("Paul Prospect", "paul@example.com")
    add_booking(prospect, paris(2026, 9, 20, 10), kind="discovery", minutes=30)
    done = add_customer("Fini", "fini@example.com")
    pid = add_purchase(done, 1)
    add_booking(done, paris(2026, 9, 30, 10), purchase_id=pid)
    refunded = add_customer("Remboursé", "r@example.com")
    add_purchase(refunded, 3, status="refunded")
    rows = {r["name"]: r for r in cockpit.get("/api/consultant/learners").json()["learners"]}
    assert rows["Paul Prospect"]["status"] == "prospect" and rows["Paul Prospect"]["idle_days"] == 14
    assert rows["Fini"]["status"] == "termine" and rows["Fini"]["sessions_to_deliver"] == 0
    assert rows["Remboursé"]["status"] == "rembourse" and rows["Remboursé"]["hours_purchased"] == 0
    assert rows["Paul Prospect"]["alerts"] == []


def test_a_consultant_sees_only_their_learners(cockpit):
    with SessionLocal() as db:
        db.add(StaffUser(email="claire@exemple.fr", is_consultant=True))
        db.commit()
    other = add_customer("Chez Claire", "c@example.com", consultant_id=2)
    mine = add_customer("Sans consultant", "s@example.com", consultant_id=None)
    names = [r["name"] for r in cockpit.get("/api/consultant/learners").json()["learners"]]
    assert names == ["Sans consultant"]
    assert cockpit.get(f"/api/consultant/learners/{other}").status_code == 404
    assert cockpit.get(f"/api/consultant/learners/{mine}").status_code == 200


def test_detail(cockpit, jean):
    call = add_booking(jean, paris(2026, 8, 25, 10), kind="discovery", minutes=30, message="Automatiser les devis")
    add_report(call)
    d = cockpit.get(f"/api/consultant/learners/{jean}").json()
    assert d["customer"]["email"] == "jean@dupont-conseil.fr"
    assert d["time"]["sessions_to_deliver"] == 3 and d["time"]["session_duration_min"] == 60
    [purchase] = d["purchases"]
    assert purchase["booking_url"] == f"https://booking.iafluence.test/fr/reservation/tok-{purchase['id']}"
    assert [t["kind"] for t in d["timeline"]] == ["session", "session", "session", "discovery"]
    discovery = d["timeline"][-1]
    assert discovery["message"] == "Automatiser les devis" and discovery["report"]["synthese"] == SYNTHESE
    assert d["company"] is None and d["research"]["status"] is None and d["plan"] is None


def test_notes_and_company_name(cockpit, jean):
    r = cockpit.patch(f"/api/consultant/learners/{jean}", json={"notes": "  Très pressé  ", "company_name": "Dupont SAS"})
    assert r.json() == {
        "customer_id": jean,
        "company_name": "Dupont SAS",
        "notes": "Très pressé",
        "acquisition_source": None,
        "acquisition_detail": None,
    }
    r = cockpit.patch(f"/api/consultant/learners/{jean}", json={"notes": ""})
    assert r.json()["notes"] is None and r.json()["company_name"] == "Dupont SAS"


def test_cockpit_needs_the_consultant_role(client, jean):
    assert client.post("/api/admin/login", json={"password": "test-password"}).status_code == 200
    assert client.get("/api/consultant/learners").status_code == 401


# --- company profile ----------------------------------------------------------------------------------------------

DUPONT = {
    "siren": "812345678", "nom_complet": "DUPONT CONSEIL", "etat_administratif": "A", "date_creation": "2015-06-01",
    "tranche_effectif_salarie": "02", "siege": {"adresse": "1 rue X 69001 LYON", "activite_principale": "70.22Z"},
    "dirigeants": [{"type_dirigeant": "personne physique", "nom": "DUPONT", "prenoms": "Jean", "qualite": "Gérant"}],
    "finances": {"2024": {"ca": 300000, "resultat_net": -5000}, "2023": {"ca": 400000, "resultat_net": 20000}},
    "complements": {"est_qualiopi": True, "est_ess": False},
}


def test_company_search_attach_detach(cockpit, fakes, jean):
    fakes["company"].companies = [DUPONT]
    r = cockpit.get(f"/api/consultant/learners/{jean}/company/search").json()
    # Searched from the email domain.
    assert r["query"] == "dupont conseil" and fakes["company"].queries == ["dupont conseil"]
    [found] = r["results"]
    assert (found["nom"], found["effectif"], found["activite_code"], found["labels"]) == (
        "DUPONT CONSEIL", "3 à 5 salariés", "70.22Z", ["Certifié Qualiopi"]
    )
    assert found["dirigeants"] == [{"nom": "Jean DUPONT", "qualite": "Gérant"}]

    attached = cockpit.put(f"/api/consultant/learners/{jean}/company", json={"siren": "812345678"}).json()
    assert attached["siren"] == "812345678"
    d = cockpit.get(f"/api/consultant/learners/{jean}").json()
    assert d["customer"]["siren"] == "812345678" and d["customer"]["company_name"] == "DUPONT CONSEIL"
    assert d["company"]["finances"][0] == {"annee": 2024, "ca": 300000, "resultat_net": -5000}

    assert cockpit.delete(f"/api/consultant/learners/{jean}/company").json() == {"status": "detached"}
    d = cockpit.get(f"/api/consultant/learners/{jean}").json()
    assert d["company"] is None and d["customer"]["siren"] is None


def test_company_errors(cockpit, fakes, jean):
    assert cockpit.put(f"/api/consultant/learners/{jean}/company", json={"siren": "123"}).status_code == 422
    r = cockpit.put(f"/api/consultant/learners/{jean}/company", json={"siren": "999999999"})
    assert r.status_code == 404
    assert cockpit.get(f"/api/consultant/learners/{jean}/company/search?q=a").status_code == 422
    fakes["company"].fail = company.CompanyError("Annuaire des entreprises injoignable (ConnectError).")
    r = cockpit.get(f"/api/consultant/learners/{jean}/company/search?q=dupont")
    assert r.status_code == 502 and "injoignable" in r.json()["detail"]


def test_nothing_to_search_with_a_webmail_address(cockpit, fakes):
    cid = add_customer("Léa", "lea@gmail.com")
    assert cockpit.get(f"/api/consultant/learners/{cid}/company/search").json() == {"query": "", "results": []}
    assert fakes["company"].queries == []


def test_signals():
    today = NOW.date()
    profile = company.normalize(DUPONT, today)
    assert profile["signaux"] == [
        {"niveau": "ok", "texte": "Active depuis 11 ans"},
        {"niveau": "attention", "texte": "Résultat net négatif en 2024"},
        {"niveau": "attention", "texte": "Chiffre d'affaires en baisse de 25 % en 2024"},
    ]
    closed = company.normalize(DUPONT | {"etat_administratif": "C", "date_fermeture": "2025-01-31", "finances": None, "tranche_effectif_salarie": "NN"}, today)
    assert closed["signaux"] == [
        {"niveau": "alerte", "texte": "Entreprise fermée (depuis le 2025-01-31)"},
        {"niveau": "info", "texte": "Aucun compte publié (comptes confidentiels ou petite structure)"},
        {"niveau": "info", "texte": "Pas de salarié déclaré"},
    ]
    young = company.normalize(DUPONT | {"date_creation": "2026-03-01", "finances": {"2025": {"ca": 100, "resultat_net": 1}, "2024": {"ca": 50, "resultat_net": 1}}}, today)
    assert young["signaux"] == [
        {"niveau": "attention", "texte": "Entreprise créée il y a moins d'un an"},
        {"niveau": "ok", "texte": "Chiffre d'affaires en hausse en 2025"},
    ]
    assert company.normalize({"siren": "1", "date_creation": "pas une date"}, today)["etat"] == "active"


def test_live_register(monkeypatch):
    import httpx

    calls = []

    def get(url, params, headers, timeout):
        calls.append((url, params))
        return httpx.Response(200, json={"results": [DUPONT]})

    monkeypatch.setattr(company.httpx, "get", get)
    assert company.LiveCompanyRegister().search("dupont") == [DUPONT]
    assert calls == [("https://recherche-entreprises.api.gouv.fr/search", {"q": "dupont", "page": 1, "per_page": 8})]
    for status, message in [(429, "trop de requêtes"), (500, "erreur 500")]:
        monkeypatch.setattr(company.httpx, "get", lambda *a, status=status, **kw: httpx.Response(status))
        with pytest.raises(company.CompanyError, match=message):
            company.LiveCompanyRegister().search("x")

    def down(*a, **kw):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(company.httpx, "get", down)
    with pytest.raises(company.CompanyError, match="injoignable"):
        company.LiveCompanyRegister().search("x")


# --- web research -------------------------------------------------------------------------------------------------

RESEARCH = {
    "synthese": "Cabinet de conseil lyonnais de 4 personnes.",
    "activite_reelle": ["Conseil en organisation pour PME"],
    "personne": {"role": "Gérant", "linkedin_url": "https://www.linkedin.com/in/jean-dupont"},
    "entreprise": {"site_web": "https://dupont-conseil.fr", "linkedin_url": ""},
    "signaux_positifs": ["Recrute un consultant"],
    "points_attention": [],
    "angles_ia": ["Comptes rendus de mission assistés"],
    "questions_a_poser": ["Combien de missions par an ?"],
    "sources": [{"titre": "Site officiel", "url": "https://dupont-conseil.fr"}],
    "confiance": "elevee",
}


def test_research_needs_codex(cockpit, jean):
    assert cockpit.post(f"/api/consultant/learners/{jean}/research").status_code == 409


def test_research_with_web_search_and_public_data_only(cockpit, fakes, codex_on, jean):
    cockpit.patch(f"/api/consultant/learners/{jean}", json={"notes": "secret du consultant"})
    fakes["codex"].answers = [json.dumps(RESEARCH)]
    assert cockpit.post(f"/api/consultant/learners/{jean}/research").status_code == 202
    [turn] = fakes["codex"].turns
    assert turn["web_search"] is True
    assert "dupont-conseil.fr" in turn["prompt"] and "jean@dupont-conseil.fr" not in turn["prompt"]
    assert "secret du consultant" not in turn["prompt"]
    assert "recherche entreprise" in turn["instructions"]
    research = cockpit.get(f"/api/consultant/learners/{jean}").json()["research"]
    assert research["status"] == "ready" and research["content"] == RESEARCH and research["error"] is None


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        (json.dumps(RESEARCH | {"sources": [{"titre": "x", "url": "javascript:alert(1)"}]}), "Recherche impossible : sortie Codex invalide"),
        (json.dumps(RESEARCH | {"personne": {"role": "", "linkedin_url": "ftp://x"}}), "Recherche impossible"),
        (CodexUnavailable("codex app-server injoignable"), "Recherche impossible : codex app-server injoignable"),
        (CodexNotConnected("x"), "Codex n'est pas connecté : connectez-le dans l'administration."),
    ],
)
def test_research_failures(cockpit, fakes, codex_on, jean, answer, error):
    fakes["codex"].answers = [answer]
    cockpit.post(f"/api/consultant/learners/{jean}/research")
    research = cockpit.get(f"/api/consultant/learners/{jean}").json()["research"]
    assert research["status"] == "failed" and research["error"].startswith(error)


def test_one_research_at_a_time(cockpit, codex_on, jean):
    with SessionLocal() as db:
        db.add(CustomerProfile(customer_id=jean, research_status="running", research_claimed_until=NOW + timedelta(minutes=1)))
        db.commit()
    assert cockpit.post(f"/api/consultant/learners/{jean}/research").status_code == 409
    with SessionLocal() as db:
        db.execute(update(CustomerProfile).values(research_claimed_until=NOW - timedelta(minutes=1)))
        db.commit()
    # The holder vanished (restart): a new research may start.
    assert cockpit.post(f"/api/consultant/learners/{jean}/research").status_code == 202


# --- action plans -------------------------------------------------------------------------------------------------


def plan_of(cockpit, cid):
    return cockpit.get(f"/api/consultant/learners/{cid}").json()["plan"]


def test_generate_then_chat(cockpit, fakes, codex_on, jean):
    call = add_booking(jean, paris(2026, 8, 25, 10), kind="discovery", minutes=30, message="Automatiser les devis")
    add_report(call)
    fakes["codex"].answers = [plan_answer(3, reponse="Choix : les devis d'abord.")]
    assert cockpit.post(f"/api/consultant/learners/{jean}/plan").json() == {"status": "pending"}
    [turn] = fakes["codex"].turns
    assert turn["web_search"] is False and "directeur de mission" in turn["instructions"]
    dossier = json.loads(turn["prompt"].split("<<<DOSSIER\n")[1].split("\nDOSSIER>>>")[0])
    assert dossier["accompagnement"]["seances_a_planifier"] == 3
    assert dossier["appel_decouverte"][0]["sujet_indique_par_le_prospect"] == "Automatiser les devis"
    assert dossier["appel_decouverte"][0]["compte_rendu"] == SYNTHESE
    assert len(dossier["seances_passees"]) == 2 and "plan_actuel" not in dossier
    assert "Rédige le plan d'accompagnement initial" in turn["prompt"]

    plan = plan_of(cockpit, jean)
    assert (plan["status"], plan["busy"], plan["version"], plan["error"]) == ("ready", False, 1, None)
    assert len(plan["content"]["seances"]) == 3
    assert plan["messages"] == [{"role": "assistant", "content": "Choix : les devis d'abord.", "created_at": "2026-10-05T08:00:00+02:00"}]

    fakes["codex"].answers = [plan_answer(3, reponse="Fait.", objectif="Réponses aux avis en 24 h")]
    r = cockpit.post(f"/api/consultant/learners/{jean}/plan/messages", json={"message": "Priorise les avis Google"})
    assert r.status_code == 202
    chat_turn = fakes["codex"].turns[-1]
    assert "message_consultant :\nPriorise les avis Google" in chat_turn["prompt"]
    dossier = json.loads(chat_turn["prompt"].split("<<<DOSSIER\n")[1].split("\nDOSSIER>>>")[0])
    assert dossier["plan_actuel"]["objectif"] == "Diviser par trois le temps des devis"
    assert dossier["conversation"] == [{"role": "assistant", "message": "Choix : les devis d'abord."}]
    plan = plan_of(cockpit, jean)
    assert plan["version"] == 2 and plan["content"]["objectif"] == "Réponses aux avis en 24 h"
    assert [m["role"] for m in plan["messages"]] == ["assistant", "consultant", "assistant"]

    assert cockpit.patch(f"/api/consultant/learners/{jean}/plan", json={"validated": True}).json() == {
        "validated_at": "2026-10-05T08:00:00+02:00"
    }
    # « Régénérer » : a full rewrite, asked as a message; validation is lifted by the new version.
    fakes["codex"].answers = [plan_answer(3)]
    cockpit.post(f"/api/consultant/learners/{jean}/plan")
    assert action_plans.REWRITE_REQUEST in fakes["codex"].turns[-1]["prompt"]
    plan = plan_of(cockpit, jean)
    assert plan["version"] == 3 and plan["validated_at"] is None


def test_the_plan_must_fit_the_sessions_left(cockpit, fakes, codex_on, jean):
    fakes["codex"].answers = [plan_answer(5), plan_answer(3)]
    cockpit.post(f"/api/consultant/learners/{jean}/plan")
    assert "exactement 3 séance(s), pas 5" in fakes["codex"].turns[1]["prompt"]
    assert plan_of(cockpit, jean)["status"] == "ready"


def test_a_plan_that_never_fits_fails(cockpit, fakes, codex_on, jean):
    fakes["codex"].answers = [plan_answer(3, minutes=45), "pas du JSON"]
    cockpit.post(f"/api/consultant/learners/{jean}/plan")
    plan = plan_of(cockpit, jean)
    assert plan["status"] == "failed" and plan["error"].startswith("Plan impossible à rédiger : sortie Codex invalide")
    assert "chaque séance dure 60 min" in fakes["codex"].turns[1]["prompt"]
    detail = cockpit.get("/api/consultant/learners").json()["learners"][0]
    assert {"niveau": "attention", "texte": "Le plan d'action n'a pas pu être rédigé"} in detail["alerts"]


def test_codex_not_connected(cockpit, fakes, codex_on, jean):
    fakes["codex"].connected = None
    cockpit.post(f"/api/consultant/learners/{jean}/plan")
    assert plan_of(cockpit, jean)["error"] == "Codex n'est pas connecté : connectez-le dans l'administration."


def test_without_hours_the_agent_proposes_a_programme(cockpit, fakes, codex_on):
    cid = add_customer("Paul Prospect", "paul@example.com")
    fakes["codex"].answers = [plan_answer(7), plan_answer(4)]
    cockpit.post(f"/api/consultant/learners/{cid}/plan")
    assert "6 séances au plus" in fakes["codex"].turns[1]["prompt"]
    assert len(plan_of(cockpit, cid)["content"]["seances"]) == 4


def test_chat_rules(cockpit, fakes, codex_on, jean):
    r = cockpit.post(f"/api/consultant/learners/{jean}/plan/messages", json={"message": "Bonjour"})
    assert r.status_code == 404 and r.json()["detail"] == "Générez d'abord le plan."
    assert cockpit.post(f"/api/consultant/learners/{jean}/plan/messages", json={"message": "  "}).status_code == 422
    assert cockpit.patch(f"/api/consultant/learners/{jean}/plan", json={"validated": True}).status_code == 404
    with SessionLocal() as db:
        db.add(ActionPlan(customer_id=jean, status="generating", claimed_until=NOW + timedelta(minutes=5)))
        db.commit()
    r = cockpit.post(f"/api/consultant/learners/{jean}/plan/messages", json={"message": "Et alors ?"})
    assert r.status_code == 409 and "en cours de rédaction" in r.json()["detail"]
    assert cockpit.post(f"/api/consultant/learners/{jean}/plan").status_code == 409


def test_request_validation_messages():
    with SessionLocal() as db:
        cid = add_customer("X", "x@example.com")
        customer = db.get(Customer, cid)
        with pytest.raises(action_plans.PlanError, match="trop long"):
            action_plans.request(db, customer, 1, NOW, "x" * 4001)


# --- the plan written by itself after a purchase -------------------------------------------------------------------


def test_purchase_after_a_discovery_call_queues_the_plan(client, fakes, token_for, codex_on):
    cid = add_customer("Jean Dupont", "jean@example.com")
    call = add_booking(cid, paris(2026, 10, 2, 10), kind="discovery", minutes=30)
    add_report(call, status="summarizing", summary=None)
    token_for(hours=2, email="jean@example.com", name="Jean Dupont")
    with SessionLocal() as db:
        plan = db.scalar(select(ActionPlan))
        assert (plan.status, plan.purchase_id) == ("pending", 1)

    # The call's summary is still being written: the plan waits for it (the purchase used the real clock).
    now = datetime.now(UTC)
    action_plans.process(fakes["codex"], now)
    assert fakes["codex"].turns == []
    with SessionLocal() as db:
        db.execute(update(SessionReport).values(status="drafted", summary=SYNTHESE))
        db.commit()
    fakes["codex"].answers = [plan_answer(2)]
    action_plans.process(fakes["codex"], now)
    assert "Cadrer le projet d'assistant" in fakes["codex"].turns[0]["prompt"]
    with SessionLocal() as db:
        assert db.scalar(select(ActionPlan.status)) == "ready"


def test_the_summary_is_not_awaited_forever(fakes, codex_on):
    cid = add_customer("Jean Dupont", "jean@example.com")
    call = add_booking(cid, paris(2026, 10, 2, 10), kind="discovery", minutes=30)
    add_report(call, status="waiting_transcript", summary=None)
    with SessionLocal() as db:
        db.add(ActionPlan(customer_id=cid, status="pending", created_at=NOW - timedelta(hours=9), updated_at=NOW))
        db.commit()
    fakes["codex"].answers = [plan_answer(1)]
    action_plans.process(fakes["codex"], NOW)
    assert len(fakes["codex"].turns) == 1


def test_no_plan_without_a_discovery_call(client, token_for):
    token_for(hours=2)
    with SessionLocal() as db:
        assert db.scalar(select(ActionPlan)) is None


def test_one_plan_per_customer_even_with_a_second_purchase(client, token_for):
    cid = add_customer("Jean Dupont", "jean@example.com")
    add_booking(cid, paris(2026, 10, 2, 10), kind="discovery", minutes=30)
    token_for("cs_a", hours=2, email="jean@example.com")
    token_for("cs_b", hours=3, email="jean@example.com")
    with SessionLocal() as db:
        assert len(db.scalars(select(ActionPlan)).all()) == 1


def test_manual_purchase_also_queues_the_plan(cockpit):
    cid = add_customer("Jean Dupont", "jean@example.com")
    add_booking(cid, paris(2026, 10, 2, 10), kind="discovery", minutes=30)
    r = cockpit.post("/api/consultant/clients", json={"name": "Jean Dupont", "email": "jean@example.com", "acquisition_source": "site", "hours": 2, "send_link": False})
    assert r.status_code == 201
    with SessionLocal() as db:
        assert db.scalar(select(ActionPlan.status)) == "pending"


def test_a_failing_plan_never_blocks_the_payment(client, token_for, monkeypatch):
    def broken(*a, **kw):
        raise RuntimeError("bug")

    monkeypatch.setattr(action_plans, "on_purchase", broken)
    assert token_for(hours=2)


def test_a_vanished_holder_is_taken_over(fakes, codex_on):
    cid = add_customer("Jean Dupont", "jean@example.com")
    with SessionLocal() as db:
        db.add(ActionPlan(customer_id=cid, status="generating", claimed_until=NOW - timedelta(seconds=1), created_at=NOW, updated_at=NOW))
        db.commit()
    fakes["codex"].answers = [plan_answer(1)]
    action_plans.process(fakes["codex"], NOW)
    with SessionLocal() as db:
        assert db.scalar(select(ActionPlan.status)) == "ready"


def test_run_forever_survives_errors(monkeypatch):
    import asyncio

    calls = []

    def boom(codex, now):
        calls.append(now)
        raise RuntimeError("x")

    monkeypatch.setattr(action_plans, "process", boom)

    async def main():
        task = asyncio.create_task(action_plans.run_forever(lambda: None, 0.01, lambda: NOW))
        # Wait for the second cycle instead of a fixed delay: a slow CI runner can take >50 ms per cycle.
        for _ in range(500):
            if len(calls) >= 2:
                break
            await asyncio.sleep(0.01)
        task.cancel()

    asyncio.run(main())
    assert len(calls) >= 2


# --- discovery topic and default consultant -------------------------------------------------------------------------


def test_discovery_keeps_the_topic_and_assigns_the_consultant(client):
    from app.routers import public

    public.discovery_limiter.reset()
    r = client.post(
        "/api/discovery",
        json={"name": "Paul", "email": "paul@example.com", "start": paris(2026, 10, 6, 14).isoformat(), "message": "Devis"},
    )
    assert r.status_code == 201, r.text
    with SessionLocal() as db:
        booking = db.scalar(select(Booking))
        assert booking.message == "Devis" and booking.customer.consultant_id == 1


def test_activity_without_any_event():
    customer = Customer(name="x", email="x@example.com", created_at=datetime(2026, 9, 1, tzinfo=UTC))
    customer.purchases = []
    act = learners.activity(customer, [], NOW)
    assert (act.status, act.idle_days, act.pace_days) == ("prospect", 34, None)
