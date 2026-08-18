#!/bin/bash
# 每日中央自動化的單一入口。真正的模組決策在 run_automation.py。

set -uo pipefail

PROJECT="/Users/jirlong/Library/CloudStorage/Dropbox/Programming/news2048"
PYTHON="/usr/bin/python3"

cd "$PROJECT" || exit 1
exec "$PYTHON" tools/run_automation.py
