# video-summarizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone CLI that turns a video (local file, direct URL, or yt-dlp site URL) into one structured markdown file — transcript + summary + chapters, plus opt-in on-screen visual notes.

**Architecture:** A three-stage cheap-first pipeline. Stage 1 resolves a transcript (reuse yt-dlp subtitles if present, else extract audio with ffmpeg and run Whisper). Stage 2 sends the transcript text to a cheap LLM for summary + chapters. Stage 3 (opt-in `--visual`) runs a Gemini Pro video pass. Each stage resolves its work through a small backend registry (`name -> function`), and every backend takes an injected client/`run_fn` so tests never touch the network, a GPU, or real binaries. `cli.py` is the only module that knows all three stages.

**Tech Stack:** Python 3.11+, `pytest`, `argparse`, `google-genai` (Gemini), external CLI tools `yt-dlp` / `ffmpeg` / `whisper.cpp` (invoked via `subprocess`, injected as `run_fn` in tests). `src/` layout, console entry point `video-summarizer`.

---

## File Structure

- `pyproject.toml` — package metadata, deps, console entry point, pytest config.
- `.gitignore` — ignore `.env`, `analyses/`, `__pycache__/`, `*.egg-info`, temp wavs.
- `.env.example` — documents `GEMINI_API_KEY`.
- `README.md` — install + usage.
- `src/video_summarizer/__init__.py` — package marker + version.
- `src/video_summarizer/errors.py` — `ConfigError` (exit 2) and `StageError` (partial/exit 1) exception types shared across modules.
- `src/video_summarizer/transcribe.py` — Stage 1: subtitle fetch (yt-dlp), audio extraction (ffmpeg), Whisper backend registry, `resolve_transcript()` orchestrator.
- `src/video_summarizer/summarize.py` — Stage 2: summarizer backend registry, `summarize()` dispatcher, default `gemini-flash` backend.
- `src/video_summarizer/visual.py` — Stage 3: visualizer backend registry, `visual_notes()` dispatcher, default `gemini-pro` backend.
- `src/video_summarizer/render.py` — assemble the final markdown string + compute output filename/slug.
- `src/video_summarizer/cli.py` — argparse, orchestration (tiering), exit codes.
- `tests/test_transcribe.py`, `tests/test_summarize.py`, `tests/test_visual.py`, `tests/test_render.py`, `tests/test_cli.py`.

**Shared data shapes** (plain dicts, used across modules):
- Transcript: `{"text": str, "segments": [{"start": float, "text": str}], "source": str}` where `source` is `"subtitles"` or `"whisper:<model>"`.
- Analysis: `{"summary": str, "chapters": [{"time": str, "title": str}]}` where `time` is `"MM:SS"`.
- Visual: `{"notes": [str]}`.

---

## Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `src/video_summarizer/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "video-summarizer"
version = "0.1.0"
description = "Turn a video into a structured markdown: transcript + summary + chapters + optional visual notes."
requires-python = ">=3.11"
dependencies = ["google-genai>=1.0.0"]

[project.optional-dependencies]
dev = ["pytest>=8.0.0"]

[project.scripts]
video-summarizer = "video_summarizer.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 2: Write `.gitignore`**

```gitignore
.env
analyses/
__pycache__/
*.egg-info/
*.pyc
*.wav
.venv/
```

- [ ] **Step 3: Write `.env.example`**

```bash
# Required for the default summarizer (gemini-flash) and for --visual (gemini-pro).
# Not required if you select a local summary backend and omit --visual.
GEMINI_API_KEY=your-key-here
```

- [ ] **Step 4: Write `src/video_summarizer/__init__.py`**

```python
"""video-summarizer: video -> structured markdown (transcript + summary + chapters + optional visual notes)."""

__version__ = "0.1.0"
```

- [ ] **Step 5: Write `tests/__init__.py`**

```python
```

- [ ] **Step 6: Verify the toolchain runs**

Run: `cd /Users/kunwu/Workspace/playground/video-summarizer && python3 -m pytest -q`
Expected: `no tests ran` (exit code 5) — confirms pytest is importable and config is valid.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .gitignore .env.example src/video_summarizer/__init__.py tests/__init__.py
git commit -m "chore: project scaffold (pyproject, gitignore, package skeleton)"
```

---

## Task 2: Error types

**Files:**
- Create: `src/video_summarizer/errors.py`
- Test: `tests/test_render.py` (the import smoke test lives with render; errors have no behavior to test on their own)

- [ ] **Step 1: Write `src/video_summarizer/errors.py`**

```python
"""Shared exception types.

ConfigError  -> usage/config problem before any work was done; CLI maps to exit 2.
StageError   -> a single pipeline stage failed; isolated so other stages still run; CLI maps to exit 1.
"""


class ConfigError(Exception):
    """Missing required tool, env var, or invalid arguments."""


class StageError(Exception):
    """A pipeline stage failed but the run can continue with partial output."""
```

- [ ] **Step 2: Commit**

```bash
git add src/video_summarizer/errors.py
git commit -m "feat: shared ConfigError/StageError exception types"
```

---

## Task 3: Subtitle parsing (VTT → transcript)

**Files:**
- Create: `src/video_summarizer/transcribe.py`
- Test: `tests/test_transcribe.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_transcribe.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_transcribe.py -v`
Expected: FAIL with `ImportError: cannot import name 'parse_vtt'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/video_summarizer/transcribe.py
"""Stage 1: resolve a transcript, cheapest source first.

Order: yt-dlp subtitles (URL sources) -> ffmpeg audio extraction + Whisper.
All subprocess calls go through an injected `run_fn` (default subprocess.run)
so tests never invoke real binaries.
"""

import re

_TS = re.compile(r"(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})\s*-->")
_TAG = re.compile(r"<[^>]+>")


def _ts_to_seconds(h, m, s, ms) -> float:
    return (int(h or 0) * 3600) + (int(m) * 60) + int(s) + int(ms) / 1000.0


def parse_vtt(text: str) -> dict:
    """Parse WebVTT into {'segments': [{'start','text'}], 'text': str}."""
    segments = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = _TS.search(lines[i])
        if m:
            start = _ts_to_seconds(*m.groups())
            i += 1
            cue_lines = []
            while i < len(lines) and lines[i].strip():
                cue_lines.append(_TAG.sub("", lines[i]).strip())
                i += 1
            cue = " ".join(p for p in cue_lines if p)
            if cue:
                segments.append({"start": start, "text": cue})
        else:
            i += 1
    return {"segments": segments, "text": " ".join(s["text"] for s in segments)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_transcribe.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/video_summarizer/transcribe.py tests/test_transcribe.py
git commit -m "feat: parse WebVTT subtitles into transcript segments"
```

---

## Task 4: Subtitle fetch via yt-dlp

**Files:**
- Modify: `src/video_summarizer/transcribe.py`
- Test: `tests/test_transcribe.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_transcribe.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_transcribe.py -k fetch_subtitles -v`
Expected: FAIL with `ImportError: cannot import name 'fetch_subtitles'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to src/video_summarizer/transcribe.py
import glob
import os
import subprocess


def fetch_subtitles(url: str, workdir, run_fn=subprocess.run) -> dict | None:
    """Try to download subtitles/auto-captions for `url`. Returns a transcript
    dict (with source='subtitles') or None if no subtitle track was produced."""
    out_tmpl = os.path.join(str(workdir), "sub")
    cmd = [
        "yt-dlp", "--write-subs", "--write-auto-subs",
        "--sub-format", "vtt", "--sub-langs", "en.*,en",
        "--skip-download", "-o", out_tmpl, "--", url,
    ]
    run_fn(cmd, capture_output=True, text=True)
    vtts = sorted(glob.glob(os.path.join(str(workdir), "*.vtt")))
    if not vtts:
        return None
    with open(vtts[0], encoding="utf-8") as fh:
        parsed = parse_vtt(fh.read())
    if not parsed["text"]:
        return None
    parsed["source"] = "subtitles"
    return parsed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_transcribe.py -k fetch_subtitles -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/video_summarizer/transcribe.py tests/test_transcribe.py
git commit -m "feat: fetch subtitles via yt-dlp (skip-download)"
```

---

## Task 5: Audio extraction + Whisper backend registry

**Files:**
- Modify: `src/video_summarizer/transcribe.py`
- Test: `tests/test_transcribe.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_transcribe.py
from video_summarizer.transcribe import extract_audio, WHISPER_BACKENDS, transcribe_audio


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_transcribe.py -k "audio or whisper" -v`
Expected: FAIL with `ImportError` for `extract_audio` / `WHISPER_BACKENDS` / `transcribe_audio`

- [ ] **Step 3: Write minimal implementation**

```python
# append to src/video_summarizer/transcribe.py
from .errors import ConfigError, StageError


def extract_audio(video_path: str, workdir, run_fn=subprocess.run) -> str:
    """Extract 16kHz mono WAV from a video via ffmpeg. Returns the wav path."""
    out = os.path.join(str(workdir), "audio.wav")
    cmd = ["ffmpeg", "-y", "-i", video_path, "-ar", "16000", "-ac", "1", out]
    proc = run_fn(cmd, capture_output=True, text=True)
    if getattr(proc, "returncode", 0) != 0:
        raise StageError("ffmpeg audio extraction failed")
    return out


def _whisper_cpp_backend(audio_path: str, run_fn, model: str) -> dict:
    """Run whisper.cpp (`whisper-cli`) and read its plain-text output."""
    out_base = audio_path + ".out"
    cmd = ["whisper-cli", "-m", f"models/ggml-{model}.bin",
           "-f", audio_path, "-otxt", "-of", out_base]
    proc = run_fn(cmd, capture_output=True, text=True)
    if getattr(proc, "returncode", 0) != 0:
        raise StageError("whisper.cpp transcription failed")
    with open(out_base + ".txt", encoding="utf-8") as fh:
        text = fh.read().strip()
    return {"segments": [{"start": 0.0, "text": text}], "text": text}


WHISPER_BACKENDS = {"whisper.cpp": _whisper_cpp_backend}


def transcribe_audio(audio_path: str, backend: str, model: str,
                     registry=None, run_fn=subprocess.run) -> dict:
    """Dispatch to a Whisper backend; stamps source='whisper:<model>'."""
    registry = WHISPER_BACKENDS if registry is None else registry
    fn = registry.get(backend)
    if fn is None:
        raise ConfigError(f"unknown whisper backend: {backend}")
    result = fn(audio_path, run_fn=run_fn, model=model)
    result["source"] = f"whisper:{model}"
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_transcribe.py -k "audio or whisper" -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/video_summarizer/transcribe.py tests/test_transcribe.py
git commit -m "feat: ffmpeg audio extraction + pluggable Whisper backend (default whisper.cpp)"
```

---

## Task 6: Transcript resolver (tiering: subs → whisper)

**Files:**
- Modify: `src/video_summarizer/transcribe.py`
- Test: `tests/test_transcribe.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_transcribe.py
from video_summarizer.transcribe import resolve_transcript


def test_resolve_uses_subtitles_when_available(tmp_path):
    def subs(url, workdir, run_fn): return {"text": "from subs", "segments": [], "source": "subtitles"}
    def boom(*a, **k): raise AssertionError("whisper should not run when subs exist")

    result = resolve_transcript(
        "https://example.com/v", is_url=True, workdir=tmp_path,
        whisper_backend="whisper.cpp", model="small",
        fetch_fn=subs, extract_fn=boom, transcribe_fn=boom,
    )
    assert result["text"] == "from subs"


def test_resolve_falls_back_to_whisper_when_no_subs(tmp_path):
    def subs(url, workdir, run_fn): return None
    def extract(video, workdir, run_fn): return "a.wav"
    def whisper(audio, backend, model, run_fn): return {"text": "from whisper", "segments": [], "source": "whisper:small"}

    result = resolve_transcript(
        "https://example.com/v", is_url=True, workdir=tmp_path,
        whisper_backend="whisper.cpp", model="small",
        fetch_fn=subs, extract_fn=extract, transcribe_fn=whisper,
    )
    assert result["text"] == "from whisper"


def test_resolve_local_file_skips_subtitle_fetch(tmp_path):
    def subs(*a, **k): raise AssertionError("local files have no subtitles to fetch")
    def extract(video, workdir, run_fn): return "a.wav"
    def whisper(audio, backend, model, run_fn): return {"text": "local", "segments": [], "source": "whisper:small"}

    result = resolve_transcript(
        "/path/movie.mp4", is_url=False, workdir=tmp_path,
        whisper_backend="whisper.cpp", model="small",
        fetch_fn=subs, extract_fn=extract, transcribe_fn=whisper,
    )
    assert result["text"] == "local"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_transcribe.py -k resolve -v`
Expected: FAIL with `ImportError: cannot import name 'resolve_transcript'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to src/video_summarizer/transcribe.py
def resolve_transcript(source: str, is_url: bool, workdir, whisper_backend: str,
                       model: str, run_fn=subprocess.run,
                       fetch_fn=fetch_subtitles, extract_fn=extract_audio,
                       transcribe_fn=transcribe_audio) -> dict:
    """Cheapest source first: subtitles (URLs only) -> ffmpeg + Whisper."""
    if is_url:
        subs = fetch_fn(source, workdir, run_fn=run_fn)
        if subs is not None:
            return subs
    audio = extract_fn(source, workdir, run_fn=run_fn)
    return transcribe_fn(audio, backend=whisper_backend, model=model, run_fn=run_fn)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_transcribe.py -k resolve -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/video_summarizer/transcribe.py tests/test_transcribe.py
git commit -m "feat: transcript resolver with subs->whisper tiering"
```

---

## Task 7: Summarizer (Stage 2) — registry + JSON parsing

**Files:**
- Create: `src/video_summarizer/summarize.py`
- Test: `tests/test_summarize.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_summarize.py
import pytest
from video_summarizer.summarize import summarize, SUMMARIZERS
from video_summarizer.errors import ConfigError


def test_default_summarizer_registered():
    assert "gemini-flash" in SUMMARIZERS


def test_summarize_dispatches_to_backend():
    def fake(transcript_text, client, lang):
        return {"summary": "it is about X", "chapters": [{"time": "00:00", "title": "Intro"}]}

    result = summarize("some transcript", backend="fake", client=object(),
                       lang="en", registry={"fake": fake})
    assert result["summary"] == "it is about X"
    assert result["chapters"][0]["title"] == "Intro"


def test_summarize_unknown_backend_raises_config_error():
    with pytest.raises(ConfigError):
        summarize("t", backend="nope", client=None, lang="en", registry={})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_summarize.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'video_summarizer.summarize'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/video_summarizer/summarize.py
"""Stage 2: summary + chapters from transcript text via a pluggable text LLM.

Backends take (transcript_text, client, lang) and return
{'summary': str, 'chapters': [{'time': 'MM:SS', 'title': str}]}.
The Gemini client is injected so tests never call the network.
"""

import json

from .errors import ConfigError, StageError

_PROMPT = (
    "You are summarizing a video transcript. Respond with ONLY a JSON object "
    'with keys "summary" (a 3-5 sentence string) and "chapters" (a list of '
    '{"time": "MM:SS", "title": string}). Transcript follows:\n\n'
)


def _extract_json(text: str) -> dict:
    """Pull the first {...} JSON object out of an LLM response."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise StageError("summarizer returned no JSON object")
    return json.loads(text[start : end + 1])


def _gemini_flash_backend(transcript_text: str, client, lang: str) -> dict:
    resp = client.models.generate_content(
        model="gemini-flash-latest",
        contents=_PROMPT + transcript_text,
    )
    data = _extract_json(resp.text)
    return {"summary": data.get("summary", ""), "chapters": data.get("chapters", [])}


SUMMARIZERS = {"gemini-flash": _gemini_flash_backend}


def summarize(transcript_text: str, backend: str, client, lang: str,
              registry=None) -> dict:
    registry = SUMMARIZERS if registry is None else registry
    fn = registry.get(backend)
    if fn is None:
        raise ConfigError(f"unknown summary backend: {backend}")
    return fn(transcript_text, client=client, lang=lang)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_summarize.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/video_summarizer/summarize.py tests/test_summarize.py
git commit -m "feat: Stage 2 summarizer (pluggable, default gemini-flash)"
```

---

## Task 8: Visual notes (Stage 3, opt-in)

**Files:**
- Create: `src/video_summarizer/visual.py`
- Test: `tests/test_visual.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_visual.py
import pytest
from video_summarizer.visual import visual_notes, VISUALIZERS
from video_summarizer.errors import ConfigError


def test_default_visualizer_registered():
    assert "gemini-pro" in VISUALIZERS


def test_visual_notes_dispatches_to_backend():
    def fake(video_path, client): return {"notes": ["a chart on screen", "title card"]}

    result = visual_notes("movie.mp4", backend="fake", client=object(),
                          registry={"fake": fake})
    assert result["notes"] == ["a chart on screen", "title card"]


def test_visual_notes_unknown_backend_raises_config_error():
    with pytest.raises(ConfigError):
        visual_notes("movie.mp4", backend="nope", client=None, registry={})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_visual.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'video_summarizer.visual'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/video_summarizer/visual.py
"""Stage 3 (opt-in): on-screen visual notes via Gemini Pro video-native.

Backends take (video_path, client) and return {'notes': [str]}.
This is the only token-heavy stage; the CLI runs it only when --visual is set.
"""

from .errors import ConfigError, StageError

_PROMPT = (
    "Watch this video and list concise bullet notes about what appears ON SCREEN "
    "(visible text, charts, scenes, key visuals) that the audio alone would miss. "
    "Respond with one note per line, no numbering."
)


def _gemini_pro_backend(video_path: str, client) -> dict:
    uploaded = client.files.upload(file=video_path)
    resp = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=[uploaded, _PROMPT],
    )
    notes = [line.strip("-• ").strip() for line in resp.text.splitlines() if line.strip()]
    return {"notes": notes}


VISUALIZERS = {"gemini-pro": _gemini_pro_backend}


def visual_notes(video_path: str, backend: str, client, registry=None) -> dict:
    registry = VISUALIZERS if registry is None else registry
    fn = registry.get(backend)
    if fn is None:
        raise ConfigError(f"unknown visual backend: {backend}")
    return fn(video_path, client=client)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_visual.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/video_summarizer/visual.py tests/test_visual.py
git commit -m "feat: Stage 3 opt-in visual notes (pluggable, default gemini-pro)"
```

---

## Task 9: Markdown rendering + output path

**Files:**
- Create: `src/video_summarizer/render.py`
- Test: `tests/test_render.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_render.py
from video_summarizer.render import slugify, render_markdown


def test_slugify_ascii_lowercase_hyphen():
    assert slugify("My Great Video!") == "my-great-video"
    assert slugify("  spaces   and--dashes ") == "spaces-and-dashes"


def test_render_markdown_without_visual_omits_section():
    md = render_markdown(
        title="Talk", source="https://x/v", duration="12:00", date="2026-06-16",
        transcript={"text": "hello", "segments": [{"start": 0.0, "text": "hello"}], "source": "subtitles"},
        analysis={"summary": "a talk", "chapters": [{"time": "00:00", "title": "Start"}]},
        visual=None,
    )
    assert "# Talk" in md
    assert "transcript-source: subtitles" in md
    assert "## Summary" in md and "a talk" in md
    assert "## Chapters" in md and "00:00 — Start" in md
    assert "## Visual notes" not in md
    assert "## Transcript" in md and "[00:00] hello" in md


def test_render_markdown_with_visual_includes_section():
    md = render_markdown(
        title="Talk", source="movie.mp4", duration="01:00", date="2026-06-16",
        transcript={"text": "hi", "segments": [{"start": 0.0, "text": "hi"}], "source": "whisper:small"},
        analysis={"summary": "s", "chapters": []},
        visual={"notes": ["chart on screen"]},
    )
    assert "## Visual notes" in md
    assert "- chart on screen" in md
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_render.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'video_summarizer.render'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/video_summarizer/render.py
"""Assemble the final markdown document and compute the output filename."""

import re


def slugify(title: str) -> str:
    s = title.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _fmt_seconds(secs: float) -> str:
    total = int(secs)
    return f"{total // 60:02d}:{total % 60:02d}"


def render_markdown(title, source, duration, date, transcript, analysis, visual) -> str:
    lines = [
        f"# {title}",
        f"_{source} · {duration} · {date} · transcript-source: {transcript['source']}_",
        "",
        "## Summary",
        analysis.get("summary", ""),
        "",
        "## Chapters",
    ]
    for ch in analysis.get("chapters", []):
        lines.append(f"- {ch['time']} — {ch['title']}")
    if not analysis.get("chapters"):
        lines.append("_(none)_")
    if visual is not None:
        lines += ["", "## Visual notes"]
        for note in visual.get("notes", []):
            lines.append(f"- {note}")
    lines += ["", "## Transcript"]
    for seg in transcript.get("segments", []):
        lines.append(f"[{_fmt_seconds(seg['start'])}] {seg['text']}")
    if not transcript.get("segments"):
        lines.append(transcript.get("text", ""))
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_render.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/video_summarizer/render.py tests/test_render.py
git commit -m "feat: markdown rendering + slugify"
```

---

## Task 10: CLI orchestration + exit codes

**Files:**
- Create: `src/video_summarizer/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'video_summarizer.cli'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/video_summarizer/cli.py
"""CLI + orchestration for video-summarizer.

Pipeline: resolve_transcript (Stage 1) -> summarize (Stage 2)
-> visual_notes (Stage 3, only with --visual) -> render markdown to --out.
"""

import argparse
import datetime
import os
import subprocess
import sys
import tempfile

from .errors import ConfigError, StageError
from .render import render_markdown, slugify
from .summarize import summarize
from .transcribe import resolve_transcript
from .visual import visual_notes

_URL_PREFIXES = ("http://", "https://")


def today_str() -> str:
    return datetime.date.today().isoformat()


def probe_duration(source: str, run_fn=subprocess.run) -> str:
    """ffprobe duration as MM:SS; best-effort, returns '??:??' on failure."""
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "default=nw=1:nk=1", source]
    try:
        proc = run_fn(cmd, capture_output=True, text=True)
        secs = int(float(proc.stdout.strip()))
        return f"{secs // 60:02d}:{secs % 60:02d}"
    except Exception:
        return "??:??"


def make_gemini_client():
    """Build a Gemini client from GEMINI_API_KEY. Raises ConfigError if unset."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise ConfigError("GEMINI_API_KEY is required (set it or use a local backend)")
    from google import genai
    return genai.Client(api_key=key)


def _title_from_source(source: str) -> str:
    base = os.path.basename(source.rstrip("/")) or source
    return os.path.splitext(base)[0] or "video"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    p = argparse.ArgumentParser(prog="video-summarizer")
    p.add_argument("source", help="local file, direct URL, or yt-dlp site URL")
    p.add_argument("--visual", action="store_true", help="run opt-in Gemini Pro visual pass")
    p.add_argument("--out", default="./analyses", help="output directory")
    p.add_argument("--whisper-backend", default="whisper.cpp")
    p.add_argument("--summary-backend", default="gemini-flash")
    p.add_argument("--whisper-model", default="small")
    p.add_argument("--lang", default="en")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    is_url = args.source.startswith(_URL_PREFIXES)
    title = _title_from_source(args.source)

    if args.dry_run:
        plan = (f"source={args.source} is_url={is_url} visual={args.visual} "
                f"whisper={args.whisper_backend}:{args.whisper_model} "
                f"summary={args.summary_backend} out={args.out}")
        print("DRY RUN — would run:\n  " + plan)
        return 0

    try:
        client = make_gemini_client()
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    exit_code = 0
    with tempfile.TemporaryDirectory() as workdir:
        try:
            transcript = resolve_transcript(
                args.source, is_url=is_url, workdir=workdir,
                whisper_backend=args.whisper_backend, model=args.whisper_model)
        except ConfigError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        except StageError as e:
            print(f"error: transcript failed: {e}", file=sys.stderr)
            return 1

        try:
            analysis = summarize(transcript["text"], backend=args.summary_backend,
                                 client=client, lang=args.lang)
        except StageError as e:
            print(f"warning: summary failed: {e}", file=sys.stderr)
            analysis = {"summary": "_(summary failed)_", "chapters": []}
            exit_code = 1

        visual = None
        if args.visual:
            try:
                visual = visual_notes(args.source, backend="gemini-pro", client=client)
            except StageError as e:
                print(f"warning: visual notes failed: {e}", file=sys.stderr)
                exit_code = 1

        md = render_markdown(
            title=title, source=args.source,
            duration=probe_duration(args.source), date=today_str(),
            transcript=transcript, analysis=analysis, visual=visual)

        os.makedirs(args.out, exist_ok=True)
        out_path = os.path.join(args.out, f"{slugify(title)}.md")
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(md)
        print(out_path)

    return exit_code
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_cli.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest -q`
Expected: PASS (all tests across the 5 test files)

- [ ] **Step 6: Commit**

```bash
git add src/video_summarizer/cli.py tests/test_cli.py
git commit -m "feat: CLI orchestration, --visual gate, exit codes"
```

---

## Task 11: README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`**

````markdown
# video-summarizer

Turn a video (local file, direct URL, or yt-dlp site URL) into one structured
markdown file — transcript + summary + chapters, plus opt-in on-screen visual
notes. Read the markdown to summarize and ask questions about the video.

## How it works (cheap-first)

1. **Transcript** — reuse `yt-dlp` subtitles if present; else extract audio with
   `ffmpeg` and transcribe with Whisper (`whisper.cpp` by default).
2. **Summary + chapters** — a cheap text LLM (`gemini-flash`) over the transcript.
3. **Visual notes** — opt-in (`--visual`) Gemini Pro video pass. Off by default.

## Install

```bash
pip install -e ".[dev]"
cp .env.example .env   # add GEMINI_API_KEY
set -a; source .env; set +a
```

Requires on PATH: `yt-dlp` (URLs), `ffmpeg`, and a Whisper binary (`whisper.cpp`).

## Usage

```bash
video-summarizer "https://www.youtube.com/watch?v=..."        # transcript + summary + chapters
video-summarizer ./talk.mp4 --visual                          # + on-screen visual notes
video-summarizer ./talk.mp4 --dry-run                         # show the plan, do nothing
```

Output: `./analyses/<slug>.md`.

## Test

```bash
python3 -m pytest -q
```
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README with install + usage"
```

---

## Self-Review Notes

- **Spec coverage:** Stage 1 subs→whisper (Tasks 3–6); Stage 2 summary+chapters (Task 7); Stage 3 opt-in visual (Task 8); pluggable registries (Tasks 5, 7, 8); markdown output shape (Task 9); CLI flags + exit codes + dry-run (Task 10); config/env (Tasks 1, 10); error isolation (Task 10 maps `StageError`→partial, `ConfigError`→exit 2); testing via injection (all test tasks). README (Task 11). Phase-2 wiring intentionally excluded per spec.
- **Injection consistency:** `resolve_transcript` takes `fetch_fn`/`extract_fn`/`transcribe_fn` for tests; `cli.py` imports the real `resolve_transcript`/`summarize`/`visual_notes` as module attributes so `monkeypatch.setattr(cli, ...)` works. Backend dispatchers all share the `registry=` override shape.
- **Type consistency:** transcript dict (`text`/`segments`/`source`), analysis dict (`summary`/`chapters[{time,title}]`), visual dict (`notes`) are used identically in `render.py` and `cli.py`.
