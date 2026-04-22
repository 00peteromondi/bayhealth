#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$APP_DIR"

echo "-> BayAfya Railway release: running migrations"
if python manage.py migrate --noinput; then
  echo "-> BayAfya Railway release: collecting static files"
  python manage.py collectstatic --noinput || echo "-> collectstatic failed during release; startup will retry"
else
  echo "-> Release-phase database setup unavailable; deferring migrations/static collection to runtime startup"
fi
