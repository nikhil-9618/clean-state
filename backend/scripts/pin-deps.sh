#!/usr/bin/env bash
# Regenerate backend/requirements.lock.txt from requirements.in using the
# pinned Python base image, then record the dev tool versions.
#
# Usage:  bash backend/scripts/pin-deps.sh
set -euo pipefail

cd "$(dirname "$0")/.."

IMAGE_TAG="cleanslate-lock:local"

echo "==> building lock stage"
docker build --target lock -t "$IMAGE_TAG" .

echo "==> extracting requirements.lock.txt"
CONTAINER_ID="$(docker create "$IMAGE_TAG")"
trap 'docker rm -f "$CONTAINER_ID" >/dev/null 2>&1 || true' EXIT
docker cp "$CONTAINER_ID:/tmp/requirements.lock.txt" ./requirements.lock.txt
docker rm -f "$CONTAINER_ID" >/dev/null

echo "==> requirements.lock.txt"
cat ./requirements.lock.txt

echo
echo "Next: review the file, then rebuild the runtime image:"
echo "  docker build -t cleanslate-api:local ./backend"
