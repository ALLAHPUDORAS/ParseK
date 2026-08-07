import logging
import re
import socket
import subprocess
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger("LeadPipeline.GeoFilter")

CIS_TERMS = {
    "ru", "by", "ua", "russia", "belarus", "ukraine", "россия", "беларусь", "рф", "рб", "снг", "cis"
}
CIS_MX_HINTS = ("yandex", "mail.ru", "vk.com", "rambler", "ukr.net")
BLOCKED_BRAND_TERMS = {
    "1win", "1xcasino", "1xbet", "pin-up", "pinup", "mostbet", "admiralx", "parimatch", "gg.bet", "olimp", "pinupcasino"
}
SLAVIC_NAME_TERMS = {
    "kateryna", "anton", "denis", "vlad", "sergey", "sergei", "misha", "olga", "irina", "nikita",
    "ilya", "anastasia", "natasha", "alexandr", "alexei", "dmitri", "pavel", "maksim", "maxim", "yevgen",
    "evgen", "ivan", "dasha", "svetlana"
}
SLAVIC_SUFFIXES = [
    "skaya", "ova", "eva", "ko", "chuk", "yuk", "enko", "yshyn", "vich", "vna"
]


class GeoFilter:
    @classmethod
    def _contains_slavic_marker(cls, text: Optional[str]) -> bool:
        if not text or not isinstance(text, str):
            return False
        normalized = re.sub(r"[^a-z0-9]+", " ", text.strip().lower())
        tokens = normalized.split()
        for token in tokens:
            if token in SLAVIC_NAME_TERMS:
                return True
            if token.startswith(tuple(SLAVIC_NAME_TERMS)):
                return True
            if token.endswith(tuple(SLAVIC_SUFFIXES)):
                return True
        return False

    @classmethod
    def _check_slavic_name_or_email(cls, company_name: str, contacts: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        if cls._contains_slavic_marker(company_name):
            return False, "Slavic/CIS heuristic match (Email/Name pattern)"

        emails = contacts.get("emails") or []
        if isinstance(emails, str):
            emails = [emails]

        for email in emails:
            local = str(email).split("@", 1)[0].lower()
            if cls._contains_slavic_marker(local):
                return False, "Slavic/CIS heuristic match (Email/Name pattern)"

        return True, None

    @staticmethod
    def is_allowed(text: Optional[str]) -> bool:
        if not text:
            return True
        lowered = re.sub(r"[^a-zA-Zа-яА-Я0-9]+", " ", text.strip().lower())
        tokens = set(lowered.split())
        for token in CIS_TERMS:
            if token in tokens:
                return False
            if token in lowered:
                return False
        return True

    @staticmethod
    def _extract_domain(url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        parsed = urlparse(url if url.startswith("http") else f"https://{url}")
        hostname = parsed.hostname or ""
        if not hostname:
            return None
        return hostname.lower().lstrip(".")

    @staticmethod
    def _check_opencorporates(domain: Optional[str], company_name: Optional[str]) -> Tuple[bool, Optional[str]]:
        if not domain and not company_name:
            return True, None
        try:
            import urllib.request
            import urllib.parse

            query_terms = [term for term in [company_name, domain] if term]
            if not query_terms:
                return True, None
            q = urllib.parse.quote(" ".join(query_terms))
            url = f"https://api.opencorporates.com/v0.2/companies/search?q={q}"
            with urllib.request.urlopen(url, timeout=8) as response:
                body = response.read().decode("utf-8", errors="ignore")
            if not body:
                return True, None
            payload = body.lower()
            for token in CIS_TERMS:
                if token in payload:
                    return False, f"Legal jurisdiction match: {token}"
        except Exception as exc:
            logger.debug("OpenCorporates lookup failed: %s", exc)
        return True, None

    @staticmethod
    def _check_mx(domain: Optional[str]) -> Tuple[bool, Optional[str]]:
        if not domain:
            return True, None
        try:
            import dns.resolver as resolver

            answers = resolver.resolve(domain, "MX", lifetime=5)
            hosts = [str(r.exchange).rstrip(".").lower() for r in answers]
            for host in hosts:
                if any(hint in host for hint in CIS_MX_HINTS):
                    return False, f"MX record points to CIS provider: {host}"
        except Exception as exc:
            try:
                result = subprocess.run(["nslookup", "-type=MX", domain], capture_output=True, text=True, timeout=8)
                output = (result.stdout or "") + (result.stderr or "")
                if any(hint in output.lower() for hint in CIS_MX_HINTS):
                    return False, "MX record points to CIS provider"
            except Exception as inner_exc:
                logger.debug("MX lookup failed for %s: %s", domain, inner_exc)
        return True, None

    @staticmethod
    def _is_blocked_brand(company_name: str, domain: Optional[str]) -> bool:
        normalized = " ".join(filter(None, [company_name or "", domain or ""])) .lower()
        for term in BLOCKED_BRAND_TERMS:
            if term in normalized:
                return True
        return False

    @staticmethod
    def _contains_slavic_indicator(value: Optional[str]) -> bool:
        if not value or not isinstance(value, str):
            return False
        candidate = value.strip().lower()
        if candidate.startswith("@"):
            candidate = candidate.lstrip("@")
        if "@" in candidate:
            candidate = candidate.split("@", 1)[0]
        normalized = re.sub(r"[^a-z0-9]+", " ", candidate)
        tokens = set(normalized.split())
        for term in SLAVIC_NAME_TERMS:
            if term in tokens or term in normalized:
                return True
        return False

    @classmethod
    def _check_slavic_contact_indicators(cls, contacts: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        if not isinstance(contacts, dict):
            return True, None
        for contact_type in ["emails", "telegram"]:
            values = contacts.get(contact_type) or []
            if isinstance(values, str):
                values = [values]
            for value in values:
                if cls._contains_slavic_indicator(value):
                    return False, f"Slavic indicator found in {contact_type}: {value}"
        return True, None

    @classmethod
    def filter_lead(cls, lead: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        company_name = (lead.get("name") or "").strip()
        website = (lead.get("website") or "").strip()
        geo = (lead.get("geo") or "").strip()
        contacts = lead.get("raw_contacts") or lead.get("contacts") or {}

        if not cls.is_allowed(geo):
            logger.info("[GEO-FILTER] Dropped %s (Reason: geo=%s)", company_name or "Unknown", geo)
            return False, f"Geo-Fence ({geo})"

        if cls._is_blocked_brand(company_name, website):
            logger.info("[GEO-FILTER] Dropped %s (Reason: blocked brand/domain)", company_name or "Unknown")
            return False, "Blocked brand/domain"

        slavic_ok, slavic_reason = cls._check_slavic_name_or_email(company_name, contacts)
        if not slavic_ok:
            logger.info("[GEO-FILTER] Dropped %s (Reason: %s)", company_name or "Unknown", slavic_reason)
            return False, slavic_reason

        domain = cls._extract_domain(website)
        if not domain and contacts.get("emails"):
            emails = contacts.get("emails") or []
            if isinstance(emails, str):
                emails = [emails]
            if emails:
                domain = cls._extract_domain(emails[0].split("@", 1)[-1])

        if domain:
            legal_ok, legal_reason = cls._check_opencorporates(domain, company_name)
            if not legal_ok:
                logger.info("[GEO-FILTER] Dropped %s (Reason: %s)", company_name or "Unknown", legal_reason)
                return False, legal_reason
            mx_ok, mx_reason = cls._check_mx(domain)
            if not mx_ok:
                logger.info("[GEO-FILTER] Dropped %s (Reason: %s)", company_name or "Unknown", mx_reason)
                return False, mx_reason

        return True, None
