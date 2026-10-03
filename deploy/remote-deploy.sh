#!/bin/bash
# Runs on the VM. Pulls the commit's image and restarts the stack; the registry
# token is the workflow's own short-lived token and is logged out afterwards.
set -euo pipefail
cd ~/fetchall
git fetch --quiet origin main
git checkout --quiet --detach "$FETCHALL_TAG"
echo "$REGISTRY_TOKEN" | docker login ghcr.io -u "$ACTOR" --password-stdin >/dev/null
trap 'docker logout ghcr.io >/dev/null' EXIT
cd deploy
export FETCHALL_TAG
docker compose -f compose.prod.yaml pull --quiet
docker compose -f compose.prod.yaml up -d --remove-orphans --no-build
docker image prune -f >/dev/null
for _ in $(seq 30); do
  if docker compose -f compose.prod.yaml exec -T api python -c \
      "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" 2>/dev/null; then
    echo "deployed $FETCHALL_TAG"
    exit 0
  fi
  sleep 2
done
echo "API did not become healthy after deploying $FETCHALL_TAG" >&2
exit 1
