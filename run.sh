#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "── Flâneur Backend ─────────────────────────"

# Venv
if [ ! -d ".venv" ]; then
  echo "▶ Création du venv Python..."
  python3 -m venv .venv
fi

source .venv/bin/activate

# Dépendances
echo "▶ Installation des dépendances..."
pip install -q -r backend/requirements.txt

# Playwright Chromium
if ! python3 -c "from playwright.sync_api import sync_playwright; sync_playwright().__enter__().chromium.executable_path" 2>/dev/null | grep -q "chromium"; then
  echo "▶ Installation de Chromium (Playwright)..."
  playwright install chromium
fi

echo "▶ Démarrage du backend sur http://localhost:8000"
echo "   Frontend  : http://localhost:8000"
echo "   Datasette : http://localhost:8001"
echo "────────────────────────────────────────────"

python3 -m datasette backend/events.db --port 8001 &

uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
