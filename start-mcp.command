#!/bin/sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
exec "$project_dir/.venv/bin/python" "$project_dir/scripts/launch.py"
