#!/usr/bin/env bash
# Inicia el Portal de Proveedores en http://127.0.0.1:5050
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi
[ -f .env ] && set -a && . ./.env && set +a
exec .venv/bin/python app.py
