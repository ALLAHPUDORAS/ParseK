import sys
sys.path.append('.')
from src.main import validate_leads

# sample raw leads to exercise validators
raw_leads = [
    {"name": "Good Co", "raw_contacts": {"emails": ["john.doe@example.com"]}, "geo": "EU", "status": "Active", "vertical": "Gambling", "source": "Test"},
    {"name": "Role Co", "raw_contacts": {"emails": ["info@roleco.com"]}, "geo": "EU", "status": "Active", "vertical": "Gambling", "source": "Test"},
    {"name": "Maybe Admin", "raw_contacts": {"emails": ["adminuser@company.com"]}, "geo": "EU", "status": "Active", "vertical": "Gambling", "source": "Test"},
    {"name": "No Contacts", "raw_contacts": {"emails": []}, "geo": "EU", "status": "Active", "vertical": "Gambling", "source": "Test"},
    {"name": "RU Company", "raw_contacts": {"emails": ["ivan@example.ru"]}, "geo": "RU", "status": "Active", "vertical": "Gambling", "source": "Test"},
]

valid = validate_leads(raw_leads)
print('Valid leads count:', len(valid))
for v in valid:
    print(v['name'], v.get('contacts'))
