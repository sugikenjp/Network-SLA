#!/bin/bash
# check-sla.sh - SLA疎通チェック起動スクリプト（Docker版）
# ===========================================================
# 概要:
#   crontab から定期実行されるシェルラッパー。
#   環境変数 TEAM_NAME を引数として sla.py を呼び出し、
#   実行結果をログファイルに記録する。
#
# 注意:
#   cron は通常の環境変数を引き継がないため、
#   entrypoint.sh が書き出した /etc/environment を source して
#   TEAM_NAME と PATH を読み込む。

export LANG=C

# /etc/environment から環境変数を読み込む
# （cron 実行時は PATH 等が引き継がれないため python3 が見つからない問題を解消）
if [ -f /etc/environment ]; then
    set -a
    source /etc/environment
    set +a
fi

if [ -z "${TEAM_NAME}" ]; then
    echo "[ERROR] 環境変数 TEAM_NAME が設定されていません。" >&2
    exit 1
fi

LOG_DIR="/var/log/sla"
mkdir -p "${LOG_DIR}"

DATE=$(date +%F)

# python3 のフルパスを指定（PATH が通っていない場合の保険）
PYTHON=$(which python3 2>/dev/null || echo "/usr/local/bin/python3")

echo "$(date '+%Y-%m-%d %H:%M:%S') [INFO] チェック開始: ${TEAM_NAME}" >> "${LOG_DIR}/sla_${TEAM_NAME}_${DATE}.log"

${PYTHON} /app/sla.py "${TEAM_NAME}" >> "${LOG_DIR}/sla_${TEAM_NAME}_${DATE}.log" 2>&1
