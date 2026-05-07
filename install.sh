#!/usr/bin/env bash
# install.sh — clone, install, link, and sanity-check the clonemate skill.
set -euo pipefail

REPO_URL="${CLONEMATE_REPO_URL:-https://github.com/yeasy1003/clonemate.git}"
INSTALL_DIR="${CLONEMATE_INSTALL_DIR:-$HOME/.claude-personal/skills/clonemate-src}"
LINK_DIR="${CLONEMATE_LINK_DIR:-$HOME/.claude-personal/skills/clonemate}"

if ! command -v git >/dev/null 2>&1; then
  echo "[clonemate] git is required" >&2; exit 1
fi
if ! command -v git-filter-repo >/dev/null 2>&1; then
  echo "[clonemate] git-filter-repo missing — install with: brew install git-filter-repo (macOS) or pip install git-filter-repo" >&2
  exit 1
fi

if [ -d "$INSTALL_DIR/.git" ]; then
  git -C "$INSTALL_DIR" fetch --quiet
  git -C "$INSTALL_DIR" pull --quiet --ff-only
else
  git clone --quiet "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"
pip install -q -e ".[dev]"

# Link into Claude Code skills dir.
mkdir -p "$(dirname "$LINK_DIR")"
if [ -L "$LINK_DIR" ] || [ -e "$LINK_DIR" ]; then
  rm -rf "$LINK_DIR"
fi
ln -s "$INSTALL_DIR" "$LINK_DIR"

# Final sanity gate.
python -m clonemate.sanitize_check "$INSTALL_DIR"

echo "[clonemate] installed at $INSTALL_DIR, linked from $LINK_DIR"
