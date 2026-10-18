#!/bin/sh
# macOS / Linux convenience launcher. The installed justkernel command works on all hosts.
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$project_dir"
if ! command -v uv >/dev/null 2>&1; then
  printf '%s\n' 'Install uv from https://docs.astral.sh/uv/ and run this launcher again.' >&2
  exit 1
fi
exec uv run --project "$project_dir" python -m aworker.lab.supervisor --open "$@"
