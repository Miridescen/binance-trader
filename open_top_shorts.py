"""
每天定时策略：
  08:50 → 撤销所有未成交限价单 + 市价平掉所有持仓
  09:00 → 涨幅榜 TOP10 开 3 倍限价空单，每单保证金 10 USDT
         跌幅榜 TOP10 开 3 倍限价多单，每单保证金 10 USDT
  未成交则每 60 秒换价重下，最多 10 次，超过后改市价单
"""

import math
import time
import logging
from datetime import datetime, timedelta
from binance_client import (
    auth_get, auth_post, auth_delete,
    get_exchange_info, get_ticker_24h, get_mark_price, is_hedge_mode,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

LEVERAGE             = 3
MARGIN_PER_POS       = 10
TOP_N                = 10
MIN_VOLUME           = 10_000_000
ORDER_CHECK_INTERVAL = 60
MAX_RETRIES          = 10
CLOSE_HOUR, CLOSE_MINUTE = 8, 50
OPEN_HOUR,  OPEN_MINUTE  = 9, 0


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

def run_close():
    log.info("=" * 50)
    log.info("【平仓开始】")
    hedge = is_hedge_mode()
    log.info("撤销所有挂单...")
    cancel_all_open_orders()
    log.info("市价平仓...")
    close_all_positions(hedge)
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


def run_open():
    log.info("=" * 50)
    log.info(f"【开单开始】杠杆 {LEVERAGE}x  保证金 {MARGIN_PER_POS} USDT  名义 {MARGIN_PER_POS * LEVERAGE} USDT")

    valid_symbols, symbol_info = get_exchange_info()   # 只请求一次
    tickers = get_ticker_24h(valid_symbols, MIN_VOLUME)
    tickers.sort(key=lambda x: float(x["priceChangePercent"]), reverse=True)
    top_gainers = tickers[:TOP_N]
    top_losers  = tickers[-TOP_N:][::-1]
    hedge       = is_hedge_mode()

    log.info(f"持仓模式：{'双向（对冲）' if hedge else '单向'}")

    run_batch_orders("空单（涨幅榜）", top_gainers, "SELL", symbol_info, hedge)
    run_batch_orders("多单（跌幅榜）", top_losers,  "BUY",  symbol_info, hedge)

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
