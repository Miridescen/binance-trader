#!/usr/bin/env python3
"""
归档老明细数据：把 KEEP_DAYS 天前的 detail 表数据导出到 CSV.gz，并从主库删除。

用法:
    python3 scripts/archive_old_details.py              # 默认保留 60 天
    KEEP_DAYS=90 python3 scripts/archive_old_details.py # 保留 90 天

dry-run（仅导出不删除）:
    DRY_RUN=1 python3 scripts/archive_old_details.py

说明:
  - DELETE 不会立即缩小数据库文件，删除的空间会被后续 INSERT 复用
  - 如需缩文件大小可手动 VACUUM（注意会锁库 1-2 分钟）
  - 归档文件路径: /root/binance-trader/archive/{table}-before-{date}.csv.gz
"""
from __future__ import annotations
import csv
import gzip
import os
import sqlite3
import sys
from datetime import datetime, timedelta

DB = os.environ.get("DB", "/root/binance-trader/trader.db")
ARCHIVE_DIR = os.environ.get("ARCHIVE_DIR", "/root/binance-trader/archive")
KEEP_DAYS = int(os.environ.get("KEEP_DAYS", 60))
DRY_RUN = os.environ.get("DRY_RUN") == "1"
BATCH = 5000  # DELETE 分批大小，避免长事务锁库

TABLES = [
    "positions_detail",
    "virtual_detail",
    "virtual_detail_4h",
    "virtual_detail_8h",
    "virtual_detail_12h",
]


def archive_table(conn: sqlite3.Connection, tbl: str, cutoff: str) -> tuple[int, int]:
    """导出 < cutoff 的行到 CSV.gz；DELETE。返回 (导出行数, 删除行数)"""
    cur = conn.execute(f"SELECT COUNT(*) FROM {tbl} WHERE time < ?", (cutoff,))
    n_to_archive = cur.fetchone()[0]
    if n_to_archive == 0:
        print(f"  {tbl:25s} 无早于 {cutoff[:10]} 的数据，跳过")
        return 0, 0

    out = f"{ARCHIVE_DIR}/{tbl}-before-{cutoff[:10]}.csv.gz"
    print(f"  {tbl:25s} 待归档 {n_to_archive} 行 → {out}")

    rows = conn.execute(f"SELECT * FROM {tbl} WHERE time < ? ORDER BY id", (cutoff,))
    cols = [d[0] for d in rows.description]
    n_written = 0
    with gzip.open(out, "wt", newline="", compresslevel=6) as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow(r)
            n_written += 1
    print(f"  {tbl:25s} 已导出 {n_written} 行  (gz 文件大小: {os.path.getsize(out)/1024/1024:.1f} MB)")

    if DRY_RUN:
        print(f"  {tbl:25s} [DRY_RUN] 跳过 DELETE")
        return n_written, 0

    # 分批 DELETE，避免长事务锁库
    n_deleted = 0
    while True:
        cur = conn.execute(
            f"DELETE FROM {tbl} WHERE id IN ("
            f"  SELECT id FROM {tbl} WHERE time < ? LIMIT ?"
            f")",
            (cutoff, BATCH),
        )
        deleted = cur.rowcount
        conn.commit()
        if deleted == 0:
            break
        n_deleted += deleted
    print(f"  {tbl:25s} 已删除 {n_deleted} 行")
    return n_written, n_deleted


def main():
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    cutoff_dt = datetime.now() - timedelta(days=KEEP_DAYS)
    cutoff = cutoff_dt.strftime("%Y-%m-%d %H:%M:%S")

    print(f"DB:         {DB}")
    print(f"归档目录:   {ARCHIVE_DIR}")
    print(f"保留天数:   {KEEP_DAYS}")
    print(f"时间 cutoff: {cutoff} （删除此时间之前的明细）")
    print(f"DRY_RUN:    {DRY_RUN}")
    print()

    conn = sqlite3.connect(DB, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    total_archived = total_deleted = 0
    for tbl in TABLES:
        try:
            a, d = archive_table(conn, tbl, cutoff)
            total_archived += a
            total_deleted += d
        except sqlite3.OperationalError as e:
            print(f"  {tbl:25s} ❌ 失败：{e}")
        except Exception as e:
            print(f"  {tbl:25s} ❌ 异常：{e}", file=sys.stderr)
    conn.close()
    print()
    print(f"合计：归档 {total_archived} 行，删除 {total_deleted} 行")


if __name__ == "__main__":
    main()
