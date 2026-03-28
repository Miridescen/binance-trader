"""
一次性迁移脚本：将所有 CSV 数据导入 SQLite 数据库。
运行后 CSV 文件保留不删除，作为备份。
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import csv
import os
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(__file__)


def safe_float(v):
    """安全转换为 float，空值返回 None"""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def safe_int(v):
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


def read_csv(filename):
    path = os.path.join(BASE_DIR, filename)
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def migrate():
    # 延迟导入，确保 db.py 先建表
    from db import get_conn, init_db
    init_db()

    with get_conn() as conn:
        # 1. open_log.csv
        rows = read_csv("open_log.csv")
        if rows:
            conn.executemany("""
                INSERT INTO open_log (open_time, close_time, symbol, side,
                    change_pct, market_cap_usd, circulating_supply,
                    btc_change_pct, symbol_funding_rate, oi_change_pct,
                    long_short_ratio, open_commission,
                    entry_price, close_price, position_amt,
                    unrealized_pnl, roe_pct, leverage, close_commission)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [(
                r.get("open_time"), r.get("close_time"), r.get("symbol"), r.get("side"),
                safe_float(r.get("change_pct")),
                r.get("market_cap_usd"), r.get("circulating_supply"),
                safe_float(r.get("btc_change_pct")),
                safe_float(r.get("symbol_funding_rate")),
                safe_float(r.get("oi_change_pct")),
                safe_float(r.get("long_short_ratio")),
                safe_float(r.get("open_commission")),
                safe_float(r.get("entry_price")),
                safe_float(r.get("close_price")),
                safe_float(r.get("position_amt")),
                safe_float(r.get("unrealized_pnl")),
                safe_float(r.get("roe_pct")),
                safe_int(r.get("leverage")),
                safe_float(r.get("close_commission")),
            ) for r in rows])
            log.info(f"open_log: 导入 {len(rows)} 条")

        # 2. batch_summary_log.csv
        rows = read_csv("batch_summary_log.csv")
        if rows:
            conn.executemany("""
                INSERT INTO batch_summary (close_time, long_count, long_pnl,
                    short_count, short_pnl, total_pnl)
                VALUES (?, ?, ?, ?, ?, ?)
            """, [(
                r.get("close_time"),
                safe_int(r.get("long_count")),
                safe_float(r.get("long_pnl")),
                safe_int(r.get("short_count")),
                safe_float(r.get("short_pnl")),
                safe_float(r.get("total_pnl")),
            ) for r in rows])
            log.info(f"batch_summary: 导入 {len(rows)} 条")

        # 3. events_log.csv
        rows = read_csv("events_log.csv")
        if rows:
            conn.executemany("""
                INSERT INTO events_log (time, event, detail)
                VALUES (?, ?, ?)
            """, [(r.get("time"), r.get("event"), r.get("detail")) for r in rows])
            log.info(f"events_log: 导入 {len(rows)} 条")

        # 4. positions_log.csv
        rows = read_csv("positions_log.csv")
        if rows:
            conn.executemany("""
                INSERT INTO positions_log (time, balance_usdt, long_count, long_pnl,
                    short_count, short_pnl, total_pnl, funding_fee)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [(
                r.get("time"),
                safe_float(r.get("balance_usdt")),
                safe_int(r.get("long_count")),
                safe_float(r.get("long_pnl")),
                safe_int(r.get("short_count")),
                safe_float(r.get("short_pnl")),
                safe_float(r.get("total_pnl")),
                safe_float(r.get("funding_fee")),
            ) for r in rows])
            log.info(f"positions_log: 导入 {len(rows)} 条")

        # 5. positions_detail_log.csv
        rows = read_csv("positions_detail_log.csv")
        if rows:
            conn.executemany("""
                INSERT INTO positions_detail (time, symbol, side, entry_price,
                    mark_price, position_amt, unrealized_pnl, roe_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [(
                r.get("time"), r.get("symbol"), r.get("side"),
                safe_float(r.get("entry_price")),
                safe_float(r.get("mark_price")),
                safe_float(r.get("position_amt")),
                safe_float(r.get("unrealized_pnl")),
                safe_float(r.get("roe_pct")),
            ) for r in rows])
            log.info(f"positions_detail: 导入 {len(rows)} 条")

        # 6. virtual_open_log.csv
        rows = read_csv("virtual_open_log.csv")
        if rows:
            conn.executemany("""
                INSERT INTO virtual_log (open_time, close_time, symbol, side,
                    change_pct, market_cap_usd, circulating_supply, has_mcap,
                    btc_change_pct, symbol_funding_rate, oi_change_pct, long_short_ratio,
                    entry_price, close_price, unrealized_pnl, roe_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [(
                r.get("open_time"), r.get("close_time"), r.get("symbol"), r.get("side"),
                safe_float(r.get("change_pct")),
                r.get("market_cap_usd"), r.get("circulating_supply"),
                safe_int(r.get("has_mcap")),
                safe_float(r.get("btc_change_pct")),
                safe_float(r.get("symbol_funding_rate")),
                safe_float(r.get("oi_change_pct")),
                safe_float(r.get("long_short_ratio")),
                safe_float(r.get("entry_price")),
                safe_float(r.get("close_price")),
                safe_float(r.get("unrealized_pnl")),
                safe_float(r.get("roe_pct")),
            ) for r in rows])
            log.info(f"virtual_log: 导入 {len(rows)} 条")

    log.info("迁移完成！CSV 文件已保留作为备份。")


if __name__ == "__main__":
    migrate()
