#!/bin/bash
# Syntax-checks the panel's Python modules, then restarts writ-panel.service
# and confirms it came back up. Used after editing panel.py/blocks_page.py/
# block_render.py/etc. during ai-radio programming-blocks development.
set -euo pipefail
cd /opt/writ-fm

for f in panel.py blocks_page.py block_render.py block_player.py jellyfin_client.py live_source.py tts_content.py tts_engines.py llm_backends.py jf_source.py; do
  python3 -c "import ast; ast.parse(open('$f').read())"
done

systemctl restart writ-panel.service
sleep 1
systemctl is-active writ-panel.service
