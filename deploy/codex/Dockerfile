# codex app-server for the session reports (backend/app/services/codex.py): device login with the ChatGPT plan,
# then one agent turn per summary. Reached by the API only, over the internal Docker network.
FROM node:22-bookworm-slim

ARG CODEX_VERSION=0.159.2
RUN apt-get update \
 && apt-get install --yes --no-install-recommends bubblewrap socat \
 && rm -rf /var/lib/apt/lists/* \
 && npm install --global "@openai/codex@${CODEX_VERSION}" \
 && npm cache clean --force \
 && useradd --create-home codex \
 && mkdir -p /codex-home /work \
 && chown codex /codex-home /work

COPY --chmod=755 entrypoint.sh /usr/local/bin/codex-entrypoint

USER codex
# auth.json (OAuth tokens of the ChatGPT account) lives here, on the codex-home volume, readable by this user only.
ENV CODEX_HOME=/codex-home
WORKDIR /work
EXPOSE 4500
ENTRYPOINT ["codex-entrypoint"]
