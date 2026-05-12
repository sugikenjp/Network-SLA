#!/usr/bin/env python3
"""
SLA監視管理コンソール - Flask APIサーバー
"""
import os
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
