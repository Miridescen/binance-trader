"""
监控币安合约账户持仓盈亏，每小时整点统计一次
- 终端：按币种展示详细表格
- 日志：追加写入 positions_log.csv（多单/空单分别统计）
"""

import os
import csv
import time
import logging
from datetime import datetime
from binance_client import auth_get, auth_post, get_funding_income, is_hedge_mode

LOG_FILE        = os.path.join(os.path.dirname(__file__), "positions_log.csv")
EVENTS_LOG_FILE = os.path.join(os.path.dirname(__file__), "events_log.csv")
EVENTS_FIELDS   = ["time", "event", "detail"]

STOP_LOSS_ROE_PCT = -120  # ROE 低于此值触发止损（%），对应3x杠杆下价格反向移动约40%
CHECK_INTERVAL    = 60    # 止损检查间隔（秒）

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


# ── 止损 ───────────────────────────────────────────────

def log_event(event: str, detail: str):
    write_header = not os.path.exists(EVENTS_LOG_FILE) or os.path.getsize(EVENTS_LOG_FILE) == 0
    with open(EVENTS_LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EVENTS_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow({
            "time":   datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "event":  event,
            "detail": detail,
        })

def close_position(p: dict, hedge: bool) -> bool:
    """市价平掉单个持仓，成功返回 True"""
    symbol = p["symbol"]
    amt    = float(p["positionAmt"])
    side   = "BUY" if amt < 0 else "SELL"
    params = {"symbol": symbol, "side": side, "type": "MARKET",
              "quantity": abs(amt), "reduceOnly": "true"}
    if hedge:
        params.pop("reduceOnly")
        params["positionSide"] = "SHORT" if amt < 0 else "LONG"
    result = auth_post("/fapi/v1/order", params)
    return "orderId" in result

def check_stop_loss(positions: list, hedge: bool):
    """检查所有持仓，ROE 低于阈值则立即止损平仓"""
    for p in positions:
        amt      = float(p["positionAmt"])
        entry    = float(p["entryPrice"])
        mark     = float(p["markPrice"])
        pnl      = float(p["unRealizedProfit"])
        leverage = int(p["leverage"])
        margin   = entry * abs(amt) / leverage if leverage and entry else 0
        if margin == 0:
            continue
        roe = pnl / margin * 100
        if roe <= STOP_LOSS_ROE_PCT:
            symbol   = p["symbol"]
            side_str = "空" if amt < 0 else "多"
            log.warning(f"【止损触发】{symbol} {side_str}  ROE {roe:+.1f}%  标记价 {mark:.4f}")
            if close_position(p, hedge):
                detail = f"{symbol} {side_str} ROE={roe:.1f}% entry={entry} mark={mark}"
                log_event("STOP_LOSS", detail)
                log.warning(f"  {symbol} 止损平仓成功 ✅")
            else:
                log.error(f"  {symbol} 止损平仓失败 ❌")


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

CSV_FIELDS = ["time", "balance_usdt", "long_count", "long_pnl",
              "short_count", "short_pnl", "total_pnl", "funding_fee"]

def save_csv(positions: list, balance: float, now: datetime, funding_fee: float = 0.0):
    s = calc_stats(positions)
    write_header = not os.path.exists(LOG_FILE) or os.path.getsize(LOG_FILE) == 0
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow({
            "time":         now.strftime("%Y-%m-%d %H:%M:%S"),
            "balance_usdt": f"{balance:.2f}",
            "long_count":   s["long_count"],
            "long_pnl":     f"{s['long_pnl']:.2f}",
            "short_count":  s["short_count"],
            "short_pnl":    f"{s['short_pnl']:.2f}",
            "total_pnl":    f"{s['total_pnl']:.2f}",
            "funding_fee":  f"{funding_fee:.4f}",
        })


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

def main():
    log.info(f"持仓监控启动  止损线：ROE ≤ {STOP_LOSS_ROE_PCT}%  检查间隔：{CHECK_INTERVAL}s")
    log.info(f"持仓日志：{LOG_FILE}")

    hedge            = is_hedge_mode()
    last_report_hour = -1

    # 启动时立即统计一次
    try:
        collect_and_report()
        last_report_hour = datetime.now().hour
    except Exception as e:
        log.error(f"首次统计失败：{e}")

    while True:
        time.sleep(CHECK_INTERVAL)
        now = datetime.now()

        try:
            positions = get_positions()
            check_stop_loss(positions, hedge)
        except Exception as e:
            log.error(f"止损检查失败：{e}")

        # 每小时整点输出报告
        if now.hour != last_report_hour:
            try:
                collect_and_report()
                last_report_hour = now.hour
            except Exception as e:
                log.error(f"统计失败：{e}")


if __name__ == "__main__":
    main()
