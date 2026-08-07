import unittest

from src.scraper import Scraper


class FakeElement:
    def __init__(self, attributes=None, text="", click_callback=None, hover_callback=None):
        self.attributes = attributes or {}
        self._text = text
        self._click_callback = click_callback
        self._hover_callback = hover_callback

    def get_attribute(self, name):
        return self.attributes.get(name)

    def text_content(self):
        return self._text

    def evaluate(self, expression):
        return None

    def click(self):
        if self._click_callback:
            self._click_callback()

    def hover(self):
        if self._hover_callback:
            self._hover_callback()


class FakePage:
    def __init__(self, elements):
        self._elements = elements
        self._height = 1000

    def query_selector(self, selector):
        return self._elements[0] if self._elements else None

    def query_selector_all(self, selector):
        return self._elements

    def wait_for_selector(self, selector, timeout=None):
        return None

    def evaluate(self, script):
        if "document.body.scrollHeight" in script:
            return self._height
        if "window.scrollTo" in script:
            return None
        return None


class ScraperDataUrlTests(unittest.TestCase):
    def test_extract_url_from_data_href(self):
        scraper = Scraper(headless=True, max_leads=10)
        elem = FakeElement(attributes={"data-href": "/network/example"})
        url = scraper._extract_url_from_element(elem, "https://www.affpaying.com")
        self.assertEqual(url, "https://www.affpaying.com/network/example")

    def test_extract_url_from_data_url(self):
        scraper = Scraper(headless=True, max_leads=10)
        elem = FakeElement(attributes={"data-url": "https://example.com/network/test"})
        url = scraper._extract_url_from_element(elem, "https://www.affpaying.com")
        self.assertEqual(url, "https://example.com/network/test")

    def test_extract_url_from_onclick_location(self):
        scraper = Scraper(headless=True, max_leads=10)
        elem = FakeElement(attributes={"onclick": "location.href='https://example.com/company/abc'"})
        url = scraper._extract_url_from_element(elem, "https://www.affpaying.com")
        self.assertEqual(url, "https://example.com/company/abc")

    def test_find_company_links_includes_data_href_element(self):
        scraper = Scraper(headless=True, max_leads=10)
        elem = FakeElement(attributes={"data-href": "/network/example"})
        page = FakePage([elem])
        links = scraper._find_company_links(page, "https://www.affpaying.com", "Affpaying")
        self.assertEqual(links, {"https://www.affpaying.com/network/example"})

    def test_find_dynamic_company_links_via_click_reveals_card_url(self):
        page = FakePage([])

        def reveal_card():
            page._elements.append(FakeElement(attributes={"data-href": "/network/dynamic"}))

        trigger = FakeElement(attributes={"role": "button", "class": "offer-card"}, click_callback=reveal_card)
        page._elements.append(trigger)

        scraper = Scraper(headless=True, max_leads=10)
        links = scraper._find_company_links(page, "https://www.affpaying.com", "Affpaying")

        self.assertEqual(links, {"https://www.affpaying.com/network/dynamic"})


if __name__ == "__main__":
    unittest.main()
