"""
简单的 Flask API，为前端提供 CSV 数据
"""
import csv
import os
from flask import Flask, jsonify
from flask_cors import CORS
from binance_client import auth_get

app = Flask(__name__)
CORS(app)

BASE_DIR = os.path.dirname(__file__)

def read_csv(filename):
    path = os.path.join(BASE_DIR, filename)
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

@app.route("/api/positions")
def positions():
    return jsonify(read_csv("positions_log.csv"))

@app.route("/api/open_log")
def open_log():
    return jsonify(read_csv("open_log.csv"))

@app.route("/api/virtual_log")
def virtual_log():
    return jsonify(read_csv("virtual_open_log.csv"))

@app.route("/api/positions_detail")
def positions_detail():
    return jsonify(read_csv("positions_detail_log.csv"))

@app.route("/api/realtime")
def realtime():
    try:
        account = auth_get("/fapi/v2/account")
        balance = float(account.get("totalWalletBalance", 0))

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
