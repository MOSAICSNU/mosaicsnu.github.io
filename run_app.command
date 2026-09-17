#!/bin/zsh
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
APP_PYTHON="$PROJECT_DIR/.venv/bin/python"
cd "$PROJECT_DIR"

create_venv() {
  echo "Creating Python virtual environment..."
  python3 -m venv "$PROJECT_DIR/.venv"
  "$APP_PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else "Python 3.10 or newer is required")'
  "$APP_PYTHON" -m pip install -U pip
  "$APP_PYTHON" -m pip install -e .
}

if [ ! -x "$APP_PYTHON" ]; then
  create_venv
elif ! "$APP_PYTHON" -c "import sys" >/dev/null 2>&1; then
  backup_dir="$PROJECT_DIR/.venv-backup-$(date +%Y%m%d-%H%M%S)"
  echo "Backing up an unusable virtual environment to ${backup_dir:t}..."
  mv "$PROJECT_DIR/.venv" "$backup_dir"
  create_venv
fi

"$APP_PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else "Python 3.10 or newer is required; recreate the old .venv")'
if ! "$APP_PYTHON" tools/check_environment.py >/dev/null 2>&1; then
  echo "Installing required Python packages..."
  "$APP_PYTHON" -m pip install -e .
fi

# Prefer this folder's source code even when an older editable install exists.
export PYTHONPATH="$PROJECT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$APP_PYTHON" -m mosaic.main
