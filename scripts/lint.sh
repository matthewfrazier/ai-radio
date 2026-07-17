#!/bin/bash
# Lints the ai-radio overlay only -- not upstream mac/, which is foreign
# code pulled in via `git fetch upstream` and not ours to gatekeep on style.
set -euo pipefail
cd "$(dirname "$0")/.."

OVERLAY_PY=(
  panel.py blocks_page.py block_render.py block_player.py
  jellyfin_client.py jf_source.py live_source.py
  tts_content.py tts_engines.py llm_backends.py
)

RUFF=.venv/bin/ruff
[ -x "$RUFF" ] || RUFF=ruff

"$RUFF" check "${OVERLAY_PY[@]}"
