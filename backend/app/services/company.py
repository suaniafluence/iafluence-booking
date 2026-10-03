"""Company profile of a customer, from the official register (recherche-entreprises.api.gouv.fr: free, no key).

The consultant searches by name or SIREN, picks the company, and its public data is kept with the customer:
legal status (active or closed), age, headcount, activity, managers, published accounts. `signaux` turns them into
plain indicators — not a credit score: a missing balance sheet is common for small companies.
"""

import re
from datetime import date, datetime
from typing import Protocol

import httpx
from sqlalchemy.orm import Session

from app.config import get_config
from app.models import Customer, CustomerProfile

TIMEOUT_S = 10
MAX_RESULTS = 8
SIREN = re.compile(r"^\d{9}$")
# Webmail domains say nothing about the employer.
GENERIC_DOMAINS = {
    "gmail.com", "googlemail.com", "hotmail.com", "hotmail.fr", "outlook.com", "outlook.fr", "live.com", "live.fr",
    "yahoo.com", "yahoo.fr", "icloud.com", "me.com", "free.fr", "orange.fr", "wanadoo.fr", "sfr.fr", "laposte.net",
    "gmx.fr", "gmx.com", "proton.me", "protonmail.com", "aol.com", "bbox.fr", "neuf.fr", "example.com",
}
HEADCOUNT = {
    "NN": "Non employeuse",
    "00": "0 salarié",
    "01": "1 ou 2 salariés",
    "02": "3 à 5 salariés",
    "03": "6 à 9 salariés",
    "11": "10 à 19 salariés",
    "12": "20 à 49 salariés",
    "21": "50 à 99 salariés",
    "22": "100 à 199 salariés",
    "31": "200 à 249 salariés",
    "32": "250 à 499 salariés",
    "41": "500 à 999 salariés",
    "42": "1 000 à 1 999 salariés",
    "51": "2 000 à 4 999 salariés",
    "52": "5 000 à 9 999 salariés",
    "53": "10 000 salariés et plus",
}
LABELS = {
    "est_entrepreneur_individuel": "Entrepreneur individuel",
    "est_ess": "Économie sociale et solidaire",
    "est_organisme_formation": "Organisme de formation",
    "est_qualiopi": "Certifié Qualiopi",
    "est_rge": "RGE",
    "est_societe_mission": "Société à mission",
    "est_service_public": "Service public",
    "est_association": "Association",
}


class CompanyError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class CompanyRegister(Protocol):
    def search(self, query: str) -> list[dict]:
        """Raw results of the register for a name or a SIREN."""


class LiveCompanyRegister:
    def search(self, query: str) -> list[dict]:
        try:
            r = httpx.get(
                f"{get_config().company_api_url.rstrip('/')}/search",
                params={"q": query, "page": 1, "per_page": MAX_RESULTS},
                headers={"Accept": "application/json"},
                timeout=TIMEOUT_S,
            )
        except httpx.HTTPError as e:
            raise CompanyError(f"Annuaire des entreprises injoignable ({type(e).__name__}).") from e
        if r.status_code == 429:
            raise CompanyError("Annuaire des entreprises : trop de requêtes, réessayez dans une minute.", 429)
        if r.status_code != 200:
            raise CompanyError(f"Annuaire des entreprises : erreur {r.status_code}.")
        return list(r.json().get("results") or [])


def email_domain(email: str) -> str | None:
    domain = email.rsplit("@", 1)[-1].lower()
    return None if domain in GENERIC_DOMAINS else domain


def suggested_query(customer: Customer) -> str:
    """What to search first: the company name typed by the consultant, else the email domain without its TLD."""
    if customer.company_name:
        return customer.company_name
    domain = email_domain(customer.email)
    return domain.rsplit(".", 1)[0].replace("-", " ") if domain else ""


def _person(d: dict) -> dict:
    if d.get("type_dirigeant") == "personne morale":
        name = d.get("denomination") or ""
    else:
        name = " ".join(part for part in (d.get("prenoms"), d.get("nom")) if part)
    return {"nom": name.strip(), "qualite": d.get("qualite") or ""}


def _finances(raw: dict | None) -> list[dict]:
    rows = [
        {"annee": int(year), "ca": values.get("ca"), "resultat_net": values.get("resultat_net")}
        for year, values in (raw or {}).items()
        if str(year).isdigit() and isinstance(values, dict)
    ]
    return sorted(rows, key=lambda row: row["annee"], reverse=True)


def _years_since(value: str | None, today: date) -> float | None:
    try:
        created = date.fromisoformat(value) if value else None
    except ValueError:
        return None
    return None if created is None else (today - created).days / 365.25


def signals(profile: dict, today: date) -> list[dict]:
    """Plain indicators for the consultant: level ok | info | attention | alerte."""
    out = []
    if profile["etat"] == "cessee":
        out.append({"niveau": "alerte", "texte": f"Entreprise fermée (depuis le {profile.get('date_fermeture') or '?'})"})
    age = _years_since(profile.get("date_creation"), today)
    if age is not None and profile["etat"] == "active":
        if age < 1:
            out.append({"niveau": "attention", "texte": "Entreprise créée il y a moins d'un an"})
        elif age >= 3:
            out.append({"niveau": "ok", "texte": f"Active depuis {int(age)} ans"})
    finances = profile["finances"]
    if not finances:
        out.append({"niveau": "info", "texte": "Aucun compte publié (comptes confidentiels ou petite structure)"})
    else:
        last = finances[0]
        if last["resultat_net"] is not None and last["resultat_net"] < 0:
            out.append({"niveau": "attention", "texte": f"Résultat net négatif en {last['annee']}"})
        if len(finances) > 1 and last["ca"] and finances[1]["ca"] and last["ca"] < 0.8 * finances[1]["ca"]:
            drop = round(100 * (1 - last["ca"] / finances[1]["ca"]))
            out.append({"niveau": "attention", "texte": f"Chiffre d'affaires en baisse de {drop} % en {last['annee']}"})
        if last["ca"] and len(finances) > 1 and finances[1]["ca"] and last["ca"] > 1.1 * finances[1]["ca"]:
            out.append({"niveau": "ok", "texte": f"Chiffre d'affaires en hausse en {last['annee']}"})
    if profile.get("effectif_code") in ("NN", "00"):
        out.append({"niveau": "info", "texte": "Pas de salarié déclaré"})
    return out


def normalize(raw: dict, today: date) -> dict:
    siege = raw.get("siege") or {}
    complements = raw.get("complements") or {}
    profile = {
        "siren": raw.get("siren"),
        "nom": raw.get("nom_complet") or raw.get("nom_raison_sociale") or "",
        "sigle": raw.get("sigle"),
        "etat": "active" if (raw.get("etat_administratif") or "A") == "A" else "cessee",
        "date_creation": raw.get("date_creation"),
        "date_fermeture": raw.get("date_fermeture"),
        "categorie": raw.get("categorie_entreprise"),
        "nature_juridique": raw.get("nature_juridique"),
        "activite_code": raw.get("activite_principale") or siege.get("activite_principale"),
        "effectif_code": raw.get("tranche_effectif_salarie"),
        "effectif": HEADCOUNT.get(raw.get("tranche_effectif_salarie") or "", None),
        "effectif_annee": raw.get("annee_tranche_effectif_salarie"),
        "adresse": siege.get("adresse"),
        "etablissements": raw.get("nombre_etablissements_ouverts", raw.get("nombre_etablissements")),
        "dirigeants": [_person(d) for d in (raw.get("dirigeants") or [])[:8]],
        "finances": _finances(raw.get("finances")),
        "labels": [label for key, label in LABELS.items() if complements.get(key)],
    }
    profile["signaux"] = signals(profile, today)
    return profile


def search(register: CompanyRegister, query: str, today: date) -> list[dict]:
    query = query.strip()
    if len(query) < 2:
        raise CompanyError("Tapez au moins deux caractères.", 422)
    return [normalize(raw, today) for raw in register.search(query)[:MAX_RESULTS]]


def attach(db: Session, register: CompanyRegister, customer: Customer, siren: str, now: datetime) -> dict:
    """Fetch that company again (fresh data) and keep it with the customer."""
    if not SIREN.match(siren):
        raise CompanyError("Un SIREN compte 9 chiffres.", 422)
    match = next((raw for raw in register.search(siren) if raw.get("siren") == siren), None)
    if match is None:
        raise CompanyError("Aucune entreprise avec ce SIREN dans l'annuaire.", 404)
    company = normalize(match, now.date())
    profile = db.get(CustomerProfile, customer.id) or CustomerProfile(customer_id=customer.id)
    profile.company, profile.company_fetched_at = company, now
    db.add(profile)
    customer.siren, customer.company_name = siren, company["nom"] or customer.company_name
    db.commit()
    return company


def detach(db: Session, customer: Customer) -> None:
    profile = db.get(CustomerProfile, customer.id)
    if profile is not None:
        profile.company, profile.company_fetched_at = None, None
    customer.siren = None
    db.commit()
