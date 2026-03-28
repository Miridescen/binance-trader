"""
微信推送模块（Server酱）
"""

import logging
import requests

log = logging.getLogger(__name__)

SERVERCHAN_KEY = "SCT330341TrJCjA1rGzfv9WrR21CMZY3AF"


def send_wechat(title: str, content: str):
    """通过 Server酱 推送消息到微信"""
    if not SERVERCHAN_KEY:
        log.warning("Server酱 Key 未配置，跳过推送")
        return

    try:
        resp = requests.post(
            f"https://sctapi.ftqq.com/{SERVERCHAN_KEY}.send",
            data={"title": title, "desp": content},
            timeout=10,
        )
        result = resp.json()
        if result.get("code") == 0:
            log.info(f"微信推送成功: {title}")
        else:
            log.warning(f"微信推送失败: {result}")
    except Exception as e:
        log.warning(f"微信推送异常: {e}")


def build_daily_report(positions: list, balance: float) -> tuple:
    """生成每日平仓报告，返回 (title, markdown_content)"""
    from datetime import datetime

    longs  = [p for p in positions if float(p["positionAmt"]) > 0]
    shorts = [p for p in positions if float(p["positionAmt"]) < 0]

    def calc(ps):
        details = []
        for p in sorted(ps, key=lambda x: float(x["unRealizedProfit"]), reverse=True):
            amt    = float(p["positionAmt"])
            entry  = float(p["entryPrice"])
            mark   = float(p["markPrice"])
            pnl    = float(p["unRealizedProfit"])
            lev    = int(p["leverage"])
            margin = entry * abs(amt) / lev if lev and entry else 0
            roe    = pnl / margin * 100 if margin else 0
            details.append({"symbol": p["symbol"], "pnl": pnl, "roe": roe})
        total = sum(d["pnl"] for d in details)
        wins  = sum(1 for d in details if d["pnl"] > 0)
        return total, wins, details

    long_total,  long_wins,  long_details  = calc(longs)
    short_total, short_wins, short_details = calc(shorts)
    grand_total = long_total + short_total
    total_count = len(longs) + len(shorts)
    total_wins  = long_wins + short_wins

    now = datetime.now()
    sign = "+" if grand_total >= 0 else ""
    title = f"日报 {now.strftime('%m/%d')} {sign}{grand_total:.2f}U"

    lines = []
    lines.append(f"## {now.strftime('%Y-%m-%d')} 平仓报告\n")
    lines.append(f"**账户余额**: {balance:.2f} USDT\n")
    lines.append(f"**本批盈亏**: {grand_total:+.2f} USDT\n")
    lines.append(f"**胜率**: {total_wins}/{total_count}\n")

    if shorts:
        lines.append(f"\n### 空单 ({len(shorts)}笔) {short_total:+.2f} U  胜率 {short_wins}/{len(shorts)}\n")
        lines.append("| 币种 | 盈亏 | ROE |")
        lines.append("|------|------|-----|")
        for d in short_details:
            emoji = "🟢" if d["pnl"] > 0 else "🔴"
            lines.append(f"| {d['symbol']} | {d['pnl']:+.2f} | {d['roe']:+.1f}% {emoji} |")

    if longs:
        lines.append(f"\n### 多单 ({len(longs)}笔) {long_total:+.2f} U  胜率 {long_wins}/{len(longs)}\n")
        lines.append("| 币种 | 盈亏 | ROE |")
        lines.append("|------|------|-----|")
        for d in long_details:
            emoji = "🟢" if d["pnl"] > 0 else "🔴"
            lines.append(f"| {d['symbol']} | {d['pnl']:+.2f} | {d['roe']:+.1f}% {emoji} |")

    return title, "\n".join(lines)


def send_daily_report(positions: list, balance: float):
    """生成日报并推送"""
    if not positions:
        return
    title, content = build_daily_report(positions, balance)
    send_wechat(title, content)


def send_tp_sl_alert(symbol: str, side: str, reason: str, roe: float, pnl: float, entry: float, mark: float):
    """止盈/止损即时通知"""
    emoji = "🟢 止盈" if reason == "止盈" else "🔴 止损"
    title = f"{emoji} {symbol} {side} ROE{roe:+.1f}%"
    content = f"""## {reason}通知

| 项目 | 值 |
|------|-----|
| 币种 | {symbol} |
| 方向 | {side} |
| ROE | {roe:+.1f}% |
| 盈亏 | {pnl:+.2f} USDT |
| 入场价 | {entry:.6f} |
| 平仓价 | {mark:.6f} |
"""
    send_wechat(title, content)
