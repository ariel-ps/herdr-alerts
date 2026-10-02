#!/bin/sh
# Regenerate the committed alert lookup table without making installation fail
# when only the existing generated copy can be used.
set -u

build_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
generator="$build_dir/gen-alert-tables.py"

if command -v uv >/dev/null 2>&1; then
    uv run --no-project python "$generator" || {
        echo 'alerts: kept the committed table' >&2
        exit 0
    }
else
    python3 "$generator" || {
        echo 'alerts: kept the committed table' >&2
        exit 0
    }
fi
