#!/bin/sh
# Run claude-pxl (https://github.com/crsolver/claude-pxl), cloned once into ~/.cache at a pinned commit.
set -e
PXL_HOME="${PXL_HOME:-$HOME/.cache/claude-pxl}"
PXL_REV="21fee41"
if [ ! -f "$PXL_HOME/bin/pxl.js" ]; then
  git clone -q https://github.com/crsolver/claude-pxl "$PXL_HOME"
  git -C "$PXL_HOME" checkout -q "$PXL_REV" 2>/dev/null || true
fi
exec node "$PXL_HOME/bin/pxl.js" "$@"
