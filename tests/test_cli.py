import os
import runpy
import sys
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


def test_cli_title_overrides_h1_and_filename(tmp_path, monkeypatch):
    # The watcher feeds an ugly R2 .mp4 URL but knows the clean title; --title
    # must drive both the H1 and the output filename slug.
    _patch_stages(monkeypatch, [])
    monkeypatch.setenv("GEMINI_API_KEY", "x")

    code = cli.main(["https://r2.example/bilibili-20260616-BV1xx.mp4",
                     "--title", "Clean Human Title", "--out", str(tmp_path)])
    assert code == 0
    files = list(tmp_path.glob("*.md"))
    assert len(files) == 1
    assert files[0].name == "clean-human-title.md"   # filename from --title, not URL slug
    assert "# Clean Human Title" in files[0].read_text()


def test_cli_without_title_falls_back_to_source_derived(tmp_path, monkeypatch):
    _patch_stages(monkeypatch, [])
    monkeypatch.setenv("GEMINI_API_KEY", "x")

    code = cli.main(["https://r2.example/my-clip.mp4", "--out", str(tmp_path)])
    assert code == 0
    files = list(tmp_path.glob("*.md"))
    assert files[0].name == "my-clip.md"             # derived from the source basename
    assert "# my-clip" in files[0].read_text()


def test_cli_duration_from_segments_when_no_media(tmp_path, monkeypatch):
    # URL + subtitles: the media is never downloaded, so ffprobe cannot run on a
    # URL. Duration must fall back to the last transcript cue's start time
    # instead of rendering '??:??'.
    monkeypatch.setattr(cli, "resolve_transcript",
        lambda *a, **k: {"text": "hi",
                         "segments": [{"start": 0.0, "text": "a"},
                                      {"start": 125.0, "text": "b"}],
                         "source": "subtitles"})
    monkeypatch.setattr(cli, "summarize",
        lambda *a, **k: {"tldr": "s", "key_points": [], "takeaways": [], "chapters": []})
    monkeypatch.setattr(cli, "make_gemini_client", lambda: object())
    monkeypatch.setattr(cli, "today_str", lambda: "2026-06-16")
    monkeypatch.setenv("GEMINI_API_KEY", "x")

    code = cli.main(["https://example.com/v", "--out", str(tmp_path)])
    assert code == 0
    text = list(tmp_path.glob("*.md"))[0].read_text()
    assert "duration: 02:05" in text   # 125s -> 02:05, no ffprobe on the URL


def test_cli_duration_probes_local_media_not_url(tmp_path, monkeypatch):
    # URL with no subtitles: media is downloaded for Whisper, so ffprobe must be
    # handed the LOCAL media path — never the source URL (ffprobe can't read a
    # site URL and would yield '??:??').
    monkeypatch.setattr(cli, "acquire_media", lambda *a, **k: "/local/media.mp4")

    def fake_resolve(*a, **k):
        k["acquire_fn"]()  # Whisper branch downloads the media
        return {"text": "hi", "segments": [], "source": "whisper:small", "lang": "en"}
    monkeypatch.setattr(cli, "resolve_transcript", fake_resolve)
    monkeypatch.setattr(cli, "summarize",
        lambda *a, **k: {"tldr": "s", "key_points": [], "takeaways": [], "chapters": []})
    monkeypatch.setattr(cli, "make_gemini_client", lambda: object())
    monkeypatch.setattr(cli, "today_str", lambda: "2026-06-16")
    monkeypatch.setenv("GEMINI_API_KEY", "x")

    seen = {}

    def fake_probe(path, *a, **k):
        seen["path"] = path
        return "10:00"
    monkeypatch.setattr(cli, "probe_duration", fake_probe)

    code = cli.main(["https://r2.example/x.mp4", "--out", str(tmp_path)])
    assert code == 0
    assert seen["path"] == "/local/media.mp4"
    assert "10:00" in list(tmp_path.glob("*.md"))[0].read_text()


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


def test_module_entrypoint_invokes_main(monkeypatch, capsys):
    # `python -m video_summarizer.cli ...` must actually run main(); without a
    # __main__ guard the module just imports (defines functions) and exits 0
    # silently, writing nothing. --dry-run keeps this hermetic (no network/key).
    monkeypatch.setattr(sys, "argv", ["video-summarizer", "movie.mp4", "--dry-run"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("video_summarizer.cli", run_name="__main__")
    assert exc.value.code == 0
    assert "DRY RUN" in capsys.readouterr().out


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

    def fake_visual(video_path, backend, client, **kwargs):
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


def test_cli_claude_backend_uses_anthropic_client_and_default_model(tmp_path, monkeypatch):
    # --summary-backend claude must build an Anthropic client (no GEMINI key),
    # pass it to summarize, and default the model to claude-opus-4-8.
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    sentinel = object()
    monkeypatch.setattr(cli, "make_anthropic_client", lambda: sentinel)
    monkeypatch.setattr(cli, "make_gemini_client",
        lambda: (_ for _ in ()).throw(AssertionError("gemini client must not be built")))
    monkeypatch.setattr(cli, "resolve_transcript",
        lambda *a, **k: {"text": "hi", "segments": [], "source": "subtitles", "lang": "en"})
    monkeypatch.setattr(cli, "today_str", lambda: "2026-06-16")
    captured = {}

    def fake_summary(transcript_text, backend, client, lang, model, **k):
        captured.update(backend=backend, client=client, model=model)
        return {"tldr": "s", "key_points": [], "takeaways": [], "chapters": []}
    monkeypatch.setattr(cli, "summarize", fake_summary)

    code = cli.main(["https://example.com/v", "--summary-backend", "claude",
                     "--out", str(tmp_path)])
    assert code == 0
    assert captured["backend"] == "claude"
    assert captured["client"] is sentinel
    assert captured["model"] == "claude-opus-4-8"


def test_cli_gemini_failure_falls_back_to_claude(tmp_path, monkeypatch, capsys):
    # When the Gemini summary errors (e.g. rate limit) and Claude is configured,
    # the CLI retries on the claude backend instead of degrading to transcript-only.
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setattr(cli, "make_gemini_client", lambda: object())
    monkeypatch.setattr(cli, "make_anthropic_client", lambda: object())
    monkeypatch.setattr(cli, "resolve_transcript",
        lambda *a, **k: {"text": "hi", "segments": [], "source": "subtitles", "lang": "en"})
    monkeypatch.setattr(cli, "today_str", lambda: "2026-06-16")
    calls = []

    def fake_summary(transcript_text, backend, client, lang, model, **k):
        calls.append(backend)
        if backend == "gemini":
            raise RuntimeError("rate limited")
        return {"tldr": "from claude", "key_points": [], "takeaways": [], "chapters": []}
    monkeypatch.setattr(cli, "summarize", fake_summary)

    code = cli.main(["https://example.com/v", "--out", str(tmp_path)])
    assert code == 0
    assert calls == ["gemini", "claude"]
    assert "from claude" in list(tmp_path.glob("*.md"))[0].read_text()
    assert "claude fallback" in capsys.readouterr().err


def test_cli_gemini_failure_without_claude_degrades(tmp_path, monkeypatch):
    # Gemini fails and Claude isn't configured → degrade to transcript-only, exit 1.
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setattr(cli, "make_gemini_client", lambda: object())
    monkeypatch.setattr(cli, "make_anthropic_client",
        lambda: (_ for _ in ()).throw(ConfigError("ANTHROPIC_API_KEY is required")))
    monkeypatch.setattr(cli, "resolve_transcript",
        lambda *a, **k: {"text": "hi", "segments": [{"start": 0.0, "text": "hi"}], "source": "subtitles", "lang": "en"})
    monkeypatch.setattr(cli, "today_str", lambda: "2026-06-16")
    monkeypatch.setattr(cli, "summarize",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))

    code = cli.main(["https://example.com/v", "--out", str(tmp_path)])
    assert code == 1
    assert "_(summary failed)_" in list(tmp_path.glob("*.md"))[0].read_text()


def test_cli_threads_media_resolution_to_visual(tmp_path, monkeypatch):
    captured = {}

    def fake_visual(video_path, backend, client, media_resolution):
        captured["media_resolution"] = media_resolution
        return {"notes": ["x"]}

    monkeypatch.setattr(cli, "resolve_transcript",
        lambda *a, **k: {"text": "hi", "segments": [], "source": "subtitles"})
    monkeypatch.setattr(cli, "summarize",
        lambda *a, **k: {"tldr": "s", "key_points": [], "takeaways": [], "chapters": []})
    monkeypatch.setattr(cli, "visual_notes", fake_visual)
    monkeypatch.setattr(cli, "acquire_media", lambda *a, **k: "/local/media.mp4")
    monkeypatch.setattr(cli, "make_gemini_client", lambda: object())
    monkeypatch.setattr(cli, "probe_duration", lambda *a, **k: "00:30")
    monkeypatch.setattr(cli, "today_str", lambda: "2026-06-16")
    monkeypatch.setenv("GEMINI_API_KEY", "x")

    code = cli.main(["movie.mp4", "--visual", "--media-resolution", "default",
                     "--out", str(tmp_path)])
    assert code == 0
    assert captured["media_resolution"] == "default"


def test_cli_media_resolution_defaults_to_low(tmp_path, monkeypatch):
    captured = {}

    def fake_visual(video_path, backend, client, media_resolution):
        captured["media_resolution"] = media_resolution
        return {"notes": ["x"]}

    monkeypatch.setattr(cli, "resolve_transcript",
        lambda *a, **k: {"text": "hi", "segments": [], "source": "subtitles"})
    monkeypatch.setattr(cli, "summarize",
        lambda *a, **k: {"tldr": "s", "key_points": [], "takeaways": [], "chapters": []})
    monkeypatch.setattr(cli, "visual_notes", fake_visual)
    monkeypatch.setattr(cli, "acquire_media", lambda *a, **k: "/local/media.mp4")
    monkeypatch.setattr(cli, "make_gemini_client", lambda: object())
    monkeypatch.setattr(cli, "probe_duration", lambda *a, **k: "00:30")
    monkeypatch.setattr(cli, "today_str", lambda: "2026-06-16")
    monkeypatch.setenv("GEMINI_API_KEY", "x")

    code = cli.main(["movie.mp4", "--visual", "--out", str(tmp_path)])
    assert code == 0
    assert captured["media_resolution"] == "low"
