#!/usr/bin/env python
"""
sla.py - SLA疎通チェック & スコア集計スクリプト（1チーム専用 Docker版）
=======================================================================
概要:
    このコンテナが担当する1チームを対象に SLA01〜06 の疎通確認を実施し、
    結果スコアを外部の InfluxDB サーバーに記録する。
    crontab から check-sla.sh 経由で定期実行される。

実行方法:
    python3 sla.py <チーム名>
    例: python3 sla.py team01

    ※ チーム名は check-sla.sh から環境変数 TEAM_NAME として渡される。
       param.py に記載した team_name と一致していること。

マルチチーム版からの変更点:
    - param.py の各 IP はリストではなく単一の文字列値
      （例: sla01_rt_host = "1.1.1.1"）
    - team_num によるインデックス計算を廃止
      （IP を直接 param.sla01_rt_host として参照する）
    - task / fusei はスカラー値（例: task01 = 0）
    - 起動時に param.team_name と引数の一致チェックを実施
    - ping 出力のデコードを cp932 → utf-8 に変更（Linux コンテナ対応）

Docker での使われ方:
    各チーム用に独立したコンテナを起動する。
    チーム名は docker-compose.yml の environment で TEAM_NAME として渡され、
    check-sla.sh が python3 /app/sla.py ${TEAM_NAME} として呼び出す。

依存:
    - param.py    : このチーム専用のパラメータ定義ファイル
    - influxdb    : InfluxDB 1.x 用クライアント（pip install influxdb）
    - requests    : HTTP チェック用（pip install requests）
"""

import subprocess           # ping コマンドの実行に使用
from influxdb import InfluxDBClient  # InfluxDB 1.x への接続・読み書き
import sys                  # コマンドライン引数 (sys.argv) の取得
import param                # このチーム専用のパラメータ定義ファイル
import requests             # SLA06 の HTTP 疎通確認に使用


# ─────────────────────────── 初期設定 ───────────────────────────

# コマンドライン引数からチーム名を取得する。
# check-sla.sh から "python3 /app/sla.py team01" のように呼び出される。
team_name = sys.argv[1]

# param.py に定義されたチーム名と引数が一致しているか確認する。
# 不一致の場合はエラーを出力して終了する（設定ミスの早期検出）。
if team_name != param.team_name:
    print(f"ERROR: 引数のチーム名 '{team_name}' と "
          f"param.py の team_name '{param.team_name}' が一致しません。")
    print("docker-compose.yml の TEAM_NAME と param.py の team_name を確認してください。")
    sys.exit(1)

# 処理対象の SLA 項目 ID リスト
sla_list = ["sla01", "sla02", "sla03", "sla04", "sla05", "sla06"]

# 処理対象のタスク項目 ID リスト
task_list = [
    "task01", "task02", "task03", "task04", "task05",
    "task06", "task07", "task08", "task09",
]

# SLA チェック結果を格納する辞書
# キー: sla_list の要素、値: 成功 → param.slaXX_score / 失敗 → 0
sla_result = {}

# タスクポイントを格納する辞書
# キー: task_list の要素、値: param.taskXX のスカラー値
task_result = {}


# ─────────────────────────── SLA01〜05: ping 疎通確認 ───────────────────────────
#
# 判定方法:
#   ping コマンドの標準出力に "ttl=" が含まれていれば疎通成功とみなす。
#   Linux コンテナのため utf-8 でデコードし、大文字小文字を統一して判定する。
#   成功: sla_result["slaXX"] = param.slaXX_score（通常 100 点）
#   失敗: sla_result["slaXX"] = 0
#
# ping オプション:
#   -c 1 : 1回だけ送信して終了（定期チェックで無駄に待たないようにする）
#
# ターゲット IP:
#   マルチチーム版ではリストだったが、1チーム専用のためスカラー値を直接参照する。

# ── SLA01 ──
commands = ["ping", "-c", "1", param.sla01_rt_host]
ping = subprocess.run(commands, stdout=subprocess.PIPE)
result_sla01 = ping.stdout.decode("utf-8")
if "ttl=" in result_sla01.lower():
    sla_result[sla_list[0]] = param.sla01_score
else:
    sla_result[sla_list[0]] = 0

# ── SLA02 ──
commands = ["ping", "-c", "1", param.sla02_rt_host]
ping = subprocess.run(commands, stdout=subprocess.PIPE)
result_sla02 = ping.stdout.decode("utf-8")
if "ttl=" in result_sla02.lower():
    sla_result[sla_list[1]] = param.sla02_score
else:
    sla_result[sla_list[1]] = 0

# ── SLA03 ──
commands = ["ping", "-c", "1", param.sla03_rt_host]
ping = subprocess.run(commands, stdout=subprocess.PIPE)
result_sla03 = ping.stdout.decode("utf-8")
if "ttl=" in result_sla03.lower():
    sla_result[sla_list[2]] = param.sla03_score
else:
    sla_result[sla_list[2]] = 0

# ── SLA04 ──
commands = ["ping", "-c", "1", param.sla04_rt_host]
ping = subprocess.run(commands, stdout=subprocess.PIPE)
result_sla04 = ping.stdout.decode("utf-8")
if "ttl=" in result_sla04.lower():
    sla_result[sla_list[3]] = param.sla04_score
else:
    sla_result[sla_list[3]] = 0

# ── SLA05 ──
commands = ["ping", "-c", "1", param.sla05_rt_host]
ping = subprocess.run(commands, stdout=subprocess.PIPE)
result_sla05 = ping.stdout.decode("utf-8")
if "ttl=" in result_sla05.lower():
    sla_result[sla_list[4]] = param.sla05_score
else:
    sla_result[sla_list[4]] = 0


# ─────────────────────────── SLA06: HTTP 疎通確認 ───────────────────────────
#
# 判定方法:
#   このチームの web_VIP に HTTP GET リクエストを送り、
#   レスポンスボディに "menu" という文字列が含まれているかで判定する。
#
# 成功: sla_result["sla06"] = param.sla06_score（通常 100 点）
# 失敗: sla_result["sla06"] = 0

web_url = "http://" + param.sla06_web_vip

try:
    print("debug:" + web_url)
    response_web = requests.get(web_url, timeout=param.http_timeout)
except requests.exceptions.RequestException as e:
    # 接続タイムアウト・接続拒否・DNS 解決失敗などのネットワークエラー
    print(f"SLA06 http_request_error : {e}")
    sla_result[sla_list[5]] = 0
else:
    print("debug:" + response_web.text[:200])  # 先頭200文字のみ出力
    if "menu" in response_web.text:
        sla_result[sla_list[5]] = param.sla06_score
    else:
        sla_result[sla_list[5]] = 0


# ─────────────────────────── タスクポイント取得 ───────────────────────────
#
# マルチチーム版ではリスト（taskXX[team_num-1]）だったが、
# 1チーム専用のためスカラー値（taskXX）を直接参照する。

task_result[task_list[0]] = param.task01
task_result[task_list[1]] = param.task02
task_result[task_list[2]] = param.task03
task_result[task_list[3]] = param.task04
task_result[task_list[4]] = param.task05
task_result[task_list[5]] = param.task06
task_result[task_list[6]] = param.task07
task_result[task_list[7]] = param.task08
task_result[task_list[8]] = param.task09


# ─────────────────────────── InfluxDB 接続 ───────────────────────────

# InfluxDB クライアントを初期化する。
# 接続先は param.py の db_host で指定した外部 InfluxDB サーバー。
# ※ Docker コンテナ内では db_host に "localhost" を使わないこと。
dbclient = InfluxDBClient(
    host=param.db_host,
    port=param.db_port,
    username=param.db_username,
    password=param.db_password,
    database=param.db_name,
)

# Measurement の自動作成
# 初回実行時や DB 初期化後は Measurement が存在しないため確認して作成する。
dbs = dbclient.get_list_database()
if {"name": param.db_name} not in dbs:
    dbclient.create_database(param.db_name)

print(sla_result)


# ─────────────────────────── 累積スコアの計算 ───────────────────────────
#
# スコアは毎回の実行結果を加算していく累積方式。
# InfluxDB から前回の累積スコアを取得し、今回分を足して新しい累積スコアを算出する。
#
# sum_point  : SLA ポイントの累積合計
# sum_point2 : SLA + タスクポイントの累積合計（最終スコア）
#
# Measurement 名はチーム名を使用する。
# 複数チームのデータが同一 InfluxDB に書き込まれるため、
# チーム名の Measurement で識別される。

data_check_result = dbclient.query("select count(*) from " + team_name)

sum_point  = 0
sum_point2 = 0

# ── SLA ポイントの累積計算 ──
if 0 == len(list(data_check_result.get_points(measurement=team_name))):
    # 【初回実行】前回値なし: 今回の SLA スコアをそのまま sum_point とする
    for i in sla_list:
        sum_point += sla_result[i]
else:
    # 【2回目以降】最新レコードから前回の累積ポイント (sum) を取得して加算
    sum_result = dbclient.query(
        "select sum from " + team_name + " order by time desc limit 1"
    )
    for i in sla_list:
        sum_point += sla_result[i]
    sum_point2 = sum_point
    sum_point += int(
        list(sum_result.get_points(measurement=team_name))[0]["sum"]
    )

print(sum_point)

# ── タスクポイントの累積計算 ──
if 0 == len(list(data_check_result.get_points(measurement=team_name))):
    # 【初回実行】前回値なし
    for i in range(len(task_list)):
        sum_point2 += int(task_result[task_list[i]])
    sum_point2 += sum_point
else:
    # 【2回目以降】最新レコードから前回の総合累積ポイント (sum2) を取得して加算
    sum_result = dbclient.query(
        "select sum2 from " + team_name + " order by time desc limit 1"
    )
    for i in task_list:
        sum_point2 += task_result[i]
    sum_point2 += int(
        list(sum_result.get_points(measurement=team_name))[0]["sum2"]
    )

# ── 不正行為による減点の適用 ──
# param.fusei はこのチームの不正減点ポイント（通常は 0）。
# マルチチーム版ではリストだったが、スカラー値に変更。
sum_point2 -= param.fusei


# ─────────────────────────── InfluxDB への書き込み ───────────────────────────

# Measurement 名にチーム名を使用することで、
# 同一 InfluxDB に複数チームのデータを識別して格納できる。
json_body = [
    {
        "measurement": team_name,
        "tags": {
            "team":   team_name,  # Grafana 等での絞り込みに使用
            "host":   "host",
            "region": "region",
        },
        "fields": {},
    }
]

# SLA 個別スコアを fields に追加
for i in range(len(sla_list)):
    json_body[0]["fields"]["sla0" + str(i + 1)] = sla_result[sla_list[i]]

# タスク個別スコアを fields に追加
for i in range(len(task_list)):
    json_body[0]["fields"]["task0" + str(i + 1)] = task_result[task_list[i]]

print(sla_result)
print(task_result)

json_body[0]["fields"]["sum"]  = sum_point   # SLA 累積合計
json_body[0]["fields"]["sum2"] = sum_point2  # SLA + タスク累積合計（最終スコア）

print("Write points: {0}".format(json_body))
dbclient.write_points(json_body)
