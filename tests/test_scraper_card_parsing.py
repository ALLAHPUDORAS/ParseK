import unittest
from bs4 import BeautifulSoup

from src.scraper import Scraper


class TestCardParsing(unittest.TestCase):
    def setUp(self):
        self.scraper = Scraper()

    def test_extract_company_name_from_h1(self):
        html = '<html><body><h1>Test Company</h1></body></html>'
        soup = BeautifulSoup(html, 'html.parser')
        self.assertEqual(self.scraper._extract_company_name(soup), 'Test Company')

    def test_extract_company_name_from_meta_title(self):
        html = '<html><head><meta property="og:title" content="Meta Company"></head><body></body></html>'
        soup = BeautifulSoup(html, 'html.parser')
        self.assertEqual(self.scraper._extract_company_name(soup), 'Meta Company')

    def test_extract_company_website_prefers_text_anchor(self):
        html = '<html><body><a href="https://example.com">Visit website</a><a href="https://example.com/company">Company site</a></body></html>'
        soup = BeautifulSoup(html, 'html.parser')
        self.assertEqual(self.scraper._extract_company_website(soup), 'https://example.com/company')

    def test_extract_company_geo_from_text(self):
        visible_text = 'Based in Europe and servicing global clients.'
        self.assertEqual(self.scraper._extract_company_geo(visible_text), 'Europe')

    def test_extract_company_status_from_text(self):
        html = '<html><body><p>Status: Closed</p></body></html>'
        soup = BeautifulSoup(html, 'html.parser')
        self.assertEqual(self.scraper._extract_company_status(soup, self.scraper._clean_visible_text(html)), 'Status: Closed')


class TestContactExtraction(unittest.TestCase):
    def setUp(self):
        self.scraper = Scraper()

    def test_extract_contacts_from_network_payload(self):
        payload = {
            "contacts": [
                {"type": "telegram", "value": "@affguru"},
                {"type": "email", "value": "ops@example.com"},
                {"type": "skype", "value": "live:demo-user"},
            ]
        }
        contacts = self.scraper._extract_contacts_from_payload(payload)
        self.assertEqual(contacts["telegram"], ["@affguru"])
        self.assertEqual(contacts["emails"], ["ops@example.com"])
        self.assertEqual(contacts["skype"], ["demo-user"])


class TestUrlFiltering(unittest.TestCase):
    def setUp(self):
        self.scraper = Scraper()

    def test_affpaying_card_url_pattern(self):
        self.assertTrue(self.scraper._is_company_card_url('https://www.affpaying.com/network/example', 'Affpaying'))
        self.assertFalse(self.scraper._is_company_card_url('https://www.affpaying.com/add-network', 'Affpaying'))

    def test_offervault_card_url_pattern(self):
        self.assertTrue(self.scraper._is_company_card_url('https://www.offervault.com/affiliate-networks/example', 'Offervault'))
        self.assertFalse(self.scraper._is_company_card_url('https://www.offervault.com/affiliate-networks', 'Offervault'))

    def test_affplus_card_url_pattern(self):
        self.assertTrue(self.scraper._is_company_card_url('https://www.affplus.com/n/example', 'Affplus'))
        self.assertFalse(self.scraper._is_company_card_url('https://www.affplus.com/offers', 'Affplus'))

    def test_affplus_offer_page_detection(self):
        self.assertTrue(self.scraper._is_affplus_offer_page('https://www.affplus.com/o/granniestomeet-soi-cpa-mobile-us'))
        self.assertTrue(self.scraper._is_affplus_offer_page('https://www.affplus.com/offer/test-offer'))
        self.assertFalse(self.scraper._is_affplus_offer_page('https://www.affplus.com/n/adsempire'))
        self.assertFalse(self.scraper._is_affplus_offer_page('https://www.affplus.com/offers'))

    def test_extract_affplus_network_url_from_html(self):
        html = '<html><body><a href="/n/adsempire">Affiliate Network</a><a href="/o/test-offer">Offer</a></body></html>'
        network_url = self.scraper._find_affplus_network_url(None, html, 'https://www.affplus.com')
        self.assertEqual(network_url, 'https://www.affplus.com/n/adsempire')


if __name__ == '__main__':
    unittest.main()
