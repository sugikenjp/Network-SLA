#!/bin/bash
# start.sh - WEBコンソール起動スクリプト（Docker不使用時）
# ==========================================================
# Docker を使わずローカルで WEBコンソールのみ起動する場合に使用する。
# SLA チェック（sla.py の定期実行）は別途 crontab で設定すること。

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Python 仮想環境（存在する場合は自動で有効化）
if [ -d ".venv" ]; then
  source .venv/bin/activate
fi

# 依存パッケージの確認・インストール
pip install -r requirements.txt -q

# 必要なディレクトリを作成
mkdir -p config static log

# 起動
PORT=${PORT:-5000}
echo "==================================="
echo "  SLA管理コンソール"
echo "  http://localhost:${PORT}"
echo "==================================="
python3 app.py
