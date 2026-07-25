import sys
from pathlib import Path

# make ingest/ importable as a flat package (parse.py, fetch.py)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ingest"))

FIXTURES = ROOT / "tests" / "fixtures"
