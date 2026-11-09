#!/usr/bin/env bash
# Symlink the tool scripts into a folder in the PATH, named after their tool folder.
# Usage: setup.sh [-u] [dir]
#   dir  target folder (default: ~/.local/bin)
#   -u   remove the links that point into this repo

set -euo pipefail

REPO_DIR=$(cd "$(dirname "$0")" && pwd)
SCRIPTS=(
  create-branch-from-jira/create-branch.sh
  sn_switcher/sn_switcher.sh
  jira_log_bucket/jira_log_bucket.py
  poll/poll_ci.py
)

UNINSTALL=0
if [ "${1:-}" = "-u" ]; then
  UNINSTALL=1
  shift
fi
case "${1:-}" in
  -h|--help) sed -n '2,5s/^# \{0,1\}//p' "$0"; exit 0 ;;
  -*) echo "Error: unknown option: $1" >&2; exit 1 ;;
esac
DIR="${1:-$HOME/.local/bin}"
DIR="${DIR%/}"

if [ "$UNINSTALL" = 1 ]; then
  for s in "${SCRIPTS[@]}"; do
    link="$DIR/$(dirname "$s")"
    if [ -L "$link" ] && [[ "$(readlink "$link")" == "$REPO_DIR/"* ]]; then
      rm "$link"
      echo "removed $link"
    fi
  done
  exit 0
fi

mkdir -p "$DIR"
for s in "${SCRIPTS[@]}"; do
  link="$DIR/$(dirname "$s")"
  if [ -e "$link" ] && [ ! -L "$link" ]; then
    echo "Warning: $link exists and is not a symlink, skipped" >&2
    continue
  fi
  chmod +x "$REPO_DIR/$s"
  ln -sfn "$REPO_DIR/$s" "$link"
  echo "linked $link -> $REPO_DIR/$s"
done

case ":$PATH:" in
  *":$DIR:"*) ;;
  *) echo "Warning: $DIR is not in your PATH; add it to your shell profile:" >&2
     echo "  export PATH=\"$DIR:\$PATH\"" >&2 ;;
esac
