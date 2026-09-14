import json

import history as hist


def test_add_entry_extracts_title_and_link_sources():
    articles = [
        {"title": "Article One", "link": "https://example.com/1", "description": "..."},
        {"title": "No link here"},
        {"link": "https://example.com/no-title"},
    ]
    result = hist.add_entry([], "apple earnings", "A summary.", articles)

    assert len(result) == 1
    entry = result[0]
    assert entry["query"] == "apple earnings"
    assert entry["summary"] == "A summary."
    assert entry["sources"] == [{"title": "Article One", "link": "https://example.com/1"}]
    assert "timestamp" in entry


def test_add_entry_caps_history_length():
    history = [{"query": f"q{i}", "summary": "", "sources": [], "timestamp": ""} for i in range(hist.MAX_ENTRIES)]
    result = hist.add_entry(history, "newest", "s", [])

    assert len(result) == hist.MAX_ENTRIES
    assert result[-1]["query"] == "newest"
    assert result[0]["query"] == "q1"


def test_save_and_load_history_round_trip(tmp_path, monkeypatch):
    fake_path = tmp_path / "query_history.json"
    monkeypatch.setattr(hist, "HISTORY_FILE", fake_path)

    history = [{"query": "q", "summary": "s", "sources": [], "timestamp": "t"}]
    hist.save_history(history)

    assert json.loads(fake_path.read_text(encoding="utf-8")) == history
    assert hist.load_history() == history


def test_load_history_returns_empty_list_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(hist, "HISTORY_FILE", tmp_path / "does_not_exist.json")

    assert hist.load_history() == []


def test_load_history_returns_empty_list_on_corrupt_file(tmp_path, monkeypatch):
    fake_path = tmp_path / "query_history.json"
    fake_path.write_text("not valid json", encoding="utf-8")
    monkeypatch.setattr(hist, "HISTORY_FILE", fake_path)

    assert hist.load_history() == []
