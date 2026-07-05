#!/usr/bin/env bash
# Create forwarder venv and install dependencies (easyocr, Google Drive API, etc.)
set -euo pipefail

FORWARDER_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$FORWARDER_DIR/venv"

cd "$FORWARDER_DIR"

if [ ! -x "$VENV/bin/python" ]; then
  if python3 -m venv "$VENV" 2>/dev/null; then
    echo "Created venv with python3 -m venv"
  else
    echo "python3-venv not available — bootstrapping with virtualenv.pyz"
    echo "  (Or run: sudo apt install python3.12-venv)"
    curl -sSLo /tmp/virtualenv.pyz https://bootstrap.pypa.io/virtualenv.pyz
    python3 /tmp/virtualenv.pyz "$VENV"
  fi
fi

"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install -r requirements.txt

echo ""
echo "Done. Use venv Python for forwarder and tests:"
echo "  $VENV/bin/python app.py"
echo "  $VENV/bin/python scripts/test_tier1.py"
