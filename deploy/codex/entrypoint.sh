#!/bin/sh
# Starts `codex app-server` on the internal Docker network, for the API only.
#
# - The app-server binds to localhost because Codex refuses non-loopback WebSocket listeners. A TCP relay exposes it
#   only on the container's private Docker network; clients must still present CODEX_WS_TOKEN.
# - The agent only writes text: shell, apps, plugins, browser, web search and image tools are off, so a transcript
#   cannot make it run anything. Threads are ephemeral and history is off: no prompt (hence no transcript) is kept.
set -eu

: "${CODEX_WS_TOKEN:?CODEX_WS_TOKEN is missing (deploy/.env)}"
umask 077
token_file=$(mktemp)
printf '%s' "$CODEX_WS_TOKEN" > "$token_file"
unset CODEX_WS_TOKEN

# Codex requires WebSocket authentication for a non-localhost listener even when its capability-token options are
# supplied. Keep Codex on loopback and expose a separate, unauthenticated-at-the-TCP-layer relay. No host port is
# published by docker-compose; application-layer authentication remains enforced by the app-server.
socat "TCP-LISTEN:${CODEX_PORT:-4500},fork,reuseaddr" "TCP:127.0.0.1:${CODEX_INTERNAL_PORT:-4501}" &

exec codex app-server \
  --listen "ws://127.0.0.1:${CODEX_INTERNAL_PORT:-4501}" \
  --ws-auth capability-token --ws-token-file "$token_file" \
  --disable shell_tool --disable unified_exec --disable apps --disable plugins --disable browser_use \
  --disable computer_use --disable image_generation --disable multi_agent --disable memories \
  -c 'web_search="disabled"' \
  -c 'history.persistence="none"'
