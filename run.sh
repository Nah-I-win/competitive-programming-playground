#!/usr/bin/env bash
# Launch the Competitive Programming Playground.
set -euo pipefail
cd "$(dirname "$0")"
exec python3 -m app.main "$@"