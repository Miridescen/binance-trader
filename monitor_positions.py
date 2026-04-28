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
from binance_client import auth_get, auth_post, get_funding_income, is_hedge_mode, get_mark_price
import db

CHECK_INTERVAL       = 20           # 检查间隔（秒）
SPECIAL_SNAPSHOTS    = {(8, 29), (9, 30)}   # 额外快照时间点 (hour, minute)：平仓前 / 开仓后

# ── 止损配置 ────────────────────────────────────────
# 灰度上线：先用 -200%（几乎不触发，仅打通链路），观察 2 天稳定后改 -100%
STOPLOSS_ROE             = -200.0   # ROE 触及此值视为待止损
STOPLOSS_CONFIRM_COUNT   = 2        # 连续 N 次确认才平仓（防插针）
# 8:25~8:55 是定时平仓窗口，止损路径必须避开避免与限价/市价兜底撞车
STOPLOSS_SKIP_MIN_FROM   = (8, 25)
STOPLOSS_SKIP_MIN_TO     = (8, 55)
LEVERAGE_FALLBACK        = 3        # row 缺 leverage 时的兜底，与策略 LEVERAGE 一致

# 同一币种连续触发计数（symbol -> int）
_stoploss_hits: dict = {}

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

COL = {"symbol": 14, "side": 16, "amt": 10, "entry": 10, "mark": 10, "pnl": 11, "roe": 8, "lev": 5}

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

    # 从 open_log 获取 side 标记
    side_map = {}
    try:
        with db.get_conn() as conn:
            r = conn.execute(
                "SELECT symbol, side FROM open_log WHERE close_time IS NULL ORDER BY id DESC"
            ).fetchall()
            for row in r:
                if row["symbol"] not in side_map:
                    side_map[row["symbol"]] = row["side"]
    except Exception:
        pass

    rows = []
    for p in positions:
        amt      = float(p["positionAmt"])
        entry    = float(p["entryPrice"])
        mark     = float(p["markPrice"])
        pnl      = float(p["unRealizedProfit"])
        leverage = int(p["leverage"])
        margin   = entry * abs(amt) / leverage if leverage and entry else 0
        roe      = pnl / margin * 100 if margin else 0
        sym      = p["symbol"]
        side     = side_map.get(sym, "涨幅榜-空（有过滤）" if amt < 0 else "多")
        rows.append({
            "time":            ts,
            "symbol":          sym,
            "side":            side,
            "entry_price":     entry,
            "mark_price":      mark,
            "position_amt":    abs(amt),
            "unrealized_pnl":  pnl,
            "roe_pct":         roe,
        })
    if rows:
        db.insert_positions_detail(rows)


# ── ROE 硬止损 ────────────────────────────────────────

def _in_close_window(now: datetime) -> bool:
    """8:25~8:55 是定时平仓窗口，止损路径必须避开"""
    fh, fm = STOPLOSS_SKIP_MIN_FROM
    th, tm = STOPLOSS_SKIP_MIN_TO
    minutes = now.hour * 60 + now.minute
    return fh * 60 + fm <= minutes <= th * 60 + tm


def _market_close_one(symbol: str, amt: float, hedge: bool) -> bool:
    """市价平掉单个持仓。返回是否下单成功。"""
    side = "BUY" if amt < 0 else "SELL"
    params = {"symbol": symbol, "side": side, "type": "MARKET",
              "quantity": abs(amt), "reduceOnly": "true"}
    if hedge:
        params.pop("reduceOnly")
        params["positionSide"] = "SHORT" if amt < 0 else "LONG"
    try:
        result = auth_post("/fapi/v1/order", params)
    except Exception as e:
        log.error(f"❌ 止损下单 {symbol} 异常：{e}")
        return False
    if "orderId" not in result:
        log.error(f"❌ 止损下单 {symbol} 失败：{result.get('msg', result)}")
        return False
    log.warning(f"🚨 止损成交 {symbol} 数量 {abs(amt)} ✅")
    return True


def _do_stoploss(symbol: str, amt: float, hedge: bool):
    """ROE 止损完整路径：先币安 API 平仓 → 等成交 → 用 mark 重算 pnl/roe → FIFO 回填 open_log"""
    # Step 1: 调币安 API 平仓（顺序绝不能反，否则本地已写但账户没动）
    if not _market_close_one(symbol, amt, hedge):
        return

    # Step 2: 等成交回报落地（市价单一般 < 1s，给 2s 余量）
    time.sleep(2)

    # Step 3: 取 FIFO 最早未平仓记录
    row = db.get_oldest_open_position(symbol)
    if not row:
        log.warning(f"  {symbol} 平仓后未在 open_log 找到对应未平仓记录")
        return

    # Step 4: 取 mark_price 重算 pnl/roe（实际有滑点，但与定时平仓口径一致）
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        mark = get_mark_price(symbol)
    except Exception:
        log.warning(f"  {symbol} 取 mark 失败，仅写 close_time + reason")
        db.update_close_data(symbol, "", {"close_time": ts, "close_reason": "ROE止损"})
        return

    entry  = row["entry_price"]
    amt_db = row["position_amt"] or abs(amt)
    lev    = row["leverage"] or LEVERAGE_FALLBACK
    margin = entry * amt_db / lev if lev and entry else 0
    is_short = "空" in (row["side"] or "")
    pnl = (entry - mark) * amt_db if is_short else (mark - entry) * amt_db
    roe = pnl / margin * 100 if margin else 0

    db.update_close_data(symbol, "", {
        "close_time":     ts,
        "close_price":    mark,
        "unrealized_pnl": round(pnl, 4),
        "roe_pct":        round(roe, 2),
        "close_reason":   "ROE止损",
    })
    log.warning(f"  ✅ 回填 {symbol} close={mark:.6f} pnl={pnl:+.4f} roe={roe:+.1f}%")


def check_and_stoploss(positions: list, now: datetime):
    """每次拉到 positions 后调用：扫描所有持仓，连续 N 次 ROE ≤ 阈值则平仓"""
    if _in_close_window(now):
        return  # 让定时平仓走完

    triggered_now = set()
    hedge = None  # 懒加载，仅有持仓需要平时才查
    for p in positions:
        amt = float(p["positionAmt"])
        if amt == 0:
            continue
        symbol   = p["symbol"]
        entry    = float(p["entryPrice"])
        pnl      = float(p["unRealizedProfit"])
        leverage = int(p["leverage"])
        margin   = entry * abs(amt) / leverage if leverage and entry else 0
        roe      = pnl / margin * 100 if margin else 0

        if roe <= STOPLOSS_ROE:
            triggered_now.add(symbol)
            hits = _stoploss_hits.get(symbol, 0) + 1
            _stoploss_hits[symbol] = hits
            log.warning(f"⚠️ {symbol} ROE {roe:+.1f}% ≤ {STOPLOSS_ROE}% (确认 {hits}/{STOPLOSS_CONFIRM_COUNT})")
            if hits >= STOPLOSS_CONFIRM_COUNT:
                if hedge is None:
                    try:
                        hedge = is_hedge_mode()
                    except Exception as e:
                        log.error(f"查 hedge_mode 失败：{e}")
                        hedge = False
                _do_stoploss(symbol, amt, hedge)
                _stoploss_hits.pop(symbol, None)

    # 反弹的（本轮不再触发）清零确认计数
    for sym in list(_stoploss_hits.keys()):
        if sym not in triggered_now:
            _stoploss_hits.pop(sym, None)


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
    try:
        check_and_stoploss(positions, now)
    except Exception as e:
        log.error(f"止损检查异常：{e}")

def main():
    log.info(f"持仓监控启动  间隔：{CHECK_INTERVAL}s")
    log.info(f"持仓日志：SQLite 数据库")
    log.info(f"特殊快照时间：{sorted(SPECIAL_SNAPSHOTS)}")
    log.info(f"ROE 止损：阈值 {STOPLOSS_ROE}% / 连续 {STOPLOSS_CONFIRM_COUNT} 次确认 / 跳过 {STOPLOSS_SKIP_MIN_FROM[0]:02d}:{STOPLOSS_SKIP_MIN_FROM[1]:02d}~{STOPLOSS_SKIP_MIN_TO[0]:02d}:{STOPLOSS_SKIP_MIN_TO[1]:02d}")

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
