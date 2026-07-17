#!/bin/bash
# Runs the ai-radio overlay's integration tests only -- not the upstream
# mac/ suite, which needs its full ML dependency stack (torch, transformers,
# etc.) installed to even import.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m unittest tests.test_ai_radio_blocks -v
