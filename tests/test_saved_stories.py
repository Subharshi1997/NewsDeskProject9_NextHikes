import json

import saved_stories


def test_load_saved_returns_empty_list_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(saved_stories, "SAVED_FILE", tmp_path / "does_not_exist.json")
    assert saved_stories.load_saved() == []


def test_load_saved_returns_empty_list_on_corrupt_file(tmp_path, monkeypatch):
    fake_path = tmp_path / "saved_stories.json"
    fake_path.write_text("not valid json", encoding="utf-8")
    monkeypatch.setattr(saved_stories, "SAVED_FILE", fake_path)
    assert saved_stories.load_saved() == []


def test_save_and_load_round_trip(tmp_path, monkeypatch):
    fake_path = tmp_path / "saved_stories.json"
    monkeypatch.setattr(saved_stories, "SAVED_FILE", fake_path)

    saved_stories.save_saved(["story-1", "story-2"])

    assert json.loads(fake_path.read_text(encoding="utf-8")) == ["story-1", "story-2"]
    assert saved_stories.load_saved() == ["story-1", "story-2"]


def test_save_saved_accepts_a_set(tmp_path, monkeypatch):
    fake_path = tmp_path / "saved_stories.json"
    monkeypatch.setattr(saved_stories, "SAVED_FILE", fake_path)

    saved_stories.save_saved({"story-1"})

    assert saved_stories.load_saved() == ["story-1"]
