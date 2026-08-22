"""
Flask API，为前端提供数据（从 SQLite 数据库读取）
"""
import os
from datetime import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS
from binance_client import auth_get, auth_get_with
import db


app = Flask(__name__)
CORS(app)


# 子账号（24h 实盘）密钥文件；与主账号 .env 并存，API 服务只读用于查子账号余额/持仓
SUB24H_ENV = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env.sub24h")


def _load_sub24h_keys():
    """解析 .env.sub24h（KEY=VALUE，跳过注释）。缺文件/缺键返回 (None, None)。"""
    key = secret = None
    try:
        with open(SUB24H_ENV) as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                k, v = s.split("=", 1)
                k = k.strip(); v = v.strip().strip('"').strip("'")
                if k == "BINANCE_API_KEY":
                    key = v
                elif k == "BINANCE_API_SECRET":
                    secret = v
    except FileNotFoundError:
        pass
    return key, secret


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


_summary_ver = {}   # window -> version（已平仓行数+最新平仓时间），没变就跳过增量刷新


def _maybe_refresh_summary(w):
    """仅当有新平仓（版本变化）时才跑一次增量物化，把新收尾的组写进汇总表。"""
    log_table = f"virtual_log_{w}"
    with db.get_conn() as conn:
        v = conn.execute(
            f"SELECT COUNT(*) AS n, MAX(close_time) AS mx FROM {log_table} WHERE close_time IS NOT NULL"
        ).fetchone()
    ver = (v["n"], v["mx"])
    if _summary_ver.get(w) != ver:
        try:
            db.refresh_virtual_summaries(w)
        except Exception:
            pass
        _summary_ver[w] = ver


@app.route("/api/virtual_totals")
def virtual_totals():
    """各方向累计（读物化汇总表，瞬间）。?window=4h/8h/12h/24h&time=HH:MM(可选)"""
    w = _validate_window(request.args.get("window", "4h"))
    if w is None:
        return jsonify({"error": "invalid window"}), 400
    time = request.args.get("time") or None
    _maybe_refresh_summary(w)
    return jsonify(db.get_virtual_summary_totals(w, time))


@app.route("/api/virtual_inprogress")
def virtual_inprogress():
    """进行中的组（+10u 已提前平但窗口未结束），数量极少，实时算。?window=..."""
    w = _validate_window(request.args.get("window", "4h"))
    if w is None:
        return jsonify({"error": "invalid window"}), 400
    return jsonify(db.get_virtual_inprogress(w))


@app.route("/api/virtual_times")
def virtual_times():
    """该窗口出现过的开仓时段（HH:MM）列表，供时段筛选下拉。?window=..."""
    w = _validate_window(request.args.get("window", "4h"))
    if w is None:
        return jsonify({"error": "invalid window"}), 400
    _maybe_refresh_summary(w)
    return jsonify(db.get_virtual_summary_times(w))


@app.route("/api/virtual_groups")
def virtual_groups():
    """分页读组级汇总（已收尾组）。
    ?window=4h/8h/12h/24h&side=&time=HH:MM&sort=open_time|sum_pnl_actual|sum_pnl_if_held&order=desc|asc&page=1&page_size=30
    返回 {total, page, page_size, rows:[...]}。进行中的组走 /api/virtual_inprogress。"""
    w = _validate_window(request.args.get("window", "4h"))
    if w is None:
        return jsonify({"error": "invalid window"}), 400
    side = request.args.get("side") or None
    time = request.args.get("time") or None
    sort = request.args.get("sort", "open_time")
    order = request.args.get("order", "desc")
    try:
        page = max(1, int(request.args.get("page", 1)))
        page_size = min(200, max(1, int(request.args.get("page_size", 30))))
    except (ValueError, TypeError):
        page, page_size = 1, 30
    _maybe_refresh_summary(w)
    total, rows = db.get_virtual_summary_page(w, side, time, sort, order, page, page_size)
    return jsonify({"total": total, "page": page, "page_size": page_size, "rows": rows})


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


def _build_realtime(auth_fn, side_tables):
    """构造某个账号的实时快照。auth_fn 是签名 GET 调用（主账号 auth_get，子账号用显式密钥）。
    side_tables 是拿 side 标记的未平仓表名（按优先级），仅用于给持仓打方向标签。"""
    account = auth_fn("/fapi/v2/account")
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
    pos_risk = auth_fn("/fapi/v2/positionRisk")
    active_risk = [p for p in pos_risk if float(p["positionAmt"]) != 0]

    # 从未平仓记录获取 side 标记，区分涨幅空/跌幅空（side_tables 均为代码内常量，无注入风险）
    side_map = {}
    try:
        with db.get_conn() as conn:
            for tbl in side_tables:
                rows = conn.execute(
                    f"SELECT symbol, side FROM {tbl} "
                    "WHERE close_time IS NULL OR close_time = '' ORDER BY id DESC"
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

    return {
        "balance":      round(balance, 2),
        "margin_used":  round(margin_used, 2),
        "total_pnl":    round(total_pnl, 2),
        "long_pnl":     round(long_pnl, 2),
        "short_pnl":    round(short_pnl, 2),
        "long_count":   long_count,
        "short_count":  short_count,
        "positions":    details,
    }


@app.route("/api/realtime")
def realtime():
    """主账号（8h 实盘）实时快照。"""
    try:
        data = _build_realtime(auth_get, ["open_log_8h", "open_log_4h", "open_log"])
        data["configured"] = True
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/realtime_24h")
def realtime_24h():
    """子账号（24h 实盘）实时快照。未配置密钥时优雅返回 configured=false，前端只显示空块不报错。"""
    key, secret = _load_sub24h_keys()
    if not key or not secret:
        return jsonify({"configured": False})
    try:
        data = _build_realtime(
            lambda path, extra=None: auth_get_with(key, secret, path, extra),
            ["open_log_24h"],
        )
        data["configured"] = True
        return jsonify(data)
    except Exception as e:
        # 子账号查询失败不拖垮整个看板，返回 200 带 error 让前端提示
        return jsonify({"configured": True, "error": str(e)}), 200


@app.route("/api/open_log_24h")
def open_log_24h():
    """24h 周期实盘开仓记录。支持 ?anchor=YYYY-MM-DD HH:MM 过滤；默认返回全部"""
    anchor = request.args.get("anchor")
    if anchor:
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM open_log_24h WHERE substr(open_anchor, 1, 16) = ? ORDER BY id",
                (anchor[:16],)
            ).fetchall()
            rows = [dict(r) for r in rows]
        return jsonify(_strip_id(rows))
    return jsonify(_strip_id(db.get_open_log_24h_all()))


# 已知的自动开单开关（前端显示这些；缺行=默认开启）
SWITCH_KEYS = ["real_8h", "real_24h"]


@app.route("/api/switches")
def get_switches():
    """返回各策略自动开单开关状态（缺记录=默认 true/开启）。"""
    saved = db.get_all_switches()
    return jsonify({k: saved.get(k, True) for k in SWITCH_KEYS})


@app.route("/api/switch", methods=["POST"])
def set_switch():
    """切换某策略自动开单开关。body: {key, enabled(bool)}"""
    data = request.get_json(force=True, silent=True) or {}
    key = data.get("key")
    enabled = data.get("enabled")
    if key not in SWITCH_KEYS or not isinstance(enabled, bool):
        return jsonify({"error": "参数错误：key 需为已知策略，enabled 需为布尔"}), 400
    db.set_switch(key, enabled)
    return jsonify({"ok": True, "key": key, "enabled": enabled})


@app.route("/api/open_log_24h/anchors")
def open_log_24h_anchors():
    """返回 24h 所有周期 anchor（按 open_anchor 分组）倒序 + 笔数"""
    with db.get_conn() as conn:
        rows = conn.execute("""
            SELECT substr(open_anchor, 1, 16) AS anchor, COUNT(*) AS n
            FROM open_log_24h
            WHERE open_anchor IS NOT NULL AND open_anchor != ''
            GROUP BY anchor
            ORDER BY anchor DESC
        """).fetchall()
        return jsonify([{"anchor": r["anchor"], "n": r["n"]} for r in rows])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)
