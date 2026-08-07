"""Export raw scraped company cards without validation to src/output/raw_leads.json/csv/txt
"""
import os
import time
import json
import logging
import sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.scraper import Scraper
from src.exporter import Exporter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('export_raw')

def main():
    scraper = Scraper(headless=True, max_leads=50, concurrency=None)
    start = time.monotonic()
    raw = scraper.scrape_source()
    duration = time.monotonic() - start
    logger.info('Scraped %d raw company cards in %.1fs', len(raw), duration)

    exporter = Exporter()
    os.makedirs('src/output', exist_ok=True)
    exporter.to_json(raw, filename='raw_leads.json')
    exporter.to_csv(raw, filename='raw_leads.csv')
    exporter.to_text(raw, filename='raw_leads.txt')
    logger.info('Exported raw leads to src/output/')

if __name__ == '__main__':
    main()
