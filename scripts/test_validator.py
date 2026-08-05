from src.validator import LeadValidator
samples = [
    'info@example.com', 'info123@example.com', 'info-team@example.com',
    'john.info@example.com', 'adminuser@example.com', 'support@example.com',
    'support-team@example.com', 'jane.doe@example.com', 'sales_ops@example.com'
]
for s in samples:
    print(s, LeadValidator.is_valid_email(s))
