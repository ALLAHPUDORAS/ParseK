import logging
import re
import time
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Comment
from playwright.sync_api import Playwright, sync_playwright, TimeoutError as PlaywrightTimeoutError
import multiprocessing

from src.config import (
    PAGE_LOAD_TIMEOUT,
    SITE_CONFIGS,
    USER_AGENT,
    DEFAULT_MAX_LEADS,
    COMPANY_CARD_SELECTORS,
    DYNAMIC_CARD_TRIGGERS,
)
from src.config import LOGS_DIR
import os
import json
import urllib.robotparser

logger = logging.getLogger("LeadPipeline.Scraper")


def _worker_scrape_company(args):
    """Worker entrypoint for multiprocessing: args == (url, headless)"""
    # kept for compatibility; not used when initializer sets up browser
    url, headless = args
    try:
        # fallback: create a temporary Scraper which will create its own browser
        worker = Scraper(headless=headless, max_leads=1, concurrency=1)
        return worker.scrape_company_page(None, url)
    except Exception:
        logger.exception("Worker failed to scrape %s", url)
        return None


# Globals used by worker processes when initialized with _worker_init
_WORKER_P = None
_WORKER_BROWSER = None
_WORKER_CONTEXT = None
_WORKER_PAGE = None
_WORKER_LAST_CALL = None
_WORKER_LOCK = None
_WORKER_DELAYS = None
_WORKER_COUNTS = None
_WORKER_LIMITS = None


def _worker_init(headless: bool, user_agent: str, last_call_proxy=None, lock_obj=None, per_site_delays=None, current_counts=None, per_site_limits=None):
    """Initializer for multiprocessing pool workers.
    Starts Playwright and a single browser/context/page per worker process.
    """
    global _WORKER_P, _WORKER_BROWSER, _WORKER_CONTEXT, _WORKER_PAGE, _WORKER_LAST_CALL, _WORKER_LOCK, _WORKER_DELAYS
    try:
        from playwright.sync_api import sync_playwright
        _WORKER_P = sync_playwright().start()
        _WORKER_BROWSER = _WORKER_P.chromium.launch(headless=headless, args=["--no-sandbox", "--disable-dev-shm-usage"])
        _WORKER_CONTEXT = _WORKER_BROWSER.new_context(user_agent=user_agent, locale="en-US", accept_downloads=False)
        _WORKER_PAGE = _WORKER_CONTEXT.new_page()
        _WORKER_PAGE.set_default_timeout(PAGE_LOAD_TIMEOUT)
        _WORKER_LAST_CALL = last_call_proxy
        _WORKER_LOCK = lock_obj
        _WORKER_DELAYS = per_site_delays or {}
        _WORKER_COUNTS = current_counts
        _WORKER_LIMITS = per_site_limits or {}
    except Exception:
        logger.exception("Failed to initialize worker Playwright browser")


def _worker_close():
    global _WORKER_P, _WORKER_BROWSER, _WORKER_CONTEXT, _WORKER_PAGE
    try:
        if _WORKER_PAGE:
            try:
                _WORKER_PAGE.close()
            except Exception:
                pass
        if _WORKER_CONTEXT:
            try:
                _WORKER_CONTEXT.close()
            except Exception:
                pass
        if _WORKER_BROWSER:
            try:
                _WORKER_BROWSER.close()
            except Exception:
                pass
        if _WORKER_P:
            try:
                _WORKER_P.stop()
            except Exception:
                pass
    except Exception:
        logger.exception("Error closing worker Playwright resources")


def _worker_process_url(url: str) -> Optional[Dict[str, Any]]:
    """Process a single URL using the worker-global page/browser. Returns parsed lead dict or None."""
    global _WORKER_PAGE
    if not _WORKER_PAGE:
        # fallback to simple per-call Scraper
        try:
            tmp = Scraper(headless=True, max_leads=1, concurrency=1)
            return tmp.scrape_company_page(None, url)
        except Exception:
            logger.exception("Fallback worker failed for %s", url)
            return None

    try:
        # Enforce per-site crawl delays and per-site concurrency using shared manager dicts and lock
        site = urlparse(url).netloc
        try:
            delay = None
            if _WORKER_DELAYS:
                delay = _WORKER_DELAYS.get(site) or _WORKER_DELAYS.get(site.split(":")[0])

            # acquire per-site slot
            acquired = False
            if _WORKER_COUNTS is not None and _WORKER_LOCK is not None:
                limit = None
                if _WORKER_LIMITS:
                    limit = _WORKER_LIMITS.get(site) or _WORKER_LIMITS.get(site.split(":")[0])
                if not limit:
                    limit = 1
                while True:
                    with _WORKER_LOCK:
                        cur = _WORKER_COUNTS.get(site, 0)
                        if cur < limit:
                            _WORKER_COUNTS[site] = cur + 1
                            acquired = True
                            break
                    time.sleep(0.05)

            # respect crawl delay
            if _WORKER_LAST_CALL is not None and _WORKER_LOCK is not None and delay:
                with _WORKER_LOCK:
                    last = _WORKER_LAST_CALL.get(site)
                    now = time.time()
                    if last:
                        elapsed = now - last
                        to_wait = max(0.0, float(delay) - elapsed)
                        if to_wait > 0:
                            time.sleep(to_wait + 0.05)
                    _WORKER_LAST_CALL[site] = time.time()

        except Exception:
            pass

        _WORKER_PAGE.goto(url, timeout=PAGE_LOAD_TIMEOUT)
        _WORKER_PAGE.wait_for_load_state("domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
        try:
            _WORKER_PAGE.wait_for_selector("body", timeout=3000)
        except Exception:
            pass
        html = _WORKER_PAGE.content()
        # use Scraper instance for parsing helpers
        parser = Scraper(headless=False, max_leads=1, concurrency=1)
        source = urlparse(url).netloc
        vertical = "Unknown"
        for name, config in SITE_CONFIGS.items():
            if config["base_url"].replace("https://", "").replace("http://", "") in source:
                vertical = name
                break
        parsed = parser._parse_company_card(html, url, source, vertical)
        # release per-site slot
        try:
            if acquired and _WORKER_COUNTS is not None and _WORKER_LOCK is not None:
                with _WORKER_LOCK:
                    _WORKER_COUNTS[site] = max(0, _WORKER_COUNTS.get(site, 1) - 1)
        except Exception:
            pass

        return parsed
    except Exception:
        logger.exception("Worker error processing %s", url)
        return None

class Scraper:
    def __init__(self, headless: bool = True, max_leads: int = DEFAULT_MAX_LEADS, concurrency: int = None):
        self.headless = headless
        self.max_leads = max_leads
        # If not provided, use safe default tuned for ~4GB RAM
        if concurrency is None:
            from src.config import DEFAULT_CONCURRENCY_4GB
            concurrency = DEFAULT_CONCURRENCY_4GB
        self.concurrency = max(1, int(concurrency or 1))
        self.visited_urls: Set[str] = set()
        self.company_urls: Set[str] = set()
        self.scraped_pages = 0
        self.failed_pages = 0
        self.skipped_urls = 0

    def _get_browser_context(self, playwright: Playwright):
        return playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ]
        )

    def _normalize_url(self, base: str, href: str) -> Optional[str]:
        if not href:
            return None

        href = href.strip()
        if href.startswith("javascript:") or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            return None

        parsed = urlparse(href)
        if not parsed.netloc:
            href = urljoin(base, href)

        return href

    def _extract_url_from_element(self, element, base_url: str) -> Optional[str]:
        candidates = [
            element.get_attribute("href"),
            element.get_attribute("data-href"),
            element.get_attribute("data-url"),
            element.get_attribute("data-company-url"),
            element.get_attribute("data-card-url"),
        ]
        for candidate in candidates:
            if candidate:
                normalized = self._normalize_url(base_url, candidate)
                if normalized:
                    return normalized

        onclick = None
        try:
            onclick = element.get_attribute("onclick")
        except Exception:
            onclick = None
        if onclick:
            match = re.search(r"['\"](https?://[^'\"]+)['\"]", onclick)
            if match:
                return match.group(1)
            match = re.search(r"location\.href\s*=\s*['\"]([^'\"]+)['\"]", onclick)
            if match:
                return self._normalize_url(base_url, match.group(1))

        return None

    def _is_company_card_url(self, url: str, site_name: str) -> bool:
        if not url or url in self.company_urls:
            return False

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False

        path = parsed.path.rstrip("/")
        path_lower = path.lower()

        # Исключаем системные и служебные разделы
        junk_keywords = [
            "add-network", "add-your-network", "add-program", "add-offer",
            "login", "register", "signup", "contact", "privacy", "terms",
            "about", "blog", "faq", "help", "support", "reviews", "news"
        ]
        if any(junk in path_lower for junk in junk_keywords):
            return False

        # Исключаем корень каталогов
        if path_lower in ["/networks", "/offers", "/affiliate-networks", "/network", "/offer", ""]:
            return False

        config = SITE_CONFIGS.get(site_name)
        if config:
            patterns = config.get("company_url_patterns", [])
            for pattern in patterns:
                if re.search(pattern, path_lower):
                    return True
            return False

        # Запасная проверка глубины пути
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 2:
            first_dir = parts[0].lower()
            if first_dir in {"network", "affiliate-networks", "n", "o", "offer", "details"}:
                return True

        return False

    def _is_affplus_offer_page(self, url: str) -> bool:
        if not url:
            return False
        parsed = urlparse(url)
        path = parsed.path.rstrip("/").lower()
        return bool(re.match(r"^/(?:o|offer|details)/[A-Za-z0-9_-]+$", path))

    def _find_affplus_network_url(self, page, html: str, base_url: str) -> Optional[str]:
        if not base_url:
            return None

        candidates = set()
        try:
            if page is not None:
                anchors = page.query_selector_all("a[href]")
                for anchor in anchors:
                    href = None
                    try:
                        href = anchor.get_attribute("href")
                    except Exception:
                        continue
                    if not href:
                        continue
                    href = href.strip()
                    if re.match(r"^/(?:n|network)/[A-Za-z0-9_-]+$", href, flags=re.IGNORECASE):
                        normalized = self._normalize_url(base_url, href)
                        if normalized and self._is_company_card_url(normalized, "Affplus"):
                            candidates.add(normalized)
        except Exception:
            pass

        if not candidates and html:
            for match in re.findall(r'href=["\'](/(?:n|network)/[A-Za-z0-9_-]+)["\']', html, flags=re.IGNORECASE):
                normalized = self._normalize_url(base_url, match)
                if normalized and self._is_company_card_url(normalized, "Affplus"):
                    candidates.add(normalized)

        if candidates:
            return sorted(candidates)[0]
        return None

    def _build_selector_query(self, selectors: List[str]) -> str:
        return ", ".join(set(selectors))

    def _retry_action(self, action, retries: int = 3, initial_delay: float = 1.0, action_name: str = "action"):
        delay = initial_delay
        for attempt in range(1, retries + 1):
            try:
                return action()
            except PlaywrightTimeoutError as exc:
                logger.warning("Timeout on %s attempt %d/%d: %s", action_name, attempt, retries, exc)
                if attempt == retries:
                    raise
                time.sleep(delay)
                delay *= 2
            except Exception as exc:
                logger.warning("Error on %s attempt %d/%d: %s", action_name, attempt, retries, exc)
                if attempt == retries:
                    raise
                time.sleep(delay)
                delay *= 2

    def _extract_links_from_page(self, page, base_url: str, site_name: str, selectors: List[str]) -> Set[str]:
        links = set()
        query = self._build_selector_query(selectors)
        try:
            anchors = page.query_selector_all(query)
        except Exception as exc:
            logger.warning("Unable to query anchor tags: %s", exc)
            return links

        for anchor in anchors:
            try:
                normalized = self._extract_url_from_element(anchor, base_url)
                if normalized and self._is_company_card_url(normalized, site_name):
                    links.add(normalized)
            except Exception:
                continue

        return links

    def _find_dynamic_company_links(self, page, base_url: str, site_name: str, existing_links: Set[str], triggers: List[str]) -> Set[str]:
        links = set()
        dynamic_selectors = triggers or DYNAMIC_CARD_TRIGGERS
        # include any site-specific extra_triggers from config
        try:
            cfg = SITE_CONFIGS.get(site_name, {})
            extras = cfg.get("extra_triggers") or []
            if extras:
                dynamic_selectors = list(dynamic_selectors) + list(extras)
        except Exception:
            pass

        for selector in dynamic_selectors:
            try:
                triggers = page.query_selector_all(selector)
            except Exception:
                continue

            for trigger in triggers:
                try:
                    direct_url = self._extract_url_from_element(trigger, base_url)
                    if direct_url and self._is_company_card_url(direct_url, site_name):
                        links.add(direct_url)
                        continue

                    try:
                        trigger.hover()
                    except Exception:
                        pass
                    try:
                        trigger.click()
                    except Exception:
                        pass

                    try:
                        page.wait_for_selector("a[href], [data-href], [data-url], [data-company-url], [data-card-url], [onclick]", timeout=3000)
                    except Exception:
                        pass

                    new_links = self._extract_links_from_page(page, base_url, site_name, selectors=triggers)
                    for link in new_links:
                        if link not in existing_links:
                            links.add(link)
                except Exception:
                    continue

        return links

    def _find_company_links(self, page, base_url: str, site_name: str, selectors: List[str] = None, triggers: List[str] = None) -> Set[str]:
        links = set()
        selectors = selectors or COMPANY_CARD_SELECTORS
        triggers = triggers or DYNAMIC_CARD_TRIGGERS
        query = self._build_selector_query(selectors)

        try:
            last_height = page.evaluate("document.body.scrollHeight")
            while True:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                try:
                    page.wait_for_selector(query, timeout=3000)
                except Exception:
                    pass
                new_height = page.evaluate("document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height

            links = self._extract_links_from_page(page, base_url, site_name, selectors=selectors)
            dynamic_links = self._find_dynamic_company_links(page, base_url, site_name, links, triggers=triggers)
            links.update(dynamic_links)

            # Fallback: if no links found, try regex-based extraction from HTML content
            if not links:
                try:
                    html = page.content()
                    regex_links = self._extract_links_via_regex(html, base_url, site_name)
                    links.update(regex_links)
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("Unable to query anchor tags: %s", exc)
            return links

        logger.info("Discovered %d valid company links on current page for %s", len(links), site_name)
        return links

    def _extract_links_via_regex(self, html: str, base_url: str, site_name: str) -> Set[str]:
        links = set()
        if not html:
            return links

        # common patterns: href="/network/xxx", data-href="/network/xxx", location.href='/network/xxx'
        patterns = [r'href\s*=\s*"([^"]*?/network/[^"\s]*)"',
                    r"href\s*=\s*'([^'\s]*?/network/[^'\s]*)'",
                    r'data-[-\w]+\s*=\s*"([^"]*?/network/[^"\s]*)"',
                    r"data-[-\w]+\s*=\s*'([^'\s]*?/network/[^'\s]*)'",
                    r"location\.href\s*=\s*'([^']*?/network/[^'\s]*)'",
                    r'location\.href\s*=\s*"([^"]*?/network/[^"\s]*)"']

        for pat in patterns:
            for match in re.findall(pat, html, flags=re.IGNORECASE):
                try:
                    normalized = self._normalize_url(base_url, match)
                    if normalized and self._is_company_card_url(normalized, site_name):
                        links.add(normalized)
                except Exception:
                    continue

        # Also search for raw /network/slug occurrences and build URLs
        if not links:
            for m in re.findall(r"(/network/[A-Za-z0-9_-]+)", html, flags=re.IGNORECASE):
                try:
                    normalized = self._normalize_url(base_url, m)
                    if normalized and self._is_company_card_url(normalized, site_name):
                        links.add(normalized)
                except Exception:
                    continue

        return links

    def _find_next_page(self, page, pagination_patterns: List[str]) -> Optional[str]:
        def normalize_text(text: Optional[str]) -> str:
            return (text or "").strip().lower()

        def extract_fallback_href(element) -> Optional[str]:
            href = None
            try:
                href = element.get_attribute("href")
            except Exception:
                href = None

            if href:
                return href

            try:
                href = element.evaluate(
                    "(el) => {"
                    "const anchor = el.closest('a');"
                    "if (anchor) return anchor.getAttribute('href');"
                    "const child = el.querySelector('a');"
                    "if (child) return child.getAttribute('href');"
                    "return el.getAttribute('data-href') || el.getAttribute('onclick');"
                    "}"
                )
            except Exception:
                href = None

            if href and isinstance(href, str):
                match = re.search(r"(['\"])(https?://[^'\"]+)\1", href)
                if match:
                    return match.group(2)
                return href

            return None

        def search_all_next_links() -> Optional[str]:
            try:
                anchors = page.query_selector_all("a, button")
                for anchor in anchors:
                    try:
                        text = normalize_text(anchor.text_content())
                        if "next" in text or "»" in text or "след" in text:
                            candidate = extract_fallback_href(anchor)
                            if candidate:
                                return candidate
                    except Exception:
                        continue
            except Exception:
                pass
            return None

        for selector in pagination_patterns:
            try:
                element = page.query_selector(selector)
                if not element:
                    continue

                href = extract_fallback_href(element)
                if href:
                    return href

                text = normalize_text(element.text_content())
                if "next" in text or "»" in text or "след" in text:
                    return search_all_next_links()
            except Exception:
                continue

        return search_all_next_links()

    def _clean_visible_text(self, content: str) -> str:
        soup = BeautifulSoup(content, "html.parser")
        for element in soup(["script", "style", "noscript"]):
            element.decompose()
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()
        return soup.get_text(" ", strip=True)

    def _extract_company_name(self, soup: BeautifulSoup) -> str:
        if soup.select_one("h1"):
            return soup.select_one("h1").get_text(strip=True)

        for tag in ["h2", "h3", "strong", "b"]:
            element = soup.select_one(tag)
            if element:
                text = element.get_text(strip=True)
                if text and len(text.split()) <= 6:
                    return text

        og_title = soup.select_one("meta[property='og:title']")
        if og_title and og_title.get("content"):
            return og_title.get("content").strip()

        if soup.title and soup.title.get_text(strip=True):
            return soup.title.get_text(strip=True)

        return ""

    def _extract_company_website(self, soup: BeautifulSoup) -> str:
        website = ""
        candidates = []
        for link in soup.select("a[href]"):
            href = link.get("href", "").strip()
            text = link.get_text(strip=True)
            if href.startswith("http") and not any(block in href.lower() for block in ["/login", "/register", "/signup", "/contact", "/privacy", "#"]):
                if text and text.lower() not in {"visit website", "website", "here", "click here"}:
                    candidates.append((href, text))
                else:
                    candidates.append((href, ""))

        if candidates:
            for href, text in candidates:
                if text and text.lower() not in {"visit website", "website"}:
                    return href
            return candidates[0][0]

        return website

    def _extract_company_geo(self, visible_text: str) -> str:
        geo_candidates = re.findall(
            r"\b(?:EU|Europe|LATAM|Asia|Russia|Belarus|CIS|USA|UK|Canada|Global|Worldwide|Eastern Europe|Western Europe|Central America|South America|Africa|MENA)\b",
            visible_text,
            re.IGNORECASE
        )
        if geo_candidates:
            return geo_candidates[0].strip()

        location_match = re.search(
            r"(?:HQ|Headquarters|Based in|Location|Located in)[:\s]+([A-Za-z0-9\s,-]+)",
            visible_text,
            re.IGNORECASE
        )
        if location_match:
            return location_match.group(1).strip()

        return ""

    def _extract_company_status(self, soup: BeautifulSoup, visible_text: str) -> str:
        status_keywords = ["closed", "blacklisted", "inactive", "offline", "suspended"]
        for element in soup.select("span, div, p, li, strong, b, em"):
            text = element.get_text(strip=True)
            low = text.lower()
            if any(keyword in low for keyword in status_keywords) and "status" in low:
                return text
            if any(keyword in low for keyword in status_keywords) and len(text.split()) <= 4:
                return text

        for keyword in status_keywords:
            if keyword in visible_text.lower():
                return keyword.capitalize()

        return ""

    def _is_valid_telegram_handle(self, handle: str) -> bool:
        handle_lower = handle.lower().lstrip("@")
        invalid_handles = {
            "media", "supports", "keyframes", "font-face",
            "charset", "document", "pageview", "viewport",
            "import", "function", "return", "window", "script",
            "body", "html", "head", "link", "meta", "style",
            "affplus", "offervault", "affpaying", "telegram", "joinchat", "channel"
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

        if not content:
            return contacts

        additional_values = []
        try:
            soup = BeautifulSoup(content, "html.parser")
            for element in soup.find_all(True):
                for attr_name in ["data-tippy", "data-tooltip", "data-title", "title", "aria-label", "alt", "data-content"]:
                    attr_value = element.get(attr_name)
                    if attr_value:
                        if isinstance(attr_value, list):
                            additional_values.extend(attr_value)
                        else:
                            additional_values.append(str(attr_value))
        except Exception:
            additional_values = []

        all_contact_values = [content] + additional_values

        # 1. Поиск Email из mailto: и видимых ссылок (исключаем статику и скрипты)
        for value in all_contact_values:
            mailto_matches = re.findall(r"mailto:([A-Za-z0-9_.+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9-.]+)", value, flags=re.IGNORECASE)
            for email in mailto_matches:
                email_clean = email.strip().strip(".,;:\"'")
                if email_clean:
                    contacts["emails"].append(email_clean)

        for value in all_contact_values:
            raw_emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", value)
            for email in raw_emails:
                email_clean = email.strip().strip(".,;:\"'")
                if not any(junk in email_clean.lower() for junk in [".png", ".jpg", ".jpeg", ".webp", ".svg", ".css", ".js", "example", "domain", "affplus", "bootstrap", "schema.org"]):
                    contacts["emails"].append(email_clean)

        # 2. Поиск Telegram СТРОГО по прямым ссылкам (t.me/, telegram.me/, tg://)
        for value in all_contact_values:
            tg_matches = re.findall(r"(?:t\.me/|telegram\.me/|tg://resolve\?domain=)([A-Za-z0-9_]{5,32})", value, flags=re.IGNORECASE)
            for match in tg_matches:
                if self._is_valid_telegram_handle(match):
                    contacts["telegram"].append(f"@{match}")

        # 2b. Поиск Telegram из объектов tooltip и атрибутов (@username)
        for value in additional_values:
            raw_handles = re.findall(r"@([A-Za-z0-9_]{5,32})", value)
            for handle in raw_handles:
                if self._is_valid_telegram_handle(handle):
                    contacts["telegram"].append(f"@{handle}")

        # 3. Поиск Skype (skype:, live:, skype?chat=)
        for value in all_contact_values:
            skype_matches = re.findall(r"(?:skype:|live:|skype\?chat=)([A-Za-z0-9_.:-]+)", value, flags=re.IGNORECASE)
            for match in skype_matches:
                clean_skype = match.strip().strip(".,;:\"'")
                if len(clean_skype) > 3 and not any(j in clean_skype.lower() for j in ["http", "javascript", "undefined"]):
                    contacts["skype"].append(clean_skype)

        # 4. Поиск Discord
        for value in all_contact_values:
            discord_matches = re.findall(r"(?:discord\.gg/|discord\.com/invite/|discordapp\.com/users/)([A-Za-z0-9_#.-]+)", value, flags=re.IGNORECASE)
            for match in discord_matches:
                contacts["discord"].append(match.strip())

        # Дедупликация
        for key in contacts:
            contacts[key] = list(dict.fromkeys(contacts[key]))

        return contacts

    def _parse_company_card(self, page_content: str, page_url: str, source: str, vertical: str) -> Dict[str, Any]:
        soup = BeautifulSoup(page_content, "html.parser")
        name = ""
        website = ""
        geo = ""
        status = ""

        if soup.select_one("h1"):
            name = soup.select_one("h1").get_text(strip=True)

        if not name and soup.title:
            name = soup.title.get_text(strip=True)

        name = self._extract_company_name(soup)

        website = self._extract_company_website(soup)

        visible_text = self._clean_visible_text(page_content)
        geo = self._extract_company_geo(visible_text)

        status = self._extract_company_status(soup, visible_text)

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

    def _scrape_pagination(
        self,
        page,
        base_url: str,
        site_name: str,
        pagination_selectors: List[str],
        company_selectors: List[str] = None,
        dynamic_triggers: List[str] = None,
    ) -> Set[str]:
        urls = set()
        current_url = page.url
        visited_pages = {current_url}
        company_selectors = company_selectors or COMPANY_CARD_SELECTORS
        dynamic_triggers = dynamic_triggers or DYNAMIC_CARD_TRIGGERS

        pagination_query = self._build_selector_query(pagination_selectors)
        company_query = self._build_selector_query(company_selectors)

        while True:
            logger.info("Scraping listing page %s", current_url)
            self.scraped_pages += 1
            
            try:
                page.wait_for_selector(company_query, timeout=5000)
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    # networkidle may not be reached; continue anyway
                    pass
            except Exception:
                pass

            found_links = self._find_company_links(
                page,
                base_url,
                site_name,
                selectors=company_selectors,
                triggers=dynamic_triggers,
            )

            next_href = self._find_next_page(page, pagination_selectors)
            if not next_href:
                break

            next_url = self._normalize_url(base_url, next_href)
            if not next_url or next_url in visited_pages:
                break

            visited_pages.add(next_url)
            try:
                self._retry_action(
                    lambda: page.goto(next_url, timeout=PAGE_LOAD_TIMEOUT),
                    action_name=f"navigate to next listing page {next_url}",
                )
                self._retry_action(
                    lambda: page.wait_for_load_state("domcontentloaded", timeout=PAGE_LOAD_TIMEOUT),
                    action_name=f"wait for next listing page {next_url}",
                )
                try:
                    page.wait_for_selector(company_query, timeout=3000)
                except Exception:
                    pass
                current_url = next_url
            except Exception as exc:
                logger.warning("Failed to open next listing page %s: %s", next_url, exc)
                self.failed_pages += 1
                break

        return urls

    def scrape_source(self) -> List[Dict[str, Any]]:
        raw_leads: List[Dict[str, Any]] = []
        logger.info("Starting scraping for all configured sources")

        # load state (persisted urls) if exists
        try:
            self._load_state()
        except Exception:
            logger.debug("No previous state loaded")

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
                        search_template = config.get("search_page_template")
                        page_urls = set()
                        if search_template:
                            max_pages = config.get("max_search_pages", 3)
                            for page_num in range(1, max_pages + 1):
                                search_path = search_template.format(vertical=vertical, page=page_num)
                                listing_url = urljoin(config["base_url"], search_path)
                                logger.info("Opening search listing url: %s", listing_url)
                                try:
                                    rp = urllib.robotparser.RobotFileParser()
                                    rp.set_url(urljoin(config["base_url"], "/robots.txt"))
                                    rp.read()
                                    if not rp.can_fetch(USER_AGENT, listing_url):
                                        logger.info("Disallowed by robots.txt: %s", listing_url)
                                        break
                                except Exception:
                                    logger.debug("robots.txt check failed for %s", config.get("base_url"))

                                self._retry_action(
                                    lambda: page.goto(listing_url, timeout=PAGE_LOAD_TIMEOUT),
                                    action_name=f"navigate to listing page {listing_url}",
                                )
                                self._retry_action(
                                    lambda: page.wait_for_load_state("domcontentloaded", timeout=PAGE_LOAD_TIMEOUT),
                                    action_name=f"wait for listing page {listing_url}",
                                )
                                time.sleep(2.5)

                                found_urls = self._find_company_links(
                                    page,
                                    config["base_url"],
                                    source_name,
                                    selectors=config.get("company_card_selectors", COMPANY_CARD_SELECTORS),
                                    triggers=config.get("dynamic_card_triggers", DYNAMIC_CARD_TRIGGERS),
                                )
                                if not found_urls and page_num > 1:
                                    break
                                page_urls.update(found_urls)
                                if len(page_urls) >= self.max_leads:
                                    break
                        else:
                            listing_url = urljoin(config["base_url"], path)
                            logger.info("Opening listing url: %s", listing_url)
                            try:
                                rp = urllib.robotparser.RobotFileParser()
                                rp.set_url(urljoin(config["base_url"], "/robots.txt"))
                                rp.read()
                                if not rp.can_fetch(USER_AGENT, listing_url):
                                    logger.info("Disallowed by robots.txt: %s", listing_url)
                                    continue
                            except Exception:
                                logger.debug("robots.txt check failed for %s", config.get("base_url"))
                            self._retry_action(
                                lambda: page.goto(listing_url, timeout=PAGE_LOAD_TIMEOUT),
                                action_name=f"navigate to listing page {listing_url}",
                            )
                            self._retry_action(
                                lambda: page.wait_for_load_state("domcontentloaded", timeout=PAGE_LOAD_TIMEOUT),
                                action_name=f"wait for listing page {listing_url}",
                            )
                            time.sleep(2.5)
                            page_urls = self._scrape_pagination(
                                page,
                                config["base_url"],
                                source_name,
                                config.get("pagination_selectors", config.get("pagination_patterns", [])),
                            )

                        for item_url in page_urls:
                            if item_url not in self.company_urls:
                                self.company_urls.add(item_url)
                                if len(self.company_urls) >= self.max_leads:
                                    break
                    except PlaywrightTimeoutError:
                        logger.warning("Timeout loading source listing %s %s", source_name, vertical)
                    except Exception as exc:
                        logger.exception("Failed to scrape source listing %s %s: %s", source_name, vertical, exc)

            logger.info("Total unique company URLs collected: %d. Starting detailed scraping...", len(self.company_urls))

            # persist discovered URLs so we can resume if interrupted
            try:
                self._save_state()
            except Exception:
                logger.exception("Failed to persist scraper state")

            # Process company pages; use parallel workers if concurrency > 1
            company_list = list(self.company_urls)
            if self.concurrency > 1 and company_list:
                # initialize pool workers with a single browser/context/page per process
                manager = multiprocessing.Manager()
                last_call = manager.dict()
                lock = manager.Lock()
                current_counts = manager.dict()
                # build per-site delays map (domain -> seconds)
                per_site_delays = {}
                for name, cfg in SITE_CONFIGS.items():
                    base = cfg.get("base_url", "")
                    if base:
                        host = base.replace("https://", "").replace("http://", "")
                        per_site_delays[host] = cfg.get("crawl_delay", 1)

                per_site_limits = {}
                for name, cfg in SITE_CONFIGS.items():
                    base = cfg.get("base_url", "")
                    if base:
                        host = base.replace("https://", "").replace("http://", "")
                        per_site_limits[host] = cfg.get("max_concurrency", 1)

                init_args = (self.headless, USER_AGENT, last_call, lock, per_site_delays, current_counts, per_site_limits)
                with multiprocessing.Pool(processes=self.concurrency, initializer=_worker_init, initargs=init_args, maxtasksperchild=50) as pool:
                    try:
                        for result in pool.imap_unordered(_worker_process_url, company_list):
                            if result:
                                raw_leads.append(result)
                                if len(raw_leads) >= self.max_leads:
                                    break
                            else:
                                self.skipped_urls += 1
                    finally:
                        # ensure workers clean up Playwright resources
                        pool.close()
                        pool.join()
            else:
                for company_url in company_list:
                    if len(raw_leads) >= self.max_leads:
                        break
                    try:
                        raw_lead = self.scrape_company_page(page, company_url)
                        if raw_lead:
                            raw_leads.append(raw_lead)
                        else:
                            self.skipped_urls += 1
                    except Exception as exc:
                        logger.exception("Failed to scrape company card %s: %s", company_url, exc)
                        self.failed_pages += 1
                        self.skipped_urls += 1

            context.close()
            browser.close()

        logger.info("Finished scraping. Found %d company cards.", len(raw_leads))
        return raw_leads

    def _reveal_hover_contacts(self, page) -> None:
        hover_selectors = [
            "[aria-label*='Telegram']",
            "[title*='Telegram']",
            "[class*='telegram']",
            "[class*='tg']",
            "[data-tooltip*='Telegram']",
            "[data-title*='Telegram']",
            "a[href*='t.me/']",
            "a[href^='tg://']",
            "button[title*='Telegram']",
            "button[aria-label*='Telegram']",
            "svg[class*='telegram']",
            "svg[title*='Telegram']",
            "[aria-label*='Email']",
            "[aria-label*='Mail']",
            "[title*='Email']",
            "[title*='Mail']",
            "[class*='email']",
            "[class*='mail']",
            "a[href^='mailto:']",
            "button[title*='Email']",
            "button[aria-label*='Email']",
            "svg[class*='email']",
            "svg[class*='mail']",
        ]
        query = ", ".join(hover_selectors)
        try:
            elements = page.query_selector_all(query)
            for element in elements:
                try:
                    element.hover()
                    page.wait_for_timeout(500)
                except Exception:
                    continue
        except Exception:
            return

    def scrape_company_page(self, page, url: str) -> Optional[Dict[str, Any]]:
        logger.info("Opening company card: %s", url)
        self.scraped_pages += 1

        used_local_page = False
        html = None
        try:
            if page is None:
                used_local_page = True
                with sync_playwright() as playwright:
                    browser = self._get_browser_context(playwright)
                    context = browser.new_context(user_agent=USER_AGENT, locale="en-US", accept_downloads=False)
                    local_page = context.new_page()
                    local_page.set_default_timeout(PAGE_LOAD_TIMEOUT)
                    self._retry_action(
                        lambda: local_page.goto(url, timeout=PAGE_LOAD_TIMEOUT),
                        action_name=f"navigate to company card {url}",
                    )
                    self._retry_action(
                        lambda: local_page.wait_for_load_state("domcontentloaded", timeout=PAGE_LOAD_TIMEOUT),
                        action_name=f"wait for company card {url}",
                    )
                    try:
                        local_page.wait_for_selector("body", timeout=3000)
                    except Exception:
                        pass
                    self._reveal_hover_contacts(local_page)
                    html = local_page.content()
                    context.close()
                    browser.close()
            else:
                self._retry_action(
                    lambda: page.goto(url, timeout=PAGE_LOAD_TIMEOUT),
                    action_name=f"navigate to company card {url}",
                )
                self._retry_action(
                    lambda: page.wait_for_load_state("domcontentloaded", timeout=PAGE_LOAD_TIMEOUT),
                    action_name=f"wait for company card {url}",
                )
                try:
                    page.wait_for_selector("body", timeout=3000)
                except Exception:
                    pass
                self._reveal_hover_contacts(page)
                html = page.content()
        except Exception as exc:
            logger.warning("Error fetching company card %s: %s", url, exc)
            self.failed_pages += 1
            return None

        source = urlparse(url).netloc
        vertical = "Unknown"
        for name, config in SITE_CONFIGS.items():
            if config["base_url"].replace("https://", "").replace("http://", "") in source:
                vertical = name
                break

        return self._parse_company_card(html, url, source, vertical)

    def _state_file(self) -> str:
        return os.path.join(LOGS_DIR, "scraper_state.json")

    def _load_state(self) -> None:
        path = self._state_file()
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    urls = data.get("company_urls", [])
                    visited = data.get("visited_urls", [])
                    self.company_urls.update(urls)
                    self.visited_urls.update(visited)
                    logger.info("Loaded %d saved company_urls and %d visited_urls from state", len(urls), len(visited))
            except Exception:
                logger.exception("Failed to read state file %s", path)

    def _save_state(self) -> None:
        path = self._state_file()
        try:
            os.makedirs(LOGS_DIR, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({
                    "company_urls": list(self.company_urls),
                    "visited_urls": list(self.visited_urls),
                }, fh, ensure_ascii=False, indent=2)
            logger.info("Persisted scraper state: %s", path)
        except Exception:
            logger.exception("Failed to persist state to %s", path)