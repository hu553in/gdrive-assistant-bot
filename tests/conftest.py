import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "example")
os.environ.setdefault("STORAGE_GOOGLE_DRIVE_FOLDER_IDS", '["example1","example2"]')
