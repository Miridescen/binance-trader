"""
简单的 Flask API，为前端提供 CSV 数据
"""
import csv
import os
from flask import Flask, jsonify
from flask_cors import CORS

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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)
