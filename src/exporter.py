import csv
import json
import logging
import os
from typing import List, Dict, Any

from src.config import OUTPUT_DIR, DEFAULT_EXPORT_CSV, DEFAULT_EXPORT_JSON, DEFAULT_EXPORT_TEXT

logger = logging.getLogger("LeadPipeline.Exporter")

class Exporter:
    def __init__(self, output_dir: str = OUTPUT_DIR):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def to_json(self, leads: List[Dict[str, Any]], filename: str = DEFAULT_EXPORT_JSON) -> str:
        path = os.path.join(self.output_dir, filename)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(leads, handle, ensure_ascii=False, indent=2)
        logger.info("Exported %d leads to JSON: %s", len(leads), path)
        return path

    def to_csv(self, leads: List[Dict[str, Any]], filename: str = DEFAULT_EXPORT_CSV) -> str:
        path = os.path.join(self.output_dir, filename)
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["name", "vertical", "geo", "website", "status", "source", "contacts"])
            for lead in leads:
                contacts = []
                contact_data = lead.get("contacts", {})
                for contact_type in ["emails", "telegram", "skype", "discord"]:
                    if contact_data.get(contact_type):
                        contacts.append(f"{contact_type}:{','.join(contact_data[contact_type])}")
                writer.writerow([
                    lead.get("name", ""),
                    lead.get("vertical", ""),
                    lead.get("geo", ""),
                    lead.get("website", ""),
                    lead.get("status", ""),
                    lead.get("source", ""),
                    " | ".join(contacts)
                ])
        logger.info("Exported %d leads to CSV: %s", len(leads), path)
        return path

    def to_text(self, leads: List[Dict[str, Any]], filename: str = DEFAULT_EXPORT_TEXT) -> str:
        path = os.path.join(self.output_dir, filename)
        lines = []
        for lead in leads:
            contact_data = lead.get("contacts", {})
            contacts = []
            for contact_type in ["telegram", "skype", "emails", "discord"]:
                if contact_data.get(contact_type):
                    contacts.extend(contact_data[contact_type])
            contact_str = ", ".join(contacts)
            line = f"{lead.get('name', '')} | {lead.get('vertical', '')}/{lead.get('geo', '')} | Contact: {contact_str}"
            lines.append(line)

        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines))

        logger.info("Exported %d leads to text: %s", len(leads), path)
        return path
