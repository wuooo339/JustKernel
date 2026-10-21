#!/usr/bin/env bash
# Push the current Refactor worktree branch to origin/refactor.
#
# This machine has two GitHub CLI accounts:
#   - secserg: active default, read-only on wuooo339/JustKernel
#   - gresces: write access to wuooo339/JustKernel
#
# The script temporarily switches to gresces, pushes, and always restores
# secserg. It never prints a token.
#
# Some networks resolve github.com to an unreachable address while the API
# and alternate GitHub edge IPs work. Set GITHUB_RESOLVE_IP to override the
# fallback, or set it to an empty string to use normal DNS.
set -euo pipefail

remote="${REMOTE:-origin}"
target="${1:-HEAD:refactor}"
resolve_ip="${GITHUB_RESOLVE_IP-140.82.112.3}"

if ! command -v gh >/dev/null 2>&1; then
  echo "gh is required for authenticated pushes" >&2
  exit 1
fi

git_args=()
if [[ -n "$resolve_ip" ]]; then
  git_args=(-c "http.curloptResolve=github.com:443:${resolve_ip}")
fi

restore() {
  gh auth switch --user secserg >/dev/null 2>&1 || true
}
trap restore EXIT

gh auth switch --user gresces >/dev/null
GIT_TERMINAL_PROMPT=0 git "${git_args[@]}" push -u "$remote" "$target"
echo "remote tip:"
GIT_TERMINAL_PROMPT=0 git "${git_args[@]}" ls-remote "$remote" refs/heads/refactor
