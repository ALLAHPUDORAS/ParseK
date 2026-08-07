import argparse
import logging
import os
import sys
from typing import List, Dict, Any, Optional, Set
import json
from urllib.parse import urljoin
import signal
import threading
import time

from src.config import LOGS_DIR, OUTPUT_DIR, DEFAULT_EXPORT_JSON, DEFAULT_MAX_LEADS, DEFAULT_POLL_INTERVAL, PAGE_LOAD_TIMEOUT, SITE_CONFIGS
from src.exporter import Exporter
from src.scraper import Scraper
from src.validator import LeadValidator
from playwright.sync_api import sync_playwright
import socket
from http.server import HTTPServer, BaseHTTPRequestHandler
try:
    from prometheus_client import start_http_server, Summary, Counter
    PROM_AVAILABLE = True
except Exception:
    PROM_AVAILABLE = False

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


def _load_cached_leads(output_dir: str) -> List[Dict[str, Any]]:
    cached_file = os.path.join(output_dir, DEFAULT_EXPORT_JSON)
    logger = logging.getLogger("LeadPipeline.Main")
    if not os.path.exists(cached_file):
        return []
    try:
        with open(cached_file, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
        logger.warning("Cached leads file %s has unexpected format; ignoring legacy cache.", cached_file)
    except Exception as exc:
        logger.exception("Failed to load cached leads from %s: %s", cached_file, exc)
    return []


def _purge_output_files(exporter: Exporter) -> None:
    for filename in [DEFAULT_EXPORT_JSON, "leads.csv", "leads_formatted.xlsx", "leads_report.html"]:
        path = os.path.join(exporter.output_dir, filename)
        try:
            if os.path.exists(path):
                os.remove(path)
                logging.getLogger("LeadPipeline.Main").info("Removed stale output file: %s", path)
        except Exception as exc:
            logging.getLogger("LeadPipeline.Main").exception("Failed to remove stale output file %s: %s", path, exc)


def validate_leads(raw_leads: List[Dict[str, Any]], exporter: Exporter | None = None) -> tuple:
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
        is_valid, reason, processed = validator.is_lead_allowed(raw)
        if is_valid and processed:
            stats["valid_count"] += 1
            logger.info("Valid lead: %s", processed.get("name"))
            logger.info(
                "[INFO] Extracted contacts: TG=%d (valid), Email=%d, Discord=%d, LinkedIn=%d, X=%d",
                len(processed.get("contacts", {}).get("telegram", [])),
                len(processed.get("contacts", {}).get("emails", [])),
                len(processed.get("contacts", {}).get("discord", [])),
                len(processed.get("contacts", {}).get("linkedin", [])),
                len(processed.get("contacts", {}).get("twitter_x", [])),
            )
            valid_leads.append(processed)
            if exporter and len(valid_leads) % 5 == 0:
                exporter.save_leads(valid_leads)
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
            logger.warning("[DROPPED] Lead '%s' -> Reason: %s", raw.get("name", "Unknown"), reason)
            print(f"[DROPPED] Lead '{raw.get('name', 'Unknown')}' -> Reason: {reason}")

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
    parser.add_argument("--one-shot", action="store_true", help="Run pipeline once and exit")
    return parser.parse_args()


def _build_listing_url(config: Dict[str, Any], vertical: str, path: str) -> str:
    search_template = config.get("search_page_template")
    if search_template:
        return urljoin(config["base_url"], search_template.format(vertical=vertical, page=1))
    return urljoin(config["base_url"], path)


def run_catalog_pipeline(scraper: Scraper, headless: bool, max_leads: int) -> List[Dict[str, Any]]:
    logger = logging.getLogger("LeadPipeline.Main")
    raw_leads: List[Dict[str, Any]] = []
    collected_urls: Set[str] = set()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(user_agent="Mozilla/5.0", locale="en-US", accept_downloads=False)
        page = context.new_page()
        page.set_default_timeout(PAGE_LOAD_TIMEOUT)

        logger.info("Phase 1: harvesting candidate company URLs from catalog/listing pages")
        for source_name, config in SITE_CONFIGS.items():
            if len(collected_urls) >= max_leads:
                break

            for vertical, path in config.get("categories", {}).items():
                if len(collected_urls) >= max_leads:
                    break

                listing_url = _build_listing_url(config, vertical, path)
                logger.info("Opening catalog listing: %s", listing_url)
                try:
                    page.goto(listing_url, timeout=PAGE_LOAD_TIMEOUT)
                    page.wait_for_load_state("domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
                    page.wait_for_timeout(2500)

                    cards = scraper.extract_catalog_cards(page)
                    logger.info("Found %d candidate cards on %s", len(cards), listing_url)
                    for card in cards:
                        detail_url = card.get("url")
                        if not detail_url:
                            continue
                        if scraper._is_company_card_url(detail_url, source_name):
                            collected_urls.add(detail_url)
                            logger.info("Accepted company profile URL: %s", detail_url)
                except Exception as exc:
                    logger.exception("Failed to process listing %s: %s", listing_url, exc)

        logger.info("Phase 1 complete. Collected %d unique company profile URLs", len(collected_urls))

        logger.info("Phase 2: deep scraping individual company profile pages")
        for index, detail_url in enumerate(sorted(collected_urls), start=1):
            if len(raw_leads) >= max_leads:
                break
            logger.info("Scraping company profile: %s", detail_url)
            try:
                lead = scraper.scrape_company_page(page, detail_url)
                if lead:
                    raw_leads.append(lead)
            except Exception as exc:
                logger.exception("Failed to scrape detail page %s: %s", detail_url, exc)

        context.close()
        browser.close()

# All raw leads are collected and returned for strict validation downstream.

    return raw_leads


def run_pipeline(args):
    logger = logging.getLogger("LeadPipeline.Main")
    logger.info("Starting lead scraping pipeline cycle")
    logger.info("Headless mode: %s", args.headless)
    logger.info("Max leads: %s", args.max_leads)

    scraper = Scraper(headless=args.headless, max_leads=args.max_leads, concurrency=1)
    exporter = Exporter()
    logger.info("Resolved output directory for this pipeline run: %s", exporter.output_dir)
    print(f"Output directory: {exporter.output_dir}")

    legacy_leads = _load_cached_leads(exporter.output_dir)
    if legacy_leads:
        logger.info("Revalidating %d cached legacy leads from %s", len(legacy_leads), os.path.join(exporter.output_dir, DEFAULT_EXPORT_JSON))

    exporter.purge_previous_exports()

    start_time = time.monotonic()
    raw_leads = run_catalog_pipeline(scraper, headless=args.headless, max_leads=args.max_leads)
    if not raw_leads:
        logger.info("Catalog pipeline returned no leads, falling back to legacy scrape_source flow")
        raw_leads = scraper.scrape_source()

    if legacy_leads:
        raw_leads.extend(legacy_leads)

    if SHUTDOWN_EVENT.is_set():
        return

    if raw_leads:
        exporter.save_raw_leads(raw_leads)

    valid_leads, stats, sample_rejections = validate_leads(raw_leads, exporter=exporter)

    # Write validation summary to JSON for persistent metrics
    try:
        with open(VALIDATION_SUMMARY, "w", encoding="utf-8") as fh:
            json.dump({
                "total_processed": stats["total_processed"],
                "valid_count": stats["valid_count"],
                "rejected_count": stats["rejected_count"],
                "by_reason": stats["by_reason"],
                "sample_rejections": sample_rejections,
                "scraper_metrics": {
                    "scraped_pages": getattr(scraper, "scraped_pages", 0),
                    "failed_pages": getattr(scraper, "failed_pages", 0),
                    "skipped_urls": getattr(scraper, "skipped_urls", 0),
                },
                "time_spent_seconds": round(time.monotonic() - start_time, 2),
            }, fh, ensure_ascii=False, indent=2)
        logger.info("Validation summary written: %s", VALIDATION_SUMMARY)
    except Exception as e:
        logger.exception("Failed to write validation summary: %s", e)

    if not valid_leads:
        logger.warning("No valid leads were produced after validation in this cycle.")
        exporter.save_empty_export()
        return

    if args.export_json or args.export_csv or not any([args.export_json, args.export_csv, args.export_text]):
        exporter.save_leads(valid_leads)
    if args.export_text:
        exporter.to_text(valid_leads)

    logger.info("Pipeline cycle complete. Valid leads: %d", len(valid_leads))
    print(f"Pipeline cycle complete. Valid leads: {len(valid_leads)}")


def main():
    configure_logging()
    logger = logging.getLogger("LeadPipeline.Main")
    # start lightweight HTTP endpoints for health and metrics
    def _start_health_server():
        class _HealthHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/health":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(b'{"status":"ok"}')
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, format, *args):
                return

        try:
            server = HTTPServer(("0.0.0.0", 8000), _HealthHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            logger.info("Health server listening on :8000/health")
        except Exception:
            logger.exception("Failed to start health server on :8000")

    _start_health_server()

    if PROM_AVAILABLE:
        try:
            start_http_server(8001)
            logger.info("Prometheus metrics available on :8001/metrics")
        except Exception:
            logger.exception("Failed to start Prometheus metrics server")
    args = parse_args()

    # signal handlers for graceful shutdown
    def _handle_signal(signum, frame):
        logger.info("Signal %s received, requesting graceful shutdown...", signum)
        SHUTDOWN_EVENT.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    is_one_shot = args.one_shot or os.getenv("ONE_SHOT") == "1"

    if is_one_shot:
        logger.info("One-shot mode enabled. Running single pipeline cycle...")
        try:
            run_pipeline(args)
        except Exception as exc:
            logger.exception("Fatal error during pipeline run: %s", exc)
            sys.exit(1)
        return

    poll_interval_env = os.getenv("POLL_INTERVAL")
    if poll_interval_env and poll_interval_env.isdigit():
        delay_seconds = int(poll_interval_env)
    else:
        delay_seconds = DEFAULT_POLL_INTERVAL

    while not SHUTDOWN_EVENT.is_set():
        try:
            run_pipeline(args)
        except Exception as exc:
            logger.exception("Fatal error during pipeline cycle run: %s", exc)

        if SHUTDOWN_EVENT.is_set():
            break

        logger.info("Cycle finished. Waiting for %d seconds before the next scraping run...", delay_seconds)
        
        # Ожидание с возможностью прерывания по сигналу
        for _ in range(max(1, delay_seconds // 10)):
            if SHUTDOWN_EVENT.is_set():
                break
            time.sleep(10)

    logger.info("Pipeline shut down gracefully.")


if __name__ == "__main__":
    main()