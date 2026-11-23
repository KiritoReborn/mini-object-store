#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
umask 077

if [ -f .env ] && grep -Eq '^[[:space:]]*(export[[:space:]]+)?ARTAUD_API_KEY[[:space:]]*=' .env; then
    printf '%s\n' 'Keeping the existing ARTAUD_API_KEY entry. Its value must be at least 32 characters.'
    exit 0
fi

key=$(openssl rand -hex 32)
printf '\nARTAUD_API_KEY=%s\n' "$key" >> .env
printf '%s\n' 'Owner key added to .env. Enter its value in the dashboard Connection settings.'
