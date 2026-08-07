import unittest

from src.scraper import Scraper


class ScraperUrlFilteringTests(unittest.TestCase):
    def setUp(self):
        self.scraper = Scraper(headless=True, max_leads=1, concurrency=1)

    def test_accepts_single_segment_company_profile_url(self):
        url = "https://www.affpaying.com/mybid"
        self.assertTrue(self.scraper._is_company_card_url(url, "Affpaying"))

    def test_rejects_search_and_pagination_urls(self):
        for url in [
            "https://www.affpaying.com/search?q=Gambling&page=3",
            "https://www.affpaying.com/search?sort=popularity",
            "https://www.affpaying.com/?page=2",
        ]:
            with self.subTest(url=url):
                self.assertFalse(self.scraper._is_company_card_url(url, "Affpaying"))


if __name__ == "__main__":
    unittest.main()
