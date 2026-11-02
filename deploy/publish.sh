#!/usr/bin/env bash
# Sync this worker/ folder to the standalone public repo that GitHub Actions + Streamlit Cloud run from.
# Usage: worker/deploy/publish.sh [commit message]
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
REPO="${PUBLISH_REPO:-Manjunadh86/fresher-jobs-worker}"
DEST="${PUBLISH_DIR:-$HOME/.cache/fresher-jobs-worker}"
MSG="${1:-sync worker $(date +%F)}"

if [ ! -d "$DEST/.git" ]; then
  gh repo clone "$REPO" "$DEST"
fi
cd "$DEST" && git pull --rebase -q
rsync -a --delete \
  --exclude .git --exclude data --exclude .env --exclude '__pycache__' --exclude '.streamlit/secrets.toml' \
  "$SRC/" "$DEST/"
git add -A
git commit -qm "$MSG" || { echo "nothing to publish"; exit 0; }
git push -q
echo "published to https://github.com/$REPO"
