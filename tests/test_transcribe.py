import types

from video_summarizer.transcribe import parse_vtt

VTT = """WEBVTT

00:00:00.000 --> 00:00:02.000
Hello world

00:00:02.000 --> 00:00:05.000
this is a test
"""


def test_parse_vtt_extracts_segments_and_text():
    result = parse_vtt(VTT)
    assert result["segments"] == [
        {"start": 0.0, "text": "Hello world"},
        {"start": 2.0, "text": "this is a test"},
    ]
    assert result["text"] == "Hello world this is a test"


def test_parse_vtt_strips_cue_tags_and_blank_lines():
    vtt = "WEBVTT\n\n00:00:01.500 --> 00:00:03.000\n<c>Tagged</c> line\n"
    result = parse_vtt(vtt)
    assert result["segments"] == [{"start": 1.5, "text": "Tagged line"}]


def test_parse_vtt_decodes_html_entities():
    vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nTom &amp; Jerry &#39;run&#39;\n"
    result = parse_vtt(vtt)
    assert result["segments"] == [{"start": 0.0, "text": "Tom & Jerry 'run'"}]


def test_parse_vtt_handles_hours_in_timestamp():
    vtt = "WEBVTT\n\n01:02:03.500 --> 01:02:05.000\nlate cue\n"
    result = parse_vtt(vtt)
    assert result["segments"] == [{"start": 3723.5, "text": "late cue"}]


import os
from video_summarizer.transcribe import fetch_subtitles


def test_fetch_subtitles_returns_transcript_when_vtt_written(tmp_path):
    vtt_path = tmp_path / "sub.en.vtt"

    def fake_run(cmd, **kwargs):
        vtt_path.write_text(
            "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhi there\n", encoding="utf-8"
        )
        class R: returncode = 0
        return R()

    result = fetch_subtitles("https://example.com/v", tmp_path, run_fn=fake_run)
    assert result is not None
    assert result["source"] == "subtitles"
    assert result["text"] == "hi there"


def test_fetch_subtitles_returns_none_when_no_vtt(tmp_path):
    def fake_run(cmd, **kwargs):
        class R: returncode = 0
        return R()

    assert fetch_subtitles("https://example.com/v", tmp_path, run_fn=fake_run) is None


from video_summarizer.transcribe import (
    extract_audio,
    WHISPER_BACKENDS,
    transcribe_audio,
    _whisper_cpp_backend,
)


def test_extract_audio_builds_ffmpeg_command(tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R: returncode = 0
        return R()

    out = extract_audio("movie.mp4", tmp_path, run_fn=fake_run)
    assert out.endswith(".wav")
    cmd = calls[0]
    assert cmd[0] == "ffmpeg"
    assert "movie.mp4" in cmd
    assert "16000" in cmd  # -ar 16000


def test_default_whisper_backend_registered():
    assert "whisper.cpp" in WHISPER_BACKENDS


def test_transcribe_audio_uses_selected_backend():
    def fake_backend(audio_path, run_fn, model):
        return {"segments": [{"start": 0.0, "text": "spoken"}], "text": "spoken"}

    result = transcribe_audio(
        "a.wav", backend="fake", model="small",
        registry={"fake": fake_backend}, run_fn=lambda *a, **k: None,
    )
    assert result["text"] == "spoken"
    assert result["source"] == "whisper:small"


from video_summarizer.transcribe import resolve_transcript


def test_resolve_uses_subtitles_when_available(tmp_path):
    def subs(url, workdir, run_fn, lang): return {"text": "from subs", "segments": [], "source": "subtitles", "lang": "en"}
    def boom(*a, **k): raise AssertionError("whisper should not run when subs exist")

    result = resolve_transcript(
        "https://example.com/v", is_url=True, workdir=tmp_path,
        whisper_backend="whisper.cpp", model="small",
        fetch_fn=subs, extract_fn=boom, transcribe_fn=boom,
    )
    assert result["text"] == "from subs"


def test_resolve_falls_back_to_whisper_when_no_subs(tmp_path):
    def subs(url, workdir, run_fn, lang): return None
    def extract(video, workdir, run_fn): return "a.wav"
    def whisper(audio, backend, model, run_fn): return {"text": "from whisper", "segments": [], "source": "whisper:small"}

    result = resolve_transcript(
        "https://example.com/v", is_url=True, workdir=tmp_path,
        whisper_backend="whisper.cpp", model="small",
        fetch_fn=subs, acquire_fn=lambda: "media.mp4",
        extract_fn=extract, transcribe_fn=whisper,
    )
    assert result["text"] == "from whisper"


def test_resolve_local_file_skips_subtitle_fetch(tmp_path):
    def subs(*a, **k): raise AssertionError("local files have no subtitles to fetch")
    def extract(video, workdir, run_fn): return "a.wav"
    def whisper(audio, backend, model, run_fn): return {"text": "local", "segments": [], "source": "whisper:small"}

    result = resolve_transcript(
        "/path/movie.mp4", is_url=False, workdir=tmp_path,
        whisper_backend="whisper.cpp", model="small",
        fetch_fn=subs, acquire_fn=lambda: "/path/movie.mp4",
        extract_fn=extract, transcribe_fn=whisper,
    )
    assert result["text"] == "local"


def test_fetch_subtitles_requests_preferred_lang(tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R: returncode = 0
        return R()

    fetch_subtitles("https://example.com/v", tmp_path, run_fn=fake_run, lang="de")
    cmd = calls[0]
    sub_langs = cmd[cmd.index("--sub-langs") + 1]
    assert "de" in sub_langs


def test_fetch_subtitles_detects_language_from_filename(tmp_path):
    vtt_path = tmp_path / "sub.zh-Hans.vtt"

    def fake_run(cmd, **kwargs):
        vtt_path.write_text(
            "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nni hao\n", encoding="utf-8"
        )
        class R: returncode = 0
        return R()

    result = fetch_subtitles("https://example.com/v", tmp_path, run_fn=fake_run, lang="zh")
    assert result["lang"] == "zh-Hans"


def test_resolve_whisper_path_stamps_lang_hint(tmp_path):
    def subs(url, workdir, run_fn, lang): return None
    def extract(video, workdir, run_fn): return "a.wav"
    def whisper(audio, backend, model, run_fn): return {"text": "x", "segments": [], "source": "whisper:small"}

    result = resolve_transcript(
        "https://example.com/v", is_url=True, workdir=tmp_path,
        whisper_backend="whisper.cpp", model="small", lang="fr",
        fetch_fn=subs, acquire_fn=lambda: "media.mp4",
        extract_fn=extract, transcribe_fn=whisper,
    )
    assert result["lang"] == "fr"


def test_resolve_whisper_branch_calls_acquire(tmp_path):
    acquired = []

    def subs(url, workdir, run_fn, lang): return None
    def acquire(): acquired.append(True); return "/local/media.mp4"
    def extract(video, workdir, run_fn):
        assert video == "/local/media.mp4"  # extract receives the acquired path
        return "a.wav"
    def whisper(audio, backend, model, run_fn): return {"text": "w", "segments": [], "source": "whisper:small"}

    resolve_transcript(
        "https://example.com/v", is_url=True, workdir=tmp_path,
        whisper_backend="whisper.cpp", model="small",
        fetch_fn=subs, acquire_fn=acquire, extract_fn=extract, transcribe_fn=whisper,
    )
    assert acquired == [True]


def test_resolve_subtitles_branch_skips_acquire(tmp_path):
    def subs(url, workdir, run_fn, lang): return {"text": "s", "segments": [], "source": "subtitles", "lang": "en"}
    def boom(): raise AssertionError("acquire must not run when subtitles exist")

    result = resolve_transcript(
        "https://example.com/v", is_url=True, workdir=tmp_path,
        whisper_backend="whisper.cpp", model="small",
        fetch_fn=subs, acquire_fn=boom,
    )
    assert result["text"] == "s"


def test_whisper_backend_explicit_lang_normalizes_subtag(tmp_path):
    audio = str(tmp_path / "audio.wav")
    captured = {}

    def run_fn(cmd, capture_output=False, text=True):
        captured["cmd"] = cmd
        of = cmd[cmd.index("-of") + 1]
        with open(of + ".txt", "w", encoding="utf-8") as fh:
            fh.write("你好")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    result = _whisper_cpp_backend(audio, run_fn=run_fn, model="base", lang="zh-Hans")
    cmd = captured["cmd"]
    assert cmd[cmd.index("-l") + 1] == "zh"
    assert result["lang"] == "zh"
    assert result["text"] == "你好"


def test_whisper_backend_auto_parses_detected_language(tmp_path):
    audio = str(tmp_path / "audio.wav")
    captured = {}

    def run_fn(cmd, capture_output=False, text=True):
        captured["cmd"] = cmd
        of = cmd[cmd.index("-of") + 1]
        with open(of + ".txt", "w", encoding="utf-8") as fh:
            fh.write("こんにちは")
        return types.SimpleNamespace(
            returncode=0, stdout="",
            stderr="whisper_full_with_state: auto-detected language: ja (p = 0.98)")

    result = _whisper_cpp_backend(audio, run_fn=run_fn, model="base", lang="auto")
    cmd = captured["cmd"]
    assert cmd[cmd.index("-l") + 1] == "auto"
    assert result["lang"] == "ja"


def test_whisper_backend_auto_parse_miss_leaves_lang_unset(tmp_path):
    audio = str(tmp_path / "audio.wav")

    def run_fn(cmd, capture_output=False, text=True):
        of = cmd[cmd.index("-of") + 1]
        with open(of + ".txt", "w", encoding="utf-8") as fh:
            fh.write("hello")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    result = _whisper_cpp_backend(audio, run_fn=run_fn, model="base", lang="auto")
    assert "lang" not in result
