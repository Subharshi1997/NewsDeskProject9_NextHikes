import json
from datetime import datetime, timezone
from pathlib import Path

HISTORY_FILE = Path(__file__).parent / "query_history.json"
MAX_ENTRIES = 50


def load_history():
    if not HISTORY_FILE.exists():
        return []
    try:
        with HISTORY_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def save_history(history):
    with HISTORY_FILE.open("w", encoding="utf-8") as f:
        json.dump(history[-MAX_ENTRIES:], f, indent=2)


def add_entry(history, query, summary, articles):
    sources = [
        {"title": a.get("title"), "link": a.get("link")}
        for a in articles
        if a.get("title") and a.get("link")
    ]
    history.append(
        {
            "query": query,
            "summary": summary,
            "sources": sources,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    return history[-MAX_ENTRIES:]
