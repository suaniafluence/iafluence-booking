#!/bin/sh
# Mutation testing of the backend with mutmut, inside a Linux container (mutmut needs fork()).
#
#   cd backend && ./mutation.sh            # all mutable modules
#   cd backend && ./mutation.sh "app.services.availability*"   # a subset (mutant name glob)
#
# Needs a PostgreSQL reachable from Docker. Default: the test container from the README on host port 5433,
# database iafluence_mutation (created if missing). Override with MUTATION_DATABASE_URL.
# Report: backend/mutation-report/ (summary.txt, survivors.txt with the diff of every surviving mutant).
set -eu

if [ "${MUTMUT_IN_CONTAINER:-}" != "1" ]; then
    DB_URL="${MUTATION_DATABASE_URL:-postgresql+psycopg://postgres:dev@host.docker.internal:5433/iafluence_mutation}"
    # MSYS_NO_PATHCONV: keep Git Bash on Windows from rewriting /src.
    exec env MSYS_NO_PATHCONV=1 docker run --rm \
        --add-host=host.docker.internal:host-gateway \
        -v "$(pwd)":/src:ro -v "$(pwd)/mutation-report":/report \
        -e MUTMUT_IN_CONTAINER=1 -e TEST_DATABASE_URL="$DB_URL" -e MUTANTS="${1:-}" \
        ghcr.io/astral-sh/uv:python3.12-bookworm-slim sh /src/mutation.sh
fi

# --- inside the container ------------------------------------------------------------------
# Work on a copy: bind mounts are slow on Windows and mutmut writes its mutants/ tree next to the code.
mkdir -p /work && cd /src && tar --exclude=.venv --exclude=mutants --exclude=mutation-report --exclude=__pycache__ -cf - . | tar -xf - -C /work
cd /work
export UV_PROJECT_ENVIRONMENT=/opt/venv UV_LINK_MODE=copy
uv sync --locked --group mutation --quiet

# Every mutant runs the DB tests: workers must not share the database concurrently.
uv run --no-sync mutmut run --max-children 1 ${MUTANTS:+"$MUTANTS"} || true

uv run --no-sync mutmut export-cicd-stats >/dev/null
cp mutants/mutmut-cicd-stats.json /report/stats.json
uv run --no-sync mutmut results > /report/summary.txt || true
: > /report/survivors.txt
for m in $(uv run --no-sync mutmut results 2>/dev/null | awk -F: '/: survived/ {print $1}'); do
    uv run --no-sync mutmut show "$m" >> /report/survivors.txt 2>&1
    echo >> /report/survivors.txt
done
python3 - <<'PY'
import json
s = json.load(open("/report/stats.json"))
tested = s["killed"] + s["survived"] + s.get("timeout", 0) + s.get("suspicious", 0)
score = 100 * (s["killed"] + s.get("timeout", 0)) / tested if tested else 0
print(f"\nMutation score: {score:.1f}%  ({s['killed']} killed, {s['survived']} survived, "
      f"{s.get('no_tests', 0)} without tests, {s.get('timeout', 0)} timeouts) -> backend/mutation-report/")
PY
