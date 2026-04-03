"""
监控币安合约账户持仓盈亏，每小时整点统计一次；
额外在 08:50（平仓前）和 09:30（开仓后）各做一次特殊快照。
- 终端：按币种展示详细表格
- 日志：追加写入 positions_log.csv（多单/空单分别统计）
"""

import os
import time
import logging
from datetime import datetime
from binance_client import auth_get, get_funding_income, is_hedge_mode
import db

CHECK_INTERVAL       = 20           # 检查间隔（秒）
SPECIAL_SNAPSHOTS    = {(8, 50), (9, 30)}   # 额外快照时间点 (hour, minute)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ── 数据获取 ───────────────────────────────────────────

def get_positions() -> list:
    data = auth_get("/fapi/v2/positionRisk")
    return [p for p in data if float(p["positionAmt"]) != 0]

def get_account_balance() -> float:
    data = auth_get("/fapi/v2/account")
    for asset in data["assets"]:
        if asset["asset"] == "USDT":
            return float(asset["marginBalance"])
    return 0.0


# ── 统计 ───────────────────────────────────────────────

def calc_stats(positions: list) -> dict:
    long_pnl = short_pnl = 0.0
    long_cnt = short_cnt = profit_cnt = loss_cnt = 0
    for p in positions:
        amt = float(p["positionAmt"])
        pnl = float(p["unRealizedProfit"])
        if amt > 0:
            long_pnl += pnl
            long_cnt += 1
        else:
            short_pnl += pnl
            short_cnt += 1
        if pnl > 0:
            profit_cnt += 1
        elif pnl < 0:
            loss_cnt += 1
    return {
        "long_count":  long_cnt,
        "short_count": short_cnt,
        "long_pnl":    long_pnl,
        "short_pnl":   short_pnl,
        "total_pnl":   long_pnl + short_pnl,
        "profit_cnt":  profit_cnt,
        "loss_cnt":    loss_cnt,
    }


# ── 表格打印 ───────────────────────────────────────────

COL = {"symbol": 14, "side": 4, "amt": 10, "entry": 10, "mark": 10, "pnl": 11, "roe": 8, "lev": 5}

def sep(char="-"):
    print(char * (sum(COL.values()) + len(COL) * 3 + 1))

def print_report(positions: list, balance: float, now: datetime, funding_fee: float = 0.0):
    s = calc_stats(positions)
    sep("=")
    print(f"  统计时间：{now.strftime('%Y-%m-%d %H:%M:%S')}    账户余额：{balance:.2f} USDT")
    print(f"  未实现总盈亏：{s['total_pnl']:+.2f} USDT    "
          f"盈利仓位：{s['profit_cnt']}  亏损仓位：{s['loss_cnt']}")
    sep("-")
    print(f"  多单（{s['long_count']:>2} 笔）总盈亏：{s['long_pnl']:>+10.2f} USDT    "
          f"空单（{s['short_count']:>2} 笔）总盈亏：{s['short_pnl']:>+10.2f} USDT")
    print(f"  本小时资金费率：{funding_fee:>+10.4f} USDT")
    sep("=")

    if not positions:
        print("  当前无持仓")
        sep("=")
        return

    print(
        f"| {'交易对':<{COL['symbol']}} | {'方向':<{COL['side']}} "
        f"| {'持仓量':>{COL['amt']}} | {'开仓价':>{COL['entry']}} "
        f"| {'标记价':>{COL['mark']}} | {'未实现盈亏':>{COL['pnl']}} "
        f"| {'ROE':>{COL['roe']}} | {'杠杆':>{COL['lev']}} |"
    )
    sep()

    for p in sorted(positions, key=lambda p: float(p["unRealizedProfit"]), reverse=True):
        amt      = float(p["positionAmt"])
        entry    = float(p["entryPrice"])
        mark     = float(p["markPrice"])
        pnl      = float(p["unRealizedProfit"])
        leverage = int(p["leverage"])
        margin   = entry * abs(amt) / leverage if leverage and entry else 0
        roe      = pnl / margin * 100 if margin else 0
        side     = "多" if amt > 0 else "空"
        pnl_str  = f"+{pnl:.2f}" if pnl >= 0 else f"{pnl:.2f}"
        print(
            f"| {p['symbol']:<{COL['symbol']}} | {side:<{COL['side']}} "
            f"| {abs(amt):>{COL['amt']}.4f} | {entry:>{COL['entry']}.4f} "
            f"| {mark:>{COL['mark']}.4f} | {pnl_str:>{COL['pnl']}} "
            f"| {roe:>+{COL['roe']}.1f}% | {leverage:>{COL['lev']}}x |"
        )
    sep("=")


# ── CSV 日志 ───────────────────────────────────────────

def save_csv(positions: list, balance: float, now: datetime, funding_fee: float = 0.0):
    s = calc_stats(positions)
    db.insert_positions_log({
        "time":         now.strftime("%Y-%m-%d %H:%M:%S"),
        "balance_usdt": balance,
        "long_count":   s["long_count"],
        "long_pnl":     s["long_pnl"],
        "short_count":  s["short_count"],
        "short_pnl":    s["short_pnl"],
        "total_pnl":    s["total_pnl"],
        "funding_fee":  funding_fee,
    })


# ── 仓位明细 CSV ──────────────────────────────────────

def save_detail_csv(positions: list, now: datetime):
    """每小时写入每个仓位的详细盈亏到数据库"""
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for p in positions:
        amt      = float(p["positionAmt"])
        entry    = float(p["entryPrice"])
        mark     = float(p["markPrice"])
        pnl      = float(p["unRealizedProfit"])
        leverage = int(p["leverage"])
        margin   = entry * abs(amt) / leverage if leverage and entry else 0
        roe      = pnl / margin * 100 if margin else 0
        rows.append({
            "time":            ts,
            "symbol":          p["symbol"],
            "side":            "多" if amt > 0 else "空",
            "entry_price":     entry,
            "mark_price":      mark,
            "position_amt":    abs(amt),
            "unrealized_pnl":  pnl,
            "roe_pct":         roe,
        })
    if rows:
        db.insert_positions_detail(rows)


# ── 主循环 ─────────────────────────────────────────────

def collect_and_report():
    now       = datetime.now()
    positions = get_positions()
    balance   = get_account_balance()
    end_ms    = int(now.timestamp() * 1000)
    start_ms  = end_ms - 3_600_000
    try:
        funding_fee = get_funding_income(start_ms, end_ms)
    except Exception as e:
        log.warning(f"获取资金费率失败：{e}")
        funding_fee = 0.0
    print_report(positions, balance, now, funding_fee)
    save_csv(positions, balance, now, funding_fee)
    save_detail_csv(positions, now)

def main():
    log.info(f"持仓监控启动  间隔：{CHECK_INTERVAL}s（仅监控，无止盈止损）")
    log.info(f"持仓日志：SQLite 数据库")
    log.info(f"特殊快照时间：{sorted(SPECIAL_SNAPSHOTS)}")

    last_report_slot   = -1       # 上次采集的时间槽（每20分钟一个槽）
    reported_specials  = set()    # 记录当天已触发的特殊快照 (hour, minute)
    REPORT_INTERVAL    = 2        # 采集间隔（分钟）

    # 启动时立即统计一次
    try:
        collect_and_report()
        now = datetime.now()
        last_report_slot = now.hour * 60 + now.minute // REPORT_INTERVAL * REPORT_INTERVAL
    except Exception as e:
        log.error(f"首次统计失败：{e}")

    while True:
        time.sleep(CHECK_INTERVAL)
        now = datetime.now()

        # 每天 0 点重置特殊快照记录
        if now.hour == 0 and now.minute < 1:
            reported_specials.clear()

        # 特殊时间点快照（08:50 平仓前 / 09:30 开仓后）
        key = (now.hour, now.minute)
        if key in SPECIAL_SNAPSHOTS and key not in reported_specials:
            try:
                log.info(f"【特殊快照】{now.hour:02d}:{now.minute:02d}")
                collect_and_report()
                reported_specials.add(key)
            except Exception as e:
                log.error(f"特殊快照失败：{e}")

        # 每 20 分钟采集一次（:00, :20, :40）
        current_slot = now.hour * 60 + now.minute // REPORT_INTERVAL * REPORT_INTERVAL
        if current_slot != last_report_slot:
            try:
                collect_and_report()
                last_report_slot = current_slot
            except Exception as e:
                log.error(f"统计失败：{e}")


if __name__ == "__main__":
    main()
