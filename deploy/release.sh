#!/usr/bin/env bash
# Production release manager, shipped inside each release and run on the server.
#
#   release.sh activate <release-id>    build the API image, switch `current`, restart, health check;
#                                       rolls back to the previous release if the health check fails
#   release.sh rollback [<release-id>]  go back to the given release (default: the one before `current`)
#   release.sh compose <args...>        docker compose on the current release, e.g.
#                                       release.sh compose exec api python -m scripts.list_calendars
#
# Layout:
#   $APP_DIR/releases/<release-id>/   backend sources, frontend build, deploy files
#   $APP_DIR/current -> releases/<release-id>
#   $APP_DIR/shared/.env              production secrets, never part of a release
#
# Database migrations run when the API starts and are NOT reverted by a rollback.
set -euo pipefail

SCRIPT_DIR=$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
APP_DIR=${APP_DIR:-$(dirname "$(dirname "$(dirname "$SCRIPT_DIR")")")}
RELEASES=$APP_DIR/releases
SHARED_ENV=$APP_DIR/shared/.env
KEEP_RELEASES=${KEEP_RELEASES:-3}
API_IMAGE=iafluence-booking-api

log() { printf '==> %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# Read KEY=value from shared/.env without sourcing it (values may contain spaces or "$").
env_value() {
  local v
  v=$(grep -E "^$1=" "$SHARED_ENV" | tail -n 1 | cut -d= -f2- | sed -E 's/[[:space:]]+#.*$//') || true
  v=${v%\"}; v=${v#\"}; v=${v%\'}; v=${v#\'}
  printf '%s' "${v:-$2}"
}

[ -f "$SHARED_ENV" ] || die "$SHARED_ENV is missing (start from deploy/.env.example)"
PROJECT=$(env_value COMPOSE_PROJECT_NAME iafluence)
WEB_PORT=$(env_value WEB_PORT 3004)

compose() {
  local id=$1; shift
  RELEASE_ID=$id docker compose -p "$PROJECT" -f "$RELEASES/$id/deploy/docker-compose.yml" "$@"
}

current_id() {
  [ -L "$APP_DIR/current" ] && basename "$(readlink "$APP_DIR/current")" || true
}

switch_current() {
  ln -sfn "releases/$1" "$APP_DIR/current.tmp"
  mv -Tf "$APP_DIR/current.tmp" "$APP_DIR/current"
}

release_ids() {
  find "$RELEASES" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort
}

health_check() {
  local id=$1 i
  for i in $(seq 1 40); do
    if compose "$id" exec -T api python -c \
         "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)" >/dev/null 2>&1 \
       && curl -fsS --max-time 5 "http://127.0.0.1:$WEB_PORT/api/health" >/dev/null 2>&1 \
       && curl -fsS --max-time 5 "http://127.0.0.1:$WEB_PORT/" 2>/dev/null | grep -q 'id="root"'; then
      log "Health check OK (API, then API and frontend through Caddy)"
      return 0
    fi
    sleep 3
  done
  return 1
}

# A stack started by hand from a git clone (`cd deploy && docker compose up`) runs as project "deploy".
guard_legacy_stack() {
  if [ "$PROJECT" != deploy ] && docker volume inspect deploy_pgdata >/dev/null 2>&1 \
     && ! docker volume inspect "${PROJECT}_pgdata" >/dev/null 2>&1; then
    die "volume deploy_pgdata belongs to a manually started stack. Add COMPOSE_PROJECT_NAME=deploy to $SHARED_ENV to take it over and keep its data."
  fi
}

prune() {
  local current id
  current=$(current_id)
  for id in $(release_ids | head -n "-$KEEP_RELEASES"); do
    [ "$id" = "$current" ] && continue
    log "Removing old release $id"
    rm -rf "${RELEASES:?}/$id"
    docker image rm "$API_IMAGE:$id" >/dev/null 2>&1 || true
  done
  rm -f "$RELEASES"/*.tar.gz
  docker image prune -f >/dev/null
}

activate() {
  local id=$1 previous
  [ -d "$RELEASES/$id" ] || die "release $id not found in $RELEASES"
  previous=$(current_id)
  guard_legacy_stack
  ln -sfn "$SHARED_ENV" "$RELEASES/$id/deploy/.env"

  # Also the codex app-server image when the "codex" profile is on (tagged by Codex version: rebuilt on change only).
  log "Building images for $id (API: runtime dependencies only; current release keeps serving)"
  compose "$id" build

  log "Switching current -> releases/$id (previous: ${previous:-none})"
  switch_current "$id"
  compose "$id" up -d --remove-orphans

  if health_check "$id"; then
    prune
    log "Release $id is live"
    return 0
  fi

  compose "$id" logs --tail 80 api web >&2 || true
  if [ -n "$previous" ] && [ "$previous" != "$id" ] && [ -d "$RELEASES/$previous" ]; then
    log "Health check failed: rolling back to $previous"
    switch_current "$previous"
    compose "$previous" up -d --remove-orphans
    health_check "$previous" || log "WARNING: $previous does not pass the health check either"
    # Drop the broken release so that a later `rollback` never lands on it.
    rm -rf "${RELEASES:?}/$id"
    docker image rm "$API_IMAGE:$id" >/dev/null 2>&1 || true
  fi
  die "release $id failed its health check"
}

rollback() {
  local target=${1:-} current
  current=$(current_id)
  if [ -z "$target" ]; then
    target=$(release_ids | awk -v c="$current" '$0 < c' | tail -n 1)
  fi
  [ -n "$target" ] && [ -d "$RELEASES/$target" ] || die "no release to roll back to"
  log "Rolling back ${current:-none} -> $target (database migrations are not reverted)"
  ln -sfn "$SHARED_ENV" "$RELEASES/$target/deploy/.env"
  switch_current "$target"
  compose "$target" up -d --remove-orphans
  health_check "$target" || die "$target failed its health check"
  log "Release $target is live"
}

case "${1:-}" in
  activate) [ $# -eq 2 ] || die "usage: $0 activate <release-id>"; activate "$2" ;;
  rollback) rollback "${2:-}" ;;
  compose)
    shift
    id=$(current_id)
    [ -n "$id" ] || die "no current release"
    compose "$id" "$@"
    ;;
  *) die "usage: $0 activate <release-id> | rollback [<release-id>] | compose <args...>" ;;
esac
