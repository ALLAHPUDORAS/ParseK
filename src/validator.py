"""
Validator Module: Filters companies by GEO, validates contacts via Regex,
filters out generic emails (info@, support@, etc.), and ensures data cleanliness.
"""

import re
import logging
from typing import Dict, Any, Optional, List, Tuple
from src.config import EXCLUDED_GEOS, BANNED_EMAIL_PREFIXES, EXCLUDED_STATUSES

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
        Returns True if GEO is allowed, False if rejected by GEO-Fence.
        """
        if not geo_str:
            return True

        upper_geo = geo_str.strip().upper()
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
        return True

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
                logger.debug("Filtered out generic/banned email: %s", email_clean)

        # Check Telegram
        tg = raw_contacts.get("telegram", [])
        if isinstance(tg, str):
            tg = [tg]
        for handle in tg:
            normalized = handle.strip()
            # Try to extract username from various telegram formats
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
                if LeadValidator._is_valid_telegram_handle(candidate) and candidate not in valid_contacts["telegram"]:
                    valid_contacts["telegram"].append(candidate)
                else:
                    logger.debug("Filtered out invalid telegram handle: %s", candidate)
            else:
                # fallback: if plain token looks like tg username
                candidate = normalized.lstrip('@')
                if LeadValidator._is_valid_telegram_handle(candidate):
                    cand = f"@{candidate}"
                    if cand not in valid_contacts["telegram"]:
                        valid_contacts["telegram"].append(cand)

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

        if not name:
            return False, "REJECTED: Empty company name", None

        # Status filter (case-insensitive)
        if status and status.strip().lower() in {s.lower() for s in EXCLUDED_STATUSES}:
            return False, f"REJECTED: Banned Status ({status})", None

        # Geo-fence: exclude only exact matches
        if geo and not LeadValidator.is_geo_allowed(geo):
            return False, f"REJECTED: Geo-Fence ({geo})", None

        # Process and filter contacts
        filtered_contacts = LeadValidator.filter_contacts(lead.get("raw_contacts", {}))

        has_contacts = (
            len(filtered_contacts.get("emails", [])) > 0 or
            len(filtered_contacts.get("telegram", [])) > 0 or
            len(filtered_contacts.get("skype", [])) > 0 or
            len(filtered_contacts.get("discord", [])) > 0
        )

        if not has_contacts:
            return False, "REJECTED: Empty Contacts", None

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
