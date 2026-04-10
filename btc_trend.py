"""
BTC 长期趋势信号虚拟盘：
  每小时检查一次指标，产生多/空/观望信号
  信号反转时模拟平仓+反向开仓

指标：
  1. 200 日均线（日线收盘价）：价格在上方=多头，下方=空头
  2. 周线 RSI(14)：>50 偏多，<50 偏空
  3. 资金费率：辅助参考
  4. 恐惧贪婪指数：辅助参考
"""

import time
import logging
from datetime import datetime
from binance_client import (
    get_klines, get_mark_price, calc_sma, calc_ema, calc_rsi, calc_macd,
    get_fear_greed_index, get_funding_rate,
)
import db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

SYMBOL = "BTCUSDT"
MARGIN = 100        # 虚拟保证金 100 USDT
LEVERAGE = 3        # 虚拟杠杆 3x
CHECK_INTERVAL = 3600  # 每小时检查一次


def collect_indicators() -> dict:
    """采集所有指标，返回指标字典"""
    # 日线 K 线 → SMA200 / EMA50 / EMA200
    daily_klines = get_klines(SYMBOL, "1d", 210)
    daily_closes = [k["close"] for k in daily_klines]
    sma200 = calc_sma(daily_closes, 200)
    ema50  = calc_ema(daily_closes, 50)
    ema200 = calc_ema(daily_closes, 200)
    price  = daily_closes[-1] if daily_closes else get_mark_price(SYMBOL)

    # 周线 K 线 → RSI(14) / MACD
    weekly_klines = get_klines(SYMBOL, "1w", 40)
    weekly_closes = [k["close"] for k in weekly_klines]
    rsi_weekly = calc_rsi(weekly_closes, 14)
    macd_data  = calc_macd(weekly_closes)

    # 资金费率
    try:
        funding = get_funding_rate(SYMBOL)
    except Exception as e:
        log.warning(f"获取资金费率失败：{e}")
        funding = None

    # 恐惧贪婪指数
    try:
        fng = get_fear_greed_index()
    except Exception as e:
        log.warning(f"获取恐惧贪婪指数失败：{e}")
        fng = {"value": None, "label": "N/A"}

    return {
        "price": price,
        "sma200": sma200,
        "ema50": ema50,
        "ema200": ema200,
        "rsi_weekly": rsi_weekly,
        "macd": macd_data["macd"],
        "macd_signal": macd_data["signal"],
        "macd_histogram": macd_data["histogram"],
        "funding_rate": funding,
        "fear_greed": fng["value"],
        "fear_greed_label": fng["label"],
    }


def judge_signal(indicators: dict) -> tuple:
    """
    根据指标判断信号：多 / 空 / 观望
    采用投票机制，3 个维度各投一票：

    1. 趋势（SMA200）：价格 > SMA200 → 多票，< SMA200 → 空票
    2. 动量（周线RSI）：RSI > 50 → 多票，< 50 → 空票
    3. EMA交叉 + MACD 共同确认：
       EMA50 > EMA200 且 MACD柱 > 0 → 多票
       EMA50 < EMA200 且 MACD柱 < 0 → 空票

    3票同方向 → 强信号开仓
    2票同方向 → 弱信号开仓
    其他 → 观望

    返回: (signal, reason)
    """
    price  = indicators["price"]
    sma200 = indicators["sma200"]
    ema50  = indicators["ema50"]
    ema200 = indicators["ema200"]
    rsi    = indicators["rsi_weekly"]
    macd_h = indicators["macd_histogram"]

    # 指标不足时观望
    if sma200 is None or rsi is None:
        return "观望", "指标数据不足"

    # 投票
    votes = {"多": 0, "空": 0}
    reasons = []

    # 1. SMA200 趋势
    if price > sma200:
        votes["多"] += 1
        reasons.append("价格>SMA200")
    else:
        votes["空"] += 1
        reasons.append("价格<SMA200")

    # 2. 周线 RSI
    if rsi > 50:
        votes["多"] += 1
        reasons.append(f"RSI{rsi:.0f}>50")
    else:
        votes["空"] += 1
        reasons.append(f"RSI{rsi:.0f}<50")

    # 3. EMA交叉 + MACD 共同确认
    if ema50 is not None and ema200 is not None and macd_h is not None:
        if ema50 > ema200 and macd_h > 0:
            votes["多"] += 1
            reasons.append("EMA金叉+MACD多")
        elif ema50 < ema200 and macd_h < 0:
            votes["空"] += 1
            reasons.append("EMA死叉+MACD空")
        else:
            reasons.append("EMA/MACD矛盾")

    # 判定
    if votes["多"] >= 2:
        return "多", " + ".join(reasons)
    elif votes["空"] >= 2:
        return "空", " + ".join(reasons)
    else:
        return "观望", " + ".join(reasons)


def handle_signal(signal: str, reason: str, price: float):
    """根据信号处理虚拟开平仓"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    current = db.get_btc_signal_unclosed()

    # 当前有持仓
    if current:
        current_side = current["side"]

        # 信号与当前持仓一致，继续持有
        if signal == current_side:
            return

        # 信号反转或变为观望 → 平仓
        entry = current["entry_price"]
        notional = MARGIN * LEVERAGE
        if current_side == "多":
            pnl = (price - entry) / entry * notional
        else:
            pnl = (entry - price) / entry * notional
        roe = pnl / MARGIN * 100

        db.update_btc_signal_close(current["id"], {
            "close_time": now_str,
            "close_price": price,
            "unrealized_pnl": round(pnl, 4),
            "roe_pct": round(roe, 2),
        })
        log.info(f"【BTC 平仓】{current_side}  入场 {entry:.2f}  出场 {price:.2f}  PnL {pnl:+.2f}  ROE {roe:+.1f}%")

    # 新信号不是观望 → 开仓
    if signal in ("多", "空"):
        # 避免刚平仓的同方向重复开仓
        if current and signal == current["side"]:
            return
        db.insert_btc_signal({
            "open_time": now_str,
            "close_time": None,
            "side": signal,
            "entry_price": price,
            "close_price": None,
            "signal_reason": reason,
            "unrealized_pnl": None,
            "roe_pct": None,
        })
        log.info(f"【BTC 开仓】{signal}  价格 {price:.2f}")


def run_check():
    """单次检查"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log.info(f"── BTC 趋势信号检查 ──")

    indicators = collect_indicators()
    signal, reason = judge_signal(indicators)

    # 记录指标
    db.insert_btc_indicator({
        "time": now_str,
        **indicators,
        "signal": signal,
    })

    price  = indicators["price"]
    sma200 = indicators["sma200"]
    ema50  = indicators["ema50"]
    ema200 = indicators["ema200"]
    rsi    = indicators["rsi_weekly"]
    macd_h = indicators["macd_histogram"]
    fng    = indicators["fear_greed"]
    fr     = indicators["funding_rate"]

    sma_str  = f"{sma200:.2f}" if sma200 else "N/A"
    ema_str  = f"EMA50 {ema50:.2f} / EMA200 {ema200:.2f}" if ema50 and ema200 else "N/A"
    rsi_str  = f"{rsi:.1f}" if rsi else "N/A"
    macd_str = f"{macd_h:+.2f}" if macd_h is not None else "N/A"
    fr_str   = f"{fr*100:.4f}%" if fr else "N/A"

    log.info(f"  价格 {price:.2f}  SMA200 {sma_str}  {ema_str}")
    log.info(f"  RSI周 {rsi_str}  MACD柱 {macd_str}  资金费率 {fr_str}  恐惧贪婪 {fng}")
    log.info(f"  信号：{signal}（{reason}）")

    # 处理开平仓
    mark = get_mark_price(SYMBOL)
    handle_signal(signal, reason, mark)

    # 更新未平仓的浮盈
    current = db.get_btc_signal_unclosed()
    if current:
        entry = current["entry_price"]
        notional = MARGIN * LEVERAGE
        if current["side"] == "多":
            pnl = (mark - entry) / entry * notional
        else:
            pnl = (entry - mark) / entry * notional
        roe = pnl / MARGIN * 100
        log.info(f"  持仓中：{current['side']}  入场 {entry:.2f}  当前 {mark:.2f}  浮盈 {pnl:+.2f}  ROE {roe:+.1f}%")


def main():
    log.info("BTC 趋势信号虚拟盘启动")
    log.info(f"  标的：{SYMBOL}  虚拟保证金 {MARGIN}U  杠杆 {LEVERAGE}x")
    log.info(f"  检查间隔：{CHECK_INTERVAL}s（每小时）")
    log.info(f"  信号：SMA200 + 周线RSI(14)")

    # 启动时立即检查一次
    try:
        run_check()
    except Exception as e:
        log.error(f"首次检查失败：{e}", exc_info=True)

    while True:
        time.sleep(CHECK_INTERVAL)
        try:
            run_check()
        except Exception as e:
            log.error(f"检查失败：{e}", exc_info=True)


if __name__ == "__main__":
    main()
