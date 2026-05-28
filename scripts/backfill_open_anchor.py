#!/usr/bin/env python3
"""
回填 open_log_4h.open_anchor 字段：从 open_time 反推该笔属于哪个周期 :30 整点。

逻辑：每天 OPEN_HOURS=(0,4,8,12,16,20) 整点的 :30 是周期 anchor。
对一笔记录的 open_time，找小于等于它的最近一个 anchor。

用法:
    python3 scripts/backfill_open_anchor.py          # 默认 dry-run
    python3 scripts/backfill_open_anchor.py --execute # 真写入
"""
import argparse
import os
import sqlite3
import sys
from datetime import datetime, timedelta

DB = os.environ.get("DB", "/root/binance-trader/trader.db")
OPEN_HOURS = (0, 4, 8, 12, 16, 20)


def find_anchor(open_time_str: str) -> str | None:
    """给定 open_time，返回该周期的 anchor 时刻字符串 (YYYY-MM-DD HH:30:00)"""
    try:
        dt = datetime.strptime(open_time_str, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None
    # 找小于等于 dt 的最近 OPEN_HOURS:30:00
    best = None
    for d_offset in (0, 1):  # 今天 / 昨天
        base_date = (dt - timedelta(days=d_offset)).date()
        for h in OPEN_HOURS:
            cand = datetime.combine(base_date, datetime.min.time()).replace(hour=h, minute=30)
            if cand <= dt:
                if best is None or cand > best:
                    best = cand
    return best.strftime("%Y-%m-%d %H:%M:%S") if best else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="真写入（默认 dry-run）")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # 只回填 open_anchor 为 NULL 的记录
    rows = conn.execute("""
        SELECT id, open_time, open_anchor FROM open_log_4h
        WHERE open_anchor IS NULL OR open_anchor = ''
        ORDER BY id
    """).fetchall()

    if not rows:
        print("无需回填，所有记录都已有 open_anchor")
        return

    print(f"待回填 {len(rows)} 条记录")
    fill_map = {}
    skipped = 0
    for r in rows:
        anchor = find_anchor(r["open_time"]) if r["open_time"] else None
        if anchor is None:
            print(f"  #{r['id']} 无法推算 (open_time={r['open_time']!r})，跳过")
            skipped += 1
            continue
        fill_map.setdefault(anchor, 0)
        fill_map[anchor] += 1

    print("\n回填分布:")
    for a in sorted(fill_map, reverse=True):
        print(f"  {a}: {fill_map[a]} 条")

    if not args.execute:
        print(f"\n[DRY-RUN] 加 --execute 真写入。准备回填 {len(rows) - skipped} 条")
        return

    # 真写入
    n_ok = 0
    for r in rows:
        anchor = find_anchor(r["open_time"]) if r["open_time"] else None
        if anchor is None:
            continue
        conn.execute("UPDATE open_log_4h SET open_anchor = ? WHERE id = ?", (anchor, r["id"]))
        n_ok += 1
    conn.commit()
    conn.close()
    print(f"\n✅ 回填完成 {n_ok} 条")


if __name__ == "__main__":
    main()
