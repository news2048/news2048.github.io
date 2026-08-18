#!/bin/bash
# 每週一自動打撈 NIDSS 疫情數字的進入點，供 launchd 呼叫。
#
# 為什麼需要這層包裝，而不是讓 launchd 直接跑 python：
#   1. launchd 不會繼承你的 shell 環境，也沒有工作目錄的概念
#   2. 專案路徑含空白（CloudStorage/Dropbox），需要正確引號
#   3. 用系統內建 /usr/bin/python3（腳本只用標準庫），
#      不受 conda / homebrew 環境變動影響
#   4. 統一把輸出附加到 log，失敗時才有東西可查
#
# 手動測試：bash tools/nidss_weekly.sh

set -uo pipefail

PROJECT="/Users/jirlong/Library/CloudStorage/Dropbox/Programming/news2048"
PYTHON="/usr/bin/python3"
LOG="$HOME/Library/Logs/news2048-nidss.log"

mkdir -p "$(dirname "$LOG")"

{
  echo "===== $(date '+%Y-%m-%d %H:%M:%S %Z') 開始 ====="
  cd "$PROJECT" || { echo "✗ 找不到專案目錄：$PROJECT"; exit 1; }
  "$PYTHON" tools/fetch_nidss.py
  code=$?
  if [ $code -eq 0 ]; then
    echo "===== 完成 ====="
  else
    echo "===== 失敗（exit $code）：NIDSS 版面可能改版，需人工檢查 ====="
  fi
  exit $code
} >>"$LOG" 2>&1
