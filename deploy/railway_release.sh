#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$APP_DIR"

echo "-> BayAfya Railway release: running migrations"
python manage.py migrate --noinput

echo "-> BayAfya Railway release: collecting static files"
python manage.py collectstatic --noinput
