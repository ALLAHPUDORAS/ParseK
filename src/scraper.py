import logging
import re
import time
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Comment
from playwright.sync_api import Playwright, sync_playwright, TimeoutError as PlaywrightTimeoutError

from src.config import PAGE_LOAD_TIMEOUT, SITE_CONFIGS, USER_AGENT, DEFAULT_MAX_LEADS
from src.validator import LeadValidator

logger = logging.getLogger("LeadPipeline.Scraper")

class Scraper:
    def __init__(self, headless: bool = True, max_leads: int = DEFAULT_MAX_LEADS):
        self.headless = headless
        self.max_leads = max_leads
        self.visited_urls: Set[str] = set()
        self.company_urls: Set[str] = set()

    def _get_browser_context(self, playwright: Playwright):
        return playwright.chromium.launch(headless=self.headless, args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
        ])

    def _normalize_url(self, base: str, href: str) -> Optional[str]:
        if not href:
            return None

        href = href.strip()
        if href.startswith("javascript:") or href.startswith("#"):
            return None

        parsed = urlparse(href)
        if not parsed.netloc:
            href = urljoin(base, href)

        return href

    def _is_company_card_url(self, url: str, site_name: str) -> bool:
        if not url or url in self.company_urls:
            return False
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        if site_name == "Affpaying" and "/network" in parsed.path:
            return True
        if site_name == "Offervault" and ("affiliate-networks" in parsed.path or "network" in parsed.path):
            return True
        if site_name == "Affplus" and ("offer" in parsed.path or "network" in parsed.path or "affiliate" in parsed.path):
            return True
        return False

    def _find_company_links(self, page, base_url: str, site_name: str) -> Set[str]:
        links = set()
        try:
            anchors = page.query_selector_all("a")
        except Exception as exc:
            logger.warning("Unable to query anchor tags: %s", exc)
            return links

        for anchor in anchors:
            try:
                href = anchor.get_attribute("href")
                normalized = self._normalize_url(base_url, href)
                if normalized and self._is_company_card_url(normalized, site_name):
                    links.add(normalized)
            except Exception:
                continue

        return links

    def _find_next_page(self, page, pagination_patterns: List[str]) -> Optional[str]:
        for selector in pagination_patterns:
            try:
                element = page.query_selector(selector)
                if element:
                    href = element.get_attribute("href")
                    if href:
                        return href
                    # fallback: click button style links with text
                    text = element.text_content() or ""
                    if "next" in text.lower():
                        return href
            except Exception:
                continue
        return None

    def _clean_visible_text(self, content: str) -> str:
        soup = BeautifulSoup(content, "html.parser")
        for element in soup(["script", "style", "noscript"]):
            element.decompose()
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()
        return soup.get_text(" ", strip=True)

    def _is_valid_telegram_handle(self, handle: str) -> bool:
        handle_lower = handle.lower().lstrip("@")
        invalid_handles = {
            "media", "supports", "keyframes", "font-face",
            "charset", "document", "pageview", "viewport",
            "import", "function", "return", "window", "script",
            "body", "html", "head", "link", "meta", "style",
            "affplus", "offervault", "affpaying"
        }
        if handle_lower in invalid_handles:
            return False
        return bool(re.match(r"^[A-Za-z0-9_]{5,32}$", handle_lower))

    def _extract_contacts_from_html(self, content: str) -> Dict[str, Any]:
        contacts = {
            "emails": [],
            "telegram": [],
            "skype": [],
            "discord": []
        }

        visible_text = self._clean_visible_text(content)
        soup = BeautifulSoup(content, "html.parser")
        hrefs = [a.get("href", "") for a in soup.find_all("a", href=True)]
        combined_text = " ".join([visible_text, *hrefs])

        for email in re.findall(r"[A-Za-z0-9_.+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9-.]+", combined_text):
            contacts["emails"].append(email.strip())

        for match in re.findall(r"(?:t\.me/|telegram\.me/)([A-Za-z0-9_]{5,32})", combined_text, flags=re.IGNORECASE):
            normalized = match.strip()
            if self._is_valid_telegram_handle(normalized):
                contacts["telegram"].append(f"@{normalized}")

        for match in re.findall(r"@([A-Za-z0-9_]{5,32})", combined_text):
            if self._is_valid_telegram_handle(match):
                contacts["telegram"].append(f"@{match}")

        for match in re.findall(r"(?:skype:|live:)([A-Za-z0-9_.:-]+)", combined_text, flags=re.IGNORECASE):
            contacts["skype"].append(match.strip())

        for match in re.findall(r"discord(?:\.gg|\.com/invite|app\.com/users)?/([A-Za-z0-9_#.-]+)", combined_text, flags=re.IGNORECASE):
            contacts["discord"].append(match.strip())

        for key in contacts:
            contacts[key] = list(dict.fromkeys(contacts[key]))

        return contacts

    def _safe_text(self, element) -> str:
        try:
            return (element.text_content() or "").strip()
        except Exception:
            return ""

    def _parse_company_card(self, page_content: str, page_url: str, source: str, vertical: str) -> Dict[str, Any]:
        soup = BeautifulSoup(page_content, "html.parser")
        name = ""
        website = ""
        geo = ""
        status = ""
        raw_contacts: Dict[str, Any] = {}

        if soup.select_one("h1"):
            name = soup.select_one("h1").get_text(strip=True)

        if not name and soup.title:
            name = soup.title.get_text(strip=True)

        website_tag = soup.select_one("a[href*='http']")
        if website_tag and website_tag.get_text(strip=True).lower() not in {"visit website", "website"}:
            website = website_tag.get_text(strip=True)
        else:
            website_attr = website_tag.get("href") if website_tag else None
            if website_attr and website_attr.startswith("http"):
                website = website_attr

        visible_text = self._clean_visible_text(page_content)
        geo_candidates = re.findall(r"\b(EU|Europe|LATAM|Asia|Russia|Belarus|CIS|USA|UK|Canada)\b", visible_text, re.IGNORECASE)
        if geo_candidates:
            geo = geo_candidates[0].strip()

        labels = [x.get_text(strip=True) for x in soup.select("*") if x.name in {"span", "div", "p", "li", "strong", "b"}]
        for label in labels:
            if "status" in label.lower() and any(token in label.upper() for token in ["CLOSED", "BLACKLISTED", "INACTIVE"]):
                status = label
                break

        raw_contacts = self._extract_contacts_from_html(page_content)

        return {
            "name": name,
            "vertical": vertical,
            "geo": geo,
            "website": website,
            "status": status,
            "raw_contacts": raw_contacts,
            "source": source,
            "url": page_url
        }

    def _scrape_pagination(self, page, base_url: str, site_name: str, pagination_patterns: List[str]) -> Set[str]:
        urls = set()
        current_url = page.url
        visited_pages = {current_url}

        while True:
            logger.info("Scraping listing page %s", current_url)
            urls.update(self._find_company_links(page, base_url, site_name))
            if len(self.company_urls) + len(urls) >= self.max_leads:
                break

            next_href = self._find_next_page(page, pagination_patterns)
            if not next_href:
                break

            next_url = self._normalize_url(base_url, next_href)
            if not next_url or next_url in visited_pages:
                break

            visited_pages.add(next_url)
            try:
                page.goto(next_url, timeout=PAGE_LOAD_TIMEOUT)
                page.wait_for_load_state("networkidle", timeout=PAGE_LOAD_TIMEOUT)
                time.sleep(1)
                current_url = next_url
            except PlaywrightTimeoutError:
                logger.warning("Timeout while loading next listing page %s", next_url)
                break
            except Exception as exc:
                logger.warning("Failed to open next listing page %s: %s", next_url, exc)
                break

        return urls

    def scrape_source(self) -> List[Dict[str, Any]]:
        raw_leads: List[Dict[str, Any]] = []
        logger.info("Starting scraping for all configured sources")

        with sync_playwright() as playwright:
            browser = self._get_browser_context(playwright)
            context = browser.new_context(user_agent=USER_AGENT, locale="en-US", accept_downloads=False)
            page = context.new_page()
            page.set_default_timeout(PAGE_LOAD_TIMEOUT)

            for source_name, config in SITE_CONFIGS.items():
                if len(self.company_urls) >= self.max_leads:
                    break

                logger.info("Scraping source: %s", source_name)
                for vertical, path in config["categories"].items():
                    if len(self.company_urls) >= self.max_leads:
                        break

                    try:
                        listing_url = urljoin(config["base_url"], path)
                        logger.info("Opening listing url: %s", listing_url)
                        page.goto(listing_url, timeout=PAGE_LOAD_TIMEOUT)
                        page.wait_for_load_state("networkidle", timeout=PAGE_LOAD_TIMEOUT)
                        time.sleep(1)

                        page_urls = self._scrape_pagination(page, config["base_url"], source_name, config.get("pagination_patterns", []))
                        for item_url in page_urls:
                            if item_url not in self.company_urls:
                                self.company_urls.add(item_url)
                                if len(self.company_urls) >= self.max_leads:
                                    break
                    except PlaywrightTimeoutError:
                        logger.warning("Timeout loading source listing %s %s", source_name, vertical)
                    except Exception as exc:
                        logger.exception("Failed to scrape source listing %s %s: %s", source_name, vertical, exc)

            for company_url in list(self.company_urls):
                if len(raw_leads) >= self.max_leads:
                    break
                try:
                    raw_lead = self.scrape_company_page(page, company_url)
                    if raw_lead:
                        raw_leads.append(raw_lead)
                except Exception as exc:
                    logger.exception("Failed to scrape company card %s: %s", company_url, exc)

            context.close()
            browser.close()

        logger.info("Finished scraping. Found %d company cards.", len(raw_leads))
        return raw_leads

    def scrape_company_page(self, page, url: str) -> Optional[Dict[str, Any]]:
        logger.info("Opening company card: %s", url)
        page.goto(url, timeout=PAGE_LOAD_TIMEOUT)
        page.wait_for_load_state("networkidle", timeout=PAGE_LOAD_TIMEOUT)
        time.sleep(1)
        html = page.content()

        source = urlparse(url).netloc
        vertical = "Unknown"
        for name, config in SITE_CONFIGS.items():
            if config["base_url"].replace("https://", "") in source:
                vertical = name
                break

        return self._parse_company_card(html, url, source, vertical)
