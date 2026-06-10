"""
配额持久化存储 — SQLite 单表，服务重启不丢失。

表结构:
  quota(ip TEXT PRIMARY KEY, used INTEGER DEFAULT 0)

localhost / admin 的无限配额逻辑在 main.py 层处理，
本模块只负责 IP → used 的读写。
"""

import os
import sqlite3

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
DB_PATH = os.path.join(DATA_DIR, "quota.db")


def _get_db() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS quota ("
        "  ip TEXT PRIMARY KEY,"
        "  used INTEGER NOT NULL DEFAULT 0"
        ")"
    )
    conn.commit()
    return conn


def get_used(ip: str) -> int:
    conn = _get_db()
    row = conn.execute("SELECT used FROM quota WHERE ip = ?", (ip,)).fetchone()
    conn.close()
    return row[0] if row else 0


def increment(ip: str) -> int:
    """使用一次配额，返回新的 used 值。"""
    conn = _get_db()
    conn.execute(
        "INSERT INTO quota (ip, used) VALUES (?, 1)"
        " ON CONFLICT(ip) DO UPDATE SET used = used + 1",
        (ip,),
    )
    conn.commit()
    row = conn.execute("SELECT used FROM quota WHERE ip = ?", (ip,)).fetchone()
    conn.close()
    return row[0] if row else 1


def reset(ip: str) -> None:
    conn = _get_db()
    conn.execute("DELETE FROM quota WHERE ip = ?", (ip,))
    conn.commit()
    conn.close()
