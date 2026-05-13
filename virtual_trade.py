"""
虚拟开单（沙盘模式）：
  模式一（原有）：涨跌幅榜各 TOP10，不过滤市值 → 对照组
  模式二（新增）：与实盘相同参数的多单模拟（市值过滤 + 跌幅>=8%）
  - 不下真实订单，用标记价模拟成交
  - 时间节点与真实策略一致（08:50 虚拟平仓，09:00 虚拟开仓）
"""

import os
import time
import logging
from datetime import datetime, timedelta
from binance_client import (
    public_get, get_exchange_info, get_ticker_24h, get_mark_price, get_all_mark_prices,
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

# ── 模拟参数（与实盘一致） ──────────────────────────────────
LONG_TOP_N         = 10
LONG_MIN_CHANGE    = 8.0      # 跌幅 >= 8%
SHORT_TOP_N        = 10
SHORT_MIN_CHANGE   = 5.0      # 涨幅 >= 5%
CANDIDATE_BUF      = 6


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
        is_short = "空" in side
        if is_short:
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
        direction = "空→买" if is_short else "多→卖"
        log.info(f"  {sym}({side}) {direction}  入场 {entry:.4f}  出场 {mark:.4f}  PnL {pnl:+.4f}  ROE {roe:+.1f}%")
        time.sleep(0.1)

    log.info(f"【虚拟平仓完成】共平仓 {closed} 笔")

    # 写入虚拟盘每日汇总
    _save_virtual_daily_summary(ts[:10])


def _save_virtual_daily_summary(today: str):
    """从 virtual_log 中统计今天平仓的虚拟盘每日汇总，写入 daily_summary"""
    try:
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT side, unrealized_pnl FROM virtual_log WHERE close_time LIKE ?",
                (f"{today}%",)
            ).fetchall()
        if not rows:
            return
        summary = {}
        for r in rows:
            side = r["side"]
            pnl = r["unrealized_pnl"] or 0
            if side not in summary:
                summary[side] = {"count": 0, "wins": 0, "total_pnl": 0}
            summary[side]["count"] += 1
            summary[side]["total_pnl"] += pnl
            if pnl > 0:
                summary[side]["wins"] += 1
        db_rows = [
            {"date": today, "source": "虚拟盘", "side": side, **data}
            for side, data in summary.items()
        ]
        db.insert_daily_summary(db_rows)
        log.info(f"虚拟盘每日汇总已写入（{len(db_rows)} 组）")
    except Exception as e:
        log.warning(f"写入虚拟盘每日汇总失败：{e}")


# ── 虚拟开仓 ───────────────────────────────────────────

def virtual_open():
    log.info("【虚拟开仓开始】（沙盘模式，不下真实订单）")

    valid_symbols, _ = get_exchange_info()
    tickers = get_ticker_24h(valid_symbols, MIN_VOLUME)
    tickers.sort(key=lambda x: float(x["priceChangePercent"]), reverse=True)

    # ── 候选池 ──
    gainer_pool_raw = tickers[:TOP_N]                          # 涨幅榜 TOP10（无过滤）
    loser_pool_raw  = tickers[-TOP_N:][::-1]                   # 跌幅榜 TOP10（无过滤）
    gainer_pool_big = tickers[:SHORT_TOP_N * CANDIDATE_BUF]    # 涨幅榜候选池（有过滤用）
    loser_pool_big  = tickers[-(LONG_TOP_N * CANDIDATE_BUF):][::-1]

    all_syms = list(set(
        [t["symbol"] for t in gainer_pool_raw + loser_pool_raw + gainer_pool_big + loser_pool_big]
    ))

    # 拉市值
    try:
        market_data = get_coin_market_data(all_syms)
    except Exception as e:
        log.warning(f"CoinGecko 获取失败，has_mcap 全部标记为 False：{e}")
        market_data = {}

    def has_mcap(t):
        return bool(market_data.get(t["symbol"], {}).get("market_cap"))

    # ── 筛选有过滤的候选 ──
    if market_data:
        gainer_filtered = [t for t in gainer_pool_big
                           if has_mcap(t) and float(t["priceChangePercent"]) >= SHORT_MIN_CHANGE
                           ][:SHORT_TOP_N]
        loser_filtered  = [t for t in loser_pool_big
                           if has_mcap(t) and float(t["priceChangePercent"]) <= -LONG_MIN_CHANGE
                           ][:LONG_TOP_N]
    else:
        gainer_filtered = [t for t in gainer_pool_big
                           if float(t["priceChangePercent"]) >= SHORT_MIN_CHANGE
                           ][:SHORT_TOP_N]
        loser_filtered  = [t for t in loser_pool_big
                           if float(t["priceChangePercent"]) <= -LONG_MIN_CHANGE
                           ][:LONG_TOP_N]

    # ── 采集辅助指标 ──
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

    # ── 8 组虚拟仓位 ──
    groups = [
        ("涨幅榜-空（有过滤）", gainer_filtered, "空"),
        ("涨幅榜-空（无过滤）", gainer_pool_raw, "空"),
        ("涨幅榜-多（有过滤）", gainer_filtered, "多"),
        ("涨幅榜-多（无过滤）", gainer_pool_raw, "多"),
        ("跌幅榜-空（有过滤）", loser_filtered,  "空"),
        ("跌幅榜-空（无过滤）", loser_pool_raw,  "空"),
        ("跌幅榜-多（有过滤）", loser_filtered,  "多"),
        ("跌幅榜-多（无过滤）", loser_pool_raw,  "多"),
    ]

    for side_label, ticker_group, direction in groups:
        log.info(f"── {side_label}（{len(ticker_group)} 个）──")
        for t in ticker_group:
            sym = t["symbol"]
            pct = float(t["priceChangePercent"])

            try:
                entry = get_mark_price(sym)
            except Exception as e:
                log.warning(f"  {sym} 获取标记价失败，跳过：{e}")
                continue

            md  = market_data.get(sym, {})
            mc  = md.get("market_cap", 0)
            cs  = md.get("circulating_supply", 0)
            fr  = funding_rates.get(sym)
            oi  = oi_changes.get(sym)
            ls  = ls_ratios.get(sym)

            fr_str = f"  资金费率 {fr*100:+.4f}%" if fr is not None else ""
            log.info(f"  {sym} {side_label}  涨跌 {pct:+.2f}%  入场价 {entry:.4f}{fr_str}")

            new_rows.append({
                "open_time":           ts,
                "close_time":          None,
                "symbol":              sym,
                "side":                side_label,
                "change_pct":          pct,
                "market_cap_usd":      fmt_large(mc) if mc else None,
                "circulating_supply":  fmt_large(cs) if cs else None,
                "has_mcap":            1 if mc else 0,
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


# ── 虚拟持仓快照 ──────────────────────────────────────

MONITOR_INTERVAL = 5    # 快照间隔（分钟）；2→5 降 CPU 压力 60%
MONITOR_OFFSET   = 0    # 偏移；主盘 0 / 4h 1 / 8h 2 / 12h 3，错开多服务快照

def virtual_snapshot():
    """对所有未平仓虚拟仓位拍快照，记录当前 PnL/ROE"""
    unclosed = db.get_virtual_log_unclosed()
    if not unclosed:
        return

    # 批量拉一次全市场价，替代循环串行 API
    try:
        price_map = get_all_mark_prices()
    except Exception as e:
        log.warning(f"批量拉价失败，本次快照跳过：{e}")
        return

    now = datetime.now()
    ts  = now.strftime("%Y-%m-%d %H:%M:%S")
    rows = []

    for row in unclosed:
        sym   = row["symbol"]
        side  = row["side"]
        entry = row["entry_price"]
        if entry is None:
            continue
        mark = price_map.get(sym)
        if mark is None:
            continue

        notional = MARGIN_PER_POS * LEVERAGE
        if "空" in side:
            pnl = (entry - mark) / entry * notional
        else:
            pnl = (mark - entry) / entry * notional
        roe = pnl / MARGIN_PER_POS * 100

        rows.append({
            "time":            ts,
            "symbol":          sym,
            "side":            side,
            "entry_price":     entry,
            "mark_price":      mark,
            "unrealized_pnl":  pnl,
            "roe_pct":         roe,
        })

    if rows:
        db.insert_virtual_detail(rows)
        log.info(f"虚拟持仓快照：{len(rows)} 个仓位")


# ── 定时工具 ───────────────────────────────────────────

CHECK_INTERVAL = 60  # 主循环检查间隔（秒）

def _time_match(now, hour, minute):
    return now.hour == hour and now.minute == minute


# ── 主循环 ─────────────────────────────────────────────

def main():
    log.info("虚拟开单沙盘启动")
    log.info(f"  每天 {CLOSE_HOUR:02d}:{CLOSE_MINUTE:02d} 虚拟平仓")
    log.info(f"  每天 {OPEN_HOUR:02d}:{OPEN_MINUTE:02d} 虚拟开仓")
    log.info(f"  持仓快照：每 {MONITOR_INTERVAL} 分钟")
    log.info(f"  8组：涨幅榜/跌幅榜 × 做空/做多 × 有过滤/无过滤")
    log.info(f"  有过滤参数：涨幅>={SHORT_MIN_CHANGE}% / 跌幅>={LONG_MIN_CHANGE}% + 市值过滤，各TOP{TOP_N}")
    log.info(f"  日志：SQLite 数据库")

    did_close = False
    did_open  = False
    last_snapshot_slot = -1

    # 启动时立即快照一次
    try:
        virtual_snapshot()
        now = datetime.now()
        last_snapshot_slot = (now.hour * 60 + now.minute - MONITOR_OFFSET) // MONITOR_INTERVAL
    except Exception as e:
        log.error(f"首次快照失败：{e}")

    while True:
        time.sleep(CHECK_INTERVAL)
        now = datetime.now()

        # 每天 0 点重置开平仓标记
        if now.hour == 0 and now.minute < 1:
            did_close = False
            did_open  = False

        # 虚拟平仓
        if _time_match(now, CLOSE_HOUR, CLOSE_MINUTE) and not did_close:
            try:
                virtual_close()
                did_close = True
            except Exception as e:
                log.error(f"虚拟平仓出错：{e}", exc_info=True)

        # 虚拟开仓
        if _time_match(now, OPEN_HOUR, OPEN_MINUTE) and not did_open:
            try:
                virtual_open()
                did_open = True
            except Exception as e:
                log.error(f"虚拟开仓出错：{e}", exc_info=True)

        # 每 MONITOR_INTERVAL 分钟快照（带偏移）
        current_slot = (now.hour * 60 + now.minute - MONITOR_OFFSET) // MONITOR_INTERVAL
        if current_slot != last_snapshot_slot:
            try:
                virtual_snapshot()
                last_snapshot_slot = current_slot
            except Exception as e:
                log.error(f"虚拟快照失败：{e}")


if __name__ == "__main__":
    main()
