import os
import pytest
from video_summarizer import cli
from video_summarizer.errors import ConfigError


def _patch_stages(monkeypatch, visual_called):
    monkeypatch.setattr(cli, "resolve_transcript",
        lambda *a, **k: {"text": "hi", "segments": [{"start": 0.0, "text": "hi"}], "source": "subtitles"})
    monkeypatch.setattr(cli, "summarize",
        lambda *a, **k: {"summary": "s", "chapters": [{"time": "00:00", "title": "Intro"}]})

    def fake_visual(*a, **k):
        visual_called.append(True)
        return {"notes": ["onscreen"]}
    monkeypatch.setattr(cli, "visual_notes", fake_visual)
    monkeypatch.setattr(cli, "make_gemini_client", lambda: object())
    monkeypatch.setattr(cli, "probe_duration", lambda *a, **k: "00:30")
    monkeypatch.setattr(cli, "today_str", lambda: "2026-06-16")


def test_cli_writes_markdown_without_visual(tmp_path, monkeypatch):
    visual_called = []
    _patch_stages(monkeypatch, visual_called)
    monkeypatch.setenv("GEMINI_API_KEY", "x")

    code = cli.main(["https://example.com/v", "--out", str(tmp_path)])
    assert code == 0
    assert visual_called == []  # visual NOT run by default
    files = list(tmp_path.glob("*.md"))
    assert len(files) == 1
    text = files[0].read_text()
    assert "## Summary" in text
    assert "## Visual notes" not in text


def test_cli_runs_visual_when_flag_set(tmp_path, monkeypatch):
    visual_called = []
    _patch_stages(monkeypatch, visual_called)
    monkeypatch.setenv("GEMINI_API_KEY", "x")

    code = cli.main(["movie.mp4", "--visual", "--out", str(tmp_path)])
    assert code == 0
    assert visual_called == [True]
    assert "## Visual notes" in list(tmp_path.glob("*.md"))[0].read_text()


def test_cli_dry_run_writes_nothing(tmp_path, monkeypatch):
    _patch_stages(monkeypatch, [])
    code = cli.main(["movie.mp4", "--dry-run", "--out", str(tmp_path)])
    assert code == 0
    assert list(tmp_path.glob("*.md")) == []


def test_cli_missing_key_returns_exit_2(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    code = cli.main(["movie.mp4", "--out", str(tmp_path)])
    assert code == 2
