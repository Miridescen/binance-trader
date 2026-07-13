"""
Flask API，为前端提供数据（从 SQLite 数据库读取）
"""
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

_WINDOW_WHITELIST = {"4h", "8h", "12h", "24h"}


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


@app.route("/api/open_log_4h")
def open_log_4h():
    """支持 ?anchor=YYYY-MM-DD HH:MM 按周期 open_anchor 过滤；默认返回全部"""
    anchor = request.args.get("anchor")
    if anchor:
        # open_anchor 形如 "YYYY-MM-DD HH:MM:00"，按前 16 字符匹配（兼容缺秒的传参）
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM open_log_4h WHERE substr(open_anchor, 1, 16) = ? ORDER BY id",
                (anchor[:16],)
            ).fetchall()
            rows = [dict(r) for r in rows]
        return jsonify(_strip_id(rows))
    return jsonify(_strip_id(db.get_open_log_4h_all()))


@app.route("/api/open_log_4h/anchors")
def open_log_4h_anchors():
    """返回所有周期 anchor（按 open_anchor 分组）倒序 + 笔数"""
    with db.get_conn() as conn:
        rows = conn.execute("""
            SELECT substr(open_anchor, 1, 16) AS anchor, COUNT(*) AS n
            FROM open_log_4h
            WHERE open_anchor IS NOT NULL AND open_anchor != ''
            GROUP BY anchor
            ORDER BY anchor DESC
        """).fetchall()
        return jsonify([{"anchor": r["anchor"], "n": r["n"]} for r in rows])


@app.route("/api/open_log_8h")
def open_log_8h():
    """8h 周期实盘开仓记录。支持 ?anchor=YYYY-MM-DD HH:MM 过滤；默认返回全部"""
    anchor = request.args.get("anchor")
    if anchor:
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM open_log_8h WHERE substr(open_anchor, 1, 16) = ? ORDER BY id",
                (anchor[:16],)
            ).fetchall()
            rows = [dict(r) for r in rows]
        return jsonify(_strip_id(rows))
    return jsonify(_strip_id(db.get_open_log_8h_all()))


@app.route("/api/open_log_8h/anchors")
def open_log_8h_anchors():
    """返回所有周期 anchor（按 open_anchor 分组）倒序 + 笔数"""
    with db.get_conn() as conn:
        rows = conn.execute("""
            SELECT substr(open_anchor, 1, 16) AS anchor, COUNT(*) AS n
            FROM open_log_8h
            WHERE open_anchor IS NOT NULL AND open_anchor != ''
            GROUP BY anchor
            ORDER BY anchor DESC
        """).fetchall()
        return jsonify([{"anchor": r["anchor"], "n": r["n"]} for r in rows])


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

        # 从未平仓记录获取 side 标记，区分涨幅空/跌幅空
        # 优先 8h 实盘表（当前在跑的策略），再 4h，再老 open_log 兜底
        side_map = {}
        try:
            with db.get_conn() as conn:
                rows8 = conn.execute(
                    "SELECT symbol, side FROM open_log_8h "
                    "WHERE close_time IS NULL OR close_time = '' ORDER BY id DESC"
                ).fetchall()
                for r in rows8:
                    if r["symbol"] not in side_map:
                        side_map[r["symbol"]] = r["side"]
                rows4 = conn.execute(
                    "SELECT symbol, side FROM open_log_4h "
                    "WHERE close_time IS NULL OR close_time = '' ORDER BY id DESC"
                ).fetchall()
                for r in rows4:
                    if r["symbol"] not in side_map:
                        side_map[r["symbol"]] = r["side"]
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
            side = side_map.get(sym, "跌幅榜-空（无过滤）" if amt < 0 else "多")
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)
