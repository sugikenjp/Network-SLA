# SLA監視管理コンソール

SLA疎通監視スクリプト (sla.py / param.py) をWebブラウザから管理するツールです。

## ファイル構成

```
sla-console/
├── app.py              # Flask APIサーバー (メイン)
├── requirements.txt    # 依存パッケージ
├── start.sh            # 起動スクリプト
├── config/             # 設定ファイル保存先 (自動生成)
│   ├── teams.json
│   ├── targets.json
│   ├── schedule.json
│   ├── database.json
│   └── param.py        # 自動生成されたparam.py (本番パスがない場合)
└── static/
    └── index.html      # フロントエンド
```

## セットアップ

```bash
# 1. 依存パッケージをインストール
pip install -r requirements.txt

# 2. 起動 (デフォルト: ポート5000)
bash start.sh

# または直接
python3 app.py

# ポートを変更する場合
PORT=8080 python3 app.py
```

## アクセス

ブラウザで `http://localhost:5000` を開く。

## APIエンドポイント一覧

| メソッド | パス | 説明 |
|----------|------|------|
| GET  | /api/teams | チーム一覧取得 |
| POST | /api/teams | チーム設定保存 |
| GET  | /api/targets | ターゲットIP一覧取得 |
| POST | /api/targets | ターゲット保存 + param.py自動更新 |
| GET  | /api/schedule | スケジュール取得 |
| POST | /api/schedule | スケジュール保存 + crontab更新 |
| GET  | /api/database | DB接続設定取得 |
| POST | /api/database | DB接続設定保存 |
| POST | /api/database/test | InfluxDB接続テスト |
| GET  | /api/database/measurements | Measurement一覧取得 |
| DELETE | /api/database/reset/{team} | チームデータ削除 |
| DELETE | /api/database/reset-all | 全データ削除 |
| POST | /api/run-check | SLAチェック手動実行 |
| GET  | /api/logs | ログ取得 (?team=team01) |
| GET  | /api/export/param-py | param.py をダウンロード |

## param.py の自動更新

ターゲットIPやDB設定を保存すると、以下のパスに param.py が自動生成されます。

- `/home/user/param.py` が存在する場合 → そちらに上書き（.bak でバックアップ）
- 存在しない場合 → `config/param.py` に保存（「param.py」ボタンでダウンロード可）

## crontab の自動更新

スケジュール設定を保存すると、`# SLA-MANAGED` タグ付きのエントリが crontab に追記されます。
既存の SLA-MANAGED エントリは置き換えられます（手動エントリは保持されます）。

## 設定ファイル

`config/` フォルダ内の JSON ファイルを直接編集することもできます。

## 本番環境でのデプロイ

```bash
# gunicorn を使う場合
pip install gunicorn
gunicorn -w 2 -b 0.0.0.0:5000 app:app

# systemd サービス化 (/etc/systemd/system/sla-console.service)
# [Unit]
# Description=SLA Console
# After=network.target
# [Service]
# WorkingDirectory=/home/user/sla-console
# ExecStart=/usr/bin/python3 app.py
# Restart=always
# User=user
# [Install]
# WantedBy=multi-user.target
```
