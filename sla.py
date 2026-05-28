#!/usr/bin/env python
"""
sla.py - SLA疎通チェック & スコア集計スクリプト（1チーム専用 Docker版）
=======================================================================
概要:
    このコンテナが担当する1チームを対象に SLA01〜06 の疎通確認を実施し、
    結果スコアを外部の InfluxDB サーバーに記録する。
    crontab から check-sla.sh 経由で定期実行される。

結果出力形式（「今すぐ実行」ボタンのパース用）:
    RESULT:ping:sla01:OK:1.1.1.1
    RESULT:ping:sla02:NG:1.1.2.2
    RESULT:http:sla06:OK:192.168.1.1
    RESULT:db:write:OK
    RESULT:log:write:OK

    app.py の run_check() がこの形式をパースして
    WEBコンソールに個別結果を返す。
"""

import subprocess
import sys
import os
import param
import requests
from influxdb import InfluxDBClient


# ─────────────────────────── 初期設定 ───────────────────────────

team_name = sys.argv[1]

if team_name != param.team_name:
    print(f"ERROR: 引数のチーム名 '{team_name}' と "
          f"param.py の team_name '{param.team_name}' が一致しません。")
    sys.exit(1)

sla_list  = ["sla01", "sla02", "sla03", "sla04", "sla05", "sla06"]
task_list = ["task01","task02","task03","task04","task05",
             "task06","task07","task08","task09"]

sla_result  = {}
task_result = {}


# ─────────────────────────── SLA01〜05: ping 疎通確認 ───────────────────────────
#
# 判定: ping 出力に "ttl=" が含まれれば OK
# 結果を RESULT:ping:slaXX:OK/NG:IPアドレス の形式で出力する

def check_ping(sla_id, ip, score):
    """ping 疎通確認を実行して結果を返す。"""
    cmd = ["ping", "-c", "1", "-W", "3", ip]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    ok = "ttl=" in result.stdout.decode("utf-8", errors="replace").lower()
    print(f"RESULT:ping:{sla_id}:{'OK' if ok else 'NG'}:{ip}")
    return score if ok else 0

sla_result["sla01"] = check_ping("sla01", param.sla01_rt_host, param.sla01_score)
sla_result["sla02"] = check_ping("sla02", param.sla02_rt_host, param.sla02_score)
sla_result["sla03"] = check_ping("sla03", param.sla03_rt_host, param.sla03_score)
sla_result["sla04"] = check_ping("sla04", param.sla04_rt_host, param.sla04_score)
sla_result["sla05"] = check_ping("sla05", param.sla05_rt_host, param.sla05_score)


# ─────────────────────────── SLA06: HTTP 疎通確認 ───────────────────────────
#
# 判定: レスポンスボディに "menu" が含まれれば OK
# 結果を RESULT:http:sla06:OK/NG:IPアドレス の形式で出力する

web_url = "http://" + param.sla06_web_vip
try:
    response_web = requests.get(web_url, timeout=param.http_timeout)
    ok = "menu" in response_web.text
    print(f"RESULT:http:sla06:{'OK' if ok else 'NG'}:{param.sla06_web_vip}")
    sla_result["sla06"] = param.sla06_score if ok else 0
except requests.exceptions.RequestException as e:
    print(f"RESULT:http:sla06:NG:{param.sla06_web_vip}")
    print(f"SLA06 error: {e}")
    sla_result["sla06"] = 0


# ─────────────────────────── タスクポイント取得 ───────────────────────────

task_result["task01"] = param.task01
task_result["task02"] = param.task02
task_result["task03"] = param.task03
task_result["task04"] = param.task04
task_result["task05"] = param.task05
task_result["task06"] = param.task06
task_result["task07"] = param.task07
task_result["task08"] = param.task08
task_result["task09"] = param.task09


# ─────────────────────────── InfluxDB 接続・書き込み ───────────────────────────

try:
    dbclient = InfluxDBClient(
        host=param.db_host,
        port=param.db_port,
        username=param.db_username,
        password=param.db_password,
        database=param.db_name,
    )

    # DB が存在しなければ作成
    dbs = dbclient.get_list_database()
    if {"name": param.db_name} not in dbs:
        dbclient.create_database(param.db_name)

    # ── 累積スコアの計算 ──
    data_check = dbclient.query("select count(*) from " + team_name)
    sum_point  = 0
    sum_point2 = 0

    if 0 == len(list(data_check.get_points(measurement=team_name))):
        # 初回実行
        for i in sla_list:
            sum_point += sla_result[i]
    else:
        # 2回目以降: 前回累積を取得して加算
        sum_res = dbclient.query(
            "select sum from " + team_name + " order by time desc limit 1"
        )
        for i in sla_list:
            sum_point += sla_result[i]
        sum_point2 = sum_point
        sum_point += int(list(sum_res.get_points(measurement=team_name))[0]["sum"])

    if 0 == len(list(data_check.get_points(measurement=team_name))):
        for i in range(len(task_list)):
            sum_point2 += int(task_result[task_list[i]])
        sum_point2 += sum_point
    else:
        sum_res2 = dbclient.query(
            "select sum2 from " + team_name + " order by time desc limit 1"
        )
        for i in task_list:
            sum_point2 += task_result[i]
        sum_point2 += int(list(sum_res2.get_points(measurement=team_name))[0]["sum2"])

    sum_point2 -= param.fusei

    # ── InfluxDB への書き込み ──
    json_body = [{
        "measurement": team_name,
        "tags": {"team": team_name, "host": "host", "region": "region"},
        "fields": {},
    }]
    for i in range(len(sla_list)):
        json_body[0]["fields"]["sla0" + str(i+1)] = sla_result[sla_list[i]]
    for i in range(len(task_list)):
        json_body[0]["fields"]["task0" + str(i+1)] = task_result[task_list[i]]
    json_body[0]["fields"]["sum"]  = sum_point
    json_body[0]["fields"]["sum2"] = sum_point2

    dbclient.write_points(json_body)
    print(f"RESULT:db:write:OK")

except Exception as e:
    print(f"RESULT:db:write:NG")
    print(f"DB error: {e}")
    sys.exit(1)


# ─────────────────────────── ログ書き込み確認 ───────────────────────────
#
# ログファイルへの書き込みが正常に行われているか確認する。
# このコードが実行された時点でログが書き込まれているため OK とする。

log_dir = os.environ.get("LOG_DIR", "/var/log/sla")
log_file = os.path.join(log_dir, f"sla_{team_name}_{__import__('datetime').date.today()}.log")
try:
    # ログファイルが存在して書き込み可能かチェック
    os.makedirs(log_dir, exist_ok=True)
    with open(log_file, "a") as f:
        pass  # 追記モードで開けるか確認
    print(f"RESULT:log:write:OK")
except Exception as e:
    print(f"RESULT:log:write:NG")
    print(f"Log error: {e}")
