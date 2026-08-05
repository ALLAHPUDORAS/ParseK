"""
Validator Module: Filters companies by GEO, validates contacts via Regex,
filters out generic emails (info@, support@, etc.), and ensures data cleanliness.
"""

import os
import re
import logging
from typing import Dict, Any, Optional, List, Tuple
from src.config import EXCLUDED_GEOS, BANNED_EMAIL_PREFIXES, EXCLUDED_STATUSES

logger = logging.getLogger("LeadPipeline.Validator")

# Regex Patterns
EMAIL_REGEX = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')
TELEGRAM_REGEX = re.compile(r'(?:t\.me/|@|telegram\.me/)([a-zA-Z0-9_]{5,32})', re.IGNORECASE)
SKYPE_REGEX = re.compile(r'(?:skype:|live:)([a-zA-Z0-9_.:-]+)', re.IGNORECASE)
DISCORD_REGEX = re.compile(r'discord(?:\.gg|\.com/invite|app\.com/users)?/([a-zA-Z0-9_#.-]+)', re.IGNORECASE)
INVALID_TELEGRAM_HANDLES = {
    "info", "support", "supports", "admin", "media", "keyframes",
    "font-face", "charset", "document", "pageview", "viewport",
    "import", "function", "return", "window", "script",
    "body", "html", "head", "link", "meta", "style",
    "affplus", "offervault", "affpaying"
}

class LeadValidator:
    @staticmethod
    def is_geo_allowed(geo_str: str) -> bool:
        """
        Checks if the GEO string contains excluded regions (RU, BY, CIS).
        Returns True if GEO is allowed, False if rejected by GEO-Fence.
        """
        if not geo_str:
            return True  # If GEO is not explicitly specified or global, allow for further check
            
        upper_geo = geo_str.upper()
        # Check against explicitly excluded GEO words/codes
        for excluded in EXCLUDED_GEOS:
            if re.search(r'\b' + re.escape(excluded) + r'\b', upper_geo):
                return False
        return True

    @staticmethod
    def is_valid_email(email: str) -> bool:
        """
        Validates if email is not generic/role email (info@, support@, etc.).
        """
        if not email or not EMAIL_REGEX.match(email):
            return False
            
        local_part = email.split('@')[0].lower()

        # Treat as role email only if the local-part *starts with* a banned prefix
        # optionally followed only by separators or digits. This avoids
        # rejecting legitimate addresses that *contain* banned tokens later
        # in the local-part (e.g. "john.adminson@example.com").
        # Example matches: info@, info1@, info-team@, support_123@ -> filtered
        # Non-matches (kept): john.info@, adminuser@example.com
        banned_alternatives = [re.escape(p) for p in BANNED_EMAIL_PREFIXES]
        banned_pattern = r'^(?:' + '|'.join(banned_alternatives) + r')(?:[\W_0-9].*)?$'

        if re.match(banned_pattern, local_part):
            logger.debug("Filtered role email: %s", email)
            return False

        return True

    @staticmethod
    def _is_valid_telegram_handle(handle: str) -> bool:
        handle_value = handle.lower().lstrip("@")
        if handle_value in INVALID_TELEGRAM_HANDLES:
            return False
        return bool(re.match(r"^[a-zA-Z0-9_]{5,32}$", handle_value))

    @staticmethod
    def filter_contacts(raw_contacts: Dict[str, Any]) -> Dict[str, List[str]]:
        """
        Extracts and filters contacts into valid personal emails, TG, Skype, Discord.
        """
        valid_contacts = {
            "emails": [],
            "telegram": [],
            "skype": [],
            "discord": []
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
                logger.debug(f"Filtered out generic/banned email: {email_clean}")

        # Check Telegram
        tg = raw_contacts.get("telegram", [])
        if isinstance(tg, str):
            tg = [tg]
        for handle in tg:
            normalized = handle.strip()
            match = TELEGRAM_REGEX.search(normalized)
            if match:
                clean_handle = f"@{match.group(1)}"
                if LeadValidator._is_valid_telegram_handle(clean_handle) and clean_handle not in valid_contacts["telegram"]:
                    valid_contacts["telegram"].append(clean_handle)
                else:
                    logger.debug("Filtered out invalid telegram handle: %s", clean_handle)
            else:
                candidate = normalized if normalized.startswith("@") else f"@{normalized}"
                if LeadValidator._is_valid_telegram_handle(candidate) and candidate not in valid_contacts["telegram"]:
                    valid_contacts["telegram"].append(candidate)
                else:
                    logger.debug("Filtered out invalid telegram handle: %s", candidate)

        # Check Skype
        skype = raw_contacts.get("skype", [])
        if isinstance(skype, str):
            skype = [skype]
        for handle in skype:
            match = SKYPE_REGEX.search(handle)
            if match:
                valid_contacts["skype"].append(match.group(0))
            elif handle.strip():
                valid_contacts["skype"].append(handle.strip())

        # Check Discord
        discord = raw_contacts.get("discord", [])
        if isinstance(discord, str):
            discord = [discord]
        for handle in discord:
            if handle.strip():
                valid_contacts["discord"].append(handle.strip())

        return valid_contacts

    @staticmethod
    def validate_lead(lead: Dict[str, Any]) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Performs full validation on a lead dictionary.
        Returns (is_valid, rejection_reason, processed_lead).
        """
        name = lead.get("name", "").strip()
        status = lead.get("status", "").strip().upper()
        geo = lead.get("geo", "").strip()
        
        if not name:
            return False, "Empty company name", None
            
        if status in EXCLUDED_STATUSES:
            return False, f"Excluded status: {status}", None
            
        if not LeadValidator.is_geo_allowed(geo):
            return False, f"GEO-Fence filter triggered: {geo}", None
            
        # Process and filter contacts
        filtered_contacts = LeadValidator.filter_contacts(lead.get("raw_contacts", {}))
        
        has_contacts = (
            len(filtered_contacts["emails"]) > 0 or
            len(filtered_contacts["telegram"]) > 0 or
            len(filtered_contacts["skype"]) > 0 or
            len(filtered_contacts["discord"]) > 0
        )
        if not has_contacts:
            return False, "No valid direct contacts (emails filtered out or empty)", None
            
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
