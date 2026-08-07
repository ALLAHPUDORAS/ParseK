"""Run the full data collection pipeline and produce final clean_contacts.csv."""
import os
import sys
import subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SCRIPTS = [
    "scripts/export_raw_leads.py",
    "scripts/enrich_raw_leads.py",
    "scripts/find_external_contacts.py",
    "scripts/build_clean_contacts.py",
]


def run_script(path):
    print("Running", path)
    cmd = [sys.executable, path]
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        raise SystemExit(f"Script failed: {path}")


def main():
    for script in SCRIPTS:
        run_script(script)
    print("Done. Final file: src/output/clean_contacts.csv")


if __name__ == "__main__":
    main()
