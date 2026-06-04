#!/usr/bin/env bash
#
# release.sh — commit & push everything EXCEPT local config/runtime state.
#
# What it does:
#   1. (optional) bumps version.py: patch | minor | major
#   2. stages ALL changes (tracked + untracked) EXCEPT the exclude list below
#   3. commits with your message (version is appended automatically)
#   4. pushes the current branch to origin
#
# Usage:
#   ./release.sh "commit message"                # commit + push, no bump
#   ./release.sh patch "fix: panel state bug"    # bump patch, then commit + push
#   ./release.sh minor "feat: new dashboard"     # bump minor
#   ./release.sh major "breaking: rewrite API"   # bump major
#
# NEVER commits these (local/runtime state — keep them out of git):
#   - config/            (projects.json, settings.json, backups)
#   - *.tmp, *.log, .venv, __pycache__
#
set -euo pipefail

cd "$(dirname "$0")"

# --- paths/globs this script must never stage -------------------------------
EXCLUDES=(
  "config/"
  "*.tmp"
  "*.log"
  ".venv/"
)

# --- parse args -------------------------------------------------------------
BUMP=""
case "${1:-}" in
  patch|minor|major) BUMP="$1"; shift ;;
esac
MSG="${1:-}"
if [[ -z "$MSG" ]]; then
  echo "error: commit message required" >&2
  echo "usage: ./release.sh [patch|minor|major] \"commit message\"" >&2
  exit 1
fi

# --- bump version.py (MAJOR.MINOR.PATCH) ------------------------------------
if [[ -n "$BUMP" ]]; then
  cur=$(grep -oE '[0-9]+\.[0-9]+\.[0-9]+' version.py | head -1)
  IFS='.' read -r MA MI PA <<< "$cur"
  case "$BUMP" in
    patch) PA=$((PA+1)) ;;
    minor) MI=$((MI+1)); PA=0 ;;
    major) MA=$((MA+1)); MI=0; PA=0 ;;
  esac
  new="${MA}.${MI}.${PA}"
  sed -i "s/__version__ = \"${cur}\"/__version__ = \"${new}\"/" version.py
  echo "version bumped: ${cur} -> ${new}"
fi
VERSION=$(grep -oE '[0-9]+\.[0-9]+\.[0-9]+' version.py | head -1)

# --- stage everything, then unstage the excludes ---------------------------
git add -A
for pat in "${EXCLUDES[@]}"; do
  git reset -q -- "$pat" 2>/dev/null || true
done

if git diff --cached --quiet; then
  echo "nothing staged to commit (after excluding configs)"; exit 0
fi

echo "--- staged for commit ---"
git diff --cached --name-only
echo "-------------------------"

git commit -m "${MSG} (v${VERSION})"

branch=$(git rev-parse --abbrev-ref HEAD)
git push -u origin "$branch"
echo "pushed ${branch} (v${VERSION})"
