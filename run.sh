#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "── Flâneur Backend ─────────────────────────"

VENV="$SCRIPT_DIR/backend/.venv"
PYTHON="$VENV/bin/python3"
PIP="$VENV/bin/pip"

# Venv
if [ ! -d "$VENV" ]; then
  echo "▶ Création du venv Python dans backend/.venv..."
  python3 -m venv "$VENV"
fi

# Dépendances
echo "▶ Installation des dépendances..."
"$PIP" install -q -r backend/requirements.txt

# Playwright Chromium
if ! "$PYTHON" -c "from playwright.sync_api import sync_playwright; sync_playwright().__enter__().chromium.executable_path" 2>/dev/null | grep -q "chromium"; then
  echo "▶ Installation de Chromium (Playwright)..."
  "$VENV/bin/playwright" install chromium
fi

echo "▶ Démarrage du backend sur http://localhost:8000"
echo "   Frontend  : http://localhost:8000"
echo "   Datasette : http://localhost:8001"
echo "────────────────────────────────────────────"

"$PYTHON" -m datasette backend/events.db --port 8001 &

cd "$SCRIPT_DIR/backend"
"$VENV/bin/uvicorn" main:app --reload --host 0.0.0.0 --port 8000
