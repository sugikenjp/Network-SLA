#!/bin/bash
# SLA管理コンソール 起動スクリプト
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Python仮想環境 (任意)
if [ -d ".venv" ]; then
  source .venv/bin/activate
fi

# 依存パッケージ確認
pip install -r requirements.txt -q

# ログ・設定ディレクトリ作成
mkdir -p config

# 起動
PORT=${PORT:-5000}
echo "==================================="
echo "  SLA管理コンソール"
echo "  http://localhost:${PORT}"
echo "==================================="
python3 app.py
