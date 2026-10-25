#!/usr/bin/env bash
# Optional development-only setup. HA Green needs none of this.
set -euo pipefail
cd "$(dirname "$0")/.."
export UV_INSTALL_DIR="$PWD/.tooling/uv-linux"
export UV_NO_MODIFY_PATH=1
export UV_CACHE_DIR="$PWD/.tooling/uv-cache-linux"
export UV_PYTHON_INSTALL_DIR="$PWD/.tooling/python-linux"
mkdir -p .tooling
curl --fail --location --silent --show-error https://astral.sh/uv/install.sh -o .tooling/install-uv.sh
sh .tooling/install-uv.sh
"$UV_INSTALL_DIR/uv" python install 3.14
"$UV_INSTALL_DIR/uv" venv .venv-linux --python 3.14
"$UV_INSTALL_DIR/uv" pip install --python .venv-linux/bin/python -r requirements-dev.txt
