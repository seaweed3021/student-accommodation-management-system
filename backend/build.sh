#!/usr/bin/env bash
# Build the Lambda package folder: handler + SQL + pure-Python dependencies.
# Run from the repo root:  bash backend/build.sh   (Terraform zips backend/build/)
set -euo pipefail
cd "$(dirname "$0")"
rm -rf build && mkdir build
pip install --quiet --target build -r requirements.txt
cp handler.py build/
cp ../db/schema.sql ../db/seed.sql build/
echo "built backend/build"
