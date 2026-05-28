# Dockerfile - SLA監視システム（SLAチェック + WEBコンソール一体型）
# ===================================================================
# 概要:
#   SLA疎通チェック（cron）と WEB管理コンソール（Flask）を
#   1つのコンテナにまとめた構成。
#
# ビルド方法:
#   docker build -t network-sla .
#
# 起動方法:
#   docker-compose up -d

FROM python:3.11-slim

WORKDIR /app

# システムパッケージのインストール
# cron      : 定期実行スケジューラ
# iputils-ping : ping コマンド（SLA01〜05 の疎通確認に使用）
# procps    : ps コマンド等（デバッグ用）
RUN apt-get update && apt-get install -y \
    cron \
    iputils-ping \
    procps \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Python パッケージのインストール
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションファイルのコピー
COPY sla.py          /app/sla.py
COPY param.py        /app/param.py
COPY app.py          /app/app.py
COPY check-sla.sh    /app/check-sla.sh
COPY entrypoint.sh   /app/entrypoint.sh
COPY static/         /app/static/

# crontab の配置
COPY crontab /etc/cron.d/sla-check

# 実行権限の付与
RUN chmod +x /app/check-sla.sh /app/entrypoint.sh \
    && chmod 0644 /etc/cron.d/sla-check

# ログ・設定ディレクトリの作成
RUN mkdir -p /var/log/sla /app/config

# WEBコンソールのポートを公開
EXPOSE 5000

# 起動スクリプト（cron + Flask を同時起動）
ENTRYPOINT ["/app/entrypoint.sh"]
