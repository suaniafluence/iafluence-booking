# IAfluence Booking

[![CI](https://github.com/suaniafluence/iafluence-booking/actions/workflows/ci.yml/badge.svg?event=pull_request)](https://github.com/suaniafluence/iafluence-booking/actions/workflows/ci.yml)
[![Licence](https://img.shields.io/github/license/suaniafluence/iafluence-booking)](LICENSE)
[![Dernier commit](https://img.shields.io/github/last-commit/suaniafluence/iafluence-booking)](https://github.com/suaniafluence/iafluence-booking/commits/main)
[![Déploiement](https://img.shields.io/badge/d%C3%A9ploiement-manuel_(workflow__dispatch)-blue?logo=githubactions&logoColor=white)](https://github.com/suaniafluence/iafluence-booking/actions/workflows/deploy-prod.yml)

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![uv](https://img.shields.io/badge/uv-DE5FE9?logo=uv&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-5.8-3178C6?logo=typescript&logoColor=white)
![Vite](https://img.shields.io/badge/Vite-7-646CFF?logo=vite&logoColor=white)
![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-4-06B6D4?logo=tailwindcss&logoColor=white)
![Docker Compose](https://img.shields.io/badge/Docker_Compose-2496ED?logo=docker&logoColor=white)
![Caddy](https://img.shields.io/badge/Caddy-derri%C3%A8re_nginx-1F88C0?logo=caddy&logoColor=white)
![Stripe](https://img.shields.io/badge/Stripe-635BFF?logo=stripe&logoColor=white)
![Google Calendar](https://img.shields.io/badge/Google_Calendar-4285F4?logo=googlecalendar&logoColor=white)

![pytest](https://img.shields.io/badge/pytest-0A9EDC?logo=pytest&logoColor=white)
![Vitest](https://img.shields.io/badge/Vitest-6E9F18?logo=vitest&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-E2E-2EAD33)
![Couverture](https://img.shields.io/badge/couverture-%E2%89%A5_80_%25-brightgreen)
![Mutation](https://img.shields.io/badge/mutation_(Stryker)-%E2%89%A5_75_%25-brightgreen)

Réservation des **sessions de 1 h** après l’achat d’une prestation « Conseil IA » sur Stripe (ou d’un client ajouté à la main) : la première tout de suite, les suivantes via un lien envoyé après chaque session.

> **Conformité :** avant toute utilisation avec des clients réels, consulter l’[audit éthique, RGPD et international](docs/conformite-ethique-rgpd-international.md). L’enregistrement/transcription et le traitement par IA y sont classés **no-go** tant que les prérequis P0 (information, consentement réellement facultatif, contrats, transferts, AIPD, rétention et droits) ne sont pas clos.

Paiement Stripe → vérification → lien de réservation sécurisé → créneaux libres agrégés depuis plusieurs Google Calendars (free/busy uniquement) → création de l’événement Google Calendar + Meet + invitation → emails client et admin → suivi des heures achetées / réservées / restantes → après chaque séance, **compte rendu rédigé par votre agent Codex à partir de la transcription Fireflies**, préparé en brouillon Gmail.

```
backend/    FastAPI · SQLAlchemy · Alembic · PostgreSQL
frontend/   React · Vite · TypeScript · Tailwind
deploy/     Docker Compose · Caddy (derrière le nginx du serveur) · codex app-server · .env.example · release.sh (déploiement / rollback)
.github/    CI (tests) · Deploy Production (manuel)
```

## Fonctionnement

| Étape | Détail |
|---|---|
| Paiement | 4 Payment Links Stripe. Chaque produit porte la métadonnée `hours` (1, 2, 3, 5). |
| Redirection | Après paiement, Stripe renvoie vers `/reservation?session_id={CHECKOUT_SESSION_ID}`. Le backend vérifie la session auprès de Stripe, crée l’achat et un **token aléatoire de 256 bits**, puis le navigateur est redirigé vers `/{fr|en|es}/reservation/{token}`. Le lien est aussi envoyé par email. |
| Langues | Français, anglais, espagnol. La langue vient du site : le Payment Link est ouvert avec `?locale=en&client_reference_id=en` (Stripe s’affiche alors en anglais et la langue est lue dans la session). Elle s’applique à la page de réservation (sélecteur FR / EN / ES, qui enregistre le choix au moment de réserver), aux emails client, à l’événement Google Calendar et au compte rendu Codex. L’admin reste en français. Les anciens liens `/reservation/{token}` redirigent vers la langue de l’achat. |
| Fuseaux horaires | Les créneaux sont affichés à l’heure du visiteur (Sydney, Santiago…, regroupés par jour local), avec l’heure de Paris en dessous dès qu’elle diffère ; même chose dans l’email de confirmation. Le fuseau du navigateur est enregistré avec la réservation. |
| Webhook | `POST /webhooks/stripe` (`checkout.session.completed`, `checkout.session.async_payment_succeeded`, `charge.refunded`). Traitement idempotent : webhook et redirection peuvent arriver dans n’importe quel ordre. Un remboursement total révoque le lien et alerte l’admin. |
| Disponibilités | `freebusy.query` sur tous les calendriers activés + le calendrier des rendez-vous. Aucun titre, participant, lieu ou lien n’est jamais lu ni exposé : l’API ne renvoie que `{start, end}`. Si un calendrier est en erreur, rien n’est proposé (fail closed). |
| Calendrier imprimable | Admin, « Imprimer mon calendrier » : PDF A4 paysage, une page par semaine, sur la période choisie (un an au plus), avec **« Mis à jour le … »** en gras en haut. Tous les calendriers activés + le calendrier des rendez-vous ; chaque rendez-vous est imprimé « Occupé », sans aucun détail. Un rendez-vous dont le titre se termine par **« ? »** (`?`, `??`, `???`…) est en **pointillé** : légende « Pas encore fixé ou pas sûr » ; un rendez-vous fixé au même moment l’emporte. Impression très claire (gris léger, traits fins) pour économiser l’encre. Seule exception à la règle free/busy : `events.list` lit début, fin, statut, disponibilité, réponse de l’admin et titre — le titre uniquement pour repérer le « ? », jamais stocké, journalisé ni renvoyé. Un agenda partagé en free/busy seulement est imprimé à partir de ses plages occupées (jamais en pointillé), demandées mois par mois. Événements « Disponible », annulés ou refusés : ignorés, comme dans free/busy. |
| Règles | Horaires hebdomadaires (plusieurs plages par jour possibles), durée 60 min, tampons 15 min avant/après, préavis 24 h, horizon 30 jours, fuseau `Europe/Paris` (changements d’heure gérés). |
| Réservation | Verrou transactionnel PostgreSQL + nouvelle requête free/busy (sans cache) juste avant la création de l’événement. En base, un index unique (une session par achat) et une contrainte d’exclusion (aucun chevauchement) empêchent toute double réservation. |
| Google Calendar | Événement « Conseil IA - Nom » dans le calendrier dédié, avec le client en invité (`sendUpdates=all` : Google envoie l’invitation à n’importe quelle adresse) et un lien Meet optionnel. |
| Séances suivantes | Chaque minute, l’API clôt les sessions terminées (`confirmed` → `completed`), ce qui libère l’achat pour la réservation suivante. S’il reste des heures, l’email « Réservez votre prochaine session » (même lien) est **mis en brouillon dans Gmail** — avec le compte rendu de la séance si Fireflies et Codex sont configurés (voir « Comptes rendus ») — ou **envoyé directement** si « Envoi auto » est coché pour ce client dans l’admin. Après la dernière heure, même règle pour l’email « Merci pour votre accompagnement », qui renvoie vers `SHOP_URL` (https://iafluence.fr par défaut) pour racheter des heures. Rien pour un achat remboursé ; une session terminée depuis plus de 24 h (API arrêtée, premier déploiement) est clôturée sans email. |
| Comptes rendus | Si Fireflies et Codex sont configurés, la fin de séance crée un **compte rendu** au lieu de préparer l’email tout de suite : `waiting_transcript → summarizing → ready → drafted`, ou `failed`. Toutes les 5 min (`FIREFLIES_POLL_SECONDS`), **une seule requête** Fireflies liste les enregistrements de toutes les séances en attente ; la séance est reconnue par son heure de début (± 15 min) et l’email du client parmi les participants, ou son lien Meet. La transcription est lue une fois, en mémoire, et envoyée à **votre agent Codex** (`codex app-server`, forfait ChatGPT, aucune clé OpenAI) avec le contexte (client, prestation, n° de séance, heures restantes). Ses consignes sont les fichiers Markdown de `backend/app/codex_agent/` (à réécrire librement). Il renvoie un JSON strict, validé par un schéma pydantic : la synthèse (objectifs, points abordés, décisions, actions du client, prochaines étapes) et une **infographie SVG**, vérifiée (ni script, ni lien, ni ressource externe) puis convertie en PNG 1200 px par le serveur. Sortie invalide → une nouvelle tentative, puis `failed` + alerte admin. Pas de transcription au bout de 6 h (`FIREFLIES_MAX_WAIT_HOURS`) → email V1 sans résumé + alerte admin. |
| Email avec compte rendu | Multipart : texte + HTML, infographie intégrée (`cid:`), synthèse, puis le lien de la séance suivante (ou le remerciement et `SHOP_URL` après la dernière heure). **Toujours en brouillon** quand il contient un résumé généré, même pour un client en « Envoi auto », sauf si « Envoyer aussi les résumés sans relecture » est coché dans l’admin. Un seul compte rendu et un seul brouillon par séance, même avec plusieurs processus (`FOR UPDATE SKIP LOCKED`, réservation du compte rendu le temps du tour Codex, emails après le commit). |
| Données personnelles | La transcription n’est **jamais stockée ni journalisée** : seuls l’identifiant Fireflies, la synthèse et le PNG sont en base, effacés après `REPORT_RETENTION_DAYS` (90 jours par défaut). Côté Codex, les conversations sont éphémères et l’historique désactivé. |
| Emails | Envoyés via l’API Gmail : lien de réservation, confirmation client, lien de la session suivante ou remerciement après la dernière heure (brouillon ou envoi, avec ou sans compte rendu), notification « NOUVELLE RÉSERVATION », alertes remboursement et compte rendu. |
| Admin | `/admin` (mot de passe unique) : indicateurs du mois, heures vendues/réalisées/restantes, prochains rendez-vous, liste des clients avec la case « Envoi auto » et le lien de réservation à copier, **ajout d’un client à la main** (payé hors du site : nom, email, heures, montant, envoi ou non du lien), **annulation d’une séance à venir** (déplacement : l’événement Google est supprimé, l’heure recréditée et le lien renvoyé au client si coché) et **modification des heures achetées** (remboursement partiel, heures supplémentaires ; jamais sous les heures déjà réservées). **Comptes rendus de séance** : statut de chaque séance terminée, aperçu de la synthèse et de l’infographie, boutons « Relancer » (Fireflies ou résumé) et « Créer le brouillon sans résumé », option « Envoyer aussi les résumés sans relecture ». **Connexion Codex** : voir « Mise en production », étape 4. **Imprimer mon calendrier** : voir « Calendrier imprimable ». |
| Annulations | Règle affichée au client (page de réservation et email de confirmation) : toute séance réservée est due ; déplacement gratuit jusqu’à 24 h avant en répondant à l’email de confirmation ; au-delà, ou en cas d’absence, l’heure est consommée. Un remboursement ne se fait que dans Stripe : total → lien révoqué et alerte admin ; partiel → accès conservé, ajuster les heures dans l’admin. |

## Schémas

### Qui échange quoi

![Qui échange quoi : client, admin, frontend, backend, Stripe, Google Agenda, Gmail, PostgreSQL](docs/architecture.svg)

Hors schéma : après paiement, Stripe renvoie le client vers `/reservation?session_id=…` ; Google Agenda lui envoie l’invitation, Gmail les emails (et à l’admin les alertes). Des agendas Google, seules les plages occupées sont lues : ni titre, ni participant, ni lien (sauf le calendrier imprimable de l’admin, qui lit les titres pour y repérer un « ? » final, sans jamais les afficher).

### Parcours d’un achat et choix

![Parcours d’un achat, de la vérification du paiement à l’email de la séance suivante](docs/parcours.svg)

Au moment de réserver, le backend refuse aussi : une deuxième séance à venir sur le même achat, un achat sans heures restantes, et tout créneau si un agenda Google est en erreur (rien n’est proposé).

## Démarrage local (démo sans Google ni Stripe)

Prérequis : Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 22, PostgreSQL 16 (ou Docker).

```bash
docker run -d --name iafluence-db -e POSTGRES_PASSWORD=dev -p 5432:5432 postgres:16-alpine
```

Créer `backend/.env` :

```dotenv
DATABASE_URL=postgresql+psycopg://postgres:dev@localhost:5432/postgres
PUBLIC_BASE_URL=http://localhost:5173
FAKE_INTEGRATIONS=true
ADMIN_PASSWORD_HASH='...'   # voir « Mot de passe admin » ci-dessous
SESSION_SECRET=dev
COOKIE_SECURE=false
```

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run python -m scripts.seed_settings --admin-email vous@example.com --booking-calendar demo
uv run uvicorn app.main:app --port 8000
```

```bash
cd frontend
npm install
npm run dev
```

Avec `FAKE_INTEGRATIONS=true`, toute session `cs_demo_<heures>h_<nom>` est un paiement valide, par exemple
http://localhost:5173/reservation?session_id=cs_demo_5h_jean. Les calendriers contiennent quelques créneaux occupés fictifs et les emails s’affichent dans les logs (et sont enregistrés en `.eml` si `DEMO_OUTBOX_DIR` est défini). Fireflies a un enregistrement de chaque séance, « Connecter Codex » est validé tout seul après 4 s et l’agent de démo écrit un compte rendu à partir du contexte de la séance.

> Sur un poste où un antivirus ou un proxy intercepte le TLS, ajoutez `--system-certs` aux commandes `uv` si l’installation échoue avec `invalid peer certificate`.

## Tests

| Niveau | Outil | Commande | Seuil |
|---|---|---|---|
| Unitaires + intégration backend | pytest + PostgreSQL réel | `uv run pytest --cov` | couverture ≥ 80 % (bloquant) |
| Unitaires frontend | Vitest + Testing Library | `npm run test:coverage` | couverture ≥ 80 % (bloquant) |
| Mutation backend | mutmut (dans Docker) | `./mutation.sh` | rapport |
| Mutation frontend | Stryker | `npm run test:mutation` | score ≥ 75 % (bloquant) |
| End-to-end | Playwright | `npm run test:e2e` | — |

Une base PostgreSQL de test (port 5433 pour ne pas gêner une base de dev) :

```bash
docker run -d --name iafluence-test-db -e POSTGRES_PASSWORD=dev -p 127.0.0.1:5433:5432 postgres:16-alpine
docker exec iafluence-test-db psql -U postgres -c "CREATE DATABASE iafluence_test" -c "CREATE DATABASE iafluence_e2e" -c "CREATE DATABASE iafluence_mutation"
```

> Sous Windows, utilisez `127.0.0.1` et non `localhost` dans les URL de base : la résolution IPv6 de `localhost` ajoute ~2 s par connexion (9 min au lieu de 10 s pour la suite).

**Backend** — sans `TEST_DATABASE_URL`, seuls les tests unitaires s’exécutent. Les tests d’intégration utilisent un vrai PostgreSQL (contrainte d’exclusion, verrous) et des faux Google et Stripe : réservations concurrentes, courses résolues sous verrou, compensation Google Calendar, retard de propagation free/busy, idempotence des webhooks, remboursements, contenu exact des emails, sessions admin falsifiées ou expirées, scripts CLI.

```bash
cd backend
TEST_DATABASE_URL=postgresql+psycopg://postgres:dev@127.0.0.1:5433/iafluence_test uv run pytest --cov
```

**Frontend** — les tests s’exécutent dans le fuseau `America/Los_Angeles` pour garantir que les horaires restent affichés à l’heure de Paris quel que soit le fuseau du visiteur.

```bash
cd frontend
npm run test:coverage
```

**Tests de mutation** — ils modifient le code (un `<` devient `<=`, une condition devient `True`…) et vérifient qu’au moins un test échoue.

```bash
cd backend && ./mutation.sh                 # tout le backend, ~40 min ; ou ./mutation.sh "app.services.availability*"
cd frontend && npm run test:mutation        # ~3 min
```

`mutmut` ne fonctionne pas sous Windows (il utilise `fork()`) : `mutation.sh` le lance dans un conteneur Linux, sur une copie du code, avec la base `iafluence_mutation` (variable `MUTATION_DATABASE_URL` pour en changer). Rapports : `backend/mutation-report/` (liste et diff des mutants survivants) et `frontend/reports/mutation/index.html`. Les lignes de log, les modèles déclaratifs et les faux de démo ne sont pas mutés.

**End-to-end** — Playwright démarre le vrai backend (mode `FAKE_INTEGRATIONS`, base `iafluence_e2e` remise à zéro à chaque exécution, tâches de fin de séance chaque seconde) et le build de production du frontend, puis pilote un navigateur : du retour Stripe au rendez-vous confirmé (bureau et mobile), deux clients sur le même créneau, liens invalides, administration, connexion Codex par code appareil, et **séance terminée → brouillon Gmail avec synthèse et infographie** (le brouillon `.eml` est relu : texte + HTML + PNG `cid:`).

```bash
cd frontend
npx playwright install chromium   # une fois
npm run test:e2e                  # E2E_DATABASE_URL, UV (chemin de uv) et PW_CHANNEL=msedge sont optionnels
```

## Mise en production

### 1. Google (compte Gmail personnel)

1. Dans [Google Cloud Console](https://console.cloud.google.com/) : créer un projet, puis activer **Google Calendar API** et **Gmail API**.
2. **Écran de consentement OAuth** : type *Externe*. Ajouter votre adresse, puis **passer l’application en production** (« Publish app »).
   ⚠️ En mode *Testing*, le refresh token expire au bout de 7 jours. L’application n’a pas besoin d’être vérifiée pour votre propre compte : vous verrez un avertissement une seule fois, au moment du consentement.
3. **Identifiants** → *ID client OAuth* → type **Application de bureau** → télécharger le JSON.
4. Sur votre poste :
   ```bash
   cd backend
   uv run python -m scripts.google_oauth_init chemin/vers/client_secret.json
   ```
   Copier les trois valeurs affichées dans `deploy/.env`.
   ⚠️ Les brouillons Gmail demandent le droit `gmail.compose`. Un refresh token obtenu avant son ajout continue de fonctionner pour l’agenda et l’envoi d’emails, mais pas pour les brouillons : relancer cette commande et remplacer `GOOGLE_REFRESH_TOKEN`.
5. Créer dans Google Calendar un agenda **« IAfluence - Conseil clients »**. Son ID se trouve dans *Paramètres de l’agenda → Intégrer l’agenda*.
6. Les agendas d’autres comptes (Formation, ESC Clermont, Personnel…) doivent être **partagés avec votre compte Gmail**, au minimum avec le droit « Voir uniquement les informations de disponibilité ». C’est suffisant pour free/busy et cohérent avec l’exigence de confidentialité.
   Les agendas Outlook/Exchange ne sont pas pris en charge dans ce MVP.

### 2. Stripe

1. Pour chacun des 4 produits (Conseil IA 1 h, 2 h, 3 h, 5 h), ajouter la **métadonnée produit** `hours` = `1` / `2` / `3` / `5`.
2. Pour chaque Payment Link : *Après le paiement* → *Rediriger vers votre site* →
   `https://booking.iafluence.fr/reservation?session_id={CHECKOUT_SESSION_ID}`
   Le nom et l’email sont collectés par Stripe (`customer_details`).
3. *Developers → Webhooks* : ajouter l’endpoint `https://booking.iafluence.fr/webhooks/stripe` avec les événements `checkout.session.completed`, `checkout.session.async_payment_succeeded` et `charge.refunded`. Copier le *signing secret*.
4. Créer une **clé restreinte** avec *Checkout Sessions : lecture* et *Products : lecture*.

Tester d’abord en mode test : carte `4242 4242 4242 4242`, puis `stripe listen --forward-to localhost:8000/webhooks/stripe` en local.

### 3. Serveur (VPS) et déploiement continu

DNS : un enregistrement `A booking.iafluence.fr` qui pointe vers l’IP du VPS. Le nginx du serveur garde les ports 80/443 et le TLS (certbot) ; il transmet `booking.iafluence.fr` au Caddy de la pile, qui n’écoute que sur `127.0.0.1:3004` (`WEB_PORT` dans `shared/.env`) :

```nginx
server {
    server_name booking.iafluence.fr;
    client_max_body_size 5m;
    location / {
        proxy_pass http://127.0.0.1:3004;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    listen 80;
}
```

Puis `sudo certbot --nginx -d booking.iafluence.fr` ajoute le HTTPS.

Le serveur ne reçoit ni le dépôt, ni Node, ni les outils de test. GitHub Actions exécute les tests, construit le frontend et envoie une archive minimale (sources backend sans tests, `frontend/dist`, fichiers de `deploy/`). Sur le serveur, Docker Compose construit l’image API avec les seules dépendances runtime, puis sert le frontend via l’image Caddy officielle.

```
/var/www/iafluence-booking/
  releases/<release-id>/     une archive par déploiement (3 conservées)
  current -> releases/<id>   release active
  shared/.env                secrets de production (jamais dans le dépôt ni dans l’archive)
```

**Déployer :** GitHub → *Actions* → *Deploy Production* → *Run workflow* (branche `main`). Les jobs `test` → `build` → `deploy` s’enchaînent seulement si le précédent réussit. `deploy/release.sh` construit l’image pendant que l’ancienne version tourne, bascule `current`, redémarre, puis vérifie `/api/health` et la page d’accueil via Caddy (`127.0.0.1:3004`). En cas d’échec, il revient automatiquement à la release précédente. Les tests tournent aussi sur chaque pull request vers `main` (`.github/workflows/ci.yml`), mais pas après la fusion.

**Secrets GitHub** (*Settings → Secrets and variables → Actions*) : `PROD_HOST`, `PROD_USER`, `PROD_SSH_KEY` (clé privée dédiée), `PROD_SSH_KNOWN_HOSTS` (sortie de `ssh-keyscan -p PORT HOST`), `PROD_PORT` (facultatif, 22 par défaut). Variables facultatives : `PROD_URL` (`https://booking.iafluence.fr`, vérification publique après déploiement) et `PROD_APP_DIR` (`/var/www/iafluence-booking` par défaut).

**Préparation du serveur (une fois) :** Docker Engine et son plugin compose, un utilisateur membre du groupe `docker` dont la clé publique est autorisée, `mkdir -p /var/www/iafluence-booking/{releases,shared}`, puis `shared/.env` rempli à partir de `deploy/.env.example` (`chmod 600`).

**Revenir en arrière :**

```bash
/var/www/iafluence-booking/current/deploy/release.sh rollback            # release précédente
/var/www/iafluence-booking/current/deploy/release.sh rollback <id>       # release précise (voir releases/)
```

Les migrations Alembic s’exécutent au démarrage de l’API et ne sont pas annulées par un rollback.

Initialisation, une seule fois (après le premier déploiement) :

```bash
R=/var/www/iafluence-booking/current/deploy/release.sh
$R compose exec api python -m scripts.seed_settings \
  --admin-email contact@iafluence.fr \
  --booking-calendar "xxxx@group.calendar.google.com"
$R compose exec api python -m scripts.list_calendars                       # lister les agendas visibles
$R compose exec api python -m scripts.list_calendars --add "ID" "Formation"  # répéter pour chaque agenda
```

`release.sh compose …` exécute `docker compose` sur la release active, avec le bon nom de projet. Pour lancer la pile à la main depuis un clone, construisez d’abord le frontend (`cd frontend && npm ci && npm run build`), puis `cd deploy && docker compose up -d --build`.

Le calendrier des rendez-vous est toujours pris en compte dans les disponibilités. Inutile de l’ajouter comme source.

**Mot de passe admin :**

```bash
cd backend && uv run python -c "from argon2 import PasswordHasher; print(PasswordHasher().hash('votre-mot-de-passe'))"
```

Placer la valeur entre apostrophes dans `ADMIN_PASSWORD_HASH='…'`.

**Base de données :** en production, Neon (`DATABASE_URL=postgresql+psycopg://…` dans `shared/.env`, sans `COMPOSE_PROFILES`) ; Neon assure les sauvegardes et la restauration à un instant donné. Avec `COMPOSE_PROFILES=localdb`, la pile démarre son propre conteneur PostgreSQL.

**Sauvegardes (base locale uniquement) :**

```bash
/var/www/iafluence-booking/current/deploy/release.sh compose exec -T db pg_dump -U iafluence iafluence | gzip > backup-$(date +%F).sql.gz
```

À planifier en cron quotidien.

**Base PostgreSQL hébergée (Neon, plan gratuit) :**

Au lieu du conteneur `db`, on peut pointer `DATABASE_URL` vers Neon (`postgresql+psycopg://…@….neon.tech/…?sslmode=require`). Le plan gratuit suffit largement pour ce MVP (0,5 Go et 100 CU-heures par projet et par mois).

Le point à surveiller, c'est le réveil. Après 5 min sans requête, la base s'endort (ce n'est pas désactivable en gratuit), et la requête suivante attend quelques centaines de ms. Pour un webhook Stripe, ce n'est pas un problème, car Stripe réessaie. C'est pourquoi le moteur SQLAlchemy (`backend/app/db.py`) est configuré avec :

- `connect_timeout=10` : un timeout de connexion confortable (≥ 5 s) pour laisser le temps à la base de se réveiller ;
- `pool_pre_ping=True` : les connexions du pool coupées pendant la mise en veille sont détectées et rouvertes automatiquement.

Pour les environnements, préférez une branche Neon par environnement (`main` pour la prod, `dev`, `preview`) plutôt que des projets séparés.

### 4. Comptes rendus de séance (Fireflies + Codex)

Facultatif : sans ces réglages, l’email de fin de séance reste celui de la V1.

1. **Fireflies** : *Settings → Developer settings* → copier la clé API, puis dans `/admin` → *Connexion Fireflies* → la coller et **Connecter Fireflies**. La clé est vérifiée auprès de Fireflies (le compte s’affiche), chiffrée en base avec une clé dérivée de `SESSION_SECRET` et jamais renvoyée au navigateur ; si `SESSION_SECRET` change, il suffit de la recoller. À défaut, `FIREFLIES_API_KEY` dans `shared/.env` est utilisée. L’API est incluse dans tous les forfaits, avec un quota : **Free 50 requêtes/jour**, Pro 500/jour, Business 60/min. Une requête liste les enregistrements de toutes les séances en attente, puis une requête lit la transcription trouvée. Avec le forfait Free, passer `FIREFLIES_POLL_SECONDS=1800` (une vérification toutes les 30 min, 12 au plus par séance). L’enregistreur Fireflies doit rejoindre les réunions Meet et le client doit y figurer comme participant (invitation Google Agenda) ; sinon la séance est reconnue par son lien Meet.
2. **Service Codex** : dans `shared/.env`, ajouter `codex` à `COMPOSE_PROFILES` (`localdb,codex`, ou `codex` avec Neon), puis :
   ```dotenv
   CODEX_APP_SERVER_URL=ws://codex:4500
   CODEX_WS_TOKEN=...            # openssl rand -hex 32
   ```
   Au déploiement suivant, `release.sh` construit l’image `deploy/codex` (Node + `@openai/codex`, version fixée par `CODEX_VERSION`) et démarre `codex app-server`. Codex écoute sur la boucle locale du conteneur (contrainte de sécurité pour WebSocket) ; un relais HTTP/WebSocket réécrit l’hôte en adresse de boucle locale et l’expose uniquement au réseau Docker privé, sans port publié sur l’hôte. Le serveur exige toujours ce jeton, et ses outils (shell, web, navigateur, images, extensions) sont désactivés : l’agent ne fait qu’écrire, une transcription ne peut rien lui faire exécuter.
3. **Connexion Codex** : dans `/admin` → *Connexion Codex* → **Connecter Codex** (disponible dès l’étape 2, même sans clé Fireflies : le compte ChatGPT peut être associé avant). Ouvrir `https://auth.openai.com/codex/device` (bouton « Ouvrir OpenAI » ou « Copier »), se connecter à ChatGPT et saisir le code affiché (ex. `ABCD-1234`). La page vérifie toutes les 3 s et passe seule à « Connecté » (flux d’autorisation d’appareil OAuth 2.0, RFC 8628 : `PENDING → COMPLETED`, ou `EXPIRED` au bout de 15 min, `DENIED`, `CANCELLED`, `ERROR`). Les appels de modèle utilisent ensuite le quota de votre forfait ChatGPT. Les jetons OAuth restent dans le volume `codex-home` du conteneur `codex` : ils ne passent jamais par l’API, le navigateur ni les logs. « Connexion expirée » s’affiche si la session ChatGPT prend fin ; « Déconnecter » la ferme.
4. **L’agent** : ses consignes sont `backend/app/codex_agent/*.md` (concaténés par ordre alphabétique). Vous pouvez les réécrire avec Claude ou ChatGPT et en ajouter ; seul le format de sortie (dernière section d’`AGENTS.md`) doit rester identique. Un changement est pris en compte au déploiement suivant.
5. **Vérifier** : terminer une séance de test enregistrée par Fireflies ; en 5 à 15 min, l’admin affiche « Brouillon créé avec compte rendu » et le brouillon apparaît dans Gmail.

> ⚠️ **Conditions d’utilisation OpenAI** : un usage automatisé, côté serveur, de Codex avec un forfait ChatGPT (et non une clé API) doit être autorisé par les conditions en vigueur de votre forfait. À vérifier avant la mise en production ; sinon, passer à une clé API OpenAI côté `codex app-server` (petite adaptation : l’application n’accepte aujourd’hui qu’un compte ChatGPT).

Paramètres facultatifs : `FIREFLIES_MAX_WAIT_HOURS` (6), `CODEX_MODEL` (vide = modèle par défaut du forfait), `CODEX_TURN_TIMEOUT_SECONDS` (600), `REPORT_RETENTION_DAYS` (90 ; 0 = conservés). Mettez à jour votre registre des traitements RGPD : Fireflies et OpenAI traitent le contenu des séances.

### Réglages

Les réglages métier sont stockés en base (tables `settings` et `availability_rules`). Pour modifier les horaires, par exemple ajouter une pause déjeuner le mardi :

```sql
DELETE FROM availability_rules WHERE weekday = 1;
INSERT INTO availability_rules (weekday, start_time, end_time) VALUES (1, '09:00', '12:00'), (1, '14:00', '18:00');
-- weekday : 0 = lundi … 6 = dimanche
UPDATE settings SET buffer_before_min = 15, buffer_after_min = 15, minimum_notice_min = 1440, maximum_window_days = 30;
```

## API

| Méthode | Route | Rôle |
|---|---|---|
| GET | `/api/checkout/{session_id}` | Vérifie le paiement et renvoie `{token}` |
| GET | `/api/booking/{token}` | Client, heures achetées/réservées/restantes, rendez-vous existant |
| GET | `/api/availability?token=&from=&to=` | `{slots: [{start, end}]}` |
| POST | `/api/bookings` `{token, start}` | Crée le rendez-vous. Codes : 201 ; 409 `slot_taken` / `already_booked` ; 422 créneau non proposé ; 503 agenda indisponible |
| POST | `/webhooks/stripe` | Webhook signé |
| POST/GET | `/api/admin/login`, `/api/admin/overview` | Administration |
| POST | `/api/admin/clients` `{name, email, hours, product_name, amount_cents, send_link}` | Ajoute un client payé hors du site, renvoie `{purchase_id, booking_url}` |
| PATCH | `/api/admin/customers/{id}` `{auto_send_next_link}` | Lien de la session suivante : envoi automatique ou brouillon |
| POST | `/api/admin/bookings/{id}/cancel` `{notify}` | Annule une séance à venir, recrédite l’heure. 409 `not_cancellable` ; 502 `calendar_delete_failed` (rien n’est modifié) |
| PATCH | `/api/admin/purchases/{id}` `{hours_purchased}` | Ajuste les heures d’un achat (422 si inférieur aux heures réservées) |
| GET | `/api/admin/overview` → `reports` | `{enabled, send_without_review, sessions: [{booking_id, customer, start, …, report: {id, status, transcript_attempts, summary_attempts, error, synthese, has_image, delivery, with_summary, …} \| null}]}` |
| GET | `/api/admin/reports/{id}/image.png` | Infographie du compte rendu (admin uniquement, non mise en cache) |
| POST | `/api/admin/reports/{id}/retry` | « Relancer » : nouveau résumé si la transcription a été trouvée, sinon 6 h de recherche Fireflies de plus. 409 si un brouillon existe déjà ou si un résumé est en cours |
| POST | `/api/admin/reports/{id}/draft-without-summary` | Email V1, toujours en brouillon. 409 si déjà préparé, achat remboursé ou lien révoqué |
| PATCH | `/api/admin/report-settings` `{send_without_review}` | Envoi direct des emails avec résumé pour les clients en « Envoi auto » |
| GET | `/api/admin/codex` | `{state: connected \| expired \| disconnected \| unavailable \| not_configured, email, plan, detail, pending_login}` — jamais de jeton |
| POST | `/api/admin/codex/login` | Démarre la connexion par code appareil : `{id, status: "PENDING", verification_url, user_code, expires_at}`. 502 si `codex app-server` est injoignable |
| GET | `/api/admin/codex/login/{id}` | Statut (`PENDING`, `COMPLETED`, `EXPIRED`, `DENIED`, `CANCELLED`, `ERROR`) ; le code n’est renvoyé que tant qu’il est `PENDING` |
| POST | `/api/admin/codex/login/{id}/cancel`, `/api/admin/codex/logout` | Annule la connexion en attente ; déconnecte le compte ChatGPT |
| GET / POST / DELETE | `/api/admin/fireflies` | « Connexion Fireflies » : `{state: connected \| disconnected, source: admin \| server, email, name, detail}` ; POST `{api_key}` vérifie la clé auprès de Fireflies (400 si refusée) puis l’enregistre chiffrée ; DELETE l’efface. Jamais la clé en réponse |

## Hors MVP (évolutions prévues)

Déplacement d’un rendez-vous par le client lui-même, rappels, portail client, interface d’édition des réglages, édition du compte rendu dans l’admin avant création du brouillon.
