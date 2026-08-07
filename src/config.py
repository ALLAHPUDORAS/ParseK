"""
Configuration settings for B2B Lead Scraping & Validation Pipeline.
"""

import os
from pathlib import Path

# Load local environment variables from .env when present.
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ENV_FILE = os.path.join(ROOT_DIR, ".env")

if os.path.exists(ENV_FILE):
    for raw_line in Path(ENV_FILE).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value

# Target verticals to scrape
TARGET_VERTICALS = ["Gambling", "Casino", "Nutra", "Crypto"]

# GEO-Fence Exclusions (RU, BY, CIS countries)
EXCLUDED_GEOS = {
    "RU", "BY", "CIS", "RUSSIA", "BELARUS", "СНГ", "РОССИЯ", "БЕЛАРУСЬ",
    "RUS", "BLR", "UKRAINE", "UA"
}

# Generic / Banned email prefixes to remove
BANNED_EMAIL_PREFIXES = {
    "info", "support", "admin", "hr", "help", "contact", "sales", "billing",
    "office", "inquiries", "general", "compliance", "jobs", "careers",
    "marketing", "legal", "accounting", "finance", "media", "privacy", "team"
}

# Target status exclusions
EXCLUDED_STATUSES = {"CLOSED", "BLACKLISTED", "CLOSED/OFFLINE", "INACTIVE"}

# Target URLs for scrapers
AFFPAYING_BASE_URL = "https://www.affpaying.com"
OFFERVAULT_BASE_URL = "https://www.offervault.com"
AFFPLUS_BASE_URL = "https://www.affplus.com"

# Anti-blocking and browser configuration
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
PAGE_LOAD_TIMEOUT = 30000
DEFAULT_MAX_LEADS = 50000
DEFAULT_CONCURRENCY_4GB = 3
DEFAULT_POLL_INTERVAL = 4 * 3600

PAGINATION_SELECTORS = [
    "a[rel='next']",
    "a.next",
    "li.next a",
    "button[aria-label='Next']",
]

COMPANY_CARD_SELECTORS = [
    "a[href]",
    "[data-href]",
    "[data-url]",
    "[data-company-url]",
    "[data-card-url]",
    "[onclick]",
]

DYNAMIC_CARD_TRIGGERS = [
    "button[onclick]",
    "[data-card-url]",
    "[data-card-toggle]",
    "[data-href]",
    "[data-url]",
    "[onclick]",
    "[role='button']",
    ".network-card",
    ".offer-card",
    ".card-preview",
]

SITE_CONFIGS = {
    "Affpaying": {
        "base_url": AFFPAYING_BASE_URL,
        "categories": {
            "Gambling": "/networks/?industry=Gambling",
            "Casino": "/networks/?industry=Casino",
            "Nutra": "/networks/?industry=Nutra",
            "Crypto": "/networks/?industry=Crypto",
        },
        "search_page_template": "/search?q={vertical}&page={page}",
        "max_search_pages": 5,
        "pagination_selectors": ["a[rel='next']", "a.next", ".pagination a.next", "a[aria-label='Next']"],
        "company_card_selectors": COMPANY_CARD_SELECTORS,
        "dynamic_card_triggers": DYNAMIC_CARD_TRIGGERS,
        # site-specific extra triggers/selectors
        "extra_triggers": ["text=All Categories", ".network-list", ".networks", ".network-card a"],
        "company_url_patterns": [r"^/network/[^/]+$"],
        "crawl_delay": 1,
        "max_concurrency": 2,
    },
    "Offervault": {
        "base_url": OFFERVAULT_BASE_URL,
        "categories": {
            "Gambling": "/affiliate-networks?vertical=Gambling",
            "Casino": "/affiliate-networks?vertical=Casino",
            "Nutra": "/affiliate-networks?vertical=Nutra",
            "Crypto": "/affiliate-networks?vertical=Crypto",
        },
        "pagination_selectors": ["a[rel='next']", "a.next", "li.next a", ".pagination a.next"],
        "company_card_selectors": COMPANY_CARD_SELECTORS,
        "dynamic_card_triggers": DYNAMIC_CARD_TRIGGERS,
        "company_url_patterns": [r"^/(?:network|affiliate-networks)/[^/]+$"],
        "crawl_delay": 2,
        "max_concurrency": 2,
    },
    "Affplus": {
        "base_url": AFFPLUS_BASE_URL,
        "categories": {
            "Gambling": "/offers?vertical=Gambling",
            "Casino": "/offers?vertical=Casino",
            "Nutra": "/offers?vertical=Nutra",
            "Crypto": "/offers?vertical=Crypto",
        },
        "pagination_selectors": ["a[rel='next']", "a.next", "button[aria-label='Next']", ".pagination a.next"],
        "company_card_selectors": COMPANY_CARD_SELECTORS,
        "dynamic_card_triggers": DYNAMIC_CARD_TRIGGERS,
        "extra_triggers": [".offers-list", ".offer-card a"],
        "company_url_patterns": [r"^/(?:n|o|details|network|offer)/[a-zA-Z0-9_-]+$"],
        "crawl_delay": 1,
        "max_concurrency": 2,
    },
}

# Output directory
OUTPUT_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "output"))
LOGS_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs"))

TG_API_ID = int(os.getenv("TG_API_ID", "0") or 0)
TG_API_HASH = os.getenv("TG_API_HASH", "") or ""
TG_API_ENABLED = bool(TG_API_ID and TG_API_HASH)

DEFAULT_EXPORT_JSON = "leads.json"
DEFAULT_EXPORT_CSV = "leads.csv"
DEFAULT_EXPORT_TEXT = "leads_list.txt"
DEFAULT_EXPORT_RAW_JSON = "raw_leads.json"
DEFAULT_EXPORT_RAW_CSV = "raw_leads.csv"
DEFAULT_EXPORT_RAW_XLSX = "raw_leads.xlsx"