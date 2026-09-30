#!/bin/sh
# Starts `codex app-server` on the internal Docker network, for the API only.
#
# - WebSocket clients must present CODEX_WS_TOKEN (shared with the API through deploy/.env).
# - The agent only writes text: shell, apps, plugins, browser, web search and image tools are off, so a transcript
#   cannot make it run anything. Threads are ephemeral and history is off: no prompt (hence no transcript) is kept.
set -eu

: "${CODEX_WS_TOKEN:?CODEX_WS_TOKEN is missing (deploy/.env)}"
umask 077
token_file=$(mktemp)
printf '%s' "$CODEX_WS_TOKEN" > "$token_file"
unset CODEX_WS_TOKEN

exec codex app-server \
  --listen "ws://0.0.0.0:${CODEX_PORT:-4500}" \
  --ws-auth capability-token --ws-token-file "$token_file" \
  --disable shell_tool --disable unified_exec --disable apps --disable plugins --disable browser_use \
  --disable computer_use --disable image_generation --disable multi_agent --disable memories \
  -c 'web_search="disabled"' \
  -c 'history.persistence="none"'
