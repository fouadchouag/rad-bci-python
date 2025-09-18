#!/usr/bin/env bash
set -euo pipefail

APP="rbciad"
VERSION="${RB_VERSION:-1.10.0}"

echo "[RBciAD] Using version: $VERSION"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$DIR/.venv"

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "[RBciAD] Creating virtual environment in .venv ..."
  python3 -m venv "$VENV"
fi

# shellcheck disable=SC1090
source "$VENV/bin/activate"

echo "[RBciAD] Upgrading pip..."
python -m pip install --upgrade pip >/dev/null

echo "[RBciAD] Installing $APP==$VERSION from TestPyPI..."
python -m pip install -i https://test.pypi.org/simple --extra-index-url https://pypi.org/simple "$APP==$VERSION"

if command -v "$APP" >/dev/null 2>&1; then
  echo "[RBciAD] Launching: $APP $*"
  exec "$APP" "$@"
else
  echo "[RBciAD] Launching via module: python -m $APP $*"
  exec python -m "$APP" "$@"
fi
