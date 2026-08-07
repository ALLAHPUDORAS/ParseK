"""Enrich raw leads by visiting each company url and extracting contacts/website.
Saves results to src/output/enriched_leads.*
"""
import os
import sys
import json
import time
import logging
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.scraper import Scraper
from src.exporter import Exporter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('enrich')


def main():
    path = 'src/output/raw_leads.json'
    if not os.path.exists(path):
        logger.error('raw_leads.json not found at %s', path)
        return

    with open(path, 'r', encoding='utf-8') as fh:
        raw = json.load(fh)

    scraper = Scraper(headless=True, max_leads=1, concurrency=1)
    enriched = []
    for idx, lead in enumerate(raw, 1):
        url = lead.get('url')
        logger.info('(%d/%d) Enriching %s', idx, len(raw), url)
        try:
            # scrape company page directly
            parsed = scraper.scrape_company_page(None, url)
            if parsed:
                # merge parsed contacts and website into lead
                lead['website'] = parsed.get('website') or lead.get('website')
                lead['raw_contacts'] = parsed.get('raw_contacts') or lead.get('raw_contacts')
        except Exception:
            logger.exception('Failed to enrich %s', url)
        enriched.append(lead)
        time.sleep(0.5)

    exporter = Exporter()
    exporter.to_json(enriched, filename='enriched_leads.json')
    exporter.to_csv(enriched, filename='enriched_leads.csv')
    exporter.to_text(enriched, filename='enriched_leads.txt')
    logger.info('Enrichment finished, files written to src/output/')

if __name__ == '__main__':
    main()
