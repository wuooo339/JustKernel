#!/usr/bin/env bash
# Push the current Refactor worktree branch to origin/refactor.
#
# This machine has two GitHub CLI accounts:
#   - secserg: active default, read-only on wuooo339/JustKernel
#   - gresces: write access to wuooo339/JustKernel
#
# The script temporarily switches to gresces, pushes, and always restores
# secserg. It never prints a token.
set -euo pipefail

remote="${REMOTE:-origin}"
target="${1:-HEAD:refactor}"

if ! command -v gh >/dev/null 2>&1; then
  echo "gh is required for authenticated pushes" >&2
  exit 1
fi

restore() {
  gh auth switch --user secserg >/dev/null 2>&1 || true
}
trap restore EXIT

gh auth switch --user gresces >/dev/null
GIT_TERMINAL_PROMPT=0 git push -u "$remote" "$target"
echo "remote tip:"
GIT_TERMINAL_PROMPT=0 git ls-remote "$remote" refs/heads/refactor
