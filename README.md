# Network-SLA

ネットワーク構成演習・競技イベント等において、チームの機器への疎通状況を  
定期チェックし、スコアを InfluxDB に記録・管理するシステムです。

---

## 概要

各チームの SLA 疎通チェックを **Docker コンテナ**で実行し、  
結果を共通の **InfluxDB サーバー**に記録します。  
コンテナに内蔵された **WEB コンソール**からブラウザで設定・確認を行えます。

| 機能 | 説明 |
|------|------|
| **状態確認** | SLA チェック結果をリアルタイム表示・手動実行 |
| **チーム設定** | このコンテナが担当するチームID・名前を設定 |
| **監視ターゲット** | SLA項目ごとのターゲットIPを編集・追加・削除 |
| **タスク管理** | チャレンジタスクの完了ポイント・不正減点を設定 |
| **スケジュール** | cron 実行間隔・HTTP タイムアウトを設定 |
| **データベース** | InfluxDB 接続設定・Measurement 確認・データ初期化 |
| **ログ確認** | 当日の実行ログを表示 |

---

## システム構成

```
同一ホストで複数チームを運用できます。

      ブラウザ                   ブラウザ
         │ :5000                    │ :5001
         │                          │
  ┌──────▼────────────┐   ┌────────▼──────────┐
  │ network-sla-team01│   │network-sla-team02 │  （必要な数だけ追加）
  │  ┌─────────────┐  │   │  ┌─────────────┐  │
  │  │ Flask 5000  │  │   │  │ Flask 5000  │  │
  │  │（WEBコンソール）│  │   │  │（WEBコンソール）│  │
  │  ├─────────────┤  │   │  ├─────────────┤  │
  │  │ cron        │  │   │  │ cron        │  │
  │  │→ sla.py     │  │   │  │→ sla.py     │  │
  │  │ TEAM=team01 │  │   │  │ TEAM=team02 │  │
  └──┼─────────────┼──┘   └──┼─────────────┼──┘
     │                        │
     └───────────┬────────────┘
                 │ Measurement名でチームを識別
                 ▼
    ┌────────────────────────┐
    │    InfluxDB 1.x        │  （別途独立したサーバー）
    │    bc_db               │
    │    ├── team01          │  ← team01コンテナが書き込む
    │    └── team02          │  ← team02コンテナが書き込む
    └────────────────────────┘
```

### チームの識別方法

InfluxDB では **Measurement 名**（テーブル名相当）でチームを識別します。  
複数コンテナから同一 InfluxDB に同時書き込みしても Measurement が別々なので  
データが混在することはありません。

---

## ファイル構成

```
Network-SLA/
├── Dockerfile            # コンテナビルド定義
├── docker-compose.yml    # コンテナ起動設定
├── sla.py                # SLA疎通チェック＆スコア集計（1チーム専用）
├── param.py              # チーム専用パラメータ（WEBコンソールが自動更新）
├── app.py                # WEBコンソール Flask APIサーバー
├── check-sla.sh          # crontabから呼び出されるシェルラッパー
├── crontab               # コンテナ内の実行スケジュール定義
├── entrypoint.sh         # コンテナ起動スクリプト（cron + Flask 同時起動）
├── requirements.txt      # Pythonパッケージ依存定義
├── start.sh              # Docker不使用時のローカル起動スクリプト
├── INFLUXDB_SETUP.md     # InfluxDB 構築手順書
├── config/               # WEBコンソール設定JSON（コンテナ起動後に自動生成）
├── logs/                 # SLAチェックのログ出力先（コンテナ起動後に自動生成）
└── static/
    └── index.html        # WEBコンソール フロントエンド
```

---

## 動作環境

| 項目 | 要件 |
|------|------|
| OS | Linux（Ubuntu 20.04 以降推奨） |
| Docker | 20.10 以上 |
| Docker Compose | v2（`docker compose` コマンド） |
| InfluxDB | **1.x 系**（別途独立したサーバーで用意） |
| ブラウザ | Chrome / Firefox / Edge |

> **InfluxDB バージョンについて**  
> `pip install influxdb`（バージョン 5.3.x）は **InfluxDB サーバー 1.x 用**のクライアントです。  
> InfluxDB サーバーのバージョンとは別物です。

> **`network_mode: host` について**  
> ping の到達性が必要な場合は `docker-compose.yml` の  
> `network_mode: host` のコメントを外してください。**Linux のみ対応**です。

---

## セットアップ

### 1. リポジトリのクローン

```bash
git clone https://github.com/sugikenjp/Network-SLA.git
cd Network-SLA
```

### 2. param.py の編集

チームの環境に合わせて `param.py` を編集します。

```python
# 最低限変更が必要な箇所

team_name = "team01"           # チーム名（docker-compose.yml の TEAM_NAME と一致させる）

sla01_rt_host = "1.1.1.1"     # SLA01 の ping 対象 IP（実際の機器の IP に変更）
sla02_rt_host = "1.1.2.2"     # SLA02 の ping 対象 IP
sla03_rt_host = "1.1.3.3"     # SLA03 の ping 対象 IP
sla04_rt_host = "1.1.4.4"     # SLA04 の ping 対象 IP
sla05_rt_host = "1.1.5.5"     # SLA05 の ping 対象 IP
sla06_web_vip = "192.168.1.1" # SLA06 の HTTP 確認対象 IP

db_host = "192.168.1.100"     # InfluxDB サーバーの IP アドレス（要変更）
```

### 3. コンテナを起動

```bash
docker compose up -d
```

### 4. WEBコンソールにアクセス

```
http://<ホストのIPアドレス>:5000
```

ブラウザから IP アドレスや設定を変更して保存すると `param.py` が自動更新されます。

---

## 複数チームの運用

```bash
# team02 用にディレクトリをコピー
cp -r Network-SLA network-sla-team02
cd network-sla-team02

# param.py を team02 用に編集
vi param.py
# → team_name = "team02" に変更
# → 各 IP を team02 のものに変更

# docker-compose.yml を編集
vi docker-compose.yml
# → TEAM_NAME=team02 に変更
# → ポートを変更: "5001:5000"

# 起動
docker compose up -d
```

### 同一ホストで動かす場合のポート割り当て例

| チーム | WEBコンソール URL |
|--------|-----------------|
| team01 | http://host:5000 |
| team02 | http://host:5001 |
| team03 | http://host:5002 |

---

## SLA チェックの仕組み

```
crontab（5分ごと）
    │
    ▼
check-sla.sh ${TEAM_NAME}
    │
    ▼
sla.py team01
    │
    ├─ SLA01〜05: ping -c 1 <ターゲットIP>
    │             "ttl=" が含まれれば成功 → 100点
    │
    ├─ SLA06: HTTP GET http://<web_VIP>
    │         "menu" が含まれれば成功 → 100点
    │
    ├─ task01〜09: param.py のスカラー値を取得
    │
    ├─ InfluxDB: 前回累積スコアを取得
    │
    ├─ 今回スコア + 前回累積 → 新しい累積スコア
    │
    ├─ 不正行為減点を適用
    │
    └─ InfluxDB に書き込み（Measurement名 = team01）
       fields: sla01〜06, task01〜09, sum, sum2
```

### スコアの種類

| フィールド | 内容 |
|-----------|------|
| `sla01`〜`sla06` | 各 SLA の今回スコア（成功: 100 / 失敗: 0） |
| `task01`〜`task09` | 各タスクの今回ポイント（`param.py` のスカラー値） |
| `sum` | SLA ポイントの**累積合計** |
| `sum2` | SLA + タスクポイントの**累積合計**（最終スコア） |

---

## param.py の自動更新

WEB コンソールで設定を保存すると `param.py` が自動更新されます。  
`docker-compose.yml` の volume マウントにより  
**ホスト側のファイルも同時に更新**され、次回 cron 実行時に反映されます。

```
WEBコンソールで保存
    │
    ▼
コンテナ内 /app/param.py が更新される
    │ volume マウント（./param.py:/app/param.py）
    ▼
ホスト側 ./param.py が更新される
    │
    ▼
次回 cron 実行時（最大5分後）に新設定が使われる
```

---

## スケジュールの変更

Docker 版では cron の実行間隔を `docker-compose.yml` の  
`CRON_SCHEDULE` 環境変数で管理します。

```yaml
environment:
  - TEAM_NAME=team01
  - CRON_SCHEDULE=*/10 * * * *   # 10分ごとに変更
```

変更後はコンテナを再起動してください：

```bash
docker compose restart
```

---

## Docker を使わない場合（ローカル起動）

```bash
# 仮想環境を作成して起動（Ubuntu 推奨）
python3 -m venv .venv
source .venv/bin/activate
bash start.sh
```

> **Ubuntu では仮想環境を強く推奨します。**  
> Ubuntu 23.04 以降は `pip install` をシステム Python に直接実行するとエラーになります。

WEB コンソールのみが起動します。SLA チェックは別途 crontab で設定してください：

```
*/5 * * * * /path/to/check-sla.sh team01
```

---

## API エンドポイント一覧

| メソッド | パス | 説明 |
|----------|------|------|
| `GET` | `/api/team` | チーム設定取得 |
| `POST` | `/api/team` | チーム設定保存 → param.py 更新 |
| `GET` | `/api/targets` | 監視ターゲット取得 |
| `POST` | `/api/targets` | ターゲット保存 → param.py 更新 |
| `GET` | `/api/tasks` | タスクポイント取得 |
| `POST` | `/api/tasks` | タスクポイント保存 → param.py 更新 |
| `GET` | `/api/schedule` | スケジュール取得 |
| `POST` | `/api/schedule` | スケジュール保存 → param.py 更新 |
| `GET` | `/api/database` | DB 接続設定取得（パスワード除く） |
| `POST` | `/api/database` | DB 接続設定保存 → param.py 更新 |
| `POST` | `/api/database/test` | InfluxDB 接続テスト |
| `GET` | `/api/database/measurements` | Measurement 一覧・行数取得 |
| `DELETE` | `/api/database/reset/{team}` | 指定 Measurement 削除 |
| `DELETE` | `/api/database/reset-all` | DB 全体初期化 |
| `POST` | `/api/run-check` | SLA チェックを即時手動実行 |
| `GET` | `/api/logs` | 当日ログ取得 |
| `GET` | `/api/export/param-py` | 現在設定から param.py をダウンロード |

---

## InfluxDB の構築

InfluxDB 1.x のインストール・設定手順は [INFLUXDB_SETUP.md](./INFLUXDB_SETUP.md) を参照してください。

---

## ライセンス

MIT License  
Copyright (c) 2026 sugikenjp
