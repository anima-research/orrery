#!/bin/bash
# Deploy orrery from the repo. Refuses to run with local modifications so
# prod-hotfix clobbering can never happen again — commit upstream instead.
set -e
cd ~/orrery
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "REFUSING: local modifications present (commit them upstream first):"
  git status --short
  exit 1
fi
git pull --ff-only origin main
server/.venv/bin/pip install -q -r server/requirements.txt
cd web && ~/.bun/bin/bun install --silent && ~/.bun/bin/bun --bun node_modules/.bin/vite build && cd ..
sudo systemctl restart orrery
sleep 2
systemctl is-active orrery && curl -s localhost:8420/api/health && echo " deployed: $(git log --oneline -1)"
