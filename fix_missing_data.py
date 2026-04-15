"""
修复 04-14 和 04-15 开仓记录缺失的 entry_price/pnl/roe 数据
从 positions_detail 的 08:29 快照中恢复
在服务器上运行: python3 fix_missing_data.py
"""
import db

# 04-14 08:29:17 快照数据
data_0414 = [
    ("AIOUSDT", 0.12413, 5.9612, 59.5),
    ("AKEUSDT", 0.0006494, 5.0851, 50.8),
    ("INXUSDT", 0.018154, 4.8883, 48.9),
    ("AIOTUSDT", 0.06348, 2.4364, 24.4),
    ("SOONUSDT", 0.1251, 1.0277, 10.3),
    ("CROSSUSDT", 0.07236, 0.9139, 9.2),
    ("币安人生USDT", 0.2048, 0.9011, 9.0),
    ("BEATUSDT", 0.3838, 0.7475, 7.5),
    ("4USDT", 0.013549001355, 0.5225, 5.2),
    ("DASHUSDT", 41.68, 0.4817, 4.8),
    ("EDGEUSDT", 0.8908, 0.0233, 0.2),
    ("FFUSDT", 0.07858, -0.2172, -2.2),
    ("PIEVERSEUSDT", 0.4199, -0.2338, -2.4),
    ("TRADOORUSDT", 5.388, -0.8850, -9.9),
    ("BASUSDT", 0.0067630047351, -0.9471, -9.5),
    ("XANUSDT", 0.007409, -2.5368, -25.4),
    ("LABUSDT", 0.53182, -2.8045, -28.3),
    ("BANUSDT", 0.07535, -5.1709, -51.7),
    ("PLAYUSDT", 0.08079, -5.7531, -57.6),
    ("RAVEUSDT", 5.89127, -10.1934, -103.8),
]

# 04-15 08:29:06 快照数据
data_0415 = [
    ("AIOTUSDT", 0.05909, 0.2794, 2.8),
    ("SKYAIUSDT", 0.11046, -2.9176, -29.2),
    ("ENJUSDT", 0.04376, -10.8788, -108.9),
    ("GIGGLEUSDT", 38.72, -7.2151, -72.6),
    ("FOLKSUSDT", 1.241, -4.0247, -40.4),
    ("ONUSDT", 0.1572, 3.6653, 36.4),
    ("IRYSUSDT", 0.03332, 5.1913, 51.9),
    ("INXUSDT", 0.014985, 5.2908, 52.9),
    ("NEIROUSDT", 6.869e-05, 1.2098, 12.1),
    ("ARIAUSDT", 0.775, 24.8824, 253.5),
    ("PLAYUSDT", 0.09545, -2.2112, -22.1),
    ("RAVEUSDT", 7.60397, -27.3786, -360.1),
    ("AIOUSDT", 0.0982780983607, 5.6924, 57.0),
    ("WETUSDT", 0.16105, 3.1638, 31.7),
    ("BLESSUSDT", 0.026908, 6.4440, 64.4),
]

def fix_date(date, snapshot_data):
    print(f"\n修复 {date}:")
    with db.get_conn() as conn:
        for sym, entry, pnl, roe in snapshot_data:
            result = conn.execute(
                "UPDATE open_log SET entry_price = ?, unrealized_pnl = ?, roe_pct = ?, leverage = 3 "
                "WHERE symbol = ? AND open_time LIKE ? AND entry_price IS NULL",
                (entry, pnl, roe, sym, f"{date}%")
            )
            if result.rowcount:
                print(f"  {sym} entry={entry} pnl={pnl:+.4f} roe={roe:+.1f}% ✅")
            else:
                print(f"  {sym} 未匹配（可能已有数据）")

if __name__ == "__main__":
    fix_date("2026-04-14", data_0414)
    fix_date("2026-04-15", data_0415)
    print("\n修复完成")
