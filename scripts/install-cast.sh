#!/bin/bash
# Sets up the isolated venv that cast_ctl.py runs in (pychromecast is a heavy
# non-stdlib dep, kept out of the stdlib-only panel process -- panel shells out
# to cast_ctl.py in this venv, same pattern as jf_source.py). One-time per box.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv-cast
.venv-cast/bin/pip install --quiet --upgrade pip
.venv-cast/bin/pip install --quiet pychromecast
echo "cast venv ready: $(.venv-cast/bin/python -c 'import pychromecast; print("pychromecast", __import__("importlib.metadata", fromlist=["version"]).version("pychromecast"))')"
