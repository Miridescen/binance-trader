"""
修复 04-15 开仓记录：用 04-15 08:54 持仓明细快照的 entry_price 强制覆盖
在服务器上运行: python3 fix_0415.py
"""
import db

# 来自持仓明细 2026-04-15 08:54:15 截图（20笔）
# (symbol, entry_price)
data = [
    ("APRUSDT",      0.3278),
    ("ENJUSDT",      0.0584),
    ("GIGGLEUSDT",  50.6500),
    ("COAIUSDT",     0.4026),
    ("BUSDT",        0.1132),
    ("ONUSDT",       0.1391),
    ("IRYSUSDT",     0.0281),
    ("LABUSDT",      0.4734),
    ("AKEUSDT",      0.0007),
    ("LITUSDT",      1.0183),
    ("BARDUSDT",     0.3015),
    ("INUSDT",       0.0797),
    ("INXUSDT",      0.0124),
    ("RAVEUSDT",    17.6428),
    ("WETUSDT",      0.1459),
    ("币安人生USDT",   0.3462),
    ("XANUSDT",      0.0111),
    ("BLESSUSDT",    0.0213),
    ("BRUSDT",       0.1755),
    ("ARIAUSDT",     0.1225),
]

print("强制覆盖 04-15 开仓记录 entry_price（20笔）:")
with db.get_conn() as conn:
    for sym, entry in data:
        result = conn.execute(
            "UPDATE open_log SET entry_price = ? "
            "WHERE symbol = ? AND open_time LIKE '2026-04-15%'",
            (entry, sym)
        )
        if result.rowcount:
            print(f"  {sym:<16} entry={entry} ✅")
        else:
            print(f"  {sym:<16} 未找到04-15记录 ❌")

print("\n修复完成")
