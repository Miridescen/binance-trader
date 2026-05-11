"""12 小时周期虚拟盘入口。开仓时刻：08:30 / 20:30。"""
import logging
from virtual_trade_window import WindowedSimulator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

if __name__ == "__main__":
    WindowedSimulator(
        window="12h",
        hours=12,
        open_hours=(8, 20),
        label="12h",
    ).run()
