#!/bin/bash
# check-sla.sh - SLA疎通チェック起動スクリプト（Docker版）
# ===========================================================
# 概要:
#   crontab から定期実行されるシェルラッパー。
#   環境変数 TEAM_NAME を引数として sla.py を呼び出し、
#   実行結果をログファイルに記録する。
#
# 環境変数:
#   TEAM_NAME : docker-compose.yml の environment で設定するチーム名
#
# ログファイル:
#   /var/log/sla/sla_<TEAM_NAME>_<YYYY-MM-DD>.log

export LANG=C

if [ -z "${TEAM_NAME}" ]; then
    echo "[ERROR] 環境変数 TEAM_NAME が設定されていません。" >&2
    exit 1
fi

LOG_DIR="/var/log/sla"
mkdir -p "${LOG_DIR}"

DATE=$(date +%F)

python3 /app/sla.py "${TEAM_NAME}" >> "${LOG_DIR}/sla_${TEAM_NAME}_${DATE}.log" 2>&1
