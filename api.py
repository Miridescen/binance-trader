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
    return jsonify(_strip_id(db.get_positions_log_all()))

@app.route("/api/open_log")
def open_log():
    return jsonify(_strip_id(db.get_open_log_all()))

@app.route("/api/virtual_log")
def virtual_log():
    return jsonify(_strip_id(db.get_virtual_log_all()))

@app.route("/api/positions_detail")
def positions_detail():
    date = request.args.get("date")
    if date:
        return jsonify(_strip_id(db.get_positions_detail_by_date(date)))
    return jsonify(_strip_id(db.get_positions_detail_all()))

@app.route("/api/positions_detail/dates")
def positions_detail_dates():
    return jsonify(db.get_positions_detail_dates())

@app.route("/api/virtual_detail")
def virtual_detail():
    date = request.args.get("date")
    if date:
        return jsonify(_strip_id(db.get_virtual_detail_by_date(date)))
    return jsonify(_strip_id(db.get_virtual_detail_all()))

@app.route("/api/virtual_detail/dates")
def virtual_detail_dates():
    return jsonify(db.get_virtual_detail_dates())

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

        return jsonify({
            "balance":     round(balance, 2),
            "total_pnl":   round(total_pnl, 2),
            "long_pnl":    round(long_pnl, 2),
            "short_pnl":   round(short_pnl, 2),
            "long_count":  long_count,
            "short_count": short_count,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)
