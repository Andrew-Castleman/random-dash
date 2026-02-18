"""
SQLite schema and snapshot storage for portfolio, trending, and alerts.
Numeric fields are sanitized (NaN -> 0) before insert.
Set DATABASE_FILE in env to override DB location (relative to project root).
"""

import math
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

try:
    from config import DATABASE_PATH as DB_PATH
except ImportError:
    DB_PATH = Path(__file__).resolve().parent / "market_dashboard.db"

_lock = threading.Lock()


def _num(x, default=0.0):
    """Return float or int, or default if None/NaN."""
    if x is None:
        return default
    try:
        v = float(x)
        return default if math.isnan(v) else v
    except (TypeError, ValueError):
        return default


def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    with _lock:
        conn = get_conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    price REAL,
                    change_percent REAL,
                    volume INTEGER,
                    analysis TEXT,
                    competitor_context TEXT,
                    timestamp TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS trending_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    price REAL,
                    change_percent REAL,
                    trend_reason TEXT,
                    analysis TEXT,
                    timestamp TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    alert_type TEXT,
                    message TEXT,
                    created_at TEXT NOT NULL,
                    resolved INTEGER DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_portfolio_ts ON portfolio_snapshots(timestamp);
                CREATE INDEX IF NOT EXISTS idx_trending_ts ON trending_snapshots(timestamp);
            """)
            conn.commit()
        finally:
            conn.close()


def save_portfolio_snapshot(ticker: str, price: float, change_percent: float, volume: int, analysis: str, competitor_context: str):
    ts = datetime.utcnow().isoformat() + "Z"
    price = _num(price, 0.0)
    change_percent = _num(change_percent, 0.0)
    volume = int(_num(volume, 0))
    with _lock:
        conn = get_conn()
        try:
            conn.execute(
                "INSERT INTO portfolio_snapshots (ticker, price, change_percent, volume, analysis, competitor_context, timestamp) VALUES (?,?,?,?,?,?,?)",
                (ticker, price, change_percent, volume, analysis or "", competitor_context or "", ts),
            )
            conn.commit()
        finally:
            conn.close()


def save_trending_snapshot(ticker: str, price: float, change_percent: float, trend_reason: str, analysis: str):
    ts = datetime.utcnow().isoformat() + "Z"
    price = _num(price, 0.0)
    change_percent = _num(change_percent, 0.0)
    with _lock:
        conn = get_conn()
        try:
            conn.execute(
                "INSERT INTO trending_snapshots (ticker, price, change_percent, trend_reason, analysis, timestamp) VALUES (?,?,?,?,?,?)",
                (ticker, price, change_percent, trend_reason or "", analysis or "", ts),
            )
            conn.commit()
        finally:
            conn.close()
