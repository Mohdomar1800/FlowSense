import sys
from pathlib import Path

# Make `agent` importable as it is when the app runs (desktop/ on the path).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
