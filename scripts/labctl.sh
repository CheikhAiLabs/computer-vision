#!/usr/bin/env bash
set -euo pipefail
# Multi-camera scenarios are defined once in labctl.py (including stalled-product).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$ROOT/scripts/labctl.py" "$@"
