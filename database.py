"""
SQLite schema and snapshot storage for portfolio, trending, and alerts.
Numeric fields are sanitized (NaN -> 0) before insert.
Set DATABASE_FILE in env to override DB location (relative to project root).
"""

import logging
import math
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

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
                CREATE TABLE IF NOT EXISTS api_call_counter (
                    month_year TEXT PRIMARY KEY,
                    call_count INTEGER NOT NULL DEFAULT 0,
                    last_reset TEXT NOT NULL
                );
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


def get_monthly_api_call_count() -> int:
    """Get current month's API call count. Returns 0 if no record exists."""
    from datetime import datetime
    month_year = datetime.now().strftime("%Y-%m")
    with _lock:
        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT call_count FROM api_call_counter WHERE month_year = ?",
                (month_year,)
            ).fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()


def increment_api_call_count() -> bool:
    """
    Increment API call count for current month. Returns True if successful.
    If count >= 50, returns False and does not increment.
    Uses atomic UPDATE with WHERE clause to prevent going over limit.
    """
    from datetime import datetime
    month_year = datetime.now().strftime("%Y-%m")
    now_iso = datetime.utcnow().isoformat() + "Z"
    with _lock:
        conn = get_conn()
        try:
            # First, ensure record exists
            conn.execute(
                "INSERT OR IGNORE INTO api_call_counter (month_year, call_count, last_reset) VALUES (?, 0, ?)",
                (month_year, now_iso)
            )
            # Atomic increment only if count < 50
            cursor = conn.execute(
                "UPDATE api_call_counter SET call_count = call_count + 1 WHERE month_year = ? AND call_count < 50",
                (month_year,)
            )
            conn.commit()
            # If rows_affected > 0, increment succeeded
            success = cursor.rowcount > 0
            if not success:
                # Check if we're at limit
                row = conn.execute(
                    "SELECT call_count FROM api_call_counter WHERE month_year = ?",
                    (month_year,)
                ).fetchone()
                if row and int(row[0]) >= 50:
                    logger.warning(f"API call limit reached: {int(row[0])}/50 for {month_year}")
            return success
        finally:
            conn.close()


def reset_monthly_api_counter_if_needed():
    """Reset counter if we're in a new month. Called automatically on init."""
    from datetime import datetime
    month_year = datetime.now().strftime("%Y-%m")
    now_iso = datetime.utcnow().isoformat() + "Z"
    with _lock:
        conn = get_conn()
        try:
            # Check if we need to reset (new month)
            row = conn.execute(
                "SELECT month_year FROM api_call_counter WHERE month_year != ?",
                (month_year,)
            ).fetchone()
            if row:
                # Delete old month records
                conn.execute("DELETE FROM api_call_counter WHERE month_year != ?", (month_year,))
                conn.commit()
        finally:
            conn.close()
