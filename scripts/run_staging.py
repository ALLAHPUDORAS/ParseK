"""Run a quick one-shot staging scrape for Affpaying and Offervault.
This script temporarily restricts SITE_CONFIGS to the two targets and runs the Scraper.
"""
import argparse
import logging
import json
import os
import time
import sys

# ensure project root is importable
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src import config as cfg
import src.scraper as scraper_mod
from src.scraper import Scraper

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("staging")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--max-leads", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=None)
    args = parser.parse_args()

    # restrict SITE_CONFIGS to top2
    keep = ["Affpaying", "Offervault"]
    filtered = {k: v for k, v in cfg.SITE_CONFIGS.items() if k in keep}
    if not filtered:
        logger.error("No matching SITE_CONFIGS for %s", keep)
        return

    # monkeypatch config and scraper module SITE_CONFIGS (scraper imported SITE_CONFIGS at module load)
    cfg.SITE_CONFIGS = filtered
    scraper_mod.SITE_CONFIGS = filtered

    scraper = Scraper(headless=args.headless, max_leads=args.max_leads, concurrency=args.concurrency)
    start = time.monotonic()
    raw = scraper.scrape_source()
    duration = time.monotonic() - start

    out = {
        "duration_seconds": duration,
        "scraped_pages": scraper.scraped_pages,
        "failed_pages": scraper.failed_pages,
        "company_urls_found": len(scraper.company_urls),
        "skipped_urls": scraper.skipped_urls,
    }

    os.makedirs("logs", exist_ok=True)
    with open("logs/staging_summary.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)

    logger.info("Staging done: %s", out)

if __name__ == "__main__":
    main()
