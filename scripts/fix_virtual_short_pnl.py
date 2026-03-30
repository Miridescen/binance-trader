"""
一次性脚本：修复模拟空的 PnL/ROE 符号错误。
之前 virtual_close 中 side=="模拟空" 走了做多公式，PnL 正负反了。
修复方法：对所有已平仓的模拟空记录，PnL 和 ROE 取反。
跳过从实盘补录的数据（那些数据本身是正确的）。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db

def main():
    with db.get_conn() as conn:
        # 找出所有已平仓的模拟空，且 open_time 是模拟盘自己开的（非补录的）
        # 补录数据的 open_time 和实盘一致（09:04/09:06/09:08/09:11/10:03/09:09）
        # 模拟盘自己开的 open_time 是 09:00/09:03 左右
        # 最简单的判断：补录的数据 close_price 和实盘完全一样（精度6位），
        # 而模拟盘平仓的 close_price 是模拟盘自己算的
        # 实际上更简单：看哪些记录的 PnL 方向和价格变动方向不一致

        rows = conn.execute("""
            SELECT id, entry_price, close_price, unrealized_pnl, roe_pct
            FROM virtual_log
            WHERE side = '模拟空' AND close_time IS NOT NULL AND close_time != ''
            AND entry_price IS NOT NULL AND close_price IS NOT NULL
        """).fetchall()

        fixed = 0
        for row in rows:
            entry = row["entry_price"]
            close = row["close_price"]
            pnl = row["unrealized_pnl"]
            roe = row["roe_pct"]

            if entry is None or close is None or pnl is None:
                continue

            # 做空正确逻辑：价格跌了(close < entry) → PnL 应该 > 0
            # 如果价格跌了但 PnL < 0，或价格涨了但 PnL > 0 → 说明符号反了
            price_dropped = close < entry
            pnl_positive = pnl > 0

            if (price_dropped and not pnl_positive) or (not price_dropped and pnl_positive):
                # 符号错误，取反
                conn.execute(
                    "UPDATE virtual_log SET unrealized_pnl = ?, roe_pct = ? WHERE id = ?",
                    (-pnl, -roe, row["id"])
                )
                fixed += 1

        print(f"已修复 {fixed} 条模拟空记录的 PnL/ROE 符号")


if __name__ == "__main__":
    main()
