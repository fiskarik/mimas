#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# Render's native runtimes provide both Python and Node. Keep Python packages
# inside the checkout so the build does not need to modify the system Python.
python3 --version
node --version
python3 -c 'import sys; assert sys.version_info >= (3, 11), sys.version'
python3 -m pip install --disable-pip-version-check --no-cache-dir \
  --target .python-libs -r backend/requirements.lock.txt
npm --prefix frontend ci --include=dev
npm --prefix frontend run build

# Next's standalone server does not copy static assets or public files itself.
mkdir -p frontend/.next/standalone/.next
cp -R frontend/.next/static frontend/.next/standalone/.next/static
cp -R frontend/public frontend/.next/standalone/public
