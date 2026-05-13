"""8 小时周期虚拟盘入口。开仓时刻：00:30 / 08:30 / 16:30。"""
import logging
from virtual_trade_window import WindowedSimulator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

if __name__ == "__main__":
    WindowedSimulator(
        window="8h",
        hours=8,
        open_hours=(0, 8, 16),
        label="8h",
        snapshot_offset=2,  # 错开：主盘 0 / 4h 1 / 8h 2 / 12h 3
    ).run()
