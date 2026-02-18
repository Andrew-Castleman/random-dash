"""
Economic calendar: hybrid real data (FRED) + hardcoded 2026 schedule.
Recent releases: FRED API actuals. Upcoming: hardcoded FOMC, Jobs, CPI, etc. with countdown timers.
"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

FRED_API_KEY = os.getenv("FRED_API_KEY")

# Eastern time: use ZoneInfo when available (Python 3.9+, tzdata on Linux); else fixed UTC-5
try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except (ImportError, Exception):
    ET = timezone(timedelta(hours=-5))  # EST fallback for servers without tzdata

# FRED series: HIGH IMPACT ONLY (Jobs, CPI, Core CPI, FOMC, GDP). No weekly jobless, PPI, or medium/low.
FRED_SERIES = {
    "CPIAUCSL": {"name": "CPI", "impact": "High", "suffix": "", "icon": "inflation"},
    "CPILFESL": {"name": "Core CPI", "impact": "High", "suffix": "", "icon": "inflation"},
    "UNRATE": {"name": "Unemployment Rate", "impact": "High", "suffix": "%", "icon": "jobs"},
    "GDP": {"name": "GDP", "impact": "High", "suffix": "B", "icon": "gdp"},
    "PAYEMS": {"name": "Jobs Report", "impact": "High", "suffix": "K", "icon": "jobs"},
}

# --- 2026 Hardcoded schedule (federalreserve.gov, BLS patterns) ---

# FOMC Rate Decision dates 2026 (Rate Decision = second day, 2:00 PM ET)
FOMC_2026 = [
    ("2026-03-19", "2:00 PM ET", "FOMC Rate Decision"),
    ("2026-05-07", "2:00 PM ET", "FOMC Rate Decision"),
    ("2026-06-18", "2:00 PM ET", "FOMC Rate Decision"),
    ("2026-07-30", "2:00 PM ET", "FOMC Rate Decision"),
    ("2026-09-17", "2:00 PM ET", "FOMC Rate Decision"),
    ("2026-11-05", "2:00 PM ET", "FOMC Rate Decision"),
    ("2026-12-17", "2:00 PM ET", "FOMC Rate Decision"),
]

# Jobs Report: First Friday of month (8:30 AM ET)
JOBS_2026 = [
    "2026-03-07", "2026-04-04", "2026-05-02", "2026-06-06", "2026-07-03",
    "2026-08-07", "2026-09-04", "2026-10-02", "2026-11-06", "2026-12-04",
]

# CPI: Mid-month pattern (8:30 AM ET)
CPI_2026 = [
    "2026-03-12", "2026-04-10", "2026-05-14", "2026-06-11", "2026-07-16",
    "2026-08-13", "2026-09-10", "2026-10-15", "2026-11-13", "2026-12-10",
]

# GDP: End of quarter (8:30 AM ET) — Jan 30, Apr 30, Jul 30, Oct 30
GDP_2026 = ["2026-01-30", "2026-04-30", "2026-07-30", "2026-10-30"]

# Placeholder forecasts (high-impact only)
PLACEHOLDER_FORECASTS = {
    "FOMC Rate Decision": "5.25–5.50% (hold expected)",
    "Jobs Report": "Consensus NFP ~180K",
    "CPI": "Consensus +0.2% m/m",
    "Core CPI": "Consensus +0.2% m/m",
    "GDP": "Consensus +2.0% q/q SAAR",
    "Unemployment Rate": "Consensus 4.0%",
}


def _parse_et_time(date_str: str, time_str: str) -> datetime:
    """Parse date (YYYY-MM-DD) and time (e.g. '8:30 AM ET') into ET datetime, return for timestamp."""
    year, month, day = map(int, date_str.split("-"))
    time_str = time_str.replace(" ET", "").strip()
    if "8:30 AM" in time_str or "8:30" in time_str:
        hour, minute = 8, 30
    elif "2:00 PM" in time_str or "14:00" in time_str:
        hour, minute = 14, 0
    elif "10:00 AM" in time_str:
        hour, minute = 10, 0
    else:
        hour, minute = 8, 30
    dt = datetime(year, month, day, hour, minute, 0, tzinfo=ET)
    return dt


def _release_ts(date_str: str, time_str: str) -> int:
    """Return Unix timestamp (seconds) for release moment in ET."""
    try:
        dt = _parse_et_time(date_str, time_str)
        return int(dt.timestamp())
    except Exception:
        return 0


def _fetch_fred_observations(series_id: str, days_back: int = 60) -> list[dict]:
    """Fetch FRED observations (date, value) for the last days_back days. Returns list sorted by date desc."""
    if not FRED_API_KEY:
        return []
    url = "https://api.stlouisfed.org/fred/series/observations"
    end = datetime.now().date()
    start = end - timedelta(days=days_back)
    try:
        r = requests.get(
            url,
            params={
                "series_id": series_id,
                "api_key": FRED_API_KEY,
                "file_type": "json",
                "observation_start": start.isoformat(),
                "observation_end": end.isoformat(),
                "sort_order": "desc",
                "limit": 24,
            },
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        obs = data.get("observations", [])
        out = []
        for o in obs:
            val = o.get("value")
            if val and val != ".":
                try:
                    out.append({"date": o["date"], "value": float(val)})
                except (TypeError, ValueError):
                    pass
        return out
    except Exception as e:
        logger.warning("FRED %s: %s", series_id, e)
        return []


def _format_value(value: float, series_id: str) -> str:
    """Format value for display (e.g. CPI 2 decimals, NFP with K)."""
    cfg = FRED_SERIES.get(series_id, {})
    suffix = cfg.get("suffix", "")
    if series_id in ("PAYEMS", "ICSA"):
        if value >= 1000:
            return f"{value/1000:.1f}K{suffix}".replace("KK", "K")
        return f"{value:.0f}{suffix}"
    if series_id == "GDP":
        return f"${value:.1f}{suffix}"
    if series_id in ("UNRATE", "RSXFS") or "%" in suffix:
        return f"{value:.1f}%"
    return f"{value:.2f}{suffix}"


# For beat/miss: lower is better (inflation, unemployment); higher is better (jobs, GDP)
_LOWER_IS_BETTER = {"CPIAUCSL", "CPILFESL", "UNRATE"}


def get_recent_releases(days_back: int = 95, max_per_series: int = 3) -> list[dict]:
    """
    Fetch FRED actuals. HIGH impact only, no jobless claims.
    Uses 95 days back so monthly/quarterly series have at least 2 observations (for "previous").
    Returns top 3 with name, date, actual, previous, change_direction, beat_forecast, miss_forecast.
    Fetches all series in parallel to avoid sequential round-trips.
    """
    high_impact = [(sid, cfg) for sid, cfg in FRED_SERIES.items() if cfg.get("impact") == "High"]
    if not high_impact:
        return []
    days = max(days_back, 95)
    obs_by_series: dict[str, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=min(5, len(high_impact))) as ex:
        futures = {ex.submit(_fetch_fred_observations, series_id, days): series_id for series_id, _ in high_impact}
        for fut in as_completed(futures, timeout=15):
            series_id = futures[fut]
            try:
                obs_by_series[series_id] = fut.result()[: max_per_series + 1]
            except Exception as e:
                logger.warning("FRED %s: %s", series_id, e)
                obs_by_series[series_id] = []
    out = []
    for series_id, cfg in high_impact:
        obs = obs_by_series.get(series_id, [])
        for i in range(len(obs)):
            actual_val = obs[i]["value"]
            prev_val = obs[i + 1]["value"] if i + 1 < len(obs) else None
            if prev_val is None:
                direction = "unchanged"
            elif actual_val > prev_val:
                direction = "higher"
            elif actual_val < prev_val:
                direction = "lower"
            else:
                direction = "unchanged"
            lower_better = series_id in _LOWER_IS_BETTER
            if direction == "unchanged":
                beat_forecast = False
                miss_forecast = False
            elif lower_better:
                beat_forecast = direction == "lower"
                miss_forecast = direction == "higher"
            else:
                beat_forecast = direction == "higher"
                miss_forecast = direction == "lower"
            out.append({
                "name": cfg["name"],
                "event": cfg["name"],
                "date": obs[i]["date"],
                "actual": _format_value(actual_val, series_id),
                "previous": _format_value(prev_val, series_id) if prev_val is not None else "—",
                "direction": direction,
                "change_direction": "up" if direction == "higher" else ("down" if direction == "lower" else "unchanged"),
                "beat_forecast": beat_forecast,
                "miss_forecast": miss_forecast,
                "impact": cfg["impact"],
                "icon": cfg.get("icon", "chart"),
            })
    out.sort(key=lambda x: (x["date"], x["name"]), reverse=True)
    return out[:3]  # Only last 3 major events


def _upcoming_events_next_60_days() -> list[dict]:
    """Build upcoming HIGH impact events (FOMC, Jobs, CPI, Core CPI, GDP). No jobless claims, no PPI."""
    today = datetime.now(ET).date()
    end = today + timedelta(days=60)
    now_ts = datetime.now(ET).timestamp()
    events = []

    def add_upcoming(event: dict) -> None:
        release_ts = event["release_ts"]
        if release_ts <= 0:
            return
        sec_until = release_ts - now_ts
        days_until = int(sec_until // 86400)
        hours_until = int((sec_until % 86400) // 3600)
        if days_until == 0:
            countdown_text = "TODAY" if hours_until > 0 else "NOW"
        elif days_until == 1:
            countdown_text = "Tomorrow"
        else:
            countdown_text = f"in {days_until} days"
        if days_until > 7:
            urgency = "low"
        elif days_until >= 2:
            urgency = "medium"
        elif days_until >= 1:
            urgency = "high"
        else:
            urgency = "critical" if hours_until > 0 else "high"
        event["name"] = event["event"]
        event["days_until"] = days_until
        event["hours_until"] = hours_until
        event["countdown_text"] = countdown_text
        event["urgency"] = urgency
        event["forecast_summary"] = f"Est: {event.get('forecast', '—')}"

    for date_str, time_str, name in FOMC_2026:
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
            if today <= d <= end:
                e = {
                    "event": name,
                    "date": date_str,
                    "time": time_str,
                    "release_ts": _release_ts(date_str, time_str),
                    "forecast": PLACEHOLDER_FORECASTS.get(name, "—"),
                    "previous": "5.25–5.50%",
                    "impact": "High",
                    "icon": "fomc",
                }
                add_upcoming(e)
                events.append(e)
        except ValueError:
            pass

    for date_str in JOBS_2026:
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
            if today <= d <= end:
                e = {
                    "event": "Jobs Report",
                    "date": date_str,
                    "time": "8:30 AM ET",
                    "release_ts": _release_ts(date_str, "8:30 AM ET"),
                    "forecast": PLACEHOLDER_FORECASTS.get("Jobs Report", "—"),
                    "previous": "—",
                    "impact": "High",
                    "icon": "jobs",
                }
                add_upcoming(e)
                events.append(e)
        except ValueError:
            pass

    for date_str in CPI_2026:
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
            if today <= d <= end:
                for ev_name, fkey in (("CPI", "CPI"), ("Core CPI", "Core CPI")):
                    e = {
                        "event": ev_name,
                        "date": date_str,
                        "time": "8:30 AM ET",
                        "release_ts": _release_ts(date_str, "8:30 AM ET"),
                        "forecast": PLACEHOLDER_FORECASTS.get(fkey, "—"),
                        "previous": "—",
                        "impact": "High",
                        "icon": "inflation",
                    }
                    add_upcoming(e)
                    events.append(e)
        except ValueError:
            pass

    for date_str in GDP_2026:
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
            if today <= d <= end:
                e = {
                    "event": "GDP",
                    "date": date_str,
                    "time": "8:30 AM ET",
                    "release_ts": _release_ts(date_str, "8:30 AM ET"),
                    "forecast": PLACEHOLDER_FORECASTS.get("GDP", "—"),
                    "previous": "—",
                    "impact": "High",
                    "icon": "gdp",
                }
                add_upcoming(e)
                events.append(e)
        except ValueError:
            pass

    events.sort(key=lambda x: (x["release_ts"], x["event"]))
    seen = set()
    unique = []
    for e in events:
        key = (e["date"], e["event"])
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return unique[:5]  # Only next 5 major events


def get_economic_calendar(
    days_back_recent: int = 30,
    days_ahead_upcoming: int = 60,
) -> dict:
    """
    Returns { "recent_releases": [...], "upcoming_releases": [...] }.
    Recent: top 3 HIGH impact with beat/miss. Upcoming: next 5 with countdown_text, urgency, forecast_summary.
    """
    try:
        recent = get_recent_releases(days_back=days_back_recent)
    except Exception as e:
        logger.warning("Recent releases: %s", e)
        recent = []

    try:
        upcoming = _upcoming_events_next_60_days()
    except Exception as e:
        logger.warning("Upcoming releases: %s", e)
        upcoming = []

    return {"recent_releases": recent, "upcoming_releases": upcoming}
