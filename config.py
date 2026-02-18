"""
Application configuration from environment variables.
Use .env for local overrides; set env in production.
"""

import os
from pathlib import Path

# Base paths
BASE_DIR = Path(__file__).resolve().parent

# Server
PORT = int(os.environ.get("PORT", "5000"))
FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "false").strip().lower() in ("1", "true", "yes")

# Scraper
REQUEST_TIMEOUT = int(os.environ.get("SCRAPER_TIMEOUT", "15"))
SCRAPER_DEBUG = os.environ.get("SCRAPER_DEBUG", "false").strip().lower() in ("1", "true", "yes")

# Apartment analysis cache: how long (seconds) to reuse Claude results per listing URL. Default 1 hour.
APARTMENT_ANALYSIS_CACHE_TTL = int(os.environ.get("APARTMENT_ANALYSIS_CACHE_TTL", "3600"))

# Database
DATABASE_PATH = BASE_DIR / os.environ.get("DATABASE_FILE", "market_dashboard.db")

# API keys (loaded from .env; never log or expose)
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
