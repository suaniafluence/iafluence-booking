# IAfluence Booking

Réservation de la **première session de 1 h** après l’achat d’une prestation « Conseil IA » sur Stripe.

Paiement Stripe → vérification → lien de réservation sécurisé → créneaux libres agrégés depuis plusieurs Google Calendars (free/busy uniquement) → création de l’événement Google Calendar + Meet + invitation → emails client et admin → suivi des heures achetées / réservées / restantes.

```
backend/    FastAPI · SQLAlchemy · Alembic · PostgreSQL
frontend/   React · Vite · TypeScript · Tailwind
deploy/     Docker Compose · Caddy (TLS auto) · .env.example · release.sh (déploiement / rollback)
.github/    CI (tests) · Deploy Production (manuel)
```

## Fonctionnement

| Étape | Détail |
|---|---|
| Paiement | 4 Payment Links Stripe. Chaque produit porte la métadonnée `hours` (1, 2, 3, 5). |
| Redirection | Après paiement, Stripe renvoie vers `/reservation?session_id={CHECKOUT_SESSION_ID}`. Le backend vérifie la session auprès de Stripe, crée l’achat et un **token aléatoire de 256 bits**, puis le navigateur est redirigé vers `/reservation/{token}`. Le lien est aussi envoyé par email. |
| Webhook | `POST /webhooks/stripe` (`checkout.session.completed`, `checkout.session.async_payment_succeeded`, `charge.refunded`). Traitement idempotent : webhook et redirection peuvent arriver dans n’importe quel ordre. Un remboursement total révoque le lien et alerte l’admin. |
| Disponibilités | `freebusy.query` sur tous les calendriers activés + le calendrier des rendez-vous. Aucun titre, participant, lieu ou lien n’est jamais lu ni exposé : l’API ne renvoie que `{start, end}`. Si un calendrier est en erreur, rien n’est proposé (fail closed). |
| Règles | Horaires hebdomadaires (plusieurs plages par jour possibles), durée 60 min, tampons 15 min avant/après, préavis 24 h, horizon 30 jours, fuseau `Europe/Paris` (changements d’heure gérés). |
| Réservation | Verrou transactionnel PostgreSQL + nouvelle requête free/busy (sans cache) juste avant la création de l’événement. En base, un index unique (une session par achat) et une contrainte d’exclusion (aucun chevauchement) empêchent toute double réservation. |
| Google Calendar | Événement « Conseil IA - Nom » dans le calendrier dédié, avec le client en invité (`sendUpdates=all` : Google envoie l’invitation à n’importe quelle adresse) et un lien Meet optionnel. |
| Emails | Envoyés via l’API Gmail : lien de réservation, confirmation client, notification « NOUVELLE RÉSERVATION », alerte remboursement. |
| Admin | `/admin` (mot de passe unique) : indicateurs du mois, heures vendues/réalisées/restantes, prochains rendez-vous, liste des clients. |

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
http://localhost:5173/reservation?session_id=cs_demo_5h_jean. Les calendriers contiennent quelques créneaux occupés fictifs et les emails s’affichent dans les logs.

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

**End-to-end** — Playwright démarre le vrai backend (mode `FAKE_INTEGRATIONS`, base `iafluence_e2e` remise à zéro à chaque exécution) et le build de production du frontend, puis pilote un navigateur : du retour Stripe au rendez-vous confirmé (bureau et mobile), deux clients sur le même créneau, liens invalides, administration.

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

DNS : un enregistrement `A booking.iafluence.fr` qui pointe vers l’IP du VPS. Ports 80 et 443 ouverts.

Le serveur ne reçoit ni le dépôt, ni Node, ni les outils de test. GitHub Actions exécute les tests, construit le frontend et envoie une archive minimale (sources backend sans tests, `frontend/dist`, fichiers de `deploy/`). Sur le serveur, Docker Compose construit l’image API avec les seules dépendances runtime, puis sert le frontend via l’image Caddy officielle.

```
/var/www/iafluence-booking/
  releases/<release-id>/     une archive par déploiement (3 conservées)
  current -> releases/<id>   release active
  shared/.env                secrets de production (jamais dans le dépôt ni dans l’archive)
```

**Déployer :** GitHub → *Actions* → *Deploy Production* → *Run workflow* (branche `main`). Les jobs `test` → `build` → `deploy` s’enchaînent seulement si le précédent réussit. `deploy/release.sh` construit l’image pendant que l’ancienne version tourne, bascule `current`, redémarre, puis vérifie `/api/health` et la page d’accueil via Caddy. En cas d’échec, il revient automatiquement à la release précédente. Les tests tournent aussi à chaque push sur `main` et à chaque pull request (`.github/workflows/ci.yml`).

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

**Sauvegardes :**

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

## Hors MVP (évolutions prévues)

Modification ou annulation de rendez-vous, réservation des heures suivantes (le verrou « une session par achat » est un index unique à assouplir), rappels, portail client, interface d’édition des réglages.
