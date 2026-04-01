#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$APP_DIR"

echo "-> BayAfya Railway startup: running migrations"
python manage.py migrate --noinput

echo "-> BayAfya Railway startup: collecting static files"
python manage.py collectstatic --noinput

exec python -m daphne -b 0.0.0.0 -p "${PORT:-8000}" bayhealth_project.asgi:application
