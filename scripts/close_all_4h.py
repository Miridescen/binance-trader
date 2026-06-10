#!/usr/bin/env python3
"""
一次性市价平掉所有实盘持仓，并回写到 open_log_4h（4h 实盘策略表）。

与 close_all_positions.py 的区别：
  - 那个回写老的 open_log（24h 策略，已停用）
  - 这个回写 open_log_4h，并复用 real_trade_4h.writeback_closes() 拉真实成交/手续费/资金费

用法:
    python3 scripts/close_all_4h.py            # dry-run，仅列出持仓
    python3 scripts/close_all_4h.py --execute  # 真平仓 + 回写

建议执行前先停掉 binance-real-4h 服务，避免脚本与服务同时操作账户。
"""
from __future__ import annotations
import os
import sys
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from binance_client import auth_get, auth_post, is_hedge_mode
import db
import real_trade_4h as rt


def market_close(symbol: str, amt: float, hedge: bool) -> bool:
    """市价平掉单个持仓（空头 BUY，多头 SELL，reduceOnly）"""
    side = "BUY" if amt < 0 else "SELL"
    params = {"symbol": symbol, "side": side, "type": "MARKET",
              "quantity": abs(amt), "reduceOnly": "true"}
    if hedge:
        params.pop("reduceOnly")
        params["positionSide"] = "SHORT" if amt < 0 else "LONG"
    try:
        res = auth_post("/fapi/v1/order", params)
    except Exception as e:
        print(f"  ❌ {symbol} 下单异常: {e}")
        return False
    if "orderId" in res:
        print(f"  ✅ {symbol} 市价平 {abs(amt)}")
        return True
    print(f"  ❌ {symbol} 失败: {res.get('msg', res)}")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="真平仓（默认 dry-run）")
    args = ap.parse_args()

    positions = auth_get("/fapi/v2/positionRisk")
    actives = [p for p in positions if float(p["positionAmt"]) != 0]

    if not actives:
        print("当前账户无持仓。")
        # 仍然跑一次回写，把可能漏回写的 open_log_4h 补上
        if args.execute:
            print("跑 writeback_closes 补回填未平仓记录...")
            rt.writeback_closes()
        return

    total = sum(float(p["unRealizedProfit"]) for p in actives)
    print(f"待平 {len(actives)} 个持仓，浮盈合计 {total:+.2f} USDT")
    for p in actives:
        amt = float(p["positionAmt"])
        print(f"  {p['symbol']:<16} amt={amt:>12}  pnl={float(p['unRealizedProfit']):>+7.2f}")

    if not args.execute:
        print("\n[DRY-RUN] 加 --execute 才会真平仓。")
        return

    try:
        hedge = is_hedge_mode()
    except Exception:
        hedge = False

    print(f"\n执行市价平仓（hedge={hedge}）...")
    ok = fail = 0
    for p in actives:
        if market_close(p["symbol"], float(p["positionAmt"]), hedge):
            ok += 1
        else:
            fail += 1
        time.sleep(0.2)

    print(f"\n平仓完成：成功 {ok} / 失败 {fail}")
    print("等 12 秒后回写 open_log_4h（拉真实成交 + 手续费 + 资金费）...")
    time.sleep(12)
    rt.writeback_closes()
    print("✅ 全部完成")


if __name__ == "__main__":
    main()
