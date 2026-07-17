#!/bin/bash
# Symlinks scripts/pre-commit into .git/hooks/ -- git only runs hooks from
# .git/hooks/, which isn't tracked, so this is a one-time step per clone.
# A raw script (not the `pre-commit` pip framework) since the check itself
# is two commands (ruff + unittest); a framework would be a new dependency
# for no real gain here.
set -euo pipefail
cd "$(dirname "$0")/.."

ln -sf ../../scripts/pre-commit .git/hooks/pre-commit
chmod +x scripts/pre-commit scripts/lint.sh scripts/test.sh
echo "installed: .git/hooks/pre-commit -> scripts/pre-commit"
