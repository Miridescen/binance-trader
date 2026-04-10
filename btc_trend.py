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
    get_klines, get_mark_price, calc_sma, calc_rsi,
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
    # 日线 K 线 → 200 日均线
    daily_klines = get_klines(SYMBOL, "1d", 210)
    daily_closes = [k["close"] for k in daily_klines]
    sma200 = calc_sma(daily_closes, 200)
    price = daily_closes[-1] if daily_closes else get_mark_price(SYMBOL)

    # 周线 K 线 → RSI(14)
    weekly_klines = get_klines(SYMBOL, "1w", 20)
    weekly_closes = [k["close"] for k in weekly_klines]
    rsi_weekly = calc_rsi(weekly_closes, 14)

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
        "rsi_weekly": rsi_weekly,
        "funding_rate": funding,
        "fear_greed": fng["value"],
        "fear_greed_label": fng["label"],
    }


def judge_signal(indicators: dict) -> str:
    """
    根据指标判断信号：多 / 空 / 观望
    规则：
      - 价格 > 200日均线 且 周线RSI > 50 → 多
      - 价格 < 200日均线 且 周线RSI < 50 → 空
      - 其他 → 观望（不开仓）
    """
    price = indicators["price"]
    sma200 = indicators["sma200"]
    rsi = indicators["rsi_weekly"]

    if sma200 is None or rsi is None:
        return "观望"

    if price > sma200 and rsi > 50:
        return "多"
    elif price < sma200 and rsi < 50:
        return "空"
    else:
        return "观望"


def handle_signal(signal: str, price: float):
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
            "signal_reason": f"SMA200={'上方' if signal == '多' else '下方'} + RSI{'偏多' if signal == '多' else '偏空'}",
            "unrealized_pnl": None,
            "roe_pct": None,
        })
        log.info(f"【BTC 开仓】{signal}  价格 {price:.2f}")


def run_check():
    """单次检查"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log.info(f"── BTC 趋势信号检查 ──")

    indicators = collect_indicators()
    signal = judge_signal(indicators)

    # 记录指标
    db.insert_btc_indicator({
        "time": now_str,
        **indicators,
        "signal": signal,
    })

    price = indicators["price"]
    sma200 = indicators["sma200"]
    rsi = indicators["rsi_weekly"]
    fng = indicators["fear_greed"]
    fr = indicators["funding_rate"]

    sma_str = f"{sma200:.2f}" if sma200 else "N/A"
    rsi_str = f"{rsi:.1f}" if rsi else "N/A"
    fr_str = f"{fr*100:.4f}%" if fr else "N/A"

    log.info(f"  价格 {price:.2f}  SMA200 {sma_str}  RSI周 {rsi_str}")
    log.info(f"  资金费率 {fr_str}  恐惧贪婪 {fng}")
    log.info(f"  信号：{signal}")

    # 处理开平仓
    mark = get_mark_price(SYMBOL)
    handle_signal(signal, mark)

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
