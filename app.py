#!/usr/bin/env python3
"""
SLA監視管理コンソール - Flask APIサーバー（1チーム専用 Docker版）
=================================================================
概要:
  1チームの SLA 疎通チェックコンテナの設定をブラウザから管理する REST API サーバー。

主な責務:
  - チーム・ターゲットIP・スケジュール・タスク・DB設定を JSON ファイルで永続化
  - 設定変更時に param.py を自動生成・上書き（バックアップ付き）
  - check-sla.sh を手動トリガーで実行
  - InfluxDB への接続テスト・Measurement 管理・データ削除

マルチチーム版からの変更点:
  - チーム管理（/api/teams）を廃止 → /api/team（単一チーム）に変更
  - ターゲット IP はリストからスカラー値に変更
  - タスク管理（/api/tasks）を新設
  - generate_param_py() を Docker版 param.py 形式に合わせた
  - crontab の直接更新を廃止（docker-compose.yml の CRON_SCHEDULE で管理）
  - /api/run-check はこのコンテナの1チームのみ実行

起動方法:
  python3 app.py
  または: PORT=8080 python3 app.py

依存パッケージ: flask, flask-cors, influxdb
"""

import os
import json
import subprocess
import shutil
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, Response
from flask_cors import CORS


# ─────────────────────────── パス・定数の定義 ───────────────────────────

BASE_DIR   = Path(__file__).parent
CONFIG_DIR = BASE_DIR / "config"

# param.py の書き出し先
# start.sh で起動する場合: app.py と同じディレクトリに生成
# Docker コンテナの場合: /app/param.py に生成（volume マウントでホスト側と共有）
PARAM_FILE = BASE_DIR / "param.py"

# check-sla.sh が出力するログのディレクトリ
# Docker コンテナの場合: /var/log/sla（volume マウントでホスト側と共有）
# ローカル実行の場合: app.py と同じディレクトリの log/
LOG_DIR = Path(os.environ.get("LOG_DIR", str(BASE_DIR / "log")))

# コンテナ内の cron 設定ファイルパス
# Docker版では /etc/cron.d/sla-check に配置している
CRON_FILE = Path("/etc/cron.d/sla-check")

CONFIG_DIR.mkdir(exist_ok=True)

app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app)


# ─────────────────────────── ユーティリティ関数 ───────────────────────────

def _cfg(name: str, default=None):
    """config/<name>.json を読み込んで返す。存在しない場合は default を返す。"""
    path = CONFIG_DIR / f"{name}.json"
    if path.exists():
        return json.loads(path.read_text())
    return default


def _save_cfg(name: str, data):
    """Python オブジェクトを config/<name>.json に書き込む。"""
    path = CONFIG_DIR / f"{name}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


# ─────────────────────────── デフォルト設定値 ───────────────────────────

def _default_team():
    """初期状態のチーム設定を返す。"""
    return {"id": "team01", "name": "team01"}


def _default_targets():
    """
    初期状態の監視ターゲット設定を返す。
    IP はスカラー値（マルチチーム版のリストから変更）。
    """
    return {
        "sla01": {"type": "ping", "desc": "RTホスト疎通",     "ip": "1.1.1.1"},
        "sla02": {"type": "ping", "desc": "RTホスト疎通",     "ip": "1.1.2.2"},
        "sla03": {"type": "ping", "desc": "RTホスト疎通",     "ip": "1.1.3.3"},
        "sla04": {"type": "ping", "desc": "RTホスト疎通",     "ip": "1.1.4.4"},
        "sla05": {"type": "ping", "desc": "RTホスト疎通",     "ip": "1.1.5.5"},
        "sla06": {"type": "http", "desc": "web VIP HTTP確認", "ip": "192.168.1.1"},
    }


def _default_db():
    """初期状態の InfluxDB 接続設定を返す。"""
    return {
        "host":     "",        # 例: "192.168.1.100"（必須・要変更）
        "port":     "8086",
        "username": "user",
        "password": "user",
        "name":     "bc_db",
    }


def _default_schedule():
    """初期状態のスケジュール設定を返す。"""
    return {
        "cron_schedule": "*/5 * * * *",
        "http_timeout":  7.0,
        "script_path":   str(BASE_DIR / "check-sla.sh"),
    }


def _default_tasks():
    """初期状態のタスクポイント・不正減点設定を返す。"""
    return {
        "task01": 0, "task02": 0, "task03": 0,
        "task04": 0, "task05": 0, "task06": 0,
        "task07": 0, "task08": 0, "task09": 0,
        "fusei":  0,
    }


# ─────────────────────────── param.py 生成ロジック ───────────────────────────

def generate_param_py(team: dict, targets: dict, db: dict,
                      schedule: dict, tasks: dict) -> str:
    """
    現在の設定から Docker版 param.py のソースコードを生成する。

    マルチチーム版との違い:
        - team_name を先頭に出力
        - IP はスカラー値（リストではない）
        - num_of_team を出力しない
        - task / fusei はスカラー値
    """
    lines = [
        "# このファイルはSLA管理コンソールによって自動生成されます",
        f"# 生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "# ── チーム識別情報 ──",
        f'team_name = "{team["id"]}"',
        "",
        "# ── SLAターゲットIPアドレス ──",
    ]

    for sla_id, sla in targets.items():
        var = f"{sla_id}_rt_host" if sla["type"] == "ping" else f"{sla_id}_web_vip"
        lines.append(f'# {sla_id} ({sla.get("desc", "")})')
        lines.append(f'{var} = "{sla["ip"]}"')
    lines.append("")

    lines.append("# ── SLAスコア定義 ──")
    for sla_id in targets:
        lines.append(f"{sla_id}_score = 100")
    lines.append("")

    lines += [
        "# ── InfluxDB接続情報 ──",
        f'db_host     = "{db["host"]}"',
        f'db_port     = "{db["port"]}"',
        f'db_username = "{db["username"]}"',
        f'db_password = "{db["password"]}"',
        f'db_name     = "{db["name"]}"',
        "",
        "# ── HTTPタイムアウト ──",
        f'http_timeout = {schedule["http_timeout"]}',
        "",
        "# ── タスクポイント（0=未完了、正の整数=完了時加算ポイント） ──",
    ]
    for key in ["task01","task02","task03","task04","task05",
                "task06","task07","task08","task09"]:
        lines.append(f"{key} = {tasks.get(key, 0)}")
    lines += [
        "",
        "# ── 不正行為減点（0=減点なし） ──",
        f"fusei = {tasks.get('fusei', 0)}",
        "",
    ]
    return "\n".join(lines)


# ─────────────────────────── API: チーム設定 ───────────────────────────

@app.route("/api/team", methods=["GET"])
def get_team():
    """チーム設定を取得する。"""
    return jsonify(_cfg("team", _default_team()))


@app.route("/api/team", methods=["POST"])
def save_team():
    """
    チーム設定を保存し、param.py を再生成する。
    id を変更した場合は docker-compose.yml の TEAM_NAME も同じ値に変更すること。
    """
    data = request.get_json()
    _save_cfg("team", data)
    _apply_param_py()
    return jsonify({"ok": True, "message": "チーム設定を保存しました"})


# ─────────────────────────── API: 監視ターゲット ───────────────────────────

@app.route("/api/targets", methods=["GET"])
def get_targets():
    """監視ターゲット設定を取得する。"""
    return jsonify(_cfg("targets", _default_targets()))


@app.route("/api/targets", methods=["POST"])
def save_targets():
    """監視ターゲット設定を保存し、param.py を再生成する。"""
    data = request.get_json()
    _save_cfg("targets", data)
    _apply_param_py()
    return jsonify({"ok": True, "message": "ターゲット設定を保存し、param.py を更新しました"})


# ─────────────────────────── API: タスク・不正減点 ───────────────────────────

@app.route("/api/tasks", methods=["GET"])
def get_tasks():
    """タスクポイント・不正減点設定を取得する。"""
    return jsonify(_cfg("tasks", _default_tasks()))


@app.route("/api/tasks", methods=["POST"])
def save_tasks():
    """タスクポイント・不正減点設定を保存し、param.py を再生成する。"""
    data = request.get_json()
    _save_cfg("tasks", data)
    _apply_param_py()
    return jsonify({"ok": True, "message": "タスク設定を保存しました"})


# ─────────────────────────── API: スケジュール ───────────────────────────

@app.route("/api/schedule", methods=["GET"])
def get_schedule():
    """スケジュール設定を取得する。"""
    return jsonify(_cfg("schedule", _default_schedule()))


@app.route("/api/schedule", methods=["POST"])
def save_schedule():
    """
    スケジュール設定を保存し、cron と param.py に即時反映する。

    処理:
        1. config/schedule.json に保存
        2. /etc/cron.d/sla-check を書き換えて cron に即時反映
        3. param.py を再生成（http_timeout の変更を反映）

    備考:
        cron デーモンは /etc/cron.d/ の変更を自動検知するため
        コンテナの再起動は不要。
    """
    data = request.get_json()
    _save_cfg("schedule", data)
    cron_result = _apply_crontab(data)
    _apply_param_py()
    return jsonify({
        "ok": True,
        "message": cron_result,
    })


# ─────────────────────────── API: データベース ───────────────────────────

@app.route("/api/database", methods=["GET"])
def get_database():
    """InfluxDB 接続設定を取得する。パスワードはレスポンスに含めない。"""
    cfg = _cfg("database", _default_db())
    cfg.pop("password", None)
    return jsonify(cfg)


@app.route("/api/database", methods=["POST"])
def save_database():
    """InfluxDB 接続設定を保存し、param.py を再生成する。"""
    data = request.get_json()
    existing = _cfg("database", _default_db())
    if not data.get("password"):
        data["password"] = existing.get("password", "")
    _save_cfg("database", data)
    _apply_param_py()
    return jsonify({"ok": True, "message": "DB設定を保存しました"})


@app.route("/api/database/test", methods=["POST"])
def test_database():
    """InfluxDB への実接続を試みる。"""
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
        return jsonify({
            "ok": True,
            "message": f"接続成功。DB数: {len(dbs)}",
            "databases": [d["name"] for d in dbs],
        })
    except Exception as e:
        return jsonify({"ok": False, "message": f"接続失敗: {e}"}), 500


@app.route("/api/database/measurements", methods=["GET"])
def get_measurements():
    """Measurement 一覧と行数を取得する。"""
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
    """指定チームの Measurement を削除する（取り消し不可）。"""
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
    """データベース全体を削除して再作成する（取り消し不可）。"""
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


# ─────────────────────────── API: SLA 手動実行 ───────────────────────────

def _parse_sla_results(stdout: str) -> dict:
    """
    sla.py の stdout から RESULT: 行をパースして個別チェック結果を返す。

    sla.py が出力する形式:
        RESULT:ping:sla01:OK:1.1.1.1
        RESULT:ping:sla02:NG:1.1.2.2
        RESULT:http:sla06:OK:192.168.1.1
        RESULT:db:write:OK
        RESULT:log:write:OK

    戻り値:
        {
          "ping": {"sla01": {"ok": True,  "ip": "1.1.1.1"},
                   "sla02": {"ok": False, "ip": "1.1.2.2"}, ...},
          "http": {"sla06": {"ok": True,  "ip": "192.168.1.1"}},
          "db":   {"write": {"ok": True}},
          "log":  {"write": {"ok": True}},
        }
    """
    parsed = {"ping": {}, "http": {}, "db": {}, "log": {}}
    for line in stdout.splitlines():
        if not line.startswith("RESULT:"):
            continue
        parts = line.split(":")
        # RESULT:ping:sla01:OK:1.1.1.1  → 5要素
        # RESULT:db:write:OK             → 4要素
        if len(parts) < 4:
            continue
        kind   = parts[1]  # ping / http / db / log
        target = parts[2]  # sla01〜06 / write
        status = parts[3]  # OK / NG
        ip     = parts[4] if len(parts) > 4 else ""
        ok     = (status == "OK")
        if kind in parsed:
            parsed[kind][target] = {"ok": ok, "ip": ip}
    return parsed


@app.route("/api/run-check", methods=["POST"])
def run_check():
    """
    check-sla.sh をこのコンテナの担当チームで手動実行する。

    レスポンス (JSON):
        {
          "ok": true,
          "results": [{
            "team": "team01",
            "ok": true,
            "details": {
              "ping": {"sla01": {"ok": true,  "ip": "1.1.1.1"},
                       "sla02": {"ok": false, "ip": "1.1.2.2"}, ...},
              "http": {"sla06": {"ok": true,  "ip": "192.168.1.1"}},
              "db":   {"write": {"ok": true}},
              "log":  {"write": {"ok": true}}
            },
            "stdout": "...",
            "stderr": "..."
          }]
        }
    """
    team    = _cfg("team",     _default_team())
    sched   = _cfg("schedule", _default_schedule())
    script  = sched.get("script_path", str(BASE_DIR / "check-sla.sh"))
    team_id = team["id"]

    try:
        proc = subprocess.run(
            ["bash", script, team_id],
            capture_output=True, text=True, timeout=60,
        )
        details = _parse_sla_results(proc.stdout)
        result = {
            "team":    team_id,
            "ok":      proc.returncode == 0,
            "details": details,
            "stdout":  proc.stdout[-1000:],
            "stderr":  proc.stderr[-300:],
        }
    except subprocess.TimeoutExpired:
        result = {"team": team_id, "ok": False, "details": {}, "stdout": "", "stderr": "timeout"}
    except FileNotFoundError:
        result = {"team": team_id, "ok": False, "details": {}, "stdout": "",
                  "stderr": f"スクリプトが見つかりません: {script}"}

    return jsonify({"ok": True, "results": [result]})


# ─────────────────────────── API: ログ取得 ───────────────────────────

@app.route("/api/logs", methods=["GET"])
def get_logs():
    """
    このチームの当日ログを取得する。
    ログファイルパス: <LOG_DIR>/sla_<team_id>_<YYYY-MM-DD>.log
    """
    team    = _cfg("team", _default_team())
    team_id = team["id"]
    lines   = []
    try:
        today    = datetime.now().strftime("%Y-%m-%d")
        log_file = LOG_DIR / f"sla_{team_id}_{today}.log"
        if log_file.exists():
            for line in log_file.read_text(errors="replace").splitlines()[-200:]:
                if line.strip():
                    lines.append({"team": team_id, "text": line, "time": today})
    except Exception as e:
        lines.append({"team": "system", "text": f"ログ読み込みエラー: {e}", "time": ""})
    return jsonify(lines)


# ─────────────────────────── API: param.py ダウンロード ───────────────────────────

@app.route("/api/export/param-py", methods=["GET"])
def export_param_py():
    """現在の設定から param.py を生成してダウンロードさせる。"""
    content = generate_param_py(
        _cfg("team",     _default_team()),
        _cfg("targets",  _default_targets()),
        _cfg("database", _default_db()),
        _cfg("schedule", _default_schedule()),
        _cfg("tasks",    _default_tasks()),
    )
    return Response(
        content,
        mimetype="text/plain",
        headers={"Content-Disposition": "attachment; filename=param.py"},
    )


# ─────────────────────────── 内部処理: crontab 即時更新 ───────────────────────────

def _apply_crontab(schedule: dict) -> str:
    """
    /etc/cron.d/sla-check の実行間隔を書き換えて cron に即時反映する。

    cron デーモン（vixie-cron / cronie）は /etc/cron.d/ ファイルの変更を
    自動検知して再読み込みするため、コンテナの再起動は不要。

    引数:
        schedule : スケジュール設定 {"cron_schedule": "*/5 * * * *", ...}

    戻り値:
        結果メッセージ文字列（API レスポンスの message に使用）

    処理フロー:
        1. CRON_FILE が存在するか確認（Docker環境かどうかの判定）
        2. 現在のファイル内容を読み込む
        3. cron 式の行（# SLA-CHECK タグ付き）を新しい間隔で置き換える
        4. ファイルに書き戻す
    """
    cron_expr = schedule.get("cron_schedule", "*/5 * * * *").strip()
    team      = _cfg("team", _default_team())
    team_id   = team["id"]
    script    = schedule.get("script_path", "/app/check-sla.sh")

    # Docker環境以外（ローカルの start.sh 起動）では CRON_FILE が存在しない
    if not CRON_FILE.exists():
        return (
            f"スケジュール設定を保存しました（http_timeout を param.py に反映）。\n"
            f"cron の間隔変更はローカル環境のため手動で crontab を設定してください。"
        )

    try:
        # 新しい cron エントリを生成
        # 例: */10 * * * * root /app/check-sla.sh team01
        new_line = f"{cron_expr} root {script} {team_id}\n"

        # 既存ファイルの cron エントリ行を置き換える
        # コメント行と空行はそのまま保持し、実行行だけ更新する
        existing = CRON_FILE.read_text()
        new_lines = []
        replaced = False
        for line in existing.splitlines(keepends=True):
            # コメント行・空行はそのまま保持
            stripped = line.strip()
            if stripped.startswith("#") or stripped == "":
                new_lines.append(line)
            else:
                # 最初の実行行を新しい内容に置き換える
                if not replaced:
                    new_lines.append(new_line)
                    replaced = True
                # 2行目以降の実行行は削除（1エントリのみ管理）

        # 実行行が存在しなかった場合は末尾に追加
        if not replaced:
            new_lines.append(new_line)

        CRON_FILE.write_text("".join(new_lines))
        app.logger.info(f"crontab 更新: {new_line.strip()}")
        return (
            f"スケジュールを保存しました。\n"
            f"cron を「{cron_expr}」に更新しました（再起動不要）。"
        )

    except PermissionError:
        # 権限エラー（Docker以外の環境で root 以外で実行した場合など）
        app.logger.warning(f"crontab 書き換え権限なし: {CRON_FILE}")
        return (
            f"スケジュール設定を保存しました。\n"
            f"cron ファイルへの書き込み権限がないため、間隔は変更されませんでした。\n"
            f"docker compose restart で再起動してください。"
        )
    except Exception as e:
        app.logger.error(f"crontab 更新エラー: {e}")
        return f"設定を保存しましたが、cron の更新に失敗しました: {e}"


# ─────────────────────────── 内部処理: param.py 書き出し ───────────────────────────

def _apply_param_py():
    """
    現在の全設定から param.py を生成してファイルシステムに書き出す。

    書き出し先: PARAM_FILE（app.py と同じディレクトリの param.py）
    バックアップ: 上書き前に param.py.bak に退避する。
    """
    content = generate_param_py(
        _cfg("team",     _default_team()),
        _cfg("targets",  _default_targets()),
        _cfg("database", _default_db()),
        _cfg("schedule", _default_schedule()),
        _cfg("tasks",    _default_tasks()),
    )
    if PARAM_FILE.exists():
        shutil.copy2(PARAM_FILE, str(PARAM_FILE) + ".bak")
    PARAM_FILE.write_text(content)


# ─────────────────────────── フロントエンド配信 ───────────────────────────

@app.route("/")
def index():
    """static/index.html を返す。"""
    return send_from_directory("static", "index.html")


@app.route("/<path:path>")
def static_files(path):
    """static/ 配下のファイルを配信する。"""
    return send_from_directory("static", path)


# ─────────────────────────── エントリポイント ───────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"SLA管理コンソール起動中... http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)
