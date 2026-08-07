"""
Validator Module: Filters companies by GEO, validates contacts via Regex,
filters out generic emails (info@, support@, etc.), and ensures data cleanliness.
"""

import asyncio
import logging
import re
from typing import Dict, Any, Optional, List, Tuple

import dns.asyncresolver as asyncresolver
import dns.exception as dns_exception
import dns.resolver as dns_resolver

from src.config import EXCLUDED_GEOS, BANNED_EMAIL_PREFIXES, EXCLUDED_STATUSES
from src.geo_filter import GeoFilter
from src.validators.telegram_validator import validate_telegram_handles

logger = logging.getLogger("LeadPipeline.Validator")

# Regex Patterns
EMAIL_REGEX = re.compile(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')
# Telegram: captures either t.me/... or tg://resolve?domain=... or @username or plain username
TELEGRAM_REGEX = re.compile(r"(?:(?:https?://)?(?:www\.)?(?:t\.me/|tg://resolve\?domain=)(@?[A-Za-z0-9_]{5,32}))|@([A-Za-z0-9_]{5,32})|\b([A-Za-z0-9_]{5,32})\b", re.IGNORECASE)
SKYPE_REGEX = re.compile(r'(?:skype:)?(live:[A-Za-z0-9_.:-]+|[A-Za-z0-9_.:-]{3,})', re.IGNORECASE)
DISCORD_INVITE_REGEX = re.compile(r'(?:discord(?:\.gg|\.com/invite)/([A-Za-z0-9_-]+))', re.IGNORECASE)
DISCORD_TAG_REGEX = re.compile(r'([A-Za-z0-9_\-]{2,32}#[0-9]{4})')

class LeadValidator:
    @staticmethod
    def is_geo_allowed(geo_str: str) -> bool:
        """
        Checks if the GEO string contains excluded regions (RU, BY, CIS).
        Returns True if GEO is allowed, False only for explicit CIS indicators.
        """
        if not geo_str:
            return True

        upper_geo = geo_str.strip().upper()
        if upper_geo in {"GLOBAL", "WORLDWIDE", "WORLD", "INTERNATIONAL", "ALL"}:
            return True

        pattern = r"\b(?:" + "|".join(re.escape(ex) for ex in EXCLUDED_GEOS) + r")\b"
        return re.search(pattern, upper_geo) is None

    @staticmethod
    def is_valid_email(email: str) -> bool:
        """
        Validates if email is not generic/role email (info@, support@, etc.).
        """
        if not email:
            return False
        email = email.strip()
        if not EMAIL_REGEX.match(email):
            return False

        local = email.split('@', 1)[0].lower()

        # Reject if exact match to banned prefix
        if local in BANNED_EMAIL_PREFIXES:
            logger.debug("Filtered role email (exact): %s", email)
            return False

        # If local starts with a banned prefix, inspect next char
        for prefix in BANNED_EMAIL_PREFIXES:
            if local.startswith(prefix):
                if len(local) == len(prefix):
                    logger.debug("Filtered role email (exact start): %s", email)
                    return False
                next_char = local[len(prefix):len(prefix)+1]
                # if next char is digit -> likely generic (info123)
                if next_char.isdigit():
                    logger.debug("Filtered role email (prefix+digits): %s", email)
                    return False
                # if next char is hyphen or underscore -> generic team address
                if next_char in ('-', '_'):
                    logger.debug("Filtered role email (prefix+sep): %s", email)
                    return False
                # if next char is '.' and followed by letters -> allow (e.g. sales.john)
                if next_char == '.':
                    logger.debug("Allowed personal-looking dotted address: %s", email)
                    return True
                # if next char is letter (e.g. adminuser) -> allow
                if next_char.isalpha():
                    logger.debug("Allowed alphanumeric continuation: %s", email)
                    return True

        domain = email.rsplit('@', 1)[1].lower()
        if not LeadValidator._has_mx_records(domain):
            logger.debug("Filtered out email with no MX records: %s", email)
            return False

        return True

    @staticmethod
    def _has_mx_records(domain: str, timeout: float = 2.0) -> bool:
        domain = (domain or "").strip().lower().rstrip(".")
        if not domain or domain in {"localhost", "localdomain"}:
            return False

        async def _check() -> bool:
            try:
                answers = await asyncio.wait_for(asyncresolver.resolve(domain, "MX", lifetime=timeout), timeout=timeout)
                return bool(answers)
            except (asyncio.TimeoutError, dns_exception.Timeout, dns_resolver.NXDOMAIN, dns_resolver.NoAnswer, dns_resolver.NoNameservers, dns_exception.DNSException):
                return False

        try:
            return asyncio.run(_check())
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(asyncio.wait_for(_check(), timeout=timeout))
            finally:
                loop.close()

    @staticmethod
    def _is_valid_telegram_handle(handle: str) -> bool:
        handle_value = handle.lower().lstrip("@")
        return bool(re.match(r"^[a-zA-Z0-9_]{5,32}$", handle_value))

    @staticmethod
    def filter_contacts(raw_contacts: Dict[str, Any]) -> Dict[str, List[str]]:
        """
        Extracts and filters contacts into valid personal emails, TG, Skype, Discord.
        """
        valid_contacts = {
            "emails": [],
            "telegram": [],
            "discord": [],
            "linkedin": [],
            "twitter_x": [],
            "skype": [],
            "other_socials": []
        }
        
        # Check Emails
        emails = raw_contacts.get("emails", [])
        if isinstance(emails, str):
            emails = [emails]
        for email in emails:
            email_clean = email.strip()
            if LeadValidator.is_valid_email(email_clean):
                valid_contacts["emails"].append(email_clean)
            else:
                logger.debug("Filtered out generic/banned email: %s", email_clean)

        # Check Telegram
        tg = raw_contacts.get("telegram", [])
        if isinstance(tg, str):
            tg = [tg]
        telegram_candidates: List[str] = []
        for handle in tg:
            normalized = handle.strip()
            m = TELEGRAM_REGEX.search(normalized)
            found = None
            if m:
                for g in m.groups():
                    if g:
                        found = g
                        break
            if found:
                candidate = found.lstrip("@")
                candidate = f"@{candidate}"
                if LeadValidator._is_valid_telegram_handle(candidate):
                    telegram_candidates.append(candidate)
            else:
                candidate = normalized.lstrip('@')
                if LeadValidator._is_valid_telegram_handle(candidate):
                    telegram_candidates.append(f"@{candidate}")

        valid_contacts["telegram"] = telegram_candidates

        # Check Skype
        skype = raw_contacts.get("skype", [])
        if isinstance(skype, str):
            skype = [skype]
        for handle in skype:
            match = SKYPE_REGEX.search(handle)
            if match:
                # normalize to the username or live:... form
                val = match.group(1) if match.group(1) else match.group(0)
                if val and val not in valid_contacts["skype"]:
                    valid_contacts["skype"].append(val)
            elif handle.strip():
                valid_contacts["skype"].append(handle.strip())

        # Check Discord
        discord = raw_contacts.get("discord", [])
        if isinstance(discord, str):
            discord = [discord]
        for handle in discord:
            h = handle.strip()
            # invite links
            m_inv = DISCORD_INVITE_REGEX.search(h)
            m_tag = DISCORD_TAG_REGEX.search(h)
            if m_inv:
                invite = m_inv.group(1)
                if invite not in valid_contacts["discord"]:
                    valid_contacts["discord"].append(f"discord.gg/{invite}")
            elif m_tag:
                tag = m_tag.group(1)
                if tag not in valid_contacts["discord"]:
                    valid_contacts["discord"].append(tag)
            elif h:
                # fallback: generic username-like
                if h not in valid_contacts["discord"]:
                    valid_contacts["discord"].append(h)

        # Additional social platforms
        for contact_type in ["linkedin", "twitter_x", "other_socials"]:
            values = raw_contacts.get(contact_type, [])
            if isinstance(values, str):
                values = [values]
            for value in values:
                clean = str(value).strip()
                if clean and clean not in valid_contacts[contact_type]:
                    valid_contacts[contact_type].append(clean)

        # Deduplicate lists
        for k in valid_contacts:
            seen = []
            for item in valid_contacts[k]:
                if item not in seen:
                    seen.append(item)
            valid_contacts[k] = seen

        return valid_contacts

    @staticmethod
    def validate_lead(lead: Dict[str, Any]) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Performs full validation on a lead dictionary.
        Returns (is_valid, rejection_reason, processed_lead).
        """
        name = (lead.get("name") or "").strip()
        status = (lead.get("status") or "").strip()
        geo = (lead.get("geo") or "").strip()

        def _reject(reason: str) -> Tuple[bool, str, None]:
            logger.warning("[DROPPED] Lead '%s' -> Reason: %s", name or "Unknown", reason)
            return False, reason, None

        if not name:
            return _reject("REJECTED: Empty company name")

        # Status filter (case-insensitive)
        if status and status.strip().lower() in {s.lower() for s in EXCLUDED_STATUSES}:
            return _reject(f"REJECTED: Banned Status ({status})")

        # Geo-fence and brand/contact blocking checks
        if geo and not LeadValidator.is_geo_allowed(geo):
            return _reject(f"REJECTED: Explicit geo block ({geo})")

        filtered_contacts = LeadValidator.filter_contacts(lead.get("raw_contacts", {}) or lead.get("contacts", {}))
        lead_for_geo = dict(lead)
        lead_for_geo["raw_contacts"] = filtered_contacts
        geo_allowed, geo_reason = GeoFilter.filter_lead(lead_for_geo)
        if not geo_allowed:
            return _reject(f"REJECTED: {geo_reason}")

        has_contacts = (
            len(filtered_contacts.get("emails", [])) > 0 or
            len(filtered_contacts.get("telegram", [])) > 0 or
            len(filtered_contacts.get("skype", [])) > 0 or
            len(filtered_contacts.get("discord", [])) > 0 or
            len(filtered_contacts.get("linkedin", [])) > 0 or
            len(filtered_contacts.get("twitter_x", [])) > 0 or
            len(filtered_contacts.get("other_socials", [])) > 0
        )

        if not has_contacts:
            return _reject("REJECTED: Empty Contacts")

        validated_telegram = validate_telegram_handles(filtered_contacts.get("telegram", []))
        filtered_contacts["telegram"] = validated_telegram

        if not filtered_contacts["emails"] and not filtered_contacts["telegram"]:
            return _reject("REJECTED: No valid emails or active Telegram handles")

        # Additionally detect banned exact local-part emails among valid emails
        for e in filtered_contacts.get("emails", []):
            local = e.split('@', 1)[0].lower()
            if local in BANNED_EMAIL_PREFIXES:
                return False, f"REJECTED: Banned Email (exact local-part match: {local}@...)", None

        processed_lead = {
            "name": name,
            "vertical": lead.get("vertical", "Gambling/Nutra/Crypto"),
            "geo": geo or "Global",
            "website": lead.get("website", ""),
            "rating": lead.get("rating", ""),
            "status": status or "Active",
            "contacts": filtered_contacts,
            "source": lead.get("source", "Unknown")
        }

        return True, None, processed_lead

    def is_lead_allowed(self, lead: Dict[str, Any]) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Runs full lead validation and returns whether the lead is allowed.
        """
        return self.validate_lead(lead)
