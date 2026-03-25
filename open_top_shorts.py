"""
每天定时策略：
  08:50 → 撤销所有未成交限价单 + 市价平掉所有持仓
  09:00 → 涨幅榜 TOP10 开 3 倍限价空单，每单保证金 10 USDT
         跌幅榜 TOP10 开 3 倍限价多单，每单保证金 10 USDT
  未成交则每 60 秒换价重下，最多 10 次，超过后改市价单
"""

import csv
import math
import os
import time
import logging
from datetime import datetime, timedelta
from binance_client import (
    auth_get, auth_post, auth_delete,
    get_exchange_info, get_ticker_24h, get_mark_price, is_hedge_mode,
    get_coin_market_data, get_btc_change_pct, get_all_funding_rates,
    get_commissions_by_symbol, get_oi_changes, get_long_short_ratios,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

OPEN_LOG_FILE    = os.path.join(os.path.dirname(__file__), "open_log.csv")
EVENTS_LOG_FILE  = os.path.join(os.path.dirname(__file__), "events_log.csv")
BATCH_LOG_FILE   = os.path.join(os.path.dirname(__file__), "batch_summary_log.csv")
BATCH_FIELDS     = ["close_time", "long_count", "long_pnl",
                    "short_count", "short_pnl", "total_pnl"]
LOG_FIELDS      = ["open_time", "close_time", "symbol", "side",
                   "change_pct", "market_cap_usd", "circulating_supply",
                   "btc_change_pct", "symbol_funding_rate", "oi_change_pct",
                   "long_short_ratio", "open_commission",
                   "entry_price", "close_price", "position_amt",
                   "unrealized_pnl", "roe_pct", "leverage", "close_commission"]
EVENTS_FIELDS   = ["time", "event", "detail"]

LEVERAGE             = 3
MARGIN_PER_POS       = 10
TOP_N                = 20
CANDIDATE_BUFFER     = 6        # 拉取 TOP_N * N 倍候选，过滤无市值后取前 TOP_N
MIN_VOLUME           = 10_000_000
ORDER_CHECK_INTERVAL = 60
MAX_RETRIES          = 10
CLOSE_HOUR, CLOSE_MINUTE = 8, 50
OPEN_HOUR,  OPEN_MINUTE  = 9, 0


# ── 格式工具 ───────────────────────────────────────────

def fmt_large(n: float) -> str:
    """将大数字格式化为 B / M 单位"""
    if n >= 1e9:
        return f"{n / 1e9:.2f}B"
    if n >= 1e6:
        return f"{n / 1e6:.2f}M"
    if n > 0:
        return f"{n:.0f}"
    return "N/A"


# ── 精度工具 ───────────────────────────────────────────

def floor_to_step(value: float, step: float) -> float:
    return math.floor(value / step) * step

def round_to_tick(value: float, tick: float) -> float:
    return round(round(value / tick) * tick, max(0, -int(math.floor(math.log10(tick)))))

def fmt(value: float, step: float) -> str:
    return f"{value:.{max(0, -int(math.floor(math.log10(step))))}f}"


# ── 平仓逻辑 ───────────────────────────────────────────

def cancel_all_open_orders():
    open_orders = auth_get("/fapi/v1/openOrders")
    symbols = set(o["symbol"] for o in open_orders)
    for symbol in symbols:
        result = auth_delete("/fapi/v1/allOpenOrders", {"symbol": symbol})
        status = "✅" if result.get("code") == 200 else f"❌ {result.get('msg', result)}"
        log.info(f"撤单 {symbol} {status}")
        time.sleep(0.1)
    log.info(f"共撤销 {len(symbols)} 个交易对的挂单")

def close_all_positions(hedge: bool):
    positions = auth_get("/fapi/v2/positionRisk")
    active    = [p for p in positions if float(p["positionAmt"]) != 0]
    if not active:
        log.info("当前无持仓，无需平仓")
        return
    closed = 0
    for p in active:
        symbol = p["symbol"]
        amt    = float(p["positionAmt"])
        side   = "BUY" if amt < 0 else "SELL"
        params = {"symbol": symbol, "side": side, "type": "MARKET",
                  "quantity": abs(amt), "reduceOnly": "true"}
        if hedge:
            params.pop("reduceOnly")
            params["positionSide"] = "SHORT" if amt < 0 else "LONG"
        result = auth_post("/fapi/v1/order", params)
        if "orderId" in result:
            log.info(f"平仓 {symbol} {'空→买' if side=='BUY' else '多→卖'} 数量 {abs(amt)} ✅")
            closed += 1
        else:
            log.error(f"平仓 {symbol} 失败：{result.get('msg', result)}")
        time.sleep(0.15)
    log.info(f"共平仓 {closed}/{len(active)} 个持仓")

def save_close_log(positions: list, now: datetime):
    """平仓前把收益数据回填到对应的开仓行；无匹配行则新增一行"""
    ts   = now.strftime("%Y-%m-%d %H:%M:%S")
    rows = _read_log()

    for p in positions:
        amt      = float(p["positionAmt"])
        entry    = float(p["entryPrice"])
        mark     = float(p["markPrice"])
        pnl      = float(p["unRealizedProfit"])
        leverage = int(p["leverage"])
        margin   = entry * abs(amt) / leverage if leverage and entry else 0
        roe      = pnl / margin * 100 if margin else 0
        sym      = p["symbol"]

        close_data = {
            "close_time":    ts,
            "entry_price":   f"{entry:.6f}",
            "close_price":   f"{mark:.6f}",
            "position_amt":  f"{abs(amt):.6f}",
            "unrealized_pnl": f"{pnl:.4f}",
            "roe_pct":       f"{roe:.4f}",
            "leverage":      leverage,
        }

        # 找最近一条同币种且未平仓的开仓行（open_time 最大的那条）
        candidates = [
            (i, row) for i, row in enumerate(rows)
            if row["symbol"] == sym and not row.get("close_time")
        ]
        matched = False
        if candidates:
            # 取 open_time 最新的一条，忽略更早的孤立未平仓行
            best_i, best_row = max(candidates, key=lambda x: x[1].get("open_time", ""))
            best_row.update(close_data)
            matched = True

        if not matched:
            rows.append({
                "open_time":          "",
                "symbol":             sym,
                "side":               "多" if amt > 0 else "空",
                "change_pct":         "",
                "market_cap_usd":     "",
                "circulating_supply": "",
                **close_data,
            })

    _write_log(rows)
    log.info(f"上周期收益已回填到 {OPEN_LOG_FILE}（{len(positions)} 条）")


def _patch_close_commissions(commissions: dict):
    """平仓后将手续费回填到当天 close_time 不为空、close_commission 为空的行"""
    rows  = _read_log()
    today = datetime.now().strftime("%Y-%m-%d")
    for row in rows:
        sym = row.get("symbol", "")
        if (sym in commissions
                and row.get("close_time", "").startswith(today)
                and not row.get("close_commission")):
            row["close_commission"] = f"{commissions[sym]:.6f}"
    _write_log(rows)


def print_close_summary(positions: list):
    """平仓前打印本批次多单/空单盈亏汇总"""
    longs  = [p for p in positions if float(p["positionAmt"]) > 0]
    shorts = [p for p in positions if float(p["positionAmt"]) < 0]

    def calc(ps):
        total_pnl = sum(float(p["unRealizedProfit"]) for p in ps)
        details = []
        for p in sorted(ps, key=lambda x: float(x["unRealizedProfit"]), reverse=True):
            amt    = float(p["positionAmt"])
            entry  = float(p["entryPrice"])
            mark   = float(p["markPrice"])
            pnl    = float(p["unRealizedProfit"])
            lev    = int(p["leverage"])
            margin = entry * abs(amt) / lev if lev and entry else 0
            roe    = pnl / margin * 100 if margin else 0
            details.append((p["symbol"], pnl, roe))
        return total_pnl, details

    long_total,  long_details  = calc(longs)
    short_total, short_details = calc(shorts)
    grand_total = long_total + short_total

    sep = "=" * 60
    print(sep)
    print(f"  【本批次收益汇总】{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(sep)
    print(f"  多单（{len(longs):>2} 笔）总盈亏：{long_total:>+10.2f} USDT")
    for sym, pnl, roe in long_details:
        print(f"    {sym:<16} {pnl:>+8.2f} USDT   ROE {roe:>+7.1f}%")
    print(f"  空单（{len(shorts):>2} 笔）总盈亏：{short_total:>+10.2f} USDT")
    for sym, pnl, roe in short_details:
        print(f"    {sym:<16} {pnl:>+8.2f} USDT   ROE {roe:>+7.1f}%")
    print(sep)
    print(f"  本批次总盈亏：{grand_total:>+.2f} USDT")
    print(sep)


def save_close_summary_csv(positions: list, now: datetime):
    """将本批次多空汇总写入 batch_summary_log.csv（每批次一行）"""
    longs  = [p for p in positions if float(p["positionAmt"]) > 0]
    shorts = [p for p in positions if float(p["positionAmt"]) < 0]
    long_pnl  = sum(float(p["unRealizedProfit"]) for p in longs)
    short_pnl = sum(float(p["unRealizedProfit"]) for p in shorts)

    write_header = not os.path.exists(BATCH_LOG_FILE) or os.path.getsize(BATCH_LOG_FILE) == 0
    with open(BATCH_LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=BATCH_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow({
            "close_time":  now.strftime("%Y-%m-%d %H:%M:%S"),
            "long_count":  len(longs),
            "long_pnl":    f"{long_pnl:.4f}",
            "short_count": len(shorts),
            "short_pnl":   f"{short_pnl:.4f}",
            "total_pnl":   f"{long_pnl + short_pnl:.4f}",
        })
    log.info(f"批次盈亏已写入 {BATCH_LOG_FILE}")


def run_close():
    log.info("=" * 50)
    log.info("【平仓开始】")
    close_start_ms = int(time.time() * 1000)
    hedge     = is_hedge_mode()
    positions = auth_get("/fapi/v2/positionRisk")
    active    = [p for p in positions if float(p["positionAmt"]) != 0]
    if active:
        print_close_summary(active)
        save_close_summary_csv(active, datetime.now())
        save_close_log(active, datetime.now())
    log.info("撤销所有挂单...")
    cancel_all_open_orders()
    log.info("市价平仓...")
    close_all_positions(hedge)
    close_end_ms = int(time.time() * 1000)

    try:
        close_commissions = get_commissions_by_symbol(close_start_ms, close_end_ms)
        total_comm = sum(close_commissions.values())
        log.info(f"本批平仓手续费合计：{total_comm:.4f} USDT（{len(close_commissions)} 个币种）")
        if close_commissions:
            _patch_close_commissions(close_commissions)
    except Exception as e:
        log.warning(f"获取平仓手续费失败：{e}")

    log.info("【平仓完成】")


# ── 开单工具 ───────────────────────────────────────────

def set_leverage_verified(symbol: str) -> bool:
    """设置杠杆并验证成功，失败返回 False"""
    result = auth_post("/fapi/v1/leverage", {"symbol": symbol, "leverage": LEVERAGE})
    if "leverage" in result:
        return True
    log.error(f"  {symbol} 杠杆设置失败：{result.get('msg', result)}")
    return False

def get_order_status(symbol: str, order_id: int) -> str:
    result = auth_get("/fapi/v1/order", {"symbol": symbol, "orderId": order_id})
    return result.get("status", "UNKNOWN")

def cancel_order(symbol: str, order_id: int):
    auth_delete("/fapi/v1/order", {"symbol": symbol, "orderId": order_id})

def place_limit_order(symbol: str, info: dict, side: str, hedge: bool, attempt: int):
    """下限价单，返回 {orderId, info} 或 None"""
    step  = info["step_size"]
    tick  = info["tick_size"]
    min_n = info["min_notional"]

    mark_price = get_mark_price(symbol)
    qty        = floor_to_step(MARGIN_PER_POS * LEVERAGE / mark_price, step)
    price      = round_to_tick(mark_price, tick)

    if qty * mark_price < min_n:
        log.warning(f"  {symbol} 跳过（名义价值 {qty * mark_price:.2f} < 最低 {min_n:.2f} USDT）")
        return None

    params = {
        "symbol": symbol, "side": side, "type": "LIMIT",
        "price": fmt(price, tick), "quantity": fmt(qty, step), "timeInForce": "GTC",
    }
    if hedge:
        params["positionSide"] = "SHORT" if side == "SELL" else "LONG"

    order = auth_post("/fapi/v1/order", params)
    direction = "开空" if side == "SELL" else "开多"
    if "orderId" in order:
        log.info(f"  {symbol} 第{attempt}次{direction} ✅ 数量 {fmt(qty, step)} 限价 {fmt(price, tick)} 标记价 {mark_price}")
        return {"orderId": order["orderId"], "info": info}
    else:
        log.error(f"  {symbol} 第{attempt}次下单失败 code={order.get('code')} {order.get('msg', order)}")
        return None

def place_market_order(symbol: str, info: dict, side: str, hedge: bool):
    """市价兜底开仓"""
    step       = info["step_size"]
    mark_price = get_mark_price(symbol)
    qty        = floor_to_step(MARGIN_PER_POS * LEVERAGE / mark_price, step)
    params     = {"symbol": symbol, "side": side, "type": "MARKET", "quantity": fmt(qty, step)}
    if hedge:
        params["positionSide"] = "SHORT" if side == "SELL" else "LONG"
    result    = auth_post("/fapi/v1/order", params)
    direction = "空" if side == "SELL" else "多"
    if "orderId" in result:
        log.info(f"  {symbol} 市价开{direction}成功 数量 {fmt(qty, step)} ✅")
    else:
        log.error(f"  {symbol} 市价开{direction}失败：{result.get('msg', result)}")


def run_batch_orders(label: str, tickers: list, side: str, symbol_info: dict, hedge: bool):
    direction = "涨幅" if side == "SELL" else "跌幅"
    log.info(f"── {label} ──")
    log.info(f"{direction}榜 TOP{TOP_N}：{[t['symbol'] for t in tickers]}")

    # 第一轮下单
    pending = {}
    for i, ticker in enumerate(tickers, 1):
        symbol = ticker["symbol"]
        pct    = float(ticker["priceChangePercent"])
        info   = symbol_info.get(symbol)
        if not info:
            log.warning(f"[{i}/{TOP_N}] {symbol} 无交易对信息，跳过")
            continue

        log.info(f"[{i:>2}/{TOP_N}] {symbol} {direction}幅 {pct:>+.2f}%")
        if not set_leverage_verified(symbol):
            log.warning(f"  {symbol} 杠杆设置失败，跳过此币种")
            continue

        result = place_limit_order(symbol, info, side, hedge, attempt=1)
        if result:
            pending[symbol] = result
        time.sleep(0.15)

    # 重试循环
    for attempt in range(2, MAX_RETRIES + 2):
        if not pending:
            break
        log.info(f"等待 {ORDER_CHECK_INTERVAL}s 后检查未成交订单（{label}）...")
        time.sleep(ORDER_CHECK_INTERVAL)

        still_pending = {}
        for symbol, data in pending.items():
            status = get_order_status(symbol, data["orderId"])

            if status == "FILLED":
                log.info(f"  {symbol} ✅ 已成交")

            elif status == "PARTIALLY_FILLED":
                # 部分成交：保留原单继续等，不撤不补
                log.info(f"  {symbol} 部分成交，继续等待...")
                still_pending[symbol] = data

            elif status in ("CANCELED", "EXPIRED", "REJECTED"):
                log.warning(f"  {symbol} 状态 {status}，重新下单")
                result = place_limit_order(symbol, data["info"], side, hedge, attempt)
                if result:
                    still_pending[symbol] = result
                time.sleep(0.15)

            else:  # NEW — 未成交，换价重下
                log.info(f"  {symbol} 未成交（{status}），换价重下（第{attempt}次）")
                cancel_order(symbol, data["orderId"])
                time.sleep(0.3)   # 等待撤单生效
                result = place_limit_order(symbol, data["info"], side, hedge, attempt)
                if result:
                    still_pending[symbol] = result
                time.sleep(0.15)

        pending = still_pending

    # 市价兜底
    if pending:
        log.warning(f"仍有 {len(pending)} 个 {label} 未成交，改用市价单...")
        for symbol, data in pending.items():
            cancel_order(symbol, data["orderId"])
            time.sleep(0.3)
            place_market_order(symbol, data["info"], side, hedge)
            time.sleep(0.15)


def log_event(event: str, detail: str):
    """向 events_log.csv 追加一条策略事件记录"""
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


def _read_log() -> list:
    if not os.path.exists(OPEN_LOG_FILE) or os.path.getsize(OPEN_LOG_FILE) == 0:
        return []
    with open(OPEN_LOG_FILE, "r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_log(rows: list):
    with open(OPEN_LOG_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS, extrasaction="ignore", restval="")
        writer.writeheader()
        writer.writerows(rows)


def save_open_csv(rows: list, now: datetime):
    """将开单观察数据追加写入 open_log.csv（平仓字段留空待填）"""
    ts       = now.strftime("%Y-%m-%d %H:%M:%S")
    existing = _read_log()
    for row in rows:
        existing.append({
            "open_time":           ts,
            "close_time":          "",
            "symbol":              row["symbol"],
            "side":                row["side"],
            "change_pct":          row["change_pct"],
            "market_cap_usd":      row["market_cap_usd"],
            "circulating_supply":  row["circulating_supply"],
            "btc_change_pct":      row.get("btc_change_pct", ""),
            "symbol_funding_rate": row.get("symbol_funding_rate", ""),
            "open_commission":     row.get("open_commission", ""),
            "entry_price":         "",
            "close_price":         "",
            "position_amt":        "",
            "unrealized_pnl":      "",
            "roe_pct":             "",
            "leverage":            "",
            "close_commission":    "",
        })
    _write_log(existing)
    log.info(f"开单观察数据已写入 {OPEN_LOG_FILE}（{len(rows)} 条）")


def print_open_summary(top_gainers: list, top_losers: list, market_data: dict = None,
                       btc_pct: float = None, funding_rates: dict = None,
                       commissions: dict = None, oi_changes: dict = None,
                       long_short_ratios: dict = None):
    """开单完成后输出标的行情观察表，并保存 CSV"""
    if market_data is None:
        symbols = [t["symbol"] for t in top_gainers + top_losers]
        log.info("正在从 CoinGecko 获取市值/流通量数据...")
        try:
            market_data = get_coin_market_data(symbols)
        except Exception as e:
            log.warning(f"CoinGecko 数据获取失败，跳过观察表：{e}")
            return

    funding_rates    = funding_rates    or {}
    commissions      = commissions      or {}
    oi_changes       = oi_changes       or {}
    long_short_ratios = long_short_ratios or {}
    btc_str = f"{btc_pct:+.2f}%" if btc_pct is not None else "N/A"

    C = {"symbol": 14, "side": 4, "pct": 10, "fr": 10, "oi": 10, "ls": 8, "comm": 10, "mcap": 13, "supply": 18}
    divider = "-" * (sum(C.values()) + len(C) * 3 + 1)
    header  = "=" * len(divider)

    print(header)
    print(f"  开单标的行情观察    BTC 24h涨跌：{btc_str}")
    print(divider)
    print(
        f"| {'交易对':<{C['symbol']}} | {'方向':<{C['side']}} "
        f"| {'24h涨跌':>{C['pct']}} | {'资金费率':>{C['fr']}} "
        f"| {'OI变化':>{C['oi']}} | {'多空比':>{C['ls']}} "
        f"| {'开仓手续费':>{C['comm']}} | {'市值(USD)':>{C['mcap']}} "
        f"| {'流通量':>{C['supply']}} |"
    )
    print(divider)

    csv_rows = []
    for label, tickers, side_str in [
        ("空单（涨幅榜）", top_gainers, "空"),
        ("多单（跌幅榜）", top_losers,  "多"),
    ]:
        print(f"  {label}")
        for t in tickers:
            sym  = t["symbol"]
            pct  = float(t["priceChangePercent"])
            md   = market_data.get(sym, {})
            mc   = md.get("market_cap", 0)
            cs   = md.get("circulating_supply", 0)
            fr   = funding_rates.get(sym)
            oi   = oi_changes.get(sym)
            ls   = long_short_ratios.get(sym)
            comm = commissions.get(sym, 0.0)
            fr_str = f"{fr*100:+.4f}%" if fr is not None else "N/A"
            oi_str = f"{oi:+.2f}%"     if oi is not None else "N/A"
            ls_str = f"{ls:.3f}"        if ls is not None else "N/A"
            comm_str = f"{comm:.4f}"
            print(
                f"| {sym:<{C['symbol']}} | {side_str:<{C['side']}} "
                f"| {pct:>+{C['pct']}.2f}% | {fr_str:>{C['fr']}} "
                f"| {oi_str:>{C['oi']}} | {ls_str:>{C['ls']}} "
                f"| {comm_str:>{C['comm']}} | {fmt_large(mc):>{C['mcap']}} "
                f"| {fmt_large(cs):>{C['supply']}} |"
            )
            csv_rows.append({
                "symbol":              sym,
                "side":                side_str,
                "change_pct":          f"{pct:.4f}",
                "market_cap_usd":      fmt_large(mc) if mc else "",
                "circulating_supply":  fmt_large(cs) if cs else "",
                "btc_change_pct":      f"{btc_pct:.4f}" if btc_pct is not None else "",
                "symbol_funding_rate": f"{fr:.6f}"      if fr is not None else "",
                "oi_change_pct":       f"{oi:.4f}"      if oi is not None else "",
                "long_short_ratio":    f"{ls:.4f}"      if ls is not None else "",
                "open_commission":     f"{comm:.6f}",
            })
        print(divider)

    print(header)
    save_open_csv(csv_rows, datetime.now())


def run_open():
    log.info("=" * 50)
    log.info(f"【开单开始】杠杆 {LEVERAGE}x  保证金 {MARGIN_PER_POS} USDT  名义 {MARGIN_PER_POS * LEVERAGE} USDT")

    valid_symbols, symbol_info = get_exchange_info()
    tickers = get_ticker_24h(valid_symbols, MIN_VOLUME)
    tickers.sort(key=lambda x: float(x["priceChangePercent"]), reverse=True)
    hedge = is_hedge_mode()

    # 取 2 倍候选池，提前拉市值用于过滤无市值币
    n = TOP_N * CANDIDATE_BUFFER
    gainer_pool = tickers[:n]
    loser_pool  = tickers[-n:][::-1]

    log.info("正在从 CoinGecko 获取市值/流通量数据（过滤无市值币）...")
    try:
        market_data = get_coin_market_data([t["symbol"] for t in gainer_pool + loser_pool])
    except Exception as e:
        log.warning(f"CoinGecko 数据获取失败，不过滤市值：{e}")
        market_data = {}

    if market_data:
        def has_mcap(t):
            return bool(market_data.get(t["symbol"], {}).get("market_cap"))

        top_gainers = [t for t in gainer_pool if has_mcap(t)][:TOP_N]
        top_losers  = [t for t in loser_pool  if has_mcap(t)][:TOP_N]

        skipped = [t["symbol"] for t in gainer_pool + loser_pool if not has_mcap(t)]
        if skipped:
            detail = f"跳过无市值币 {len(skipped)} 个: {skipped}"
            log.info(detail)
            log_event("FILTER_NO_MCAP", detail)
    else:
        top_gainers = gainer_pool[:TOP_N]
        top_losers  = loser_pool[:TOP_N]

    log.info(f"持仓模式：{'双向（对冲）' if hedge else '单向'}")

    open_start_ms = int(time.time() * 1000)
    run_batch_orders("空单（涨幅榜）", top_gainers, "SELL", symbol_info, hedge)
    run_batch_orders("多单（跌幅榜）", top_losers,  "BUY",  symbol_info, hedge)
    open_end_ms = int(time.time() * 1000)

    # 开单完成后采集辅助指标
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

    all_symbols = [t["symbol"] for t in top_gainers + top_losers]

    log.info("正在获取持仓量变化（OI）...")
    try:
        oi_changes = get_oi_changes(all_symbols)
    except Exception as e:
        log.warning(f"获取OI变化失败：{e}")
        oi_changes = {}

    log.info("正在获取多空持仓比...")
    try:
        long_short_ratios = get_long_short_ratios(all_symbols)
    except Exception as e:
        log.warning(f"获取多空比失败：{e}")
        long_short_ratios = {}

    try:
        commissions = get_commissions_by_symbol(open_start_ms, open_end_ms)
        total_comm  = sum(commissions.values())
        log.info(f"本批开仓手续费合计：{total_comm:.4f} USDT（{len(commissions)} 个币种）")
    except Exception as e:
        log.warning(f"获取开仓手续费失败：{e}")
        commissions = {}

    print_open_summary(top_gainers, top_losers, market_data, btc_pct,
                       funding_rates, commissions, oi_changes, long_short_ratios)
    log.info("【开单全部完成】")


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
    log.info("策略定时器启动")
    log.info(f"  每天 {CLOSE_HOUR:02d}:{CLOSE_MINUTE:02d} 平仓")
    log.info(f"  每天 {OPEN_HOUR:02d}:{OPEN_MINUTE:02d} 开单（涨幅榜空单 + 跌幅榜多单）")

    while True:
        wait_until(CLOSE_HOUR, CLOSE_MINUTE)
        try:
            run_close()
        except Exception as e:
            log.error(f"平仓出错：{e}", exc_info=True)

        wait_until(OPEN_HOUR, OPEN_MINUTE)
        try:
            run_open()
        except Exception as e:
            log.error(f"开单出错：{e}", exc_info=True)


if __name__ == "__main__":
    main()
