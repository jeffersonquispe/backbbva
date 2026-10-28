#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export PYTHONUNBUFFERED=1
exec python3 "$ROOT/deploy/okd/automation/deploy.py" "$@"
