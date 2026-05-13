#!/usr/bin/env python3
"""
SLA監視管理コンソール - Flask APIサーバー
"""
import os#!/usr/bin/env python3
"""
SLA監視管理コンソール - Flask APIサーバー
=========================================
概要:
  SLA疎通チェックスクリプト (sla.py / check-sla.sh) の設定を
  Webブラウザから管理するための REST API サーバー。

主な責務:
  - チーム・ターゲットIP・スケジュール・DB設定を JSON ファイルで永続化
  - 設定変更時に param.py を自動生成・上書き（バックアップ付き）
  - crontab の SLA管理エントリを自動更新
  - check-sla.sh を手動トリガーで実行
  - InfluxDB への接続テスト・Measurement管理・データ削除

起動方法:
  python3 app.py
  または: PORT=8080 python3 app.py

依存パッケージ: flask, flask-cors, influxdb
"""

import os          # 環境変数取得 (PORT) に使用
import sys         # (将来的な sys.exit 用に import。現在は未使用)
import json        # JSON ファイルの読み書き
import subprocess  # crontab コマンド・check-sla.sh の外部プロセス実行
import shutil      # param.py のバックアップ (ファイルコピー) に使用
from datetime import datetime  # param.py 生成日時の埋め込みに使用
from pathlib import Path       # OS非依存のパス操作

from flask import Flask, jsonify, request, send_from_directory
# Flask      : Webアプリ本体
# jsonify    : dict/list を JSON レスポンスに変換
# request    : リクエストボディ・クエリパラメータの取得
# send_from_directory : static フォルダのファイルを安全に配信

from flask_cors import CORS
# CORS : ブラウザの Same-Origin Policy を緩和し、
#        フロントエンド (別ポート等) からの API 呼び出しを許可


# ─────────────────────────── パス・定数の定義 ───────────────────────────

# このファイルが置かれているディレクトリ (= sla-console/)
BASE_DIR   = Path(__file__).parent

# 設定 JSON を保存するディレクトリ (= sla-console/config/)
CONFIG_DIR = BASE_DIR / "config"

# 本番環境の param.py パス。
# このディレクトリが実際に存在する場合は直接上書きし、
# 存在しない場合は CONFIG_DIR/param.py に書き出す。
PARAM_FILE = Path("/home/user/sla.py").parent / "param.py"

# crontab 内の SLA管理エントリを識別するためのタグ文字列。
# このタグが含まれる行だけを差し替えることで、
# 手動で追加した他の cron エントリを保護する。
CRON_TAG = "# SLA-MANAGED"

# check-sla.sh が書き出すログファイルの格納ディレクトリ
LOG_DIR = Path("/home/user/log")

# config/ ディレクトリを事前に作成（なければ作成、あれば何もしない）
CONFIG_DIR.mkdir(exist_ok=True)

# Flask アプリケーションのインスタンス化
# static_folder  : フロントエンドの HTML/CSS/JS ファイルの置き場所
# template_folder: Jinja2 テンプレートの置き場所 (現在は未使用)
app = Flask(__name__, static_folder="static", template_folder="templates")

# すべてのルートに対して CORS を有効化
# （開発時に別ポートの devserver からアクセスするケースに対応）
CORS(app)


# ─────────────────────────── ユーティリティ関数 ───────────────────────────

def _cfg(name: str, default=None):
    """
    config/<name>.json を読み込んで Python オブジェクトとして返す。

    引数:
        name    : ファイル名のベース部分 (例: "teams" → config/teams.json)
        default : ファイルが存在しない場合に返すデフォルト値

    戻り値:
        JSON をデコードしたオブジェクト、またはデフォルト値
    """
    path = CONFIG_DIR / f"{name}.json"
    if path.exists():
        return json.loads(path.read_text())
    return default


def _save_cfg(name: str, data):
    """
    Python オブジェクトを config/<name>.json に書き込む。

    引数:
        name : ファイル名のベース部分
        data : 保存する Python オブジェクト (dict / list)

    備考:
        ensure_ascii=False により日本語がそのまま保存される。
        indent=2 で人間が読みやすい形式に整形する。
    """
    path = CONFIG_DIR / f"{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


# ─────────────────────────── デフォルト設定値 ───────────────────────────

def _default_targets():
    """
    初期状態の監視ターゲット設定を返す。

    構造:
        {
          "sla01": {
            "type": "ping" | "http",  # チェック種別
            "desc": "説明文字列",      # 管理用の説明 (param.py にコメントとして埋め込まれる)
            "ips":  ["IP1", "IP2", ...]  # チーム番号順のターゲットIPリスト
          },
          ...
        }

    備考:
        sla01〜sla05 は ping 疎通確認（TTL 含有で判定）。
        sla06 は HTTP アクセス確認（レスポンスに "menu" 文字列が含まれるかで判定）。
        IP リストの順番はチームの順番に対応 (0番目 = team01, 1番目 = team02, ...)。
    """
    return {
        "sla01": {"type": "ping", "desc": "RTホスト疎通",
                  "ips": ["1.1.1.1","2.2.1.1","3.3.1.1","4.4.1.1","5.5.1.1",
                          "6.6.1.1","7.7.1.1","8.8.1.1","9.9.1.1"]},
        "sla02": {"type": "ping", "desc": "RTホスト疎通",
                  "ips": ["1.1.2.2","2.2.2.2","3.3.2.2","4.4.2.2","5.5.2.2",
                          "6.6.2.2","7.7.2.2","8.8.2.2","9.9.2.2"]},
        "sla03": {"type": "ping", "desc": "RTホスト疎通",
                  "ips": ["1.1.3.3","2.2.3.3","3.3.3.3","4.4.3.3","5.5.3.3",
                          "6.6.3.3","7.7.3.3","8.8.3.3","9.9.3.3"]},
        "sla04": {"type": "ping", "desc": "RTホスト疎通",
                  "ips": ["1.1.4.4","2.2.4.4","3.3.4.4","4.4.4.4","5.5.4.4",
                          "6.6.4.4","7.7.4.4","8.8.4.4","9.9.4.4"]},
        "sla05": {"type": "ping", "desc": "RTホスト疎通",
                  "ips": ["1.1.5.5","2.2.5.5","3.3.5.5","4.4.5.5","5.5.5.5",
                          "6.6.5.5","7.7.5.5","8.8.5.5","9.9.5.5"]},
        "sla06": {"type": "http", "desc": "web VIP HTTP確認",
                  "ips": ["192.168.12.1","192.168.22.1","192.168.32.1","192.168.42.1",
                          "192.168.52.1","192.168.62.1","192.168.72.1","192.168.82.1",
                          "192.168.92.1"]},
    }


def _default_teams():
    """
    初期状態のチーム設定リストを返す。

    構造:
        [
          {"id": "team01", "name": "team01", "enabled": True},
          ...
        ]

    備考:
        id    : crontab や check-sla.sh に渡される識別子
        name  : UI 表示名 (現在は id と同じ値だが、将来の表示名変更に対応)
        enabled: False にするとそのチームは crontab・手動実行の対象外になる
    """
    return [
        {"id": f"team0{i}", "name": f"team0{i}", "enabled": True}
        for i in range(1, 10)
    ]


def _default_db():
    """
    初期状態の InfluxDB 接続設定を返す。

    構造:
        {
          "host"    : DBホスト名またはIPアドレス
          "port"    : ポート番号 (文字列)
          "username": 認証ユーザー名
          "password": 認証パスワード
          "name"    : 使用するデータベース名
        }

    備考:
        param.py の db_host / db_port / db_username / db_password / db_name に対応。
    """
    return {
        "host": "localhost",
        "port": "8086",
        "username": "user",
        "password": "user",
        "name": "bc_db",
    }


def _default_schedule():
    """
    初期状態のスケジュール設定を返す。

    構造:
        {
          "cron_min"    : crontab の分フィールド (例: "*/5")
          "cron_hour"   : crontab の時フィールド (例: "*")
          "cron_rest"   : crontab の「日 月 曜日」フィールド (例: "* * *")
          "http_timeout": SLA06 等 HTTP チェックのタイムアウト秒数 (float)
          "script_path" : 実行する check-sla.sh のフルパス
        }

    備考:
        デフォルトは 5 分ごとに check-sla.sh を全チームで実行する設定。
        http_timeout は param.py の http_timeout 変数に反映される。
    """
    return {
        "cron_min": "*/5",
        "cron_hour": "*",
        "cron_rest": "* * *",
        "http_timeout": 7.0,
        "script_path": "/home/user/check-sla.sh",
    }


# ─────────────────────────── param.py 生成ロジック ───────────────────────────

def generate_param_py(targets: dict, db: dict, schedule: dict, teams: list) -> str:
    """
    管理コンソールの現在設定から param.py のソースコードを文字列として生成する。

    引数:
        targets  : 監視ターゲット設定 (_default_targets() と同じ構造)
        db       : InfluxDB 接続設定 (_default_db() と同じ構造)
        schedule : スケジュール設定 (_default_schedule() と同じ構造)
        teams    : チームリスト (_default_teams() と同じ構造)

    戻り値:
        param.py として書き出すべき Python ソースコードの文字列

    生成される変数:
        slaXX_rt_host  : ping 種別ターゲットの IP リスト (チーム順)
        slaXX_web_vip  : http 種別ターゲットの IP リスト (チーム順)
        num_of_team    : 有効チーム数
        db_host 等     : InfluxDB 接続情報
        slaXX_score    : 各 SLA の満点スコア (固定: 100)
        http_timeout   : HTTP チェックのタイムアウト秒数
        taskXX         : タスク完了ポイント (全0で初期化。手動で編集)
        fusei          : 不正行為による減点 (全0で初期化。手動で編集)
    """
    lines = [
        "# このファイルはSLA管理コンソールによって自動生成されます",
        f"# 生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]

    # ── SLA ターゲット IP リストを生成 ──
    # type が "ping" → 変数名を <sla_id>_rt_host
    # type が "http" → 変数名を <sla_id>_web_vip
    for sla_id, sla in targets.items():
        var = f"{sla_id}_rt_host" if sla["type"] == "ping" else f"{sla_id}_web_vip"
        lines.append(f"# {sla_id} ({sla.get('desc', '')})")
        lines.append(f"{var} = [")
        for ip in sla["ips"]:
            lines.append(f'        "{ip}",')
        lines.append("]")
        lines.append("")

    # ── 有効チーム数 ──
    # enabled=False のチームは除外してカウント
    lines.append(f"num_of_team = {len([t for t in teams if t.get('enabled', True)])}")
    lines.append("")

    # ── InfluxDB 接続情報 ──
    lines += [
        f'db_host = "{db["host"]}"',
        f'db_port = "{db["port"]}"',
        f'db_username = "{db["username"]}"',
        f'db_password = "{db["password"]}"',
        f'db_name = "{db["name"]}"',
        "",
    ]

    # ── SLA スコアの満点定義 ──
    # 各 SLA が正常だったときに加算されるスコア (固定値 100)
    for sla_id in targets:
        lines.append(f"{sla_id}_score = 100")
    lines.append("")

    # ── HTTP タイムアウト ──
    # sla.py の requests.get() に渡される timeout 引数
    lines.append(f"http_timeout = {schedule['http_timeout']}")
    lines.append("")

    # ── タスクポイント・不正減点リスト ──
    # task01〜task09 はチーム別の追加ポイント。初期値は全チーム 0。
    # fusei はチーム別の不正行為による減点。初期値は全チーム 0。
    # これらの値は大会運営者が手動で param.py を直接編集して設定する。
    for task in [f"task{str(i).zfill(2)}" for i in range(1, 10)]:
        lines.append(f"{task} = [{', '.join(['0'] * len(teams))}]")
    lines.append("")
    lines.append(f"fusei = [{', '.join(['0'] * len(teams))}]")
    lines.append("")

    return "\n".join(lines)


# ─────────────────────────── API: チーム管理 ───────────────────────────

@app.route("/api/teams", methods=["GET"])
def get_teams():
    """
    チーム設定一覧を取得する。

    レスポンス (JSON):
        チームオブジェクトの配列
        例: [{"id": "team01", "name": "team01", "enabled": true}, ...]

    備考:
        config/teams.json が存在しない場合はデフォルト値 (team01〜team09) を返す。
    """
    return jsonify(_cfg("teams", _default_teams()))


@app.route("/api/teams", methods=["POST"])
def save_teams():
    """
    チーム設定を保存し、param.py を再生成する。

    リクエストボディ (JSON):
        チームオブジェクトの配列 (GET と同じ構造)

    レスポンス (JSON):
        {"ok": true, "message": "..."}

    副作用:
        1. config/teams.json に設定を保存
        2. param.py を再生成して書き出す (_apply_param_py)
           → チーム数が変わると num_of_team・taskXX・fusei の要素数が変わるため
    """
    data = request.get_json()
    _save_cfg("teams", data)
    _apply_param_py()
    return jsonify({"ok": True, "message": "チーム設定を保存しました"})


# ─────────────────────────── API: 監視ターゲット管理 ───────────────────────────

@app.route("/api/targets", methods=["GET"])
def get_targets():
    """
    監視ターゲット設定を取得する。

    レスポンス (JSON):
        SLA ID をキーとした設定オブジェクト
        例: {"sla01": {"type": "ping", "desc": "...", "ips": [...]}, ...}
    """
    return jsonify(_cfg("targets", _default_targets()))


@app.route("/api/targets", methods=["POST"])
def save_targets():
    """
    監視ターゲット設定を保存し、param.py を再生成する。

    リクエストボディ (JSON):
        GET と同じ構造のターゲット設定オブジェクト

    レスポンス (JSON):
        {"ok": true, "message": "..."}

    副作用:
        1. config/targets.json に保存
        2. param.py を再生成（IPアドレスの変更が即座に反映される）
    """
    data = request.get_json()
    _save_cfg("targets", data)
    _apply_param_py()
    return jsonify({"ok": True, "message": "ターゲット設定を保存し、param.py を更新しました"})


# ─────────────────────────── API: スケジュール管理 ───────────────────────────

@app.route("/api/schedule", methods=["GET"])
def get_schedule():
    """
    crontab スケジュール設定を取得する。

    レスポンス (JSON):
        {"cron_min": "*/5", "cron_hour": "*", "cron_rest": "* * *",
         "http_timeout": 7.0, "script_path": "/home/user/check-sla.sh"}
    """
    return jsonify(_cfg("schedule", _default_schedule()))


@app.route("/api/schedule", methods=["POST"])
def save_schedule():
    """
    スケジュール設定を保存し、crontab と param.py を更新する。

    リクエストボディ (JSON):
        GET と同じ構造のスケジュール設定オブジェクト

    レスポンス (JSON):
        {"ok": true, "message": "..."}

    副作用:
        1. config/schedule.json に保存
        2. crontab を更新 (_apply_crontab) — SLA-MANAGED タグ行のみ差し替え
        3. param.py を再生成 (_apply_param_py) — http_timeout の変更を反映
    """
    data = request.get_json()
    _save_cfg("schedule", data)
    _apply_crontab(data)
    _apply_param_py()
    return jsonify({"ok": True, "message": "スケジュールを保存し、crontabを更新しました"})


# ─────────────────────────── API: データベース管理 ───────────────────────────

@app.route("/api/database", methods=["GET"])
def get_database():
    """
    InfluxDB 接続設定を取得する。

    レスポンス (JSON):
        {"host": "...", "port": "...", "username": "...", "name": "..."}

    セキュリティ:
        パスワードはレスポンスに含めない (pop で除去)。
        フロントエンドのパスワード欄は「変更する場合のみ入力」とする。
    """
    cfg = _cfg("database", _default_db())
    cfg.pop("password", None)   # パスワードはGETレスポンスに含めない
    return jsonify(cfg)


@app.route("/api/database", methods=["POST"])
def save_database():
    """
    InfluxDB 接続設定を保存し、param.py を再生成する。

    リクエストボディ (JSON):
        {"host": "...", "port": "...", "username": "...", "password": "...", "name": "..."}

    レスポンス (JSON):
        {"ok": true, "message": "..."}

    備考:
        フロントエンドからパスワードが空文字で送られてきた場合は、
        既存の保存済みパスワードを維持する（パスワードのクリアを防止）。
    """
    data = request.get_json()
    existing = _cfg("database", _default_db())
    # パスワードが空の場合は既存値を引き継ぐ
    if not data.get("password"):
        data["password"] = existing.get("password", "")
    _save_cfg("database", data)
    _apply_param_py()
    return jsonify({"ok": True, "message": "DB設定を保存しました"})


@app.route("/api/database/test", methods=["POST"])
def test_database():
    """
    保存済みの接続設定を使って InfluxDB への実接続を試みる。

    レスポンス (JSON):
        成功: {"ok": true,  "message": "接続成功。DB数: N", "databases": [...]}
        失敗: {"ok": false, "message": "接続失敗: <エラー詳細>"}  (HTTP 500)

    備考:
        get_list_database() を呼ぶことで認証も含めて接続確認する。
        influxdb パッケージは関数内で遅延 import しているため、
        パッケージがない環境でもサーバー起動自体は成功する。
    """
    cfg = _cfg("database", _default_db())
    try:
        from influxdb import InfluxDBClient
        client = InfluxDBClient(
            host=cfg["host"],
            port=int(cfg["port"]),
            username=cfg.get("username", ""),
            password=cfg.get("password", ""),
            database=cfg["name"],
        )
        dbs = client.get_list_database()
        return jsonify({
            "ok": True,
            "message": f"接続成功。DB数: {len(dbs)}",
            "databases": [d["name"] for d in dbs],
        })
    except Exception as e:
        return jsonify({"ok": False, "message": f"接続失敗: {e}"}), 500


@app.route("/api/database/measurements", methods=["GET"])
def get_measurements():
    """
    InfluxDB 内の Measurement 一覧と各行数を取得する。

    レスポンス (JSON):
        [{"name": "team01", "rows": 1234}, ...]

    備考:
        行数は SELECT count(*) FROM "<name>" の最初フィールドの値を使用する。
        個別 Measurement の count 取得に失敗した場合は rows=0 として続行する。
        Measurement = InfluxDB における「テーブル」相当の概念。
        各チームのデータは team01 / team02 ... という名前の Measurement に保存される。
    """
    cfg = _cfg("database", _default_db())
    try:
        from influxdb import InfluxDBClient
        client = InfluxDBClient(
            host=cfg["host"],
            port=int(cfg["port"]),
            username=cfg.get("username", ""),
            password=cfg.get("password", ""),
            database=cfg["name"],
        )
        result = client.get_list_measurements()
        measurements = []
        for m in result:
            name = m["name"]
            try:
                # count(*) の結果は ResultSet オブジェクト。
                # get_points() でイテレータに変換後、最初の行の 2 番目の値が行数。
                cnt = list(client.query(f'SELECT count(*) FROM "{name}"').get_points())
                row_count = list(cnt[0].values())[1] if cnt else 0
            except Exception:
                row_count = 0  # count 取得失敗時はゼロ扱いで続行
            measurements.append({"name": name, "rows": row_count})
        return jsonify(measurements)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/database/reset/<team>", methods=["DELETE"])
def reset_team(team):
    """
    指定チームの Measurement を InfluxDB から削除する。

    パスパラメータ:
        team : 削除対象のチーム ID (例: "team01")

    レスポンス (JSON):
        成功: {"ok": true,  "message": "team01 のデータを削除しました"}
        失敗: {"ok": false, "message": "<エラー詳細>"}  (HTTP 500)

    注意:
        drop_measurement は取り消し不可。UI 側で confirm ダイアログを表示している。
    """
    cfg = _cfg("database", _default_db())
    try:
        from influxdb import InfluxDBClient
        client = InfluxDBClient(
            host=cfg["host"],
            port=int(cfg["port"]),
            username=cfg.get("username", ""),
            password=cfg.get("password", ""),
            database=cfg["name"],
        )
        client.drop_measurement(team)
        return jsonify({"ok": True, "message": f"{team} のデータを削除しました"})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@app.route("/api/database/reset-all", methods=["DELETE"])
def reset_all():
    """
    データベース全体を削除して再作成する（完全初期化）。

    レスポンス (JSON):
        成功: {"ok": true,  "message": "全データを初期化しました"}
        失敗: {"ok": false, "message": "<エラー詳細>"}  (HTTP 500)

    処理フロー:
        1. drop_database でデータベースごと削除
        2. create_database で同名のデータベースを空の状態で再作成

    注意:
        全チームの全記録が失われる。UI 側では confirm を 2 回表示して誤操作を防止。
    """
    cfg = _cfg("database", _default_db())
    try:
        from influxdb import InfluxDBClient
        client = InfluxDBClient(
            host=cfg["host"],
            port=int(cfg["port"]),
            username=cfg.get("username", ""),
            password=cfg.get("password", ""),
            database=cfg["name"],
        )
        client.drop_database(cfg["name"])    # DB ごと削除
        client.create_database(cfg["name"])  # 空の DB を再作成
        return jsonify({"ok": True, "message": "全データを初期化しました"})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


# ─────────────────────────── API: SLA 手動実行 ───────────────────────────

@app.route("/api/run-check", methods=["POST"])
def run_check():
    """
    check-sla.sh を手動でトリガーし、全チーム（または指定チーム）の
    SLA チェックを即時実行する。

    リクエストボディ (JSON, 省略可):
        {"teams": ["team01", "team03"]}   # 指定チームのみ実行
        {}  または省略                     # 有効な全チームを実行

    レスポンス (JSON):
        {
          "ok": true,
          "results": [
            {"team": "team01", "ok": true,  "stdout": "...", "stderr": ""},
            {"team": "team02", "ok": false, "stdout": "", "stderr": "timeout"},
            ...
          ]
        }

    実行の詳細:
        - subprocess.run で `bash <script_path> <team_id>` を実行する
        - タイムアウトは 30 秒（1 チームあたり）
        - stdout の末尾 500 文字、stderr の末尾 200 文字を返す（大量出力対策）
        - スクリプトが見つからない場合は FileNotFoundError として報告

    備考:
        実際の疎通判定は check-sla.sh / sla.py 側で行われる。
        このエンドポイントは「起動して終了コードを確認する」だけの役割。
    """
    body = request.get_json() or {}

    # リクエストで teams が指定された場合はそのチームのみ、
    # 指定がない場合は有効 (enabled=True) な全チームを対象にする
    teams = body.get("teams")
    sched = _cfg("schedule", _default_schedule())
    script = sched.get("script_path", "/home/user/check-sla.sh")

    results = []
    target_teams = (
        teams
        if teams
        else [t["id"] for t in _cfg("teams", _default_teams()) if t.get("enabled")]
    )

    for team in target_teams:
        try:
            proc = subprocess.run(
                ["bash", script, team],
                capture_output=True,  # stdout / stderr を変数に取り込む
                text=True,            # bytes ではなく str として受け取る
                timeout=30,           # 30 秒でタイムアウト
            )
            results.append({
                "team": team,
                "ok": proc.returncode == 0,   # 終了コード 0 を正常とみなす
                "stdout": proc.stdout[-500:], # 末尾 500 文字のみ返す
                "stderr": proc.stderr[-200:], # 末尾 200 文字のみ返す
            })
        except subprocess.TimeoutExpired:
            results.append({"team": team, "ok": False, "stdout": "", "stderr": "timeout"})
        except FileNotFoundError:
            results.append({
                "team": team,
                "ok": False,
                "stdout": "",
                "stderr": f"スクリプトが見つかりません: {script}",
            })

    return jsonify({"ok": True, "results": results})


# ─────────────────────────── API: ログ取得 ───────────────────────────

@app.route("/api/logs", methods=["GET"])
def get_logs():
    """
    当日のログファイルを読み込んで返す。

    クエリパラメータ:
        team (省略可) : 絞り込むチーム ID (例: ?team=team01)
                        省略時は全チームの今日のログを返す

    レスポンス (JSON):
        [{"team": "team01", "text": "ログ行の内容", "time": "2026-05-13"}, ...]

    ログファイルのパス規則:
        /home/user/log/sla_<team>_<YYYY-MM-DD>.log
        → check-sla.sh が `sla_${TEAM}_${DATE}.log` という名前で書き出す

    備考:
        - 1 ファイルから末尾 100 行のみ読む（巨大ログへの対策）
        - 全チーム取得時は最大 18 ファイル（チーム数に合わせた上限）
        - 全ログの末尾 200 行のみ返す（レスポンスサイズの制限）
        - errors="replace" により文字化けがあっても処理を続行する
    """
    team = request.args.get("team", "")
    lines = []
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        if team:
            # 特定チームのログファイルのみ対象
            files = [LOG_DIR / f"sla_{team}_{today}.log"]
        else:
            # 本日のすべてのチームのログファイルを取得（降順、最大 18 件）
            files = sorted(LOG_DIR.glob(f"sla_*_{today}.log"), reverse=True)[:18]

        for f in files:
            if f.exists():
                # 末尾 100 行のみ読み込む
                for line in f.read_text(errors="replace").splitlines()[-100:]:
                    if line.strip():  # 空行はスキップ
                        # ファイル名 "sla_team01_2026-05-13" の "_" 区切り 2 番目がチーム名
                        tm = f.stem.split("_")[1] if "_" in f.stem else "?"
                        lines.append({"team": tm, "text": line, "time": today})
    except Exception as e:
        lines.append({"team": "system", "text": f"ログ読み込みエラー: {e}", "time": ""})

    # 全体で末尾 200 行のみ返す
    return jsonify(lines[-200:])


# ─────────────────────────── API: param.py ダウンロード ───────────────────────────

@app.route("/api/export/param-py", methods=["GET"])
def export_param_py():
    """
    現在の設定から param.py を生成してファイルとしてダウンロードさせる。

    レスポンス:
        Content-Type: text/plain
        Content-Disposition: attachment; filename=param.py

    用途:
        本番サーバーへの手動配置・バックアップ取得・差分確認など。
        InfluxDB が localhost にない場合など、直接書き出せない環境での代替手段。
    """
    targets  = _cfg("targets",  _default_targets())
    db       = _cfg("database", _default_db())
    schedule = _cfg("schedule", _default_schedule())
    teams    = _cfg("teams",    _default_teams())
    content  = generate_param_py(targets, db, schedule, teams)

    from flask import Response
    return Response(
        content,
        mimetype="text/plain",
        headers={"Content-Disposition": "attachment; filename=param.py"},
    )


# ─────────────────────────── 内部処理: param.py 書き出し ───────────────────────────

def _apply_param_py():
    """
    現在の全設定から param.py を生成してファイルシステムに書き出す。

    書き出し先の優先順位:
        1. PARAM_FILE (/home/user/param.py) の親ディレクトリが存在する場合
           → 本番パスに直接上書き
        2. 存在しない場合
           → CONFIG_DIR/param.py に書き出す（ダウンロードで取得可能）

    バックアップ:
        既存ファイルがある場合は上書き前に <元ファイルパス>.bak にコピーする。
        直前の param.py を 1 世代だけ保持する簡易バックアップ。

    呼び出しタイミング:
        設定を変更する全 POST エンドポイント（チーム・ターゲット・スケジュール・DB）
        の最後に必ず呼ばれ、設定と param.py の整合性を保つ。
    """
    targets  = _cfg("targets",  _default_targets())
    db       = _cfg("database", _default_db())
    schedule = _cfg("schedule", _default_schedule())
    teams    = _cfg("teams",    _default_teams())
    content  = generate_param_py(targets, db, schedule, teams)

    # 書き出し先を決定
    dest = PARAM_FILE if PARAM_FILE.parent.exists() else CONFIG_DIR / "param.py"

    # 既存ファイルを .bak として退避
    if dest.exists():
        shutil.copy2(dest, str(dest) + ".bak")

    dest.write_text(content)


# ─────────────────────────── 内部処理: crontab 更新 ───────────────────────────

def _apply_crontab(schedule: dict):
    """
    システムの crontab を更新して SLA チェックのスケジュールを反映する。

    引数:
        schedule : スケジュール設定 (_default_schedule() と同じ構造)

    処理フロー:
        1. `crontab -l` で現在の crontab をすべて取得
        2. CRON_TAG ("# SLA-MANAGED") を含む行を除去
           （前回の SLA-MANAGED エントリをすべて削除）
        3. 有効チームごとに新しい cron エントリを生成して追記
        4. `crontab -` に全行を書き込んで crontab を更新

    生成される cron エントリの例:
        */5 * * * * /home/user/check-sla.sh team01 # SLA-MANAGED
        */5 * * * * /home/user/check-sla.sh team02 # SLA-MANAGED
        ...

    エラー処理:
        - `crontab` コマンドが存在しない環境（開発 PC 等）は FileNotFoundError を
          無視して静かにスキップする
        - crontab -l がゼロ件（空 crontab）の場合も正常に動作する

    注意:
        crontab はユーザー単位のスケジューラ。このサーバーを実行しているユーザーの
        crontab が更新される。root で実行する場合は root の crontab が更新される。
    """
    teams     = _cfg("teams", _default_teams())
    script    = schedule.get("script_path", "/home/user/check-sla.sh")
    cron_expr = f"{schedule['cron_min']} {schedule['cron_hour']} {schedule['cron_rest']}"

    # 有効チームのみ cron エントリを生成
    new_lines = [
        f"{cron_expr} {script} {t['id']} {CRON_TAG}"
        for t in teams
        if t.get("enabled")
    ]

    try:
        # 現在の crontab を取得（ユーザーの crontab が空の場合は stdout が空文字になる）
        existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True)

        # SLA-MANAGED タグを含まない行だけ残す（手動追加のエントリを保護）
        old_lines = [l for l in existing.stdout.splitlines() if CRON_TAG not in l]

        # 古い SLA エントリを除いた行 + 新しい SLA エントリを結合して crontab を更新
        crontab_content = "\n".join(old_lines + new_lines) + "\n"
        proc = subprocess.run(
            ["crontab", "-"],         # stdin から crontab を読み込むモード
            input=crontab_content,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            app.logger.warning(f"crontab update failed: {proc.stderr}")
    except FileNotFoundError:
        # crontab コマンドがない環境 (macOS 開発環境や Docker 等) は無視
        pass


# ─────────────────────────── フロントエンド配信 ───────────────────────────

@app.route("/")
def index():
    """
    ルートパス "/" にアクセスされた場合に static/index.html を返す。

    備考:
        Flask の send_from_directory はパストラバーサル攻撃を防ぐ安全なファイル配信。
    """
    return send_from_directory("static", "index.html")


@app.route("/<path:path>")
def static_files(path):
    """
    static/ 配下のその他のファイル (CSS, JS, favicon 等) を配信する。

    引数:
        path : static/ からの相対パス

    備考:
        現在はフロントエンドが index.html 1 ファイルにすべて内包されているため
        実質的には未使用だが、将来のファイル分割に対応する保険として残す。
    """
    return send_from_directory("static", path)


# ─────────────────────────── エントリポイント ───────────────────────────

if __name__ == "__main__":
    # 環境変数 PORT が設定されていればそのポートで起動、なければ 5000 番
    port = int(os.environ.get("PORT", 5000))
    print(f"SLA管理コンソール起動中... http://localhost:{port}")

    # debug=True: コード変更時に自動再起動、エラー時に詳細スタックトレースを表示。
    # 本番環境では debug=False にして gunicorn 等で起動すること。
    app.run(host="0.0.0.0", port=port, debug=True)

import sys
import json
import subprocess
import shutil
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# ───────────────────────────── 設定 ─────────────────────────────
BASE_DIR   = Path(__file__).parent
CONFIG_DIR = BASE_DIR / "config"
PARAM_FILE = Path("/home/user/sla.py").parent / "param.py"   # 本番パス
CRON_TAG   = "# SLA-MANAGED"                                  # crontab識別タグ
LOG_DIR    = Path("/home/user/log")

CONFIG_DIR.mkdir(exist_ok=True)

app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app)


# ───────────────────────────── ユーティリティ ─────────────────────────────
def _cfg(name: str, default=None):
    """config/<name>.json を読む。なければ default を返す。"""
    path = CONFIG_DIR / f"{name}.json"
    if path.exists():
        return json.loads(path.read_text())
    return default


def _save_cfg(name: str, data):
    path = CONFIG_DIR / f"{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _default_targets():
    return {
        "sla01": {"type": "ping", "desc": "RTホスト疎通",
                  "ips": ["1.1.1.1","2.2.1.1","3.3.1.1","4.4.1.1","5.5.1.1","6.6.1.1","7.7.1.1","8.8.1.1","9.9.1.1"]},
        "sla02": {"type": "ping", "desc": "RTホスト疎通",
                  "ips": ["1.1.2.2","2.2.2.2","3.3.2.2","4.4.2.2","5.5.2.2","6.6.2.2","7.7.2.2","8.8.2.2","9.9.2.2"]},
        "sla03": {"type": "ping", "desc": "RTホスト疎通",
                  "ips": ["1.1.3.3","2.2.3.3","3.3.3.3","4.4.3.3","5.5.3.3","6.6.3.3","7.7.3.3","8.8.3.3","9.9.3.3"]},
        "sla04": {"type": "ping", "desc": "RTホスト疎通",
                  "ips": ["1.1.4.4","2.2.4.4","3.3.4.4","4.4.4.4","5.5.4.4","6.6.4.4","7.7.4.4","8.8.4.4","9.9.4.4"]},
        "sla05": {"type": "ping", "desc": "RTホスト疎通",
                  "ips": ["1.1.5.5","2.2.5.5","3.3.5.5","4.4.5.5","5.5.5.5","6.6.5.5","7.7.5.5","8.8.5.5","9.9.5.5"]},
        "sla06": {"type": "http", "desc": "web VIP HTTP確認",
                  "ips": ["192.168.12.1","192.168.22.1","192.168.32.1","192.168.42.1",
                          "192.168.52.1","192.168.62.1","192.168.72.1","192.168.82.1","192.168.92.1"]},
    }


def _default_teams():
    return [{"id": f"team0{i}", "name": f"team0{i}", "enabled": True} for i in range(1, 10)]


def _default_db():
    return {"host": "localhost", "port": "8086",
            "username": "user", "password": "user", "name": "bc_db"}


def _default_schedule():
    return {"cron_min": "*/5", "cron_hour": "*", "cron_rest": "* * *",
            "http_timeout": 7.0, "script_path": "/home/user/check-sla.sh"}


# ───────────────────────────── param.py 生成 ─────────────────────────────
def generate_param_py(targets: dict, db: dict, schedule: dict, teams: list) -> str:
    """targets / db / schedule から param.py の内容を生成する。"""
    lines = [
        "# このファイルはSLA管理コンソールによって自動生成されます",
        f"# 生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]

    # SLAターゲット
    for sla_id, sla in targets.items():
        var = f"{sla_id}_rt_host" if sla["type"] == "ping" else f"{sla_id}_web_vip"
        lines.append(f"# {sla_id} ({sla.get('desc', '')})")
        lines.append(f"{var} = [")
        for ip in sla["ips"]:
            lines.append(f'        "{ip}",')
        lines.append("]")
        lines.append("")

    # チーム数
    lines.append(f"num_of_team = {len([t for t in teams if t.get('enabled', True)])}")
    lines.append("")

    # DB設定
    lines += [
        f'db_host = "{db["host"]}"',
        f'db_port = "{db["port"]}"',
        f'db_username = "{db["username"]}"',
        f'db_password = "{db["password"]}"',
        f'db_name = "{db["name"]}"',
        "",
    ]

    # SLAスコア
    for sla_id in targets:
        lines.append(f"{sla_id}_score = 100")
    lines.append("")

    # HTTPタイムアウト
    lines.append(f"http_timeout = {schedule['http_timeout']}")
    lines.append("")

    # taskリスト / fusei (全0)
    for task in [f"task{str(i).zfill(2)}" for i in range(1, 10)]:
        lines.append(f"{task} = [{', '.join(['0'] * len(teams))}]")
    lines.append("")
    lines.append(f"fusei = [{', '.join(['0'] * len(teams))}]")
    lines.append("")

    return "\n".join(lines)


# ───────────────────────────── API: チーム ─────────────────────────────
@app.route("/api/teams", methods=["GET"])
def get_teams():
    return jsonify(_cfg("teams", _default_teams()))


@app.route("/api/teams", methods=["POST"])
def save_teams():
    data = request.get_json()
    _save_cfg("teams", data)
    _apply_param_py()
    return jsonify({"ok": True, "message": "チーム設定を保存しました"})


# ───────────────────────────── API: ターゲット ─────────────────────────────
@app.route("/api/targets", methods=["GET"])
def get_targets():
    return jsonify(_cfg("targets", _default_targets()))


@app.route("/api/targets", methods=["POST"])
def save_targets():
    data = request.get_json()
    _save_cfg("targets", data)
    _apply_param_py()
    return jsonify({"ok": True, "message": "ターゲット設定を保存し、param.py を更新しました"})


# ───────────────────────────── API: スケジュール ─────────────────────────────
@app.route("/api/schedule", methods=["GET"])
def get_schedule():
    return jsonify(_cfg("schedule", _default_schedule()))


@app.route("/api/schedule", methods=["POST"])
def save_schedule():
    data = request.get_json()
    _save_cfg("schedule", data)
    _apply_crontab(data)
    _apply_param_py()
    return jsonify({"ok": True, "message": "スケジュールを保存し、crontabを更新しました"})


# ───────────────────────────── API: データベース ─────────────────────────────
@app.route("/api/database", methods=["GET"])
def get_database():
    cfg = _cfg("database", _default_db())
    cfg.pop("password", None)   # パスワードはGETで返さない
    return jsonify(cfg)


@app.route("/api/database", methods=["POST"])
def save_database():
    data = request.get_json()
    existing = _cfg("database", _default_db())
    if not data.get("password"):
        data["password"] = existing.get("password", "")
    _save_cfg("database", data)
    _apply_param_py()
    return jsonify({"ok": True, "message": "DB設定を保存しました"})


@app.route("/api/database/test", methods=["POST"])
def test_database():
    cfg = _cfg("database", _default_db())
    try:
        from influxdb import InfluxDBClient
        client = InfluxDBClient(
            host=cfg["host"], port=int(cfg["port"]),
            username=cfg.get("username", ""),
            password=cfg.get("password", ""),
            database=cfg["name"],
        )
        dbs = client.get_list_database()
        return jsonify({"ok": True, "message": f"接続成功。DB数: {len(dbs)}", "databases": [d["name"] for d in dbs]})
    except Exception as e:
        return jsonify({"ok": False, "message": f"接続失敗: {e}"}), 500


@app.route("/api/database/measurements", methods=["GET"])
def get_measurements():
    cfg = _cfg("database", _default_db())
    try:
        from influxdb import InfluxDBClient
        client = InfluxDBClient(
            host=cfg["host"], port=int(cfg["port"]),
            username=cfg.get("username", ""),
            password=cfg.get("password", ""),
            database=cfg["name"],
        )
        result = client.get_list_measurements()
        measurements = []
        for m in result:
            name = m["name"]
            try:
                cnt = list(client.query(f'SELECT count(*) FROM "{name}"').get_points())
                row_count = list(cnt[0].values())[1] if cnt else 0
            except Exception:
                row_count = 0
            measurements.append({"name": name, "rows": row_count})
        return jsonify(measurements)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/database/reset/<team>", methods=["DELETE"])
def reset_team(team):
    cfg = _cfg("database", _default_db())
    try:
        from influxdb import InfluxDBClient
        client = InfluxDBClient(
            host=cfg["host"], port=int(cfg["port"]),
            username=cfg.get("username", ""),
            password=cfg.get("password", ""),
            database=cfg["name"],
        )
        client.drop_measurement(team)
        return jsonify({"ok": True, "message": f"{team} のデータを削除しました"})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@app.route("/api/database/reset-all", methods=["DELETE"])
def reset_all():
    cfg = _cfg("database", _default_db())
    try:
        from influxdb import InfluxDBClient
        client = InfluxDBClient(
            host=cfg["host"], port=int(cfg["port"]),
            username=cfg.get("username", ""),
            password=cfg.get("password", ""),
            database=cfg["name"],
        )
        client.drop_database(cfg["name"])
        client.create_database(cfg["name"])
        return jsonify({"ok": True, "message": "全データを初期化しました"})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


# ───────────────────────────── API: SLA手動実行 ─────────────────────────────
@app.route("/api/run-check", methods=["POST"])
def run_check():
    body = request.get_json() or {}
    teams = body.get("teams")
    sched = _cfg("schedule", _default_schedule())
    script = sched.get("script_path", "/home/user/check-sla.sh")
    results = []
    target_teams = teams if teams else [t["id"] for t in _cfg("teams", _default_teams()) if t.get("enabled")]
    for team in target_teams:
        try:
            proc = subprocess.run(
                ["bash", script, team],
                capture_output=True, text=True, timeout=30
            )
            results.append({
                "team": team,
                "ok": proc.returncode == 0,
                "stdout": proc.stdout[-500:],
                "stderr": proc.stderr[-200:],
            })
        except subprocess.TimeoutExpired:
            results.append({"team": team, "ok": False, "stdout": "", "stderr": "timeout"})
        except FileNotFoundError:
            results.append({"team": team, "ok": False, "stdout": "", "stderr": f"スクリプトが見つかりません: {script}"})
    return jsonify({"ok": True, "results": results})


# ───────────────────────────── API: ログ ─────────────────────────────
@app.route("/api/logs", methods=["GET"])
def get_logs():
    team = request.args.get("team", "")
    lines = []
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        if team:
            files = [LOG_DIR / f"sla_{team}_{today}.log"]
        else:
            files = sorted(LOG_DIR.glob(f"sla_*_{today}.log"), reverse=True)[:18]
        for f in files:
            if f.exists():
                for line in f.read_text(errors="replace").splitlines()[-100:]:
                    if line.strip():
                        tm = f.stem.split("_")[1] if "_" in f.stem else "?"
                        lines.append({"team": tm, "text": line, "time": today})
    except Exception as e:
        lines.append({"team": "system", "text": f"ログ読み込みエラー: {e}", "time": ""})
    return jsonify(lines[-200:])


# ───────────────────────────── API: param.py エクスポート ─────────────────────────────
@app.route("/api/export/param-py", methods=["GET"])
def export_param_py():
    targets  = _cfg("targets",  _default_targets())
    db       = _cfg("database", _default_db())
    schedule = _cfg("schedule", _default_schedule())
    teams    = _cfg("teams",    _default_teams())
    content  = generate_param_py(targets, db, schedule, teams)
    from flask import Response
    return Response(content, mimetype="text/plain",
                    headers={"Content-Disposition": "attachment; filename=param.py"})


# ───────────────────────────── 内部処理 ─────────────────────────────
def _apply_param_py():
    """param.py を自動生成してバックアップ付きで書き出す。"""
    targets  = _cfg("targets",  _default_targets())
    db       = _cfg("database", _default_db())
    schedule = _cfg("schedule", _default_schedule())
    teams    = _cfg("teams",    _default_teams())
    content  = generate_param_py(targets, db, schedule, teams)

    # 保存先: 本番パスが存在すればそこに、なければ config/ に
    dest = PARAM_FILE if PARAM_FILE.parent.exists() else CONFIG_DIR / "param.py"
    if dest.exists():
        shutil.copy2(dest, str(dest) + ".bak")
    dest.write_text(content)


def _apply_crontab(schedule: dict):
    """crontabを更新する (既存のSLA管理エントリを置き換え)。"""
    teams    = _cfg("teams", _default_teams())
    script   = schedule.get("script_path", "/home/user/check-sla.sh")
    cron_expr = f"{schedule['cron_min']} {schedule['cron_hour']} {schedule['cron_rest']}"
    new_lines = [f"{cron_expr} {script} {t['id']} {CRON_TAG}" for t in teams if t.get("enabled")]

    try:
        existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        old_lines = [l for l in existing.stdout.splitlines() if CRON_TAG not in l]
        crontab_content = "\n".join(old_lines + new_lines) + "\n"
        proc = subprocess.run(["crontab", "-"], input=crontab_content, capture_output=True, text=True)
        if proc.returncode != 0:
            app.logger.warning(f"crontab update failed: {proc.stderr}")
    except FileNotFoundError:
        pass   # crontabコマンドがない環境 (開発時) は無視


# ───────────────────────────── フロントエンド配信 ─────────────────────────────
@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/<path:path>")
def static_files(path):
    return send_from_directory("static", path)


# ───────────────────────────── 起動 ─────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"SLA管理コンソール起動中... http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)
