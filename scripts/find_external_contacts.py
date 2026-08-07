"""For each lead in src/output/enriched_leads.json, find external links and look for emails/contact pages.
Saves to src/output/contacts_found.json
"""
import os
import sys
import json
import time
import re
from urllib.parse import urlparse
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from playwright.sync_api import sync_playwright

INPUT = 'src/output/enriched_leads.json'
OUT = 'src/output/contacts_found.json'

EMAIL_RE = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')


def is_external(href, base_netloc):
    try:
        p = urlparse(href)
        if not p.scheme.startswith('http'):
            return False
        return base_netloc not in p.netloc
    except Exception:
        return False


def main():
    if not os.path.exists(INPUT):
        print('Input not found:', INPUT)
        return
    with open(INPUT, 'r', encoding='utf-8') as fh:
        leads = json.load(fh)

    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox','--disable-dev-shm-usage'])
        context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(15000)

        for lead in leads:
            url = lead.get('url')
            print('Checking', url)
            found = {'url': url, 'external_links': [], 'emails': []}
            try:
                page.goto(url)
                page.wait_for_load_state('domcontentloaded')
                html = page.content()
                # find hrefs
                hrefs = set(re.findall(r'href=["\']([^"\']+)["\']', html))
                base_netloc = urlparse(url).netloc
                externals = []
                for h in hrefs:
                    if h.startswith('#') or h.startswith('mailto:'):
                        continue
                    if h.startswith('http') and is_external(h, base_netloc):
                        externals.append(h)
                found['external_links'] = externals[:10]

                # Check each external for emails/contact
                emails = set()
                for ext in externals[:6]:
                    try:
                        page.goto(ext)
                        page.wait_for_load_state('domcontentloaded')
                        h2 = page.content()
                        for m in EMAIL_RE.findall(h2):
                            emails.add(m)
                        # look for contact page link
                        contact_links = re.findall(r'href=["\']([^"\']*contact[^"\']*)["\']', h2, flags=re.IGNORECASE)
                        for cl in contact_links:
                            if cl.startswith('http'):
                                page.goto(cl)
                            else:
                                page.goto(urlparse(ext)._replace(path=cl).geturl())
                            page.wait_for_load_state('domcontentloaded')
                            h3 = page.content()
                            for m in EMAIL_RE.findall(h3):
                                emails.add(m)
                    except Exception:
                        continue

                # also search original page for mailtos
                for m in re.findall(r'mailto:([A-Za-z0-9_.+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9-.]+)', html):
                    emails.add(m)

                found['emails'] = list(emails)
            except Exception as e:
                print('Error visiting', url, e)
            results.append(found)
            time.sleep(0.7)

        browser.close()

    with open(OUT, 'w', encoding='utf-8') as fh:
        json.dump(results, fh, indent=2)
    print('Done, written', OUT)

if __name__ == '__main__':
    main()
