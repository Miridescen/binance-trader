"""
Flask API，为前端提供数据（从 SQLite 数据库读取）
"""
import os
from datetime import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS
from binance_client import auth_get
import db

app = Flask(__name__)
CORS(app)


def _strip_id(rows):
    """移除 id 字段，保持与原 CSV API 返回格式一致"""
    for r in rows:
        r.pop("id", None)
    return rows


@app.route("/api/positions")
def positions():
    date = request.args.get("date")
    if date:
        return jsonify(_strip_id(db.get_positions_log_by_date(date)))
    # 默认返回今天
    today = __import__('datetime').datetime.now().strftime("%Y-%m-%d")
    return jsonify(_strip_id(db.get_positions_log_by_date(today)))

@app.route("/api/open_log")
def open_log():
    return jsonify(_strip_id(db.get_open_log_all()))

@app.route("/api/virtual_log")
def virtual_log():
    return jsonify(_strip_id(db.get_virtual_log_all()))

@app.route("/api/daily_summary")
def daily_summary():
    days = request.args.get("days", type=int)
    return jsonify(db.get_daily_summary_all(days=days))

@app.route("/api/btc_indicators")
def btc_indicators():
    return jsonify(_strip_id(db.get_btc_indicators(500)))

@app.route("/api/btc_signals")
def btc_signals():
    return jsonify(_strip_id(db.get_btc_signal_log_all()))

@app.route("/api/positions_detail")
def positions_detail():
    time_str = request.args.get("time")
    if time_str:
        return jsonify(_strip_id(db.get_positions_detail_by_time(time_str)))
    date = request.args.get("date")
    if date:
        return jsonify(_strip_id(db.get_positions_detail_by_date(date)))
    return jsonify(_strip_id(db.get_positions_detail_all()))

@app.route("/api/positions_detail/dates")
def positions_detail_dates():
    return jsonify(db.get_positions_detail_dates())

@app.route("/api/positions_detail/times")
def positions_detail_times():
    date = request.args.get("date")
    if not date:
        return jsonify([])
    return jsonify(db.get_positions_detail_times(date))

@app.route("/api/virtual_detail")
def virtual_detail():
    time_str = request.args.get("time")
    if time_str:
        return jsonify(_strip_id(db.get_virtual_detail_by_time(time_str)))
    date = request.args.get("date")
    if date:
        return jsonify(_strip_id(db.get_virtual_detail_by_date(date)))
    return jsonify(_strip_id(db.get_virtual_detail_all()))

@app.route("/api/virtual_detail/dates")
def virtual_detail_dates():
    return jsonify(db.get_virtual_detail_dates())

@app.route("/api/virtual_detail/times")
def virtual_detail_times():
    date = request.args.get("date")
    if not date:
        return jsonify([])
    return jsonify(db.get_virtual_detail_times(date))

_WINDOW_WHITELIST = {"4h", "8h", "12h"}


def _validate_window(w):
    if w not in _WINDOW_WHITELIST:
        return None
    return w


@app.route("/api/virtual_log_window")
def virtual_log_window():
    """按窗口取虚拟盘记录。?window=4h/8h/12h"""
    w = _validate_window(request.args.get("window", "4h"))
    if w is None:
        return jsonify({"error": "invalid window"}), 400
    with db.get_conn() as conn:
        rows = conn.execute(f"SELECT * FROM virtual_log_{w} ORDER BY id").fetchall()
        rows = [dict(r) for r in rows]
    return jsonify(_strip_id(rows))


@app.route("/api/virtual_detail_window")
def virtual_detail_window():
    """按窗口取虚拟盘快照。?window=4h/8h/12h&open_time=&side="""
    w = _validate_window(request.args.get("window", "4h"))
    if w is None:
        return jsonify({"error": "invalid window"}), 400
    log_id = request.args.get("log_id", type=int)
    open_time = request.args.get("open_time")
    side = request.args.get("side")
    log_table = f"virtual_log_{w}"
    det_table = f"virtual_detail_{w}"
    with db.get_conn() as conn:
        if log_id:
            rows = conn.execute(
                f"SELECT * FROM {det_table} WHERE log_id = ? ORDER BY time",
                (log_id,)
            ).fetchall()
        elif open_time and side:
            rows = conn.execute(
                f"""SELECT d.* FROM {det_table} d
                    JOIN {log_table} l ON d.log_id = l.id
                    WHERE l.open_time = ? AND l.side = ?
                    ORDER BY d.time, d.symbol""",
                (open_time, side)
            ).fetchall()
        elif open_time:
            rows = conn.execute(
                f"""SELECT d.* FROM {det_table} d
                    JOIN {log_table} l ON d.log_id = l.id
                    WHERE l.open_time = ?
                    ORDER BY d.time, d.symbol""",
                (open_time,)
            ).fetchall()
        else:
            return jsonify([])
        rows = [dict(r) for r in rows]
    return jsonify(_strip_id(rows))


@app.route("/api/virtual_groups")
def virtual_groups():
    """按 (open_time, side) 聚合的组级统计：用于"+10u 触发 vs 走完窗口"对照。
       ?window=4h/8h/12h"""
    w = _validate_window(request.args.get("window", "4h"))
    if w is None:
        return jsonify({"error": "invalid window"}), 400
    log_table = f"virtual_log_{w}"
    det_table = f"virtual_detail_{w}"
    timed_reason = f"{w}_timed"

    with db.get_conn() as conn:
        groups_rows = conn.execute(
            f"""SELECT open_time, window_end, side,
                       COUNT(*) AS n_orders,
                       SUM(CASE WHEN close_reason='组内+10u' THEN 1 ELSE 0 END) AS n_hit,
                       SUM(CASE WHEN close_reason=? THEN 1 ELSE 0 END) AS n_timed,
                       SUM(unrealized_pnl) AS sum_pnl_actual,
                       MAX(close_reason) AS close_reason
                FROM {log_table}
                WHERE close_time IS NOT NULL
                GROUP BY open_time, side
                ORDER BY open_time DESC, side""",
            (timed_reason,)
        ).fetchall()
        groups = [dict(r) for r in groups_rows]

        for g in groups:
            if g["n_hit"] > 0:
                row = conn.execute(
                    f"""SELECT SUM(d.unrealized_pnl) AS sum_pnl_held, d.time
                        FROM {det_table} d
                        JOIN {log_table} l ON d.log_id = l.id
                        WHERE l.open_time = ? AND l.side = ?
                        GROUP BY d.time
                        ORDER BY d.time DESC LIMIT 1""",
                    (g["open_time"], g["side"])
                ).fetchone()
                g["sum_pnl_if_held"] = row["sum_pnl_held"] if row else None
                g["last_detail_time"] = row["time"] if row else None
            else:
                g["sum_pnl_if_held"] = g["sum_pnl_actual"]
                g["last_detail_time"] = None
    return jsonify(groups)


# 兼容旧路由：默认 window=4h，行为同旧
@app.route("/api/virtual_log_4h")
def virtual_log_4h_legacy():
    return virtual_log_window()


@app.route("/api/virtual_4h_groups")
def virtual_4h_groups_legacy():
    return virtual_groups()


@app.route("/api/virtual_detail_4h")
def virtual_detail_4h_legacy():
    return virtual_detail_window()


@app.route("/api/realtime")
def realtime():
    try:
        account = auth_get("/fapi/v2/account")
        balance = next(
            (float(a["marginBalance"]) for a in account.get("assets", []) if a["asset"] == "USDT"),
            float(account.get("totalMarginBalance", 0))
        )

        positions = [p for p in account.get("positions", []) if float(p["positionAmt"]) != 0]
        long_pnl  = sum(float(p["unrealizedProfit"]) for p in positions if float(p["positionAmt"]) > 0)
        short_pnl = sum(float(p["unrealizedProfit"]) for p in positions if float(p["positionAmt"]) < 0)
        total_pnl = long_pnl + short_pnl
        long_count  = sum(1 for p in positions if float(p["positionAmt"]) > 0)
        short_count = sum(1 for p in positions if float(p["positionAmt"]) < 0)

        # 保证金占用
        margin_used = float(account.get("totalInitialMargin", 0))

        # 持仓明细用 positionRisk 接口（字段更完整）
        pos_risk = auth_get("/fapi/v2/positionRisk")
        active_risk = [p for p in pos_risk if float(p["positionAmt"]) != 0]

        # 从 open_log 获取最近一条未平仓记录的 side 标记，用于区分涨幅空/跌幅空
        side_map = {}
        try:
            with db.get_conn() as conn:
                rows = conn.execute(
                    "SELECT symbol, side FROM open_log WHERE close_time IS NULL ORDER BY id DESC"
                ).fetchall()
                for r in rows:
                    if r["symbol"] not in side_map:
                        side_map[r["symbol"]] = r["side"]
        except Exception:
            pass

        details = []
        for p in sorted(active_risk, key=lambda x: float(x["unRealizedProfit"]), reverse=True):
            amt = float(p["positionAmt"])
            entry = float(p["entryPrice"])
            mark = float(p["markPrice"])
            pnl = float(p["unRealizedProfit"])
            lev = int(p["leverage"])
            margin = entry * abs(amt) / lev if lev and entry else 0
            roe = pnl / margin * 100 if margin else 0
            sym = p["symbol"]
            side = side_map.get(sym, "涨幅榜-空（有过滤）" if amt < 0 else "多")
            details.append({
                "symbol": sym,
                "side": side,
                "entry_price": round(entry, 6),
                "mark_price": round(mark, 6),
                "position_amt": round(abs(amt), 4),
                "unrealized_pnl": round(pnl, 4),
                "roe_pct": round(roe, 2),
                "leverage": lev,
            })

        return jsonify({
            "balance":      round(balance, 2),
            "margin_used":  round(margin_used, 2),
            "total_pnl":    round(total_pnl, 2),
            "long_pnl":     round(long_pnl, 2),
            "short_pnl":    round(short_pnl, 2),
            "long_count":   long_count,
            "short_count":  short_count,
            "positions":    details,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/dashboard")
def dashboard():
    """看板数据：最新一条持仓监控 + 最新快照的实盘和模拟盘明细"""
    try:
        last_monitor = db.get_positions_log_latest()
        if last_monitor:
            last_monitor.pop("id", None)

        with db.get_conn() as conn:
            # 用 id 倒序拿最新时间（id 单调，对应 time 单调，比 MAX(time) 快很多）
            row = conn.execute("SELECT time FROM positions_detail ORDER BY id DESC LIMIT 1").fetchone()
            latest_time = row["time"] if row else None
            real_detail = []
            if latest_time:
                rows = conn.execute(
                    "SELECT * FROM positions_detail WHERE time = ? ORDER BY unrealized_pnl DESC", (latest_time,)
                ).fetchall()
                real_detail = [dict(r) for r in rows]
                for r in real_detail:
                    r.pop("id", None)

            row2 = conn.execute("SELECT time FROM virtual_detail ORDER BY id DESC LIMIT 1").fetchone()
            virt_time = row2["time"] if row2 else None
            virt_detail = []
            if virt_time:
                rows2 = conn.execute(
                    "SELECT * FROM virtual_detail WHERE time = ? ORDER BY side, unrealized_pnl DESC", (virt_time,)
                ).fetchall()
                virt_detail = [dict(r) for r in rows2]
                for r in virt_detail:
                    r.pop("id", None)

        return jsonify({
            "monitor": last_monitor,
            "real_detail": real_detail,
            "real_detail_time": latest_time,
            "virtual_detail": virt_detail,
            "virtual_detail_time": virt_time,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)
