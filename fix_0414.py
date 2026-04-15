"""
修复 04-14 开仓记录：用 04-15 08:30 持仓明细快照的数据强制覆盖
在服务器上运行: python3 fix_0414.py
"""
import db

# 来自持仓明细 2026-04-15 08:30:07 截图
# (symbol, entry_price, close_price, pnl, roe)
data = [
    ("ARIAUSDT",    0.7750,   0.1237,   24.75,  252.11),
    ("BLESSUSDT",   0.0269,   0.0211,    6.49,   64.83),
    ("AIOUSDT",     0.0983,   0.0798,    5.63,   56.32),
    ("INXUSDT",     0.0150,   0.0124,    5.25,   52.50),
    ("IRYSUSDT",    0.0333,   0.0276,    5.17,   51.74),
    ("ONUSDT",      0.1572,   0.1373,    3.82,   37.97),
    ("WETUSDT",     0.1610,   0.1442,    3.13,   31.32),
    ("NEIROUSDT",   0.0001,   0.0001,    1.17,   11.70),
    ("AIOTUSDT",    0.0591,   0.0586,    0.23,    2.30),
    ("PLAYUSDT",    0.0954,   0.1025,   -2.22,  -22.25),
    ("SKYAIUSDT",   0.1105,   0.1213,   -2.95,  -29.55),
    ("FOLKSUSDT",   1.2410,   1.4086,   -4.04,  -40.53),
    ("GIGGLEUSDT", 38.7200,  48.5310,   -7.55,  -76.01),
    ("ENJUSDT",     0.0438,   0.0597,  -10.93, -109.35),
    ("RAVEUSDT",    7.6040,  16.8686,  -27.79, -365.52),
]

print("强制覆盖 04-14 开仓记录（15笔）:")
with db.get_conn() as conn:
    for sym, entry, close, pnl, roe in data:
        result = conn.execute(
            "UPDATE open_log SET entry_price = ?, close_price = ?, unrealized_pnl = ?, roe_pct = ?, leverage = 3 "
            "WHERE symbol = ? AND open_time LIKE '2026-04-14%'",
            (entry, close, pnl, roe, sym)
        )
        if result.rowcount:
            print(f"  {sym:<16} entry={entry}  close={close}  pnl={pnl:+.2f}  roe={roe:+.1f}% ✅")
        else:
            print(f"  {sym:<16} 未找到04-14记录 ❌")

print("\n修复完成")
