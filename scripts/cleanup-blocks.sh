#!/bin/bash
# Removes old, unreferenced programming-block render artifacts. Invoked by
# the writ-block-cleanup.timer; safe to run by hand.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -c "import json, block_render; print('removed:', json.dumps(block_render.cleanup_blocks()))"
