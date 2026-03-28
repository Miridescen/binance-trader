"""
一次性脚本：修复模拟空记录中缺失的 entry_price。
从币安 API 获取当前持仓的入场价，回填到 virtual_log 中。
对于已平仓但无入场价的记录，从 open_log 中匹配。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db
from binance_client import auth_get

def main():
    # 获取当前持仓的入场价
    positions = auth_get("/fapi/v2/positionRisk")
    price_map = {}
    for p in positions:
        if float(p["positionAmt"]) != 0:
            price_map[p["symbol"]] = float(p["entryPrice"])

    # 从 open_log 获取历史入场价
    open_log = db.get_open_log_all()
    for r in open_log:
        if r.get("entry_price") and r["symbol"] not in price_map:
            price_map[r["symbol"]] = float(r["entry_price"])

    # 修复 virtual_log 中 entry_price 为 None 的模拟空记录
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, symbol, entry_price FROM virtual_log WHERE side = '模拟空' AND entry_price IS NULL"
        ).fetchall()

        fixed = 0
        for row in rows:
            sym = row["symbol"]
            price = price_map.get(sym)
            if price:
                conn.execute(
                    "UPDATE virtual_log SET entry_price = ? WHERE id = ?",
                    (price, row["id"])
                )
                fixed += 1
                print(f"  {sym}: entry_price = {price}")
            else:
                print(f"  {sym}: 未找到入场价，跳过")

    print(f"\n已修复 {fixed} 条模拟空记录")


if __name__ == "__main__":
    main()
