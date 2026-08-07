"""Build clean CSV of emails found from src/output/contacts_found.json
"""
import os
import sys
import json
import csv
import html
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

IN = 'src/output/contacts_found.json'
OUT = 'src/output/clean_contacts.csv'

if not os.path.exists(IN):
    print('No contacts file found:', IN)
    sys.exit(1)

with open(IN, 'r', encoding='utf-8') as fh:
    data = json.load(fh)

rows = []
for item in data:
    url = item.get('url')
    externals = item.get('external_links', [])
    emails = item.get('emails', [])
    for e in emails:
        best_external = html.unescape(externals[0]) if externals else ''
        rows.append((url, e, best_external))

os.makedirs('src/output', exist_ok=True)
with open(OUT, 'w', newline='', encoding='utf-8') as fh:
    writer = csv.writer(fh, delimiter=';', quoting=csv.QUOTE_MINIMAL)
    writer.writerow(['lead_url', 'email', 'best_external_link'])
    for r in rows:
        writer.writerow(r)

print('Wrote', OUT)
