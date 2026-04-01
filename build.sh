#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

python -m pip install --upgrade pip
pip install -r requirements.txt

mkdir -p \
  media \
  staticfiles \
  static/images \
  static/css \
  static/js \
  templates

echo "-> BayAfya build dependencies installed and runtime directories prepared"
