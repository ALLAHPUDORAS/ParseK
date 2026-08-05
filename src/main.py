import argparse
import logging
import os
import sys
from typing import List, Dict, Any
import json
import signal
import threading
import time

from src.config import LOGS_DIR, OUTPUT_DIR, DEFAULT_MAX_LEADS
from src.exporter import Exporter
from src.scraper import Scraper
from src.validator import LeadValidator

LOG_FILE = os.path.join(LOGS_DIR, "pipeline.log")
VALIDATION_SUMMARY = os.path.join(LOGS_DIR, "validation_summary.json")

# Graceful shutdown flag
SHUTDOWN_EVENT = threading.Event()


def configure_logging():
    os.makedirs(LOGS_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        root_logger.setLevel(logging.INFO)

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

        # Rotating file handler to limit disk usage
        from logging.handlers import RotatingFileHandler
        file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)


def validate_leads(raw_leads: List[Dict[str, Any]]) -> tuple:
    validator = LeadValidator()
    valid_leads: List[Dict[str, Any]] = []
    logger = logging.getLogger("LeadPipeline.Main")
    stats = {
        "total_processed": 0,
        "valid_count": 0,
        "rejected_count": 0,
        "by_reason": {},
    }
    sample_rejections: List[Dict[str, Any]] = []

    for raw in raw_leads:
        stats["total_processed"] += 1
        is_valid, reason, processed = validator.validate_lead(raw)
        if is_valid and processed:
            stats["valid_count"] += 1
            logger.info("Valid lead: %s", processed.get("name"))
            valid_leads.append(processed)
        else:
            stats["rejected_count"] += 1
            reason_key = reason or "REJECTED: Unknown"
            stats["by_reason"][reason_key] = stats["by_reason"].get(reason_key, 0) + 1
            if len(sample_rejections) < 15:
                sample_rejections.append({
                    "name": raw.get("name"),
                    "reason": reason_key,
                    "raw_contacts": raw.get("raw_contacts", {}),
                })
            logger.info("Lead filtered out: %s | Reason: %s", raw.get("name", "Unknown"), reason)

    logger.info(
        "Validation summary: total=%d valid=%d rejected=%d",
        stats["total_processed"],
        stats["valid_count"],
        stats["rejected_count"],
    )
    for reason, cnt in stats["by_reason"].items():
        logger.info(" - %s: %d", reason, cnt)

    if sample_rejections:
        logger.debug("Sample rejections (up to 15): %s", sample_rejections)

    return valid_leads, stats, sample_rejections


def parse_args():
    parser = argparse.ArgumentParser(description="B2B Lead Scraping Pipeline for Gambling/Nutra/Crypto verticals")
    parser.add_argument("--headless", action="store_true", help="Run Playwright in headless browser mode")
    parser.add_argument("--max-leads", type=int, default=DEFAULT_MAX_LEADS, help="Maximum number of company cards to process")
    parser.add_argument("--export-json", action="store_true", help="Export valid leads to JSON")
    parser.add_argument("--export-csv", action="store_true", help="Export valid leads to CSV")
    parser.add_argument("--export-text", action="store_true", help="Export valid leads to plain text list")
    return parser.parse_args()


def run_pipeline(args):
    logger = logging.getLogger("LeadPipeline.Main")
    logger.info("Starting lead scraping pipeline cycle")
    logger.info("Headless mode: %s", args.headless)
    logger.info("Max leads: %s", args.max_leads)

    scraper = Scraper(headless=args.headless, max_leads=args.max_leads)
    exporter = Exporter()

    raw_leads = scraper.scrape_source()
    if SHUTDOWN_EVENT.is_set():
        return
        
    valid_leads, stats, sample_rejections = validate_leads(raw_leads)

    # Write validation summary to JSON for persistent metrics
    try:
        with open(VALIDATION_SUMMARY, "w", encoding="utf-8") as fh:
            json.dump({
                "total_processed": stats["total_processed"],
                "valid_count": stats["valid_count"],
                "rejected_count": stats["rejected_count"],
                "by_reason": stats["by_reason"],
                "sample_rejections": sample_rejections,
            }, fh, ensure_ascii=False, indent=2)
        logger.info("Validation summary written: %s", VALIDATION_SUMMARY)
    except Exception as e:
        logger.exception("Failed to write validation summary: %s", e)

    if not valid_leads:
        logger.error("No valid leads were produced after validation in this cycle.")
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

    logger.info("Pipeline cycle complete. Valid leads: %d", len(valid_leads))
    print(f"Pipeline cycle complete. Valid leads: {len(valid_leads)}")


def main():
    configure_logging()
    logger = logging.getLogger("LeadPipeline.Main")
    args = parse_args()

    # signal handlers for graceful shutdown
    def _handle_signal(signum, frame):
        logger.info("Signal %s received, requesting graceful shutdown...", signum)
        SHUTDOWN_EVENT.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    DELAY_HOURS = 4  # Пауза между бесконечными кругами сканирования (в часах)

    while not SHUTDOWN_EVENT.is_set():
        try:
            run_pipeline(args)
        except Exception as exc:
            logger.exception("Fatal error during pipeline cycle run: %s", exc)

        if SHUTDOWN_EVENT.is_set():
            break

        logger.info(f"Cycle finished. Waiting for {DELAY_HOURS} hours before the next scraping run...")
        
        # Ожидание с возможностью прерывания по сигналу
        for _ in range(DELAY_HOURS * 360):
            if SHUTDOWN_EVENT.is_set():
                break
            time.sleep(10)

    logger.info("Pipeline shut down gracefully.")


if __name__ == "__main__":
    main()