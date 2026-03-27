"""
虚拟开单（沙盘模式）：
  - 不下真实订单，用标记价模拟成交
  - 不过滤无市值币，记录 has_mcap 标记，与真实策略对比
  - 时间节点与真实策略一致（08:50 虚拟平仓，09:00 虚拟开仓）
  - 独立写入 virtual_open_log.csv

用途：验证「过滤无市值币」优化效果的对照组
"""

import os
import time
import logging
from datetime import datetime, timedelta
from binance_client import (
    public_get, get_exchange_info, get_ticker_24h, get_mark_price,
    get_coin_market_data, get_btc_change_pct, get_all_funding_rates,
    get_oi_changes, get_long_short_ratios,
)
import db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def fmt_large(n: float) -> str:
    if n >= 1e9:
        return f"{n / 1e9:.2f}B"
    if n >= 1e6:
        return f"{n / 1e6:.2f}M"
    if n > 0:
        return f"{n:.0f}"
    return "N/A"

LEVERAGE       = 3
MARGIN_PER_POS = 10
TOP_N          = 10
MIN_VOLUME     = 10_000_000
CLOSE_HOUR, CLOSE_MINUTE = 8, 50
OPEN_HOUR,  OPEN_MINUTE  = 9, 0


# ── 虚拟平仓 ───────────────────────────────────────────

def virtual_close():
    log.info("【虚拟平仓开始】")
    unclosed = db.get_virtual_log_unclosed()
    now  = datetime.now()
    ts   = now.strftime("%Y-%m-%d %H:%M:%S")
    closed = 0

    for row in unclosed:
        sym   = row["symbol"]
        side  = row["side"]
        entry = row["entry_price"]
        if entry is None:
            continue

        try:
            mark = get_mark_price(sym)
        except Exception as e:
            log.warning(f"  {sym} 获取标记价失败：{e}")
            continue

        notional = MARGIN_PER_POS * LEVERAGE
        if side == "空":
            pnl = (entry - mark) / entry * notional
        else:
            pnl = (mark - entry) / entry * notional
        roe = pnl / MARGIN_PER_POS * 100

        db.update_virtual_close(row["id"], {
            "close_time":     ts,
            "close_price":    mark,
            "unrealized_pnl": pnl,
            "roe_pct":        roe,
        })
        closed += 1
        log.info(f"  {sym} {'空→买' if side=='空' else '多→卖'}  入场 {entry:.4f}  出场 {mark:.4f}  PnL {pnl:+.4f}  ROE {roe:+.1f}%")
        time.sleep(0.1)

    log.info(f"【虚拟平仓完成】共平仓 {closed} 笔")


# ── 虚拟开仓 ───────────────────────────────────────────

def virtual_open():
    log.info("【虚拟开仓开始】（沙盘模式，不下真实订单）")

    valid_symbols, _ = get_exchange_info()
    tickers = get_ticker_24h(valid_symbols, MIN_VOLUME)
    tickers.sort(key=lambda x: float(x["priceChangePercent"]), reverse=True)

    top_gainers = tickers[:TOP_N]
    top_losers  = tickers[-TOP_N:][::-1]
    all_syms    = [t["symbol"] for t in top_gainers + top_losers]

    # 拉市值（仅用于记录 has_mcap，不过滤）
    try:
        market_data = get_coin_market_data(all_syms)
    except Exception as e:
        log.warning(f"CoinGecko 获取失败，has_mcap 全部标记为 False：{e}")
        market_data = {}

    try:
        btc_pct = get_btc_change_pct()
        log.info(f"BTC 24h涨跌幅：{btc_pct:+.2f}%")
    except Exception as e:
        log.warning(f"获取 BTC 涨跌幅失败：{e}")
        btc_pct = None

    try:
        funding_rates = get_all_funding_rates()
    except Exception as e:
        log.warning(f"获取资金费率失败：{e}")
        funding_rates = {}

    log.info("正在获取持仓量变化（OI）...")
    try:
        oi_changes = get_oi_changes(all_syms)
    except Exception as e:
        log.warning(f"获取OI变化失败：{e}")
        oi_changes = {}

    log.info("正在获取多空持仓比...")
    try:
        ls_ratios = get_long_short_ratios(all_syms)
    except Exception as e:
        log.warning(f"获取多空比失败：{e}")
        ls_ratios = {}

    now = datetime.now()
    ts  = now.strftime("%Y-%m-%d %H:%M:%S")
    new_rows = []

    for label, tickers_group, side_str in [
        ("空单（涨幅榜）", top_gainers, "空"),
        ("多单（跌幅榜）", top_losers,  "多"),
    ]:
        log.info(f"── {label} ──")
        for t in tickers_group:
            sym = t["symbol"]
            pct = float(t["priceChangePercent"])

            try:
                entry = get_mark_price(sym)
            except Exception as e:
                log.warning(f"  {sym} 获取标记价失败，跳过：{e}")
                continue

            md       = market_data.get(sym, {})
            mc       = md.get("market_cap", 0)
            cs       = md.get("circulating_supply", 0)
            has_mcap = 1 if mc else 0
            fr       = funding_rates.get(sym)
            oi       = oi_changes.get(sym)
            ls       = ls_ratios.get(sym)

            log.info(
                f"  {sym} {side_str}  涨跌 {pct:+.2f}%  "
                f"入场价 {entry:.4f}  市值 {'有' if mc else '无'}  "
                f"资金费 {fr*100:+.4f}%" if fr is not None else
                f"  {sym} {side_str}  涨跌 {pct:+.2f}%  入场价 {entry:.4f}  市值 {'有' if mc else '无'}"
            )

            new_rows.append({
                "open_time":           ts,
                "close_time":          None,
                "symbol":              sym,
                "side":                side_str,
                "change_pct":          pct,
                "market_cap_usd":      fmt_large(mc) if mc else None,
                "circulating_supply":  fmt_large(cs) if cs else None,
                "has_mcap":            has_mcap,
                "btc_change_pct":      btc_pct,
                "symbol_funding_rate": fr,
                "oi_change_pct":       oi,
                "long_short_ratio":    ls,
                "entry_price":         entry,
                "close_price":         None,
                "unrealized_pnl":      None,
                "roe_pct":             None,
            })
            time.sleep(0.1)

    if new_rows:
        db.insert_virtual_log(new_rows)
    log.info(f"【虚拟开仓完成】共记录 {len(new_rows)} 笔虚拟仓位")


# ── 定时工具 ───────────────────────────────────────────

def wait_until(hour: int, minute: int):
    now      = datetime.now()
    next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)
    wait_sec = (next_run - now).total_seconds()
    log.info(f"等待中 → 下次执行：{next_run.strftime('%Y-%m-%d %H:%M:%S')}（约 {wait_sec/3600:.1f} 小时后）")
    time.sleep(wait_sec)


# ── 主循环 ─────────────────────────────────────────────

def main():
    log.info("虚拟开单沙盘启动")
    log.info(f"  每天 {CLOSE_HOUR:02d}:{CLOSE_MINUTE:02d} 虚拟平仓")
    log.info(f"  每天 {OPEN_HOUR:02d}:{OPEN_MINUTE:02d} 虚拟开仓（涨幅榜空 + 跌幅榜多，不过滤市值）")
    log.info(f"  日志：SQLite 数据库")

    while True:
        wait_until(CLOSE_HOUR, CLOSE_MINUTE)
        try:
            virtual_close()
        except Exception as e:
            log.error(f"虚拟平仓出错：{e}", exc_info=True)

        wait_until(OPEN_HOUR, OPEN_MINUTE)
        try:
            virtual_open()
        except Exception as e:
            log.error(f"虚拟开仓出错：{e}", exc_info=True)


if __name__ == "__main__":
    main()
