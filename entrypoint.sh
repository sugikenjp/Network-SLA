#!/bin/bash
# entrypoint.sh - コンテナ起動スクリプト
# ==========================================
# 処理フロー:
#   1. 必須環境変数 TEAM_NAME の確認
#   2. CRON_SCHEDULE が設定されていれば crontab の間隔を上書き
#   3. 環境変数を /etc/environment に書き出して cron に引き継ぐ
#   4. cron デーモンをバックグラウンドで起動
#   5. Flask（WEBコンソール）をフォアグラウンドで起動

set -e

if [ -z "${TEAM_NAME}" ]; then
    echo "[ERROR] 環境変数 TEAM_NAME が設定されていません。"
    echo "[ERROR] docker-compose.yml の environment を確認してください。"
    exit 1
fi

echo "[INFO] チーム: ${TEAM_NAME} のコンテナを起動します"

# cron 実行間隔の上書き（CRON_SCHEDULE が設定されている場合）
if [ -n "${CRON_SCHEDULE}" ]; then
    echo "[INFO] cron スケジュールを '${CRON_SCHEDULE}' に変更します"
    sed -i "s|^\*/5 \* \* \* \*|${CRON_SCHEDULE}|" /etc/cron.d/sla-check
fi

# 環境変数を cron に引き継ぐ（cron は通常の環境変数を引き継がないため）
printenv | grep -v "no_proxy" > /etc/environment
echo "[INFO] 環境変数を /etc/environment に書き出しました"

# ログ・設定ディレクトリの作成
mkdir -p /var/log/sla /app/config

# cron をバックグラウンドで起動
echo "[INFO] cron を起動します（チーム: ${TEAM_NAME}）"
cron

# Flask（WEBコンソール）をフォアグラウンドで起動
# フォアグラウンドで動かすことでコンテナが生存し続ける
echo "[INFO] WEBコンソールを起動します（port: ${PORT:-5000}）"
exec python3 /app/app.py
