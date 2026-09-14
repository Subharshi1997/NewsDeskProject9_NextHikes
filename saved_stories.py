import json
from pathlib import Path

SAVED_FILE = Path(__file__).parent / "saved_stories.json"

# This is a single local-user tool (no auth -- see docs/PROJECT_AUDIT.md's
# Phase 4 notes), so "saved stories" are just local-machine-wide state, the
# same pattern history.py already uses for query_history.json. A real
# per-browser identity (cookies/localStorage) would need a new dependency
# for no real benefit here, since the one person running this app locally
# *is* the only user.


def load_saved():
    if not SAVED_FILE.exists():
        return []
    try:
        with SAVED_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def save_saved(story_ids):
    with SAVED_FILE.open("w", encoding="utf-8") as f:
        json.dump(list(story_ids), f, indent=2)
