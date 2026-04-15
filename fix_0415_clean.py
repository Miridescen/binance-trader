"""
清除 04-15 未平仓记录中的脏数据（pnl/roe/close_price）
在服务器上运行: python3 fix_0415_clean.py
"""
import db

print("清除 04-15 未平仓记录的 pnl/roe/close_price:")
with db.get_conn() as conn:
    result = conn.execute(
        "UPDATE open_log SET unrealized_pnl = NULL, roe_pct = NULL, close_price = NULL "
        "WHERE open_time LIKE '2026-04-15%' AND (close_time IS NULL OR close_time = '')"
    )
    print(f"  已清除 {result.rowcount} 笔")

print("\n完成")
