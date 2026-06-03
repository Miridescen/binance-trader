"""
基差套利子项目独立数据库（basis.db）。

与主项目 trader.db 完全隔离：
  - 不同文件
  - 不同 schema
  - 独立 WAL / 锁

如果想"扁平"看主项目数据，从 trader.db 拉；这里只放基差相关。
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "basis.db")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """建表（如果不存在）。永久保留全部数据。"""
    with get_conn() as conn:
        conn.executescript("""
        -- 基差快照：每 15 分钟一次，每个 (pair, contract) 一行
        CREATE TABLE IF NOT EXISTS basis_snapshot (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            time            TEXT,           -- 采集时间 YYYY-MM-DD HH:MM:SS
            pair            TEXT,           -- BTCUSDT / ETHUSDT
            contract_type   TEXT,           -- CURRENT_QUARTER / NEXT_QUARTER
            contract_symbol TEXT,           -- BTCUSDT_260626 等
            expiry_date     TEXT,           -- 到期日 YYYY-MM-DD (UTC)
            days_to_expiry  REAL,           -- 剩余天数（小数）
            spot_price      REAL,
            futures_price   REAL,
            basis           REAL,           -- futures - spot
            basis_pct       REAL,           -- basis / spot × 100
            annualized_pct  REAL,           -- basis_pct × 365 / days_to_expiry
            spot_vol_24h    REAL,           -- 现货 24h 成交额（USDT）
            fut_vol_24h     REAL            -- 合约 24h 成交额（USDT）
        );
        CREATE INDEX IF NOT EXISTS idx_basis_time ON basis_snapshot(time);
        CREATE INDEX IF NOT EXISTS idx_basis_pair_time ON basis_snapshot(pair, time);
        CREATE INDEX IF NOT EXISTS idx_basis_symbol_time ON basis_snapshot(contract_symbol, time);
        """)


def insert_snapshots(rows: list[dict]):
    if not rows:
        return
    with get_conn() as conn:
        conn.executemany("""
            INSERT INTO basis_snapshot (
                time, pair, contract_type, contract_symbol,
                expiry_date, days_to_expiry, spot_price, futures_price,
                basis, basis_pct, annualized_pct, spot_vol_24h, fut_vol_24h
            ) VALUES (
                :time, :pair, :contract_type, :contract_symbol,
                :expiry_date, :days_to_expiry, :spot_price, :futures_price,
                :basis, :basis_pct, :annualized_pct, :spot_vol_24h, :fut_vol_24h
            )
        """, rows)


def get_latest_snapshots() -> list[dict]:
    """每个 contract_symbol 取最新一条"""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM basis_snapshot
            WHERE id IN (
                SELECT MAX(id) FROM basis_snapshot GROUP BY contract_symbol
            )
            ORDER BY pair, contract_type
        """).fetchall()
        return [dict(r) for r in rows]


def get_snapshots_by_symbol(symbol: str, limit: int = 1000) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM basis_snapshot WHERE contract_symbol = ? "
            "ORDER BY id DESC LIMIT ?",
            (symbol, limit)
        ).fetchall()
        return [dict(r) for r in rows]


if __name__ == "__main__":
    init_db()
    print(f"basis.db 初始化完成：{DB_PATH}")
