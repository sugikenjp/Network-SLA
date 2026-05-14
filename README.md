[README.md](https://github.com/user-attachments/files/27764495/README.md)
# SLA監視管理コンソール

SLA疎通チェックスクリプト（`sla.py` / `check-sla.sh`）の設定・実行・スコア管理を  
**ブラウザから一元管理**するWebコンソールです。

---

## 概要

ネットワーク構成演習・競技イベント等において、各チームの機器への疎通状況を  
定期チェックし、スコアを InfluxDB に記録するシステムです。

従来は `param.py` を直接編集してIPアドレスやスケジュールを管理していましたが、  
本ツールを使うことでブラウザから以下をすべて操作できます。

| 機能 | 説明 |
|------|------|
| **状態確認** | 全チームの SLA チェック結果をリアルタイム表示 |
| **チーム管理** | チームの追加・削除・有効/無効の切り替え |
| **監視ターゲット** | SLA項目ごとのターゲットIPを編集・追加・削除 |
| **スケジュール** | crontab の実行間隔を設定・即時適用 |
| **データベース** | InfluxDB 接続設定・Measurement 確認・データ初期化 |
| **ログ確認** | 当日の実行ログをチーム別に表示 |

設定を保存すると **`param.py` が自動生成・上書き**され、`crontab` も自動更新されます。

---

## システム構成

```
                  ブラウザ
                     │
              HTTP (port 5000)
                     │
            ┌────────▼────────┐
            │    app.py       │  Flask APIサーバー
            │  (REST API +    │  ・設定の読み書き
            │   静的配信)      │  ・param.py 自動生成
            └────┬───────┬────┘  ・crontab 更新
                 │       │
         ┌───────┘       └───────────┐
         │                           │
  ┌──────▼──────┐            ┌───────▼───────┐
  │  config/    │            │  /home/user/  │
  │  *.json     │            │  param.py     │
  │  (設定永続化)│            │  (本番スクリプト)│
  └─────────────┘            └───────────────┘
                                      │
                              crontab が定期実行
                                      │
                            ┌─────────▼─────────┐
                            │  check-sla.sh     │
                            │  → sla.py         │
                            │  (疎通チェック)    │
                            └─────────┬─────────┘
                                      │
                            ┌─────────▼─────────┐
                            │    InfluxDB 1.x    │
                            │  (スコア記録)       │
                            └───────────────────┘
```

---

## ファイル構成

```
sla-console/
├── app.py              # Flask REST APIサーバー（メイン）
├── sla.py              # SLA疎通チェック＆スコア集計スクリプト
├── param.py            # ターゲットIP・DB設定・スコア定義（自動生成対象）
├── check-sla.sh        # crontabから呼び出されるシェルラッパー
├── requirements.txt    # Pythonパッケージ依存定義
├── start.sh            # 起動スクリプト
├── config/             # 設定ファイル保存先（初回起動時に自動生成）
│   ├── teams.json      # チーム設定
│   ├── targets.json    # 監視ターゲットIP設定
│   ├── schedule.json   # crontabスケジュール設定
│   ├── database.json   # InfluxDB接続設定
│   └── param.py        # 自動生成したparam.py（本番パスがない場合）
└── static/
    └── index.html      # フロントエンド（SPA）
```

---

## 動作環境

| 項目 | 要件 |
|------|------|
| OS | Linux（Ubuntu 20.04 以降推奨） |
| Python | 3.7 以上 |
| InfluxDB | **1.x 系**（2.x / 3.x は非対応） |
| ブラウザ | Chrome / Firefox / Edge（モダンブラウザ） |

> **注意:** Python パッケージ `influxdb`（バージョン 5.3.x）は  
> **InfluxDB サーバー 1.x 用のクライアントライブラリ**です。  
> InfluxDB サーバーのバージョンとは別物です。

---

## セットアップ

### 1. リポジトリのクローン

```bash
git clone https://github.com/<your-username>/sla-console.git
cd sla-console
```

### 2. 依存パッケージのインストール

```bash
pip install -r requirements.txt
```

仮想環境を使う場合：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. 起動

```bash
# 起動スクリプトを使う場合（推奨）
bash start.sh

# または直接起動
python3 app.py

# ポートを変更する場合
PORT=8080 python3 app.py
```

### 4. ブラウザでアクセス

```
http://localhost:5000
```

---

## 設定ファイルについて

### config/*.json

初回起動時に `config/` ディレクトリが自動作成されます。  
各 JSON ファイルを直接編集することもできますが、  
通常は **Web コンソールから操作する**ことを推奨します。

| ファイル | 内容 |
|----------|------|
| `teams.json` | チームID・表示名・有効/無効フラグ |
| `targets.json` | SLA項目ごとのターゲットIPリスト |
| `schedule.json` | crontab式・HTTPタイムアウト・スクリプトパス |
| `database.json` | InfluxDB接続情報（パスワードも含む） |

### param.py の自動生成

Web コンソールで設定を保存すると、`param.py` が自動的に生成・上書きされます。

| 条件 | 書き出し先 |
|------|-----------|
| `/home/user/param.py` の親ディレクトリが存在する | `/home/user/param.py`（上書き・`.bak` でバックアップ） |
| 存在しない | `config/param.py`（コンソールの「param.py」ボタンでダウンロード） |

### crontab の自動更新

スケジュール設定を保存すると、`# SLA-MANAGED` タグ付きの  
crontab エントリが自動で更新されます。

```
# 生成されるエントリの例（5分ごと・全チーム）
*/5 * * * * /home/user/check-sla.sh team01  # SLA-MANAGED
*/5 * * * * /home/user/check-sla.sh team02  # SLA-MANAGED
...
```

手動で追加した他の crontab エントリは **保持されます**。  
（`# SLA-MANAGED` タグのある行だけが差し替えられます）

---

## SLA チェックの仕組み

### sla.py の処理フロー

```
python3 sla.py team01
        │
        ├─ SLA01〜05: ping -c 1 <ターゲットIP>
        │             出力に "ttl=" が含まれれば成功 → スコア加算
        │
        ├─ SLA06: HTTP GET http://<web_VIP>
        │         レスポンスに "menu" が含まれれば成功 → スコア加算
        │
        ├─ task01〜09: param.py の設定値をそのまま取得
        │
        ├─ InfluxDB: 前回累積スコアを取得
        │
        ├─ 今回スコア + 前回累積 → 新しい累積スコア
        │
        ├─ 不正行為減点を適用（param.fusei）
        │
        └─ InfluxDB に書き込み
           fields: sla01〜06, task01〜09, sum（SLA累積）, sum2（総合累積）
```

### スコアの種類

| フィールド | 内容 |
|-----------|------|
| `sla01`〜`sla06` | 各 SLA の今回スコア（成功: 100 / 失敗: 0） |
| `task01`〜`task09` | 各タスクの今回ポイント（`param.py` の設定値） |
| `sum` | SLA ポイントの**累積合計** |
| `sum2` | SLA + タスクポイントの**累積合計**（最終スコア）|

### チーム番号の仕組み

```python
team_name = "team01"
team_num  = int(team_name[5])  # → 1
# param.sla01_rt_host[team_num - 1] でそのチームのIPを取得
```

チーム名の6文字目（インデックス5）の数字をチーム番号として使用します。  
`param.py` の各リストは `[team01用IP, team02用IP, ..., team09用IP]` の順に並んでいます。

---

## API エンドポイント一覧

| メソッド | パス | 説明 |
|----------|------|------|
| `GET` | `/api/teams` | チーム一覧取得 |
| `POST` | `/api/teams` | チーム設定保存 → param.py 更新 |
| `GET` | `/api/targets` | 監視ターゲット取得 |
| `POST` | `/api/targets` | ターゲット保存 → param.py 更新 |
| `GET` | `/api/schedule` | スケジュール取得 |
| `POST` | `/api/schedule` | スケジュール保存 → crontab 更新 → param.py 更新 |
| `GET` | `/api/database` | DB 接続設定取得（パスワード除く） |
| `POST` | `/api/database` | DB 接続設定保存 → param.py 更新 |
| `POST` | `/api/database/test` | InfluxDB 接続テスト |
| `GET` | `/api/database/measurements` | Measurement 一覧・行数取得 |
| `DELETE` | `/api/database/reset/{team}` | 指定チームの Measurement 削除 |
| `DELETE` | `/api/database/reset-all` | DB 全体初期化（drop → create） |
| `POST` | `/api/run-check` | SLA チェックを即時手動実行 |
| `GET` | `/api/logs` | 当日ログ取得（`?team=team01` で絞り込み） |
| `GET` | `/api/export/param-py` | 現在設定から param.py をダウンロード |

---

## 本番環境へのデプロイ

### gunicorn を使う場合（推奨）

```bash
pip install gunicorn
gunicorn -w 2 -b 0.0.0.0:5000 app:app
```

### systemd サービス化

`/etc/systemd/system/sla-console.service` を作成：

```ini
[Unit]
Description=SLA Console
After=network.target

[Service]
WorkingDirectory=/home/user/sla-console
ExecStart=/usr/bin/python3 app.py
Restart=always
User=user
Environment=PORT=5000

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable sla-console
sudo systemctl start sla-console
```

---

## .gitignore の推奨設定

機密情報（DBパスワード等）や自動生成ファイルを除外するため、  
以下の `.gitignore` を用意することを推奨します。

```gitignore
# 設定ファイル（DBパスワードを含むため除外）
config/

# param.py は自動生成されるため除外
param.py

# Python
__pycache__/
*.py[cod]
.venv/

# ログ
*.log
```

> **注意:** `config/database.json` には InfluxDB のパスワードが平文で保存されます。  
> `config/` ディレクトリは必ず `.gitignore` に追加してください。

---

## ライセンス

MIT License
