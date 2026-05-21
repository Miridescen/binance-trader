#!/usr/bin/env python3
"""
一次性手工平掉所有实盘持仓。
用法:
    python3 scripts/close_all_positions.py             # 默认 dry-run，仅打印计划
    python3 scripts/close_all_positions.py --execute   # 真平仓
    python3 scripts/close_all_positions.py --reason 手工平仓 --execute

流程：
  1. 拉 /fapi/v2/positionRisk 所有 positionAmt != 0 的仓位
  2. 对每个调用 binance 市价平仓接口
  3. 等待成交 (sleep 2s)
  4. 取 mark_price 重算 pnl/roe，FIFO 回填 open_log
  5. 找不到 entry_price 不为 NULL 的 FIFO 记录时，仅标 close_time + reason，避免脱节
"""
from __future__ import annotations
import os
import sys
import time
import argparse
from datetime import datetime

# 兼容直接运行（scripts/ 是子目录）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from binance_client import auth_get, auth_post, get_mark_price, is_hedge_mode
import db

LEVERAGE_FALLBACK = 3


def market_close_one(symbol: str, amt: float, hedge: bool) -> bool:
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
        print(f"  ❌ 下单异常 {symbol}: {e}")
        return False
    if "orderId" not in result:
        print(f"  ❌ 下单失败 {symbol}: {result.get('msg', result)}")
        return False
    print(f"  ✅ 市价平仓 {symbol} 数量 {abs(amt)}")
    return True


def writeback(symbol: str, amt: float, close_reason: str):
    """平仓后回填 open_log（FIFO 取最早未平仓记录）"""
    row = db.get_oldest_open_position(symbol)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not row:
        print(f"     ⚠️  {symbol} 未在 open_log 找到匹配未平仓记录（可能 entry_price=NULL）")
        # 兜底：把所有未平仓的同 symbol 记录标 close_time + reason
        with db.get_conn() as conn:
            n = conn.execute("""
                UPDATE open_log SET close_time = ?, close_reason = ?
                WHERE symbol = ? AND (close_time IS NULL OR close_time = '')
            """, (ts, close_reason, symbol)).rowcount
        print(f"     兜底回填 {n} 条 close_time + reason (无 entry 无法算 pnl)")
        return

    try:
        mark = get_mark_price(symbol)
    except Exception as e:
        print(f"     ⚠️  {symbol} 取 mark 失败，仅写 close_time: {e}")
        db.update_close_data(symbol, "", {"close_time": ts, "close_reason": close_reason})
        return

    entry = row["entry_price"]
    amt_db = row["position_amt"] or abs(amt)
    lev = row["leverage"] or LEVERAGE_FALLBACK
    margin = entry * amt_db / lev if lev and entry else 0
    is_short = "空" in (row["side"] or "")
    pnl = (entry - mark) * amt_db if is_short else (mark - entry) * amt_db
    roe = pnl / margin * 100 if margin else 0

    db.update_close_data(symbol, "", {
        "close_time":     ts,
        "close_price":    mark,
        "unrealized_pnl": round(pnl, 4),
        "roe_pct":        round(roe, 2),
        "close_reason":   close_reason,
    })
    print(f"     回填 close={mark:.6f} pnl={pnl:+.4f} roe={roe:+.1f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="真平仓（默认 dry-run）")
    ap.add_argument("--reason", default="手工平仓", help="close_reason 标记")
    args = ap.parse_args()

    positions = auth_get("/fapi/v2/positionRisk")
    actives = [p for p in positions if float(p["positionAmt"]) != 0]

    if not actives:
        print("当前账户无持仓，无需平仓。")
        return

    total_pnl = sum(float(p["unRealizedProfit"]) for p in actives)
    print(f"待平 {len(actives)} 个仓位，当前浮盈合计 {total_pnl:+.2f} USDT")
    print(f"{'symbol':<18} {'amt':>10} {'entry':>14} {'mark':>14} {'pnl':>10}")
    for p in actives:
        amt = float(p["positionAmt"])
        pnl = float(p["unRealizedProfit"])
        print(f"  {p['symbol']:<18} {amt:>10}  {p['entryPrice']:>12}  {p['markPrice']:>12}  {pnl:>+8.2f}")

    if not args.execute:
        print("\n[DRY-RUN] 加 --execute 参数才会真平仓。")
        return

    print(f"\n执行平仓 (close_reason={args.reason}) ...")
    try:
        hedge = is_hedge_mode()
    except Exception as e:
        print(f"查 hedge_mode 失败，按 false 处理: {e}")
        hedge = False

    ok = fail = 0
    for p in actives:
        symbol = p["symbol"]
        amt = float(p["positionAmt"])
        print(f"\n[{ok+fail+1}/{len(actives)}] {symbol} amt={amt}")
        if market_close_one(symbol, amt, hedge):
            time.sleep(2)
            try:
                writeback(symbol, amt, args.reason)
                ok += 1
            except Exception as e:
                print(f"     ❌ 回写异常: {e}")
                fail += 1
        else:
            fail += 1

    print(f"\n=== 完成 ===\n  成功 {ok} / 失败 {fail}")


if __name__ == "__main__":
    main()
