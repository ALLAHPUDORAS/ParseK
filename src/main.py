import argparse
import logging
import os
import sys
from typing import List, Dict, Any

from src.config import LOGS_DIR, OUTPUT_DIR, DEFAULT_MAX_LEADS
from src.exporter import Exporter
from src.scraper import Scraper
from src.validator import LeadValidator

LOG_FILE = os.path.join(LOGS_DIR, "pipeline.log")


def configure_logging():
    os.makedirs(LOGS_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)


def validate_leads(raw_leads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    validator = LeadValidator()
    valid_leads: List[Dict[str, Any]] = []
    logger = logging.getLogger("LeadPipeline.Main")

    for raw in raw_leads:
        is_valid, reason, processed = validator.validate_lead(raw)
        if is_valid and processed:
            logger.info("Valid lead: %s", processed.get("name"))
            valid_leads.append(processed)
        else:
            logger.info("Lead filtered out: %s | Reason: %s", raw.get("name", "Unknown"), reason)

    return valid_leads


def parse_args():
    parser = argparse.ArgumentParser(description="B2B Lead Scraping Pipeline for Gambling/Nutra/Crypto verticals")
    parser.add_argument("--headless", action="store_true", help="Run Playwright in headless browser mode")
    parser.add_argument("--max-leads", type=int, default=DEFAULT_MAX_LEADS, help="Maximum number of company cards to process")
    parser.add_argument("--export-json", action="store_true", help="Export valid leads to JSON")
    parser.add_argument("--export-csv", action="store_true", help="Export valid leads to CSV")
    parser.add_argument("--export-text", action="store_true", help="Export valid leads to plain text list")
    return parser.parse_args()


def main():
    configure_logging()
    logger = logging.getLogger("LeadPipeline.Main")
    args = parse_args()

    logger.info("Starting lead scraping pipeline")
    logger.info("Headless mode: %s", args.headless)
    logger.info("Max leads: %s", args.max_leads)

    scraper = Scraper(headless=args.headless, max_leads=args.max_leads)
    exporter = Exporter()

    raw_leads = scraper.scrape_source()
    valid_leads = validate_leads(raw_leads)

    if not valid_leads:
        logger.error("No valid leads were produced after validation. Exiting.")
        return

    if args.export_json:
        exporter.to_json(valid_leads)
    if args.export_csv:
        exporter.to_csv(valid_leads)
    if args.export_text:
        exporter.to_text(valid_leads)

    if not any([args.export_json, args.export_csv, args.export_text]):
        exporter.to_json(valid_leads)
        exporter.to_csv(valid_leads)
        exporter.to_text(valid_leads)

    logger.info("Pipeline complete. Valid leads: %d", len(valid_leads))
    print(f"Pipeline complete. Valid leads: {len(valid_leads)}")


if __name__ == "__main__":
    main()
