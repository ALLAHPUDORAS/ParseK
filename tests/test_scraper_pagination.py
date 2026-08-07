import unittest

from src.scraper import Scraper


class FakeElement:
    def __init__(self, href=None, text=""):
        self._href = href
        self._text = text

    def get_attribute(self, name):
        if name == "href":
            return self._href
        if name == "data-href":
            return None
        return None

    def text_content(self):
        return self._text

    def evaluate(self, expression):
        if "closest('a'" in expression:
            return "/next-page"
        return None


class FakePage:
    def __init__(self, element):
        self._element = element

    def query_selector(self, selector):
        return self._element


class FakeButton:
    def __init__(self, text, href=None):
        self._text = text
        self._href = href

    def get_attribute(self, name):
        return self._href if name == "href" else None

    def text_content(self):
        return self._text

    def evaluate(self, expression):
        return None


class FakePageWithButtons:
    def __init__(self, elements):
        self._elements = elements

    def query_selector(self, selector):
        return self._elements[0]

    def query_selector_all(self, selector):
        return self._elements


class ScraperPaginationTests(unittest.TestCase):
    def test_find_next_page_returns_href_from_closest_anchor_when_text_is_next(self):
        scraper = Scraper(headless=True, max_leads=10)
        page = FakePage(FakeElement(href=None, text="Next"))

        next_url = scraper._find_next_page(page, ["a.next"])

        self.assertEqual(next_url, "/next-page")

    def test_find_next_page_falls_back_to_anchor_with_next_text(self):
        scraper = Scraper(headless=True, max_leads=10)
        page = FakePageWithButtons([
            FakeButton("Next", href=None),
            FakeButton("Next", href="/next-page")
        ])

        next_url = scraper._find_next_page(page, ["a.next"])

        self.assertEqual(next_url, "/next-page")

    def test_build_next_page_url_increments_page_param(self):
        scraper = Scraper(headless=True, max_leads=10)

        self.assertEqual(
            scraper._build_next_page_url("https://example.com/networks?page=3"),
            "https://example.com/networks?page=4"
        )

    def test_build_next_page_url_defaults_to_page_2(self):
        scraper = Scraper(headless=True, max_leads=10)

        self.assertEqual(
            scraper._build_next_page_url("https://example.com/networks"),
            "https://example.com/networks?page=2"
        )


if __name__ == "__main__":
    unittest.main()
