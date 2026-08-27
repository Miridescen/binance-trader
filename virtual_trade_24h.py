"""24 小时周期虚拟盘入口。开仓时刻：每天 00:30 与 12:30，各持仓 24h，含组内 +10U 提前平。
两个开仓时刻写同一套 virtual_log_24h 表，按 open_time 区分（页面用“按时段筛选”分开看，求和各自独立）。
取代旧主模拟盘（virtual_trade.py，已废弃）。"""
import logging
from virtual_trade_window import WindowedSimulator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

if __name__ == "__main__":
    WindowedSimulator(
        window="24h",
        hours=24,
        open_hours=(0, 12),   # 每天 00:30 与 12:30 各开一窗（12:30 为新增）
        label="24h",
        snapshot_offset=4,  # 错开：4h 1 / 8h 2 / 12h 3 / 24h 4
    ).run()
