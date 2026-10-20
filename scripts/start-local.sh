#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
umask 077

if [ ! -f .env ]; then
    cp .env.example .env
fi
if ! grep -Eq '^APP_AUTH_TOKEN_SECRET=.+$' .env; then
    config_tmp=$(mktemp .env.XXXXXX)
    trap 'rm -f "$config_tmp"' EXIT HUP INT TERM
    sed '/^APP_AUTH_TOKEN_SECRET=/d' .env > "$config_tmp"
    printf '\nAPP_AUTH_TOKEN_SECRET=%s\n' "$(openssl rand -hex 32)" >> "$config_tmp"
    mv "$config_tmp" .env
    printf 'Generated a signing secret in .env. Keep this file private.\n'
fi
if [ "${1:-}" = "--init-only" ]; then
    exit 0
fi
docker compose up --build --wait "$@"
docker compose exec -T app python -m dev.main
