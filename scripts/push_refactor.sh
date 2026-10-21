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
# GitHub connectivity is intermittent on this network. By default the script
# tries normal DNS and then several known GitHub edge IPs with a short connect
# timeout. Set GITHUB_RESOLVE_IP to force one address; set it to an empty
# string to use normal DNS only.
set -euo pipefail

remote="${REMOTE:-origin}"
target="${1:-HEAD:refactor}"

if ! command -v gh >/dev/null 2>&1; then
  echo "gh is required for authenticated pushes" >&2
  exit 1
fi

if [[ -n "${GITHUB_RESOLVE_IP+x}" ]]; then
  candidates=("$GITHUB_RESOLVE_IP")
else
  candidates=("" "140.82.112.3" "140.82.113.3" "20.27.177.113")
fi

restore() {
  gh auth switch --user secserg >/dev/null 2>&1 || true
}
trap restore EXIT

gh auth switch --user gresces >/dev/null

push_once() {
  local ip="$1"
  local args=(-c "http.connectTimeout=15")
  if [[ -n "$ip" ]]; then
    args+=(-c "http.curloptResolve=github.com:443:${ip}")
  fi
  echo "push attempt: ${ip:-dns}" >&2
  GIT_TERMINAL_PROMPT=0 git "${args[@]}" push -u "$remote" "$target"
}

for ip in "${candidates[@]}"; do
  if push_once "$ip"; then
    echo "remote tip:"
    GIT_TERMINAL_PROMPT=0 git -c "http.connectTimeout=15" \
      ${ip:+-c "http.curloptResolve=github.com:443:${ip}"} \
      ls-remote "$remote" refs/heads/refactor
    exit 0
  fi
  echo "push attempt failed: ${ip:-dns}" >&2
done

echo "push failed after all resolver attempts" >&2
exit 1
