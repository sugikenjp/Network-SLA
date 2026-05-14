#!/usr/bin/env python
"""
sla.py - SLA疎通チェック & スコア集計スクリプト
=================================================
概要:
    指定チームを対象に、SLA01〜06 の疎通確認を実施し、
    結果スコアを InfluxDB に記録する。
    check-sla.sh から crontab 経由で定期実行される。

実行方法:
    python3 sla.py <チーム名>
    例: python3 sla.py team01

引数:
    team_name (str): チーム名（例: "team01"）
                     5文字目（インデックス4）の数字をチーム番号として使用する。
                     例: "team01" → team_num = 1

処理フロー:
    1. コマンドライン引数からチーム名・番号を取得
    2. SLA01〜05: ping 疎通確認（TTL 含有 → スコア加算）
    3. SLA06    : HTTP アクセス確認（"menu" 文字列含有 → スコア加算）
    4. task01〜09: param.py の設定値をそのまま取得（手動設定ポイント）
    5. InfluxDB に接続し、Measurement がなければ自動作成
    6. 前回スコアを取得して今回分を加算（累積スコア計算）
    7. 不正行為による減点を適用
    8. SLA個別・task個別・累積合計を InfluxDB に書き込む

依存:
    - param.py    : ターゲットIP・スコア・DB設定などのパラメータ定義ファイル
    - influxdb    : InfluxDB 1.x 用 Python クライアント（pip install influxdb）
    - requests    : HTTP チェック用（pip install requests）
"""

import subprocess           # ping コマンドの実行に使用
from influxdb import InfluxDBClient  # InfluxDB 1.x への接続・読み書き
import sys                  # コマンドライン引数 (sys.argv) の取得
import param                # ターゲットIP・スコア・DB設定などのパラメータ
import requests             # SLA06 の HTTP 疎通確認に使用


# ─────────────────────────── 初期設定 ───────────────────────────

# コマンドライン引数からチーム名を取得する。
# 呼び出し例: python3 sla.py team01
#   → sys.argv[0] = "sla.py"
#   → sys.argv[1] = "team01"
team_name = sys.argv[1]

# 処理対象の SLA 項目 ID リスト。
# 辞書 sla_result のキーとして使用し、インデックスで各 SLA に対応付ける。
sla_list = ["sla01", "sla02", "sla03", "sla04", "sla05", "sla06"]

# 処理対象のタスク項目 ID リスト。
# task01〜09 は大会のチャレンジタスク完了ポイントに対応する。
# 値は param.py の taskXX リストから取得する（手動設定）。
task_list = [
    "task01",
    "task02",
    "task03",
    "task04",
    "task05",
    "task06",
    "task07",
    "task08",
    "task09",
]

# SLA チェック結果を格納する辞書。
# キー: sla_list の要素（"sla01"〜"sla06"）
# 値  : 疎通成功 → param.slaXX_score（通常 100）、失敗 → 0
sla_result = {}

# タスクポイントを格納する辞書。
# キー: task_list の要素（"task01"〜"task09"）
# 値  : param.taskXX[team_num-1] の値（手動設定された加算ポイント）
task_result = {}

# チーム番号を文字列から抽出する。
# チーム名の6文字目（インデックス5）が番号に対応する。
# 例: "team01" → team_name[5] = "1" → team_num = 1
# ※ param.py の各リストは 0 始まりのため、アクセス時は team_num-1 を使う。
team_num = int(team_name[5])


# ─────────────────────────── SLA01〜05: ping 疎通確認 ───────────────────────────
#
# 判定方法:
#   ping コマンドの標準出力に "ttl=" が含まれていれば疎通成功とみなす。
#   cp932（Shift-JIS）でデコードするのは、日本語 Windows 環境の出力形式に対応するため。
#   成功: sla_result["slaXX"] = param.slaXX_score（通常 100 点）
#   失敗: sla_result["slaXX"] = 0
#
# ping オプション:
#   -c 1 : 1回だけ送信して終了（定期チェックで何度も待たないようにするため）
#
# ターゲット IP:
#   param.slaXX_rt_host はチーム番号順の IP リスト。
#   team_num-1 でそのチームのターゲット IP を取得する。

# ── SLA01: RTホスト疎通確認 ──
commands = ["ping", "-c", "1", param.sla01_rt_host[team_num - 1]]
ping = subprocess.run(commands, stdout=subprocess.PIPE)
result_sla01 = ping.stdout.decode("cp932")  # 出力を cp932 でデコード
if "ttl=" in result_sla01:
    # "ttl=" が含まれる = ICMPエコー応答が返ってきた = 疎通成功
    sla_result[sla_list[0]] = param.sla01_score
else:
    # タイムアウト・到達不能など = 疎通失敗
    sla_result[sla_list[0]] = 0

# ── SLA02: RTホスト疎通確認 ──
commands = ["ping", "-c", "1", param.sla02_rt_host[team_num - 1]]
ping = subprocess.run(commands, stdout=subprocess.PIPE)
result_sla02 = ping.stdout.decode("cp932")
if "ttl=" in result_sla02:
    sla_result[sla_list[1]] = param.sla02_score
else:
    sla_result[sla_list[1]] = 0

# ── SLA03: RTホスト疎通確認 ──
commands = ["ping", "-c", "1", param.sla03_rt_host[team_num - 1]]
ping = subprocess.run(commands, stdout=subprocess.PIPE)
result_sla03 = ping.stdout.decode("cp932")
if "ttl=" in result_sla03:
    sla_result[sla_list[2]] = param.sla03_score
else:
    sla_result[sla_list[2]] = 0

# ── SLA04: RTホスト疎通確認 ──
commands = ["ping", "-c", "1", param.sla04_rt_host[team_num - 1]]
ping = subprocess.run(commands, stdout=subprocess.PIPE)
result_sla04 = ping.stdout.decode("cp932")
if "ttl=" in result_sla04:
    sla_result[sla_list[3]] = param.sla04_score
else:
    sla_result[sla_list[3]] = 0

# ── SLA05: RTホスト疎通確認 ──
commands = ["ping", "-c", "1", param.sla05_rt_host[team_num - 1]]
ping = subprocess.run(commands, stdout=subprocess.PIPE)
result_sla05 = ping.stdout.decode("cp932")
if "ttl=" in result_sla05:
    sla_result[sla_list[4]] = param.sla05_score
else:
    sla_result[sla_list[4]] = 0

# ── (旧SLA06: WEB ping確認 — 現在は無効化) ──
# ping ではなく HTTP チェックに切り替えたため、以下のブロックはコメントアウト済み。
# IP も固定値 "192.168.92.1" になっており、チームごとに動的に変わらない実装だった。
"""
#SLA06(WEBのPING)
commands = ["ping","-c","1",'192.168.92.1']
ping = subprocess.run(commands, stdout=subprocess.PIPE)
result_sla05 = ping.stdout.decode("cp932")
if("ttl=" in result_sla05):
    sla_result[sla_list[5]] = param.sla05_score
else:
    sla_result[sla_list[5]] = 0
"""


# ─────────────────────────── SLA06: HTTP 疎通確認 ───────────────────────────
#
# 判定方法:
#   チームごとの web_VIP に HTTP GET リクエストを送り、
#   レスポンスボディに "menu" という文字列が含まれているかで判定する。
#   「menu」はWebサーバーの正常起動を示すキーワードとして使用している。
#
# 成功: sla_result["sla06"] = param.sla06_score（通常 100 点）
# 失敗: sla_result["sla06"] = 0
#
# タイムアウト:
#   param.http_timeout 秒以内に応答がなければ RequestException を送出する。
#
# エラー処理:
#   requests.exceptions.RequestException は接続エラー・タイムアウト・
#   DNS解決失敗など全ての HTTP エラーの基底クラス。これを捕捉することで
#   あらゆるネットワーク障害に対してスコア 0 として処理できる。

# チームの web_VIP IP アドレスを取得して URL を組み立てる
web_host = param.sla06_web_vip[team_num - 1]
web_url = "http://" + web_host

try:
    print("debug:" + web_url)  # デバッグ用: アクセス先 URL をログに出力
    response_web = requests.get(web_url, timeout=param.http_timeout)
except requests.exceptions.RequestException as e:
    # 接続タイムアウト・接続拒否・DNS解決失敗などのネットワークエラー
    print("SLA06 http_request_error : web_VIP")
    sla_result[sla_list[5]] = 0
else:
    # HTTP リクエスト成功時: レスポンスボディに "menu" が含まれるか確認
    print("debug:" + response_web.text)  # デバッグ用: レスポンス内容をログに出力
    if "menu" in response_web.text:
        # Webサーバーが正常に動作してメニューページを返している
        sla_result[sla_list[5]] = param.sla06_score
    else:
        # レスポンスは返ってきたが期待するコンテンツが含まれていない
        # （エラーページ・リダイレクト先の別ページ等）
        sla_result[sla_list[5]] = 0


# ─────────────────────────── タスクポイント取得 ───────────────────────────
#
# task01〜09 は大会の追加チャレンジタスクの完了ポイント。
# 各タスクの完了状況は param.py の taskXX リストで管理しており、
# 大会運営者が手動で値を設定する（0 = 未完了、正の整数 = 完了時の加算ポイント）。
#
# param.taskXX はチーム番号順のリストなので、team_num-1 でそのチームの値を取得する。
# 例: param.task01 = [10, 0, 0, 0, 0, 0, 0, 0, 10]
#     → team01（index 0）は 10 点、team09（index 8）も 10 点

task_result[task_list[0]] = param.task01[team_num - 1]  # task01 のポイントを取得
task_result[task_list[1]] = param.task02[team_num - 1]  # task02 のポイントを取得
task_result[task_list[2]] = param.task03[team_num - 1]  # task03 のポイントを取得
task_result[task_list[3]] = param.task04[team_num - 1]  # task04 のポイントを取得
task_result[task_list[4]] = param.task05[team_num - 1]  # task05 のポイントを取得
task_result[task_list[5]] = param.task06[team_num - 1]  # task06 のポイントを取得
task_result[task_list[6]] = param.task07[team_num - 1]  # task07 のポイントを取得
task_result[task_list[7]] = param.task08[team_num - 1]  # task08 のポイントを取得
task_result[task_list[8]] = param.task09[team_num - 1]  # task09 のポイントを取得


# ─────────────────────────── InfluxDB 接続 ───────────────────────────

# InfluxDB クライアントを初期化する。
# 引数: host, port, username, password, database
# ※ username・password を空文字にしているのは認証なし構成のため。
#   認証が必要な環境では param.db_username / param.db_password を使うこと。
dbclient = InfluxDBClient(param.db_host, param.db_port, "", "", param.db_name)

# ── Measurement の自動作成 ──
# 初回実行時や DB 初期化後は Measurement（= テーブル相当）が存在しないため、
# データベース一覧を確認して当該チームの DB がなければ作成する。
# ※ InfluxDB 1.x では Measurement はデータ書き込み時に自動作成されるが、
#   DB 自体が存在しない場合は先に create_database が必要。
dbs = dbclient.get_list_database()        # 既存 DB の一覧を取得
bc_db = {"name": team_name}              # 確認対象の DB 名辞書（リストの要素と同じ形式）
if bc_db not in dbs:
    # チーム名と同名の DB が存在しない場合は新規作成
    dbclient.create_database(team_name)

# デバッグ用: SLA チェック結果をログに出力
print(sla_result)


# ─────────────────────────── 累積スコアの計算 ───────────────────────────
#
# スコアは毎回の実行結果を加算していく累積方式。
# InfluxDB から前回の累積スコアを取得し、今回分を足して新しい累積スコアを算出する。
#
# sum_point  : SLA ポイントの累積合計（SLA01〜06 の成功スコア合計を積み上げる）
# sum_point2 : SLA + タスクポイントの累積合計（大会の最終スコア）
#
# 初回判定:
#   SELECT count(*) FROM <team_name> の結果が 0 件 → まだデータが書き込まれていない = 初回
#   それ以外 → 過去のデータが存在する → 前回の累積値を取得して加算する

# Measurement に既存データがあるか確認するため、レコード数を取得する
data_check_result = dbclient.query("select count(*) from " + team_name)

sum_point  = 0  # SLA 累積ポイント（初期化）
sum_point2 = 0  # SLA + タスク累積ポイント（初期化）

# ── SLA ポイントの累積計算 ──
if 0 == len(list(data_check_result.get_points(measurement=team_name))):
    # 【初回実行】まだ DB にデータが存在しない場合
    # 前回値は存在しないため、今回の SLA スコアをそのまま sum_point とする
    for i in sla_list:
        sum_point += sla_result[i]
else:
    # 【2回目以降】DB に過去データが存在する場合
    # 最新レコードから前回の SLA 累積ポイント (sum フィールド) を取得する。
    # ORDER BY time DESC LIMIT 1 で最新の1件だけを取得。
    sum_result = dbclient.query(
        "select sum from " + team_name + " order by time desc limit 1"
    )
    # 今回の SLA スコアを集計
    for i in sla_list:
        sum_point += sla_result[i]
    sum_point2 = sum_point  # タスク計算の基点として保存

    # 前回の SLA 累積ポイントを取得して加算（ResultSet → list → dict → 値）
    sum_point += int(
        (list(sum_result.get_points(measurement=team_name)))[0]["sum"]
    )

print(sum_point)  # デバッグ用: SLA 累積スコアをログに出力

# ── タスクポイントの累積計算 ──
if 0 == len(list(data_check_result.get_points(measurement=team_name))):
    # 【初回実行】前回値なし: 今回のタスクスコアをそのまま足して sum_point と合算
    for i in range(len(task_list)):
        sum_point2 += int(task_result[task_list[i]])
    sum_point2 += sum_point  # SLA 累積 + タスク = 総合計
else:
    # 【2回目以降】最新レコードから前回の総合累積ポイント (sum2 フィールド) を取得
    sum_result = dbclient.query(
        "select sum2 from " + team_name + " order by time desc limit 1"
    )
    # 今回のタスクスコアを集計
    for i in task_list:
        sum_point2 += task_result[i]
    # 前回の総合累積ポイントを取得して加算
    sum_point2 += int(
        (list(sum_result.get_points(measurement=team_name)))[0]["sum2"]
    )

# ── (旧実装: 毎回リセットして再集計する方式 — 現在は無効化) ──
# 以下の方式は累積ではなく毎回タスクスコアを全件合算する実装だったが、
# 現在の累積加算方式に変更されたためコメントアウト済み。
"""
for i in range(len(task_list)):
    sum_point2 += int(task_result[task_list[i]])
sum_point2 += sum_point
"""

# ── 不正行為による減点の適用 ──
# param.fusei はチームごとの不正減点リスト（通常は全て 0）。
# 大会運営者が不正行為を確認した場合に手動で値を設定する。
# 減点は sum_point2（総合累積スコア）から直接差し引く。
sum_point2 -= param.fusei[team_num - 1]


# ─────────────────────────── InfluxDB への書き込み ───────────────────────────
#
# InfluxDB の Line Protocol 形式に沿ったデータ構造（JSON 形式）を組み立て、
# write_points() で一括書き込みする。
#
# データ構造:
#   measurement : チーム名（例: "team01"）→ テーブル相当
#   tags        : host / region（現在は固定値。将来の拡張用に残している）
#   fields      : 実際に記録する数値データ（SLA個別・タスク個別・累積合計）
#
# InfluxDB の tags はインデックス付きで検索に使われるメタデータ。
# fields はタイムスタンプと共に記録される実データ。

# データ挿入フォーマットの初期化（fields は後で動的に追加する）
json_body = [
    {
        "measurement": team_name,  # チーム名を Measurement 名に使用
        "tags": {
            "host": "host",       # タグ: ホスト識別子（現在は固定値）
            "region": "region",   # タグ: リージョン識別子（現在は固定値）
        },
        "fields": {},             # 空の fields 辞書（以下で動的に追加）
    }
]

# ── SLA 個別スコアを fields に追加 ──
# "sla01"〜"sla06" という field 名で各 SLA の今回スコアを記録する。
# i=0 → "sla01", i=1 → "sla02", ... i=5 → "sla06"
for i in range(len(sla_list)):
    json_body[0]["fields"]["sla0" + str(i + 1)] = sla_result[sla_list[i]]

# ── タスク個別スコアを fields に追加 ──
# "task01"〜"task09" という field 名で各タスクの今回ポイントを記録する。
# i=0 → "task01", i=1 → "task02", ... i=8 → "task09"
for i in range(len(task_list)):
    json_body[0]["fields"]["task0" + str(i + 1)] = task_result[task_list[i]]

# デバッグ用: SLA チェック結果・タスク結果をログに出力
print(sla_result)
print(task_result)

# ── 累積スコアを fields に追加 ──
# sum  : SLA ポイントの累積合計（前回値 + 今回の SLA スコア）
# sum2 : SLA + タスクポイントの累積合計（大会の最終スコア）
json_body[0]["fields"]["sum"]  = sum_point
json_body[0]["fields"]["sum2"] = sum_point2

# InfluxDB への書き込み実行
# write_points() は json_body のリストを一括で書き込む。
# タイムスタンプを指定していないため、書き込み時刻が自動で付与される。
print("Write points: {0}".format(json_body))  # デバッグ用: 書き込みデータをログに出力
dbclient.write_points(json_body)
