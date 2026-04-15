"""
补全 04-15 未平仓记录的 leverage=3
在服务器上运行: python3 fix_0415_leverage.py
"""
import db

print("补全 04-15 未平仓记录的 leverage:")
with db.get_conn() as conn:
    result = conn.execute(
        "UPDATE open_log SET leverage = 3 "
        "WHERE open_time LIKE '2026-04-15%' AND (leverage IS NULL OR leverage = '')"
    )
    print(f"  已补全 {result.rowcount} 笔")

print("\n完成")
