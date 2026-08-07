import unittest

from src.geo_filter import GeoFilter
from src.validator import LeadValidator


class LeadValidatorTests(unittest.TestCase):
    def test_is_geo_allowed_matches_substrings_and_variants(self):
        self.assertFalse(LeadValidator.is_geo_allowed("Russia"))
        self.assertFalse(LeadValidator.is_geo_allowed("Russia-based"))
        self.assertFalse(LeadValidator.is_geo_allowed("ru"))
        self.assertFalse(LeadValidator.is_geo_allowed("RU/EE"))
        self.assertFalse(LeadValidator.is_geo_allowed("Belarus"))
        self.assertTrue(LeadValidator.is_geo_allowed("Europe"))
        self.assertTrue(LeadValidator.is_geo_allowed("Global"))

    def test_is_valid_email_filters_generic_prefixes(self):
        self.assertFalse(LeadValidator.is_valid_email("info@example.com"))
        self.assertFalse(LeadValidator.is_valid_email("support123@example.com"))
        self.assertFalse(LeadValidator.is_valid_email("contact_team@example.com"))
        self.assertTrue(LeadValidator.is_valid_email("sales.john@example.com"))
        self.assertTrue(LeadValidator.is_valid_email("adminuser@example.com"))

    def test_is_valid_email_requires_mx_records(self):
        self.assertFalse(LeadValidator.is_valid_email("user@example.invalid"))
        self.assertFalse(LeadValidator.is_valid_email("user@localhost"))

    def test_filter_contacts_deduplicates_and_normalizes_telegram(self):
        raw_contacts = {
            "emails": ["info@example.com", "john.doe@example.com"],
            "telegram": ["t.me/JohnDoe", "@JohnDoe", "john_doe"],
            "skype": ["skype:live:john.doe"],
            "discord": ["discord.gg/test", "JohnDoe#1234"],
            "linkedin": ["https://www.linkedin.com/company/test-company"],
            "twitter_x": ["https://x.com/test-account"],
            "other_socials": ["https://wa.me/123456789"]
        }

        filtered = LeadValidator.filter_contacts(raw_contacts)
        self.assertEqual(filtered["emails"], ["john.doe@example.com"])
        self.assertIn("@JohnDoe", filtered["telegram"])
        self.assertIn("live:john.doe", filtered["skype"])
        self.assertIn("discord.gg/test", filtered["discord"])
        self.assertIn("https://www.linkedin.com/company/test-company", filtered["linkedin"])
        self.assertIn("https://x.com/test-account", filtered["twitter_x"])
        self.assertIn("https://wa.me/123456789", filtered["other_socials"])

    def test_geo_filter_flags_cis_indicators(self):
        self.assertFalse(GeoFilter.is_allowed("RU"))
        self.assertFalse(GeoFilter.is_allowed("Belarus"))
        self.assertFalse(GeoFilter.is_allowed("UKRAINE"))
        self.assertFalse(GeoFilter.is_allowed("CIS / Slavic team"))
        self.assertTrue(GeoFilter.is_allowed("Global"))

    def test_geo_filter_rejects_slavic_email_or_name(self):
        lead = {
            "name": "Ivanov Holdings",
            "website": "example.com",
            "geo": "Global",
            "raw_contacts": {
                "emails": ["ivan@example.com"]
            }
        }
        allowed, reason = GeoFilter.filter_lead(lead)
        self.assertFalse(allowed)
        self.assertEqual(reason, "Slavic/CIS heuristic match (Email/Name pattern)")


if __name__ == "__main__":
    unittest.main()
