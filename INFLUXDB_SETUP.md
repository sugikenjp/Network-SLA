# InfluxDB 1.x 構築手順書

SLA監視スコアの記録先として使用する InfluxDB 1.x のインストール・設定手順です。

---

## 前提条件

| 項目 | 要件 |
|------|------|
| OS | Ubuntu 20.04 LTS / 22.04 LTS（推奨） |
| 権限 | sudo 実行可能なユーザー |
| ネットワーク | インターネット接続（パッケージ取得時） |
| ポート | 8086/tcp（InfluxDB HTTP API） |

> **バージョンについて**  
> `pip install influxdb`（バージョン 5.3.x）は **InfluxDB サーバー 1.x 用**のクライアントライブラリです。  
> InfluxDB サーバー自体のバージョンとは別物です。本手順では InfluxDB サーバー **1.x 系**をインストールします。

---

## 1. パッケージリポジトリの追加

InfluxDB 1.x は Ubuntu の標準リポジトリには含まれていないため、  
InfluxData 公式リポジトリを手動で追加します。

```bash
# GPG 鍵を取得してシステムに登録する
wget -q https://repos.influxdata.com/influxdata-archive.key

# 鍵のフィンガープリントを確認する（セキュリティ確認）
# 出力に "24C9 75CB A61A 024E E1B6 3178 7C3D 5715 9FC2 F927" が含まれていれば正常
gpg --show-keys --with-fingerprint --with-colons ./influxdata-archive.key 2>&1 \
  | grep -q '^fpr:\+24C975CBA61A024EE1B631787C3D57159FC2F927:$' \
  && echo "鍵の検証: OK" \
  || echo "鍵の検証: 失敗（処理を中断してください）"

# 鍵をシステムのキーリングに登録する
cat influxdata-archive.key \
  | gpg --dearmor \
  | sudo tee /etc/apt/keyrings/influxdata-archive.gpg > /dev/null

# InfluxData リポジトリを apt のソースリストに追加する
# ※ InfluxDB 1.x は "influxdb"（2.x は "influxdb2"）パッケージ名で提供される
echo 'deb [signed-by=/etc/apt/keyrings/influxdata-archive.gpg] https://repos.influxdata.com/debian stable main' \
  | sudo tee /etc/apt/sources.list.d/influxdata.list

# パッケージ情報を更新する
sudo apt-get update
```

---

## 2. InfluxDB 1.x のインストール

```bash
# InfluxDB 1.x をインストールする
# パッケージ名は "influxdb"（"influxdb2" ではない点に注意）
sudo apt-get install -y influxdb

# インストールされたバージョンを確認する
influxd version
# 出力例: InfluxDB 1.x.x (git: ...) build_date: ...
```

---

## 3. サービスの起動と自動起動設定

```bash
# InfluxDB サービスを起動する
sudo systemctl start influxdb

# OS 起動時に自動で InfluxDB が起動するよう設定する
sudo systemctl enable influxdb

# サービスの状態を確認する
sudo systemctl status influxdb
```

正常に起動している場合の出力例：

```
● influxdb.service - InfluxDB is an open-source, distributed, time series database
     Loaded: loaded (/lib/systemd/system/influxdb.service; enabled)
     Active: active (running) since ...
```

---

## 4. 動作確認（認証なし）

```bash
# HTTP API に疎通確認する（200 OK が返れば正常）
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8086/ping
# 出力: 204

# influx CLI でインタラクティブシェルに接続する
influx
```

```sql
-- データベース一覧を表示する（_internal のみ表示されれば正常）
SHOW DATABASES
```

```
> SHOW DATABASES
name: databases
name
----
_internal
```

`quit` で CLI を終了します。

---

## 5. データベースとユーザーの作成

SLA スコアを格納するデータベースと、接続用ユーザーを作成します。

```bash
# influx CLI を起動する
influx
```

CLI 内で以下を実行します：

```sql
-- SLA スコア格納用のデータベースを作成する
-- ※ param.py の db_name に対応する（デフォルト: "bc_db"）
CREATE DATABASE bc_db

-- 管理者ユーザーを作成する（パスワードは任意の文字列に変更すること）
CREATE USER admin WITH PASSWORD 'adminpassword' WITH ALL PRIVILEGES

-- SLA スクリプト用の一般ユーザーを作成する
-- ※ param.py の db_username / db_password に対応する
CREATE USER user WITH PASSWORD 'user'

-- bc_db への読み書き権限を付与する
GRANT ALL ON bc_db TO user

-- ユーザー一覧を確認する
SHOW USERS

-- データベース一覧を確認する
SHOW DATABASES
```

期待される出力：

```
> SHOW USERS
user   admin
----   -----
admin  true
user   false

> SHOW DATABASES
name: databases
name
----
_internal
bc_db
```

`quit` で CLI を終了します。

---

## 6. 認証の有効化

デフォルトでは認証が無効で、誰でも接続できる状態です。  
ユーザーを作成した後、認証を有効化します。

```bash
# InfluxDB 設定ファイルをエディタで開く
sudo nano /etc/influxdb/influxdb.conf
```

`[http]` セクションを探して `auth-enabled` を `true` に変更します：

```ini
[http]
  # ...（他の設定項目）...

  # この行を見つけてコメントを外し、true に変更する
  auth-enabled = true
```

> **検索のヒント:** nano では `Ctrl+W` で検索できます。`auth-enabled` と入力して Enter。

設定を保存して（`Ctrl+X` → `Y` → `Enter`）、InfluxDB を再起動します：

```bash
sudo systemctl restart influxdb

# 再起動後の状態を確認する
sudo systemctl status influxdb
```

---

## 7. 認証有効化後の動作確認

```bash
# 認証なしでアクセスすると失敗することを確認する
curl -s http://localhost:8086/query?q=SHOW+DATABASES
# 出力: {"error":"unable to parse authentication credentials"}

# 認証情報を付けてアクセスできることを確認する
curl -s -G http://localhost:8086/query \
  -u admin:adminpassword \
  --data-urlencode "q=SHOW DATABASES"
# 出力: {"results":[{"statement_id":0,"series":[{"name":"databases",...}]}]}

# CLI で認証付き接続する
influx -username admin -password adminpassword
```

---

## 8. ファイアウォール設定（外部からアクセスする場合）

SLA スクリプト（sla.py）が別サーバーから InfluxDB に接続する場合は、  
ポート 8086 を開放します。

```bash
# UFW（Ubuntu 標準ファイアウォール）を使用している場合
sudo ufw allow 8086/tcp

# 設定を確認する
sudo ufw status
```

> **セキュリティ注意:** ポート 8086 を外部に公開する場合は、必ず認証を有効化してください。  
> 信頼できるIPアドレスのみに制限することも推奨します：
> ```bash
> # 特定のIPからのみ許可する場合の例
> sudo ufw allow from 192.168.1.0/24 to any port 8086
> ```

---

## 9. param.py の接続設定との対応確認

作成したユーザー・データベースが `param.py` の設定と一致していることを確認します。

```python
# param.py の該当箇所
db_host     = "localhost"       # InfluxDB が動作しているホスト
db_port     = "8086"            # InfluxDB のポート番号（デフォルト）
db_username = "user"            # 手順 5 で作成したユーザー名
db_password = "user"            # 手順 5 で設定したパスワード
db_name     = "bc_db"           # 手順 5 で作成したデータベース名
```

別サーバーで動作している場合は `db_host` を InfluxDB サーバーの IP に変更します：

```python
db_host = "192.168.1.100"       # InfluxDB サーバーの IP アドレス
```

---

## 10. Python クライアントからの接続確認

sla.py と同じ環境から接続テストを行います。

```bash
# influxdb パッケージをインストールする（未インストールの場合）
pip install influxdb
```

```python
# 接続テスト用のワンライナー（Python 3）
python3 -c "
from influxdb import InfluxDBClient
client = InfluxDBClient('localhost', 8086, 'user', 'user', 'bc_db')
print('データベース一覧:', client.get_list_database())
print('接続: OK')
"
```

正常な出力例：

```
データベース一覧: [{'name': '_internal'}, {'name': 'bc_db'}]
接続: OK
```

---

## 11. 保持ポリシーの設定（任意）

デフォルトでは InfluxDB はデータを永久保持しますが、  
大会終了後に自動削除したい場合は保持ポリシー（Retention Policy）を設定できます。

```bash
influx -username admin -password adminpassword
```

```sql
-- bc_db に 30 日間の保持ポリシーを設定する例
CREATE RETENTION POLICY "30days" ON "bc_db" DURATION 30d REPLICATION 1 DEFAULT

-- 設定を確認する
SHOW RETENTION POLICIES ON bc_db
```

> **本番利用の注意:** 大会期間中はデータが失われないよう、保持期間を大会終了日より長く設定してください。

---

## 12. データのバックアップと復元

### バックアップ

```bash
# bc_db のデータをバックアップする
sudo influxd backup -database bc_db /tmp/influxdb-backup

# バックアップファイルを確認する
ls -lh /tmp/influxdb-backup/
```

### 復元

```bash
# バックアップからデータを復元する
sudo influxd restore -database bc_db -datadir /var/lib/influxdb/data /tmp/influxdb-backup

# 復元後にサービスを再起動する
sudo systemctl restart influxdb
```

---

## 13. よく使う InfluxQL コマンド

SLA スコアの確認や管理に使用する InfluxQL コマンドの例です。

```bash
# 認証付きで CLI に接続する
influx -username admin -password adminpassword -database bc_db
```

```sql
-- Measurement（テーブル）の一覧を確認する
SHOW MEASUREMENTS

-- team01 の最新 10 件のデータを確認する
SELECT * FROM team01 ORDER BY time DESC LIMIT 10

-- team01 の最新の累積スコアを確認する
SELECT sum, sum2 FROM team01 ORDER BY time DESC LIMIT 1

-- 全チームの最新スコアを比較する（各チームごとに実行）
SELECT last(sum2) FROM team01
SELECT last(sum2) FROM team02

-- team01 のデータをすべて削除する（初期化）
DROP MEASUREMENT team01

-- データベース全体を削除して再作成する（完全初期化）
DROP DATABASE bc_db
CREATE DATABASE bc_db
GRANT ALL ON bc_db TO user
```

---

## 14. トラブルシューティング

### InfluxDB が起動しない

```bash
# エラーログを確認する
sudo journalctl -u influxdb -n 50

# 設定ファイルの構文を確認する
influxd config
```

### 接続できない（Connection refused）

```bash
# InfluxDB が起動しているか確認する
sudo systemctl status influxdb

# ポート 8086 がリッスンしているか確認する
ss -tlnp | grep 8086
```

### 認証エラー（unable to parse authentication credentials）

```bash
# 認証なしで CLI に接続してユーザーを確認する（auth-enabled = false の場合）
influx
```
```sql
SHOW USERS
```

### ディスク容量の確認

```bash
# InfluxDB のデータディレクトリのサイズを確認する
du -sh /var/lib/influxdb/
```

---

## 設定ファイルリファレンス

InfluxDB の主要な設定ファイルの場所：

| ファイル | 用途 |
|----------|------|
| `/etc/influxdb/influxdb.conf` | メイン設定ファイル |
| `/var/lib/influxdb/data/` | TSM データ（実データ） |
| `/var/lib/influxdb/wal/` | WAL（Write-Ahead Log） |
| `/var/lib/influxdb/meta/` | メタデータ |
| `/var/log/influxdb/influxd.log` | ログファイル（設定による） |

---

## まとめ：構築後の確認チェックリスト

- [ ] `sudo systemctl status influxdb` → `active (running)` になっている
- [ ] `curl http://localhost:8086/ping` → HTTP 204 が返る
- [ ] `influx -username admin -password adminpassword` → CLI でログインできる
- [ ] `SHOW DATABASES` → `bc_db` が表示される
- [ ] `SHOW USERS` → `user` が表示される
- [ ] Python からの接続テスト → `接続: OK` が出力される
- [ ] `param.py` の `db_host` / `db_name` / `db_username` / `db_password` が一致している
- [ ] （外部接続の場合）ポート 8086 が開放されている
