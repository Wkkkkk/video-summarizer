import os
import pytest
from video_summarizer import cli
from video_summarizer.errors import ConfigError


def _patch_stages(monkeypatch, visual_called):
    monkeypatch.setattr(cli, "resolve_transcript",
        lambda *a, **k: {"text": "hi", "segments": [{"start": 0.0, "text": "hi"}], "source": "subtitles"})
    monkeypatch.setattr(cli, "summarize",
        lambda *a, **k: {"tldr": "a summary", "key_points": ["kp one"], "takeaways": ["tk one"], "chapters": [{"time": "00:00", "title": "Intro"}]})

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
    assert "### Key points" in text and "- kp one" in text
    assert "### Takeaways" in text and "- tk one" in text
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


def test_cli_dry_run_reports_language(tmp_path, monkeypatch, capsys):
    _patch_stages(monkeypatch, [])
    cli.main(["movie.mp4", "--dry-run", "--out", str(tmp_path)])
    out = capsys.readouterr().out
    assert "lang=en" in out          # summary fallback
    assert "whisper_lang=auto" in out  # auto-detect by default


def test_cli_missing_key_returns_exit_2(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    code = cli.main(["movie.mp4", "--out", str(tmp_path)])
    assert code == 2


def test_cli_unknown_summary_backend_returns_exit_2(tmp_path, monkeypatch):
    from video_summarizer.errors import ConfigError as _CfgErr
    monkeypatch.setattr(cli, "resolve_transcript",
        lambda *a, **k: {"text": "hi", "segments": [], "source": "subtitles"})
    monkeypatch.setattr(cli, "make_gemini_client", lambda: object())
    monkeypatch.setattr(cli, "probe_duration", lambda *a, **k: "00:30")
    monkeypatch.setattr(cli, "today_str", lambda: "2026-06-16")
    def bad_summary(*a, **k): raise _CfgErr("unknown summary backend: bogus")
    monkeypatch.setattr(cli, "summarize", bad_summary)
    monkeypatch.setenv("GEMINI_API_KEY", "x")

    code = cli.main(["movie.mp4", "--summary-backend", "bogus", "--out", str(tmp_path)])
    assert code == 2


def test_cli_summary_generic_error_writes_transcript_only(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "resolve_transcript",
        lambda *a, **k: {"text": "hi", "segments": [{"start": 0.0, "text": "hi"}], "source": "subtitles"})
    monkeypatch.setattr(cli, "make_gemini_client", lambda: object())
    monkeypatch.setattr(cli, "probe_duration", lambda *a, **k: "00:30")
    monkeypatch.setattr(cli, "today_str", lambda: "2026-06-16")
    def boom_summary(*a, **k): raise RuntimeError("sdk exploded")
    monkeypatch.setattr(cli, "summarize", boom_summary)
    monkeypatch.setenv("GEMINI_API_KEY", "x")

    code = cli.main(["movie.mp4", "--out", str(tmp_path)])
    assert code == 1
    files = list(tmp_path.glob("*.md"))
    assert len(files) == 1
    text = files[0].read_text()
    assert "_(summary failed)_" in text
    assert "## Transcript" in text


def test_cli_summary_language_follows_transcript(tmp_path, monkeypatch):
    # transcript reports zh-Hans (e.g. from Chinese subtitles); the summary
    # stage must be asked to write in that language, not the default --lang.
    monkeypatch.setattr(cli, "resolve_transcript",
        lambda *a, **k: {"text": "ni hao", "segments": [], "source": "subtitles", "lang": "zh-Hans"})
    captured = {}

    def fake_summary(transcript_text, backend, client, lang, **k):
        captured["lang"] = lang
        return {"tldr": "s", "key_points": [], "takeaways": [], "chapters": []}

    monkeypatch.setattr(cli, "summarize", fake_summary)
    monkeypatch.setattr(cli, "make_gemini_client", lambda: object())
    monkeypatch.setattr(cli, "probe_duration", lambda *a, **k: "00:30")
    monkeypatch.setattr(cli, "today_str", lambda: "2026-06-16")
    monkeypatch.setenv("GEMINI_API_KEY", "x")

    code = cli.main(["https://example.com/v", "--out", str(tmp_path)])
    assert code == 0
    assert captured["lang"] == "zh-Hans"


def test_cli_no_lang_uses_auto_whisper_and_en_hint(monkeypatch, tmp_path):
    captured = {}

    def fake_resolve(source, **kwargs):
        captured.update(kwargs)
        return {"segments": [], "text": "hi", "lang": "en", "source": "subtitles"}

    monkeypatch.setattr(cli, "make_gemini_client", lambda: object())
    monkeypatch.setattr(cli, "resolve_transcript", fake_resolve)
    monkeypatch.setattr(cli, "summarize",
                        lambda *a, **k: {"tldr": "s", "key_points": [], "takeaways": [], "chapters": []})
    monkeypatch.setattr(cli, "probe_duration", lambda *a, **k: "00:10")

    rc = cli.main([str(tmp_path / "v.mp4"), "--out", str(tmp_path / "out")])
    assert rc == 0
    assert captured["lang"] == "en"
    assert captured["whisper_lang"] == "auto"


def test_cli_explicit_lang_sets_both(monkeypatch, tmp_path):
    captured = {}

    def fake_resolve(source, **kwargs):
        captured.update(kwargs)
        return {"segments": [], "text": "hi", "lang": "zh", "source": "subtitles"}

    monkeypatch.setattr(cli, "make_gemini_client", lambda: object())
    monkeypatch.setattr(cli, "resolve_transcript", fake_resolve)
    monkeypatch.setattr(cli, "summarize",
                        lambda *a, **k: {"tldr": "s", "key_points": [], "takeaways": [], "chapters": []})
    monkeypatch.setattr(cli, "probe_duration", lambda *a, **k: "00:10")

    rc = cli.main([str(tmp_path / "v.mp4"), "--lang", "zh",
                   "--out", str(tmp_path / "out")])
    assert rc == 0
    assert captured["lang"] == "zh"
    assert captured["whisper_lang"] == "zh"


def test_cli_downloads_media_once_for_whisper_and_visual(tmp_path, monkeypatch):
    # A URL source with no subtitles + --visual: both the Whisper branch and the
    # visual stage need the media, but it must be downloaded only once and the
    # visual stage must receive the LOCAL path, not the URL.
    calls = {"n": 0}

    def fake_acquire(source, is_url, workdir, run_fn=None):
        calls["n"] += 1
        return "/local/media.mp4"
    monkeypatch.setattr(cli, "acquire_media", fake_acquire)

    def fake_resolve(*a, **k):
        media = k["acquire_fn"]()  # simulate the Whisper branch acquiring media
        return {"text": "hi", "segments": [], "source": "whisper:base.en", "lang": "en"}
    monkeypatch.setattr(cli, "resolve_transcript", fake_resolve)

    captured = {}

    def fake_visual(video_path, backend, client):
        captured["video_path"] = video_path
        return {"notes": ["onscreen"]}
    monkeypatch.setattr(cli, "visual_notes", fake_visual)
    monkeypatch.setattr(cli, "summarize", lambda *a, **k: {"tldr": "s", "key_points": [], "takeaways": [], "chapters": []})
    monkeypatch.setattr(cli, "make_gemini_client", lambda: object())
    monkeypatch.setattr(cli, "probe_duration", lambda *a, **k: "00:30")
    monkeypatch.setattr(cli, "today_str", lambda: "2026-06-16")
    monkeypatch.setenv("GEMINI_API_KEY", "x")

    code = cli.main(["https://r2.example/x.mp4", "--visual", "--out", str(tmp_path)])
    assert code == 0
    assert calls["n"] == 1                          # downloaded exactly once
    assert captured["video_path"] == "/local/media.mp4"  # visual got the local path


def test_cli_threads_summary_model(tmp_path, monkeypatch):
    captured = {}

    def fake_summary(transcript_text, backend, client, lang, model, **k):
        captured["model"] = model
        captured["backend"] = backend
        return {"tldr": "s", "key_points": [], "takeaways": [], "chapters": []}

    monkeypatch.setattr(cli, "resolve_transcript",
        lambda *a, **k: {"text": "hi", "segments": [], "source": "subtitles"})
    monkeypatch.setattr(cli, "summarize", fake_summary)
    monkeypatch.setattr(cli, "make_gemini_client", lambda: object())
    monkeypatch.setattr(cli, "probe_duration", lambda *a, **k: "00:30")
    monkeypatch.setattr(cli, "today_str", lambda: "2026-06-16")
    monkeypatch.setenv("GEMINI_API_KEY", "x")

    code = cli.main(["movie.mp4", "--summary-model", "gemini-flash-latest",
                     "--out", str(tmp_path)])
    assert code == 0
    assert captured["model"] == "gemini-flash-latest"
    assert captured["backend"] == "gemini"   # new default backend key


def test_cli_summary_model_defaults_to_pro(tmp_path, monkeypatch):
    captured = {}

    def fake_summary(transcript_text, backend, client, lang, model, **k):
        captured["model"] = model
        return {"tldr": "s", "key_points": [], "takeaways": [], "chapters": []}

    monkeypatch.setattr(cli, "resolve_transcript",
        lambda *a, **k: {"text": "hi", "segments": [], "source": "subtitles"})
    monkeypatch.setattr(cli, "summarize", fake_summary)
    monkeypatch.setattr(cli, "make_gemini_client", lambda: object())
    monkeypatch.setattr(cli, "probe_duration", lambda *a, **k: "00:30")
    monkeypatch.setattr(cli, "today_str", lambda: "2026-06-16")
    monkeypatch.setenv("GEMINI_API_KEY", "x")

    code = cli.main(["movie.mp4", "--out", str(tmp_path)])
    assert code == 0
    assert captured["model"] == "gemini-2.5-pro"
