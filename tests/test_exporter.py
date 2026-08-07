import os
import tempfile
import unittest

from src.exporter import Exporter


class ExporterTests(unittest.TestCase):
    def test_save_leads_creates_excel_and_html_reports(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            exporter = Exporter(output_dir=tmpdir)
            leads = [{
                "name": "Example Corp",
                "vertical": "Crypto",
                "geo": "Europe",
                "website": "https://example.com",
                "status": "Active",
                "source": "test",
                "raw_contacts": {
                    "emails": ["sales@example.com"],
                    "telegram": ["@ExampleBot"],
                    "discord": ["Example#1234"],
                    "linkedin": ["https://linkedin.com/company/example"],
                    "twitter_x": ["https://x.com/example"],
                    "skype": ["live:example"],
                    "other_socials": ["https://wa.me/123456789"]
                }
            }]

            exporter.save_leads(leads)

            self.assertTrue(os.path.exists(os.path.join(tmpdir, "leads.json")))
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "leads.csv")))
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "leads_formatted.xlsx")))
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "leads_report.html")))


if __name__ == "__main__":
    unittest.main()
