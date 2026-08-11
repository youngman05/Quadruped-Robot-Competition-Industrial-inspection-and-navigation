#!/usr/bin/env bash
# Start the complete four-observation inspection without command-line options.

set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec bash "$SCRIPT_DIR/run_inspection_navigation.sh" --full --confirm-motion
