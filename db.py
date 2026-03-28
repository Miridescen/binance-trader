"""
SQLite 数据库模块，替代所有 CSV 文件的读写操作。
数据库文件：trader.db（与脚本同目录）
"""

import os
import sqlite3
from datetime import datetime
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(__file__), "trader.db")


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
    """建表（如果不存在）"""
    with get_conn() as conn:
        conn.executescript("""
        -- 开仓记录（原 open_log.csv）
        CREATE TABLE IF NOT EXISTS open_log (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            open_time          TEXT,
            close_time         TEXT,
            symbol             TEXT,
            side               TEXT,
            change_pct         REAL,
            market_cap_usd     TEXT,
            circulating_supply TEXT,
            btc_change_pct     REAL,
            symbol_funding_rate REAL,
            oi_change_pct      REAL,
            long_short_ratio   REAL,
            open_commission    REAL,
            entry_price        REAL,
            close_price        REAL,
            position_amt       REAL,
            unrealized_pnl     REAL,
            roe_pct            REAL,
            leverage           INTEGER,
            close_commission   REAL,
            close_reason       TEXT
        );

        -- 批次汇总（原 batch_summary_log.csv）
        CREATE TABLE IF NOT EXISTS batch_summary (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            close_time  TEXT,
            long_count  INTEGER,
            long_pnl    REAL,
            short_count INTEGER,
            short_pnl   REAL,
            total_pnl   REAL
        );

        -- 策略事件（原 events_log.csv）
        CREATE TABLE IF NOT EXISTS events_log (
            id     INTEGER PRIMARY KEY AUTOINCREMENT,
            time   TEXT,
            event  TEXT,
            detail TEXT
        );

        -- 持仓快照汇总（原 positions_log.csv）
        CREATE TABLE IF NOT EXISTS positions_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            time         TEXT,
            balance_usdt REAL,
            long_count   INTEGER,
            long_pnl     REAL,
            short_count  INTEGER,
            short_pnl    REAL,
            total_pnl    REAL,
            funding_fee  REAL
        );

        -- 持仓快照明细（原 positions_detail_log.csv）
        CREATE TABLE IF NOT EXISTS positions_detail (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            time            TEXT,
            symbol          TEXT,
            side            TEXT,
            entry_price     REAL,
            mark_price      REAL,
            position_amt    REAL,
            unrealized_pnl  REAL,
            roe_pct         REAL
        );

        -- 虚拟开仓记录（原 virtual_open_log.csv）
        CREATE TABLE IF NOT EXISTS virtual_log (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            open_time           TEXT,
            close_time          TEXT,
            symbol              TEXT,
            side                TEXT,
            change_pct          REAL,
            market_cap_usd      TEXT,
            circulating_supply  TEXT,
            has_mcap            INTEGER,
            btc_change_pct      REAL,
            symbol_funding_rate REAL,
            oi_change_pct       REAL,
            long_short_ratio    REAL,
            entry_price         REAL,
            close_price         REAL,
            unrealized_pnl      REAL,
            roe_pct             REAL
        );

        -- 虚拟持仓快照明细
        CREATE TABLE IF NOT EXISTS virtual_detail (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            time            TEXT,
            symbol          TEXT,
            side            TEXT,
            entry_price     REAL,
            mark_price      REAL,
            unrealized_pnl  REAL,
            roe_pct         REAL
        );

        CREATE INDEX IF NOT EXISTS idx_virtual_detail_time ON virtual_detail(time);

        -- 兼容升级：为已有表添加新字段（不存在时才加）
        """)

        # ALTER TABLE 不支持 IF NOT EXISTS，用 try 兼容
        try:
            conn.execute("ALTER TABLE open_log ADD COLUMN close_reason TEXT")
        except Exception:
            pass  # 字段已存在

        conn.executescript("""
        -- 索引：加速常用查询
        CREATE INDEX IF NOT EXISTS idx_open_log_symbol ON open_log(symbol);
        CREATE INDEX IF NOT EXISTS idx_open_log_open_time ON open_log(open_time);
        CREATE INDEX IF NOT EXISTS idx_positions_log_time ON positions_log(time);
        CREATE INDEX IF NOT EXISTS idx_positions_detail_time ON positions_detail(time);
        CREATE INDEX IF NOT EXISTS idx_virtual_log_open_time ON virtual_log(open_time);
        """)


# ── open_log 操作 ────────────────────────────────────────

def insert_open_log(rows: list[dict]):
    """批量插入开仓记录"""
    with get_conn() as conn:
        conn.executemany("""
            INSERT INTO open_log (open_time, close_time, symbol, side,
                change_pct, market_cap_usd, circulating_supply,
                btc_change_pct, symbol_funding_rate, oi_change_pct,
                long_short_ratio, open_commission,
                entry_price, close_price, position_amt,
                unrealized_pnl, roe_pct, leverage, close_commission)
            VALUES (:open_time, :close_time, :symbol, :side,
                :change_pct, :market_cap_usd, :circulating_supply,
                :btc_change_pct, :symbol_funding_rate, :oi_change_pct,
                :long_short_ratio, :open_commission,
                :entry_price, :close_price, :position_amt,
                :unrealized_pnl, :roe_pct, :leverage, :close_commission)
        """, rows)


def update_close_data(symbol: str, open_time: str, close_data: dict):
    """平仓时回填收益数据：匹配最近一条未平仓的同币种记录"""
    with get_conn() as conn:
        conn.execute("""
            UPDATE open_log SET
                close_time = :close_time,
                entry_price = :entry_price,
                close_price = :close_price,
                position_amt = :position_amt,
                unrealized_pnl = :unrealized_pnl,
                roe_pct = :roe_pct,
                leverage = :leverage,
                close_reason = :close_reason,
                close_commission = COALESCE(:close_commission, close_commission)
            WHERE id = (
                SELECT id FROM open_log
                WHERE symbol = :symbol AND (close_time IS NULL OR close_time = '')
                ORDER BY open_time DESC LIMIT 1
            )
        """, {"close_reason": None, "close_commission": None, **close_data, "symbol": symbol})


def patch_close_commissions(commissions: dict, today: str):
    """平仓后回填手续费"""
    with get_conn() as conn:
        for sym, comm in commissions.items():
            conn.execute("""
                UPDATE open_log SET close_commission = ?
                WHERE symbol = ? AND close_time LIKE ? AND close_commission IS NULL
            """, (comm, sym, f"{today}%"))


def get_open_log_all() -> list[dict]:
    """读取所有开仓记录"""
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM open_log ORDER BY id").fetchall()
        return [dict(r) for r in rows]


def delete_open_log(condition: str, params: tuple = ()):
    """按条件删除开仓记录"""
    with get_conn() as conn:
        cursor = conn.execute(f"DELETE FROM open_log WHERE {condition}", params)
        return cursor.rowcount


def get_open_log_unclosed() -> list[dict]:
    """读取所有未平仓记录"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM open_log WHERE close_time IS NULL OR close_time = '' ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]


# ── batch_summary 操作 ───────────────────────────────────

def insert_batch_summary(row: dict):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO batch_summary (close_time, long_count, long_pnl,
                short_count, short_pnl, total_pnl)
            VALUES (:close_time, :long_count, :long_pnl,
                :short_count, :short_pnl, :total_pnl)
        """, row)


# ── events_log 操作 ──────────────────────────────────────

def insert_event(event: str, detail: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO events_log (time, event, detail) VALUES (?, ?, ?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), event, detail),
        )


# ── positions_log 操作 ───────────────────────────────────

def insert_positions_log(row: dict):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO positions_log (time, balance_usdt, long_count, long_pnl,
                short_count, short_pnl, total_pnl, funding_fee)
            VALUES (:time, :balance_usdt, :long_count, :long_pnl,
                :short_count, :short_pnl, :total_pnl, :funding_fee)
        """, row)


def get_positions_log_all() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM positions_log ORDER BY id").fetchall()
        return [dict(r) for r in rows]


# ── positions_detail 操作 ────────────────────────────────

def insert_positions_detail(rows: list[dict]):
    with get_conn() as conn:
        conn.executemany("""
            INSERT INTO positions_detail (time, symbol, side, entry_price,
                mark_price, position_amt, unrealized_pnl, roe_pct)
            VALUES (:time, :symbol, :side, :entry_price,
                :mark_price, :position_amt, :unrealized_pnl, :roe_pct)
        """, rows)


def get_positions_detail_all() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM positions_detail ORDER BY id").fetchall()
        return [dict(r) for r in rows]


# ── virtual_log 操作 ─────────────────────────────────────

def insert_virtual_log(rows: list[dict]):
    with get_conn() as conn:
        conn.executemany("""
            INSERT INTO virtual_log (open_time, close_time, symbol, side,
                change_pct, market_cap_usd, circulating_supply, has_mcap,
                btc_change_pct, symbol_funding_rate, oi_change_pct, long_short_ratio,
                entry_price, close_price, unrealized_pnl, roe_pct)
            VALUES (:open_time, :close_time, :symbol, :side,
                :change_pct, :market_cap_usd, :circulating_supply, :has_mcap,
                :btc_change_pct, :symbol_funding_rate, :oi_change_pct, :long_short_ratio,
                :entry_price, :close_price, :unrealized_pnl, :roe_pct)
        """, rows)


def update_virtual_close(row_id: int, close_data: dict):
    """虚拟平仓：按 id 更新"""
    with get_conn() as conn:
        conn.execute("""
            UPDATE virtual_log SET
                close_time = :close_time,
                close_price = :close_price,
                unrealized_pnl = :unrealized_pnl,
                roe_pct = :roe_pct
            WHERE id = :id
        """, {**close_data, "id": row_id})


def get_virtual_log_all() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM virtual_log ORDER BY id").fetchall()
        return [dict(r) for r in rows]


def get_virtual_log_unclosed() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM virtual_log WHERE close_time IS NULL OR close_time = '' ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]


# ── virtual_detail 操作 ───────────────────────────────────

def insert_virtual_detail(rows: list[dict]):
    with get_conn() as conn:
        conn.executemany("""
            INSERT INTO virtual_detail (time, symbol, side, entry_price,
                mark_price, unrealized_pnl, roe_pct)
            VALUES (:time, :symbol, :side, :entry_price,
                :mark_price, :unrealized_pnl, :roe_pct)
        """, rows)


def get_virtual_detail_all() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM virtual_detail ORDER BY id").fetchall()
        return [dict(r) for r in rows]


# 启动时自动建表
init_db()
