"""
基差监控主程序（Phase 1：数据采集）

每 15 分钟拉一次：
  - BTCUSDT / ETHUSDT 现货价
  - BTCUSDT_当季 / BTCUSDT_次季 合约价（U本位）
  - ETHUSDT_当季 / ETHUSDT_次季 合约价

写入 basis.db 的 basis_snapshot 表（永久保留）。

完全独立于主项目（trader.db / open_top_shorts / real_trade_4h 等），
唯一共享：服务器 Python 环境 + git 仓库 + systemd。

不需要 API key（全部用公开行情接口）。
"""
from __future__ import annotations

import os
import sys
import time
import logging
from datetime import datetime, timezone

import requests

# 兼容同目录或外部启动
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # basis/db.py

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("basis-monitor")


# ── 配置 ──
PAIRS = ["BTCUSDT", "ETHUSDT"]
INTERVAL_SEC = 15 * 60   # 15 分钟

FAPI_BASE = "https://fapi.binance.com"
SPOT_BASE = "https://api.binance.com"
HTTP_TIMEOUT = 10

# ── 告警配置 ──
ALERT_THRESHOLD = 8.0          # 年化基差 ≥ 8% 触发告警
ALERT_COOLDOWN_SEC = 6 * 3600  # 同一合约两次告警间隔 ≥ 6 小时（防刷屏）

# 复用主项目 Server酱推送（仅 import 一个纯函数，不引入其他依赖）
try:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from notify import send_wechat
    _NOTIFY_OK = True
except Exception as _e:
    _NOTIFY_OK = False
    def send_wechat(title, content):  # noqa: 占位
        log.warning(f"notify 不可用，跳过推送：{title}")

# 记录每个合约最近一次告警时间（epoch 秒）；进程内存，重启清零
_last_alert: dict[str, float] = {}


def _http_get(url, params=None):
    resp = requests.get(url, params=params or {}, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def get_quarterly_contracts() -> list[dict]:
    """拉当前 U本位的所有 CURRENT_QUARTER + NEXT_QUARTER，过滤目标 pair"""
    data = _http_get(f"{FAPI_BASE}/fapi/v1/exchangeInfo")
    out = []
    for s in data.get("symbols", []):
        if (s.get("status") == "TRADING"
            and s.get("contractType") in ("CURRENT_QUARTER", "NEXT_QUARTER")
            and s.get("pair") in PAIRS):
            out.append({
                "symbol":        s["symbol"],
                "pair":          s["pair"],
                "contract_type": s["contractType"],
                "delivery_ms":   int(s.get("deliveryDate", 0)),
            })
    return out


def get_spot_ticker(pair: str) -> tuple[float, float]:
    """返回 (lastPrice, quoteVolume_24h)"""
    data = _http_get(f"{SPOT_BASE}/api/v3/ticker/24hr", {"symbol": pair})
    return float(data["lastPrice"]), float(data["quoteVolume"])


def get_futures_ticker(symbol: str) -> tuple[float, float]:
    """返回 (lastPrice, quoteVolume_24h)"""
    data = _http_get(f"{FAPI_BASE}/fapi/v1/ticker/24hr", {"symbol": symbol})
    return float(data["lastPrice"]), float(data["quoteVolume"])


def take_snapshot():
    now = datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    log.info("─" * 60)

    try:
        contracts = get_quarterly_contracts()
    except Exception as e:
        log.error(f"拉合约列表失败：{e}")
        return
    log.info(f"目标合约 {len(contracts)} 个")

    # 拉每个 pair 的现货
    spot_cache: dict[str, tuple[float, float]] = {}
    for pair in PAIRS:
        try:
            spot_cache[pair] = get_spot_ticker(pair)
        except Exception as e:
            log.warning(f"  现货 {pair} 失败：{e}")

    rows = []
    for c in contracts:
        if c["pair"] not in spot_cache:
            continue
        try:
            f_price, f_vol = get_futures_ticker(c["symbol"])
        except Exception as e:
            log.warning(f"  合约 {c['symbol']} 失败：{e}")
            continue
        s_price, s_vol = spot_cache[c["pair"]]
        basis = f_price - s_price
        basis_pct = basis / s_price * 100 if s_price else 0
        expiry_dt = datetime.fromtimestamp(c["delivery_ms"] / 1000, tz=timezone.utc)
        days = (expiry_dt - datetime.now(tz=timezone.utc)).total_seconds() / 86400
        annualized = basis_pct * 365 / days if days > 0 else 0

        rows.append({
            "time":            ts,
            "pair":            c["pair"],
            "contract_type":   c["contract_type"],
            "contract_symbol": c["symbol"],
            "expiry_date":     expiry_dt.strftime("%Y-%m-%d"),
            "days_to_expiry":  round(days, 3),
            "spot_price":      s_price,
            "futures_price":   f_price,
            "basis":           round(basis, 4),
            "basis_pct":       round(basis_pct, 4),
            "annualized_pct":  round(annualized, 3),
            "spot_vol_24h":    round(s_vol, 2),
            "fut_vol_24h":     round(f_vol, 2),
        })
        log.info(
            f"  {c['symbol']:<22} 现 {s_price:>10.2f}  合 {f_price:>10.2f}  "
            f"基 {basis:>+9.2f} ({basis_pct:>+6.3f}%)  年化 {annualized:>+6.2f}%  "
            f"剩 {days:>5.1f}d"
        )

    if rows:
        db.insert_snapshots(rows)
    log.info(f"快照 {len(rows)} 条 已写入 {db.DB_PATH}")

    # 告警检查
    check_alerts(rows)


def check_alerts(rows: list[dict]):
    """年化基差 ≥ ALERT_THRESHOLD 时推送（带冷却，避免刷屏）"""
    hits = [r for r in rows if abs(r["annualized_pct"]) >= ALERT_THRESHOLD]
    if not hits:
        return

    now_epoch = time.time()
    to_alert = []
    for r in hits:
        sym = r["contract_symbol"]
        last = _last_alert.get(sym, 0)
        if now_epoch - last >= ALERT_COOLDOWN_SEC:
            to_alert.append(r)
            _last_alert[sym] = now_epoch
        else:
            mins = int((ALERT_COOLDOWN_SEC - (now_epoch - last)) / 60)
            log.info(f"  {sym} 年化 {r['annualized_pct']:+.2f}% 达阈值但在冷却中（剩 {mins} 分钟）")

    if not to_alert:
        return

    sign = lambda v: f"{v:+.2f}"
    title = f"⚡基差套利机会 {to_alert[0]['pair']} 年化{to_alert[0]['annualized_pct']:+.1f}%"
    lines = [f"## 基差年化 ≥ {ALERT_THRESHOLD}% 告警\n"]
    lines.append("| 合约 | 现货 | 合约 | 基差% | 年化 | 剩余 |")
    lines.append("|------|------|------|-------|------|------|")
    for r in to_alert:
        lines.append(
            f"| {r['contract_symbol']} | {r['spot_price']:.2f} | {r['futures_price']:.2f} "
            f"| {sign(r['basis_pct'])}% | **{sign(r['annualized_pct'])}%** | {r['days_to_expiry']:.0f}d |"
        )
    lines.append(f"\n采集时间：{rows[0]['time']}")
    lines.append(f"\n> 现货买入 + 季度合约做空，锁定年化收益。建议核对盘口流动性后下单。")
    try:
        send_wechat(title, "\n".join(lines))
        log.info(f"  ⚡ 已推送告警：{len(to_alert)} 个合约达阈值")
    except Exception as e:
        log.warning(f"  推送告警失败：{e}")


def main():
    db.init_db()
    log.info("=" * 60)
    log.info("基差监控启动 (Phase 1 数据采集)")
    log.info(f"  采集频率：{INTERVAL_SEC}s ({INTERVAL_SEC // 60} 分钟)")
    log.info(f"  目标币种：{PAIRS}")
    log.info(f"  数据库：  {db.DB_PATH}")
    log.info(f"  告警阈值：年化 ≥ {ALERT_THRESHOLD}%  冷却 {ALERT_COOLDOWN_SEC // 3600}h"
             f"  推送={'可用' if _NOTIFY_OK else '不可用'}")
    log.info("=" * 60)

    # 立即来一次
    try:
        take_snapshot()
    except Exception as e:
        log.error(f"首次快照失败：{e}", exc_info=True)

    while True:
        time.sleep(INTERVAL_SEC)
        try:
            take_snapshot()
        except Exception as e:
            log.error(f"快照异常：{e}", exc_info=True)


if __name__ == "__main__":
    main()
