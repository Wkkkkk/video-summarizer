# Media Acquisition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Whisper fallback (and `--visual`) work for URL sources by acquiring a local media file from any source — local path, public R2 HTTPS link, or YouTube/Bilibili URL — before audio extraction / upload.

**Architecture:** A new `acquire_media(source, is_url, workdir, run_fn)` maps any source to a local media path: local files pass through; URLs are downloaded via `yt-dlp` (its generic extractor handles direct R2 `.mp4` links as well as site URLs). `resolve_transcript`'s Whisper branch acquires before extracting audio; the CLI passes a **memoized** `get_media()` closure into `resolve_transcript` and reuses it for the visual stage, so a single download serves both. Subtitle-only runs never download.

**Tech Stack:** Python 3.11+, `pytest`, `yt-dlp`/`ffmpeg` (invoked via `subprocess`, injected as `run_fn`/`acquire_fn` in tests). Run tests with `.venv/bin/python -m pytest`.

---

## File Structure

- `src/video_summarizer/acquire.py` — **new.** `acquire_media`: source → local media path. Depends only on `subprocess`, `glob`, `os`, and `.errors.StageError`.
- `src/video_summarizer/transcribe.py` — **modify** `resolve_transcript` to acquire a local media path (via injected `acquire_fn`, default `acquire_media`) before `extract_audio`. Add `from .acquire import acquire_media`.
- `src/video_summarizer/cli.py` — **modify** `main`: build a memoized `get_media()` closure, pass it as `acquire_fn` to `resolve_transcript`, and call `visual_notes(get_media(), …)` instead of `visual_notes(args.source, …)`. Add `from .acquire import acquire_media`.
- `tests/test_acquire.py` — **new.**
- `tests/test_transcribe.py` — **modify** (update two existing resolve tests, add two).
- `tests/test_cli.py` — **modify** (add one test).
- `README.md` — **modify** (document the yt-dlp media download + YouTube JS-runtime prerequisite).

No circular imports: `acquire` imports only `errors`; `transcribe` and `cli` import `acquire`.

---

## Task 1: `acquire_media` module

**Files:**
- Create: `src/video_summarizer/acquire.py`
- Test: `tests/test_acquire.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_acquire.py
import pytest
from video_summarizer.acquire import acquire_media
from video_summarizer.errors import StageError


def _ok_run_factory(workdir, write=True):
    """Return a fake run_fn that simulates yt-dlp: optionally writes media.mp4
    into workdir and returns a process object with returncode 0."""
    def fake_run(cmd, **kwargs):
        if write:
            (workdir / "media.mp4").write_bytes(b"fake-bytes")
        class R:
            returncode = 0
        return R()
    return fake_run


def test_acquire_local_file_passes_through(tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            returncode = 0
        return R()

    out = acquire_media("/path/movie.mp4", is_url=False, workdir=tmp_path, run_fn=fake_run)
    assert out == "/path/movie.mp4"
    assert calls == []  # local files are never downloaded


def test_acquire_url_downloads_and_returns_local_path(tmp_path):
    out = acquire_media("https://r2.example/x.mp4", is_url=True,
                        workdir=tmp_path, run_fn=_ok_run_factory(tmp_path))
    assert out.endswith("media.mp4")
    assert str(tmp_path) in out


def test_acquire_url_builds_ytdlp_command(tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        (tmp_path / "media.mp4").write_bytes(b"x")
        class R:
            returncode = 0
        return R()

    acquire_media("https://r2.example/x.mp4", is_url=True, workdir=tmp_path, run_fn=fake_run)
    cmd = calls[0]
    assert cmd[0] == "yt-dlp"
    assert "https://r2.example/x.mp4" in cmd
    assert "-f" in cmd  # a format selector is passed


def test_acquire_raises_stage_error_on_nonzero_exit(tmp_path):
    def fake_run(cmd, **kwargs):
        class R:
            returncode = 1
        return R()

    with pytest.raises(StageError):
        acquire_media("https://r2.example/x.mp4", is_url=True, workdir=tmp_path, run_fn=fake_run)


def test_acquire_raises_stage_error_when_no_file_produced(tmp_path):
    # exit 0 but nothing written
    with pytest.raises(StageError):
        acquire_media("https://r2.example/x.mp4", is_url=True,
                      workdir=tmp_path, run_fn=_ok_run_factory(tmp_path, write=False))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_acquire.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'video_summarizer.acquire'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/video_summarizer/acquire.py
"""Acquire a local media file from any source.

Local paths pass through unchanged. URLs — yt-dlp sites (YouTube/Bilibili) or
direct media such as public R2 .mp4 links — are downloaded via yt-dlp into a
working directory. All subprocess calls go through an injected `run_fn` so
tests never invoke real binaries."""

import glob
import os
import subprocess

from .errors import StageError


def acquire_media(source: str, is_url: bool, workdir, run_fn=subprocess.run) -> str:
    """Return a local media path for `source`. Local files pass through; URLs
    are downloaded with yt-dlp into `workdir`. Raises StageError on download
    failure or if no media file is produced."""
    if not is_url:
        return source
    out_tmpl = os.path.join(str(workdir), "media.%(ext)s")
    cmd = ["yt-dlp", "-f", "b/bv*+ba", "-o", out_tmpl, "--", source]
    proc = run_fn(cmd, capture_output=True, text=True)
    if getattr(proc, "returncode", 0) != 0:
        raise StageError(f"media download failed: {source}")
    files = sorted(glob.glob(os.path.join(str(workdir), "media.*")))
    if not files:
        raise StageError(f"no media file produced for {source}")
    return files[0]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_acquire.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/video_summarizer/acquire.py tests/test_acquire.py
git commit -m "feat: acquire_media (local pass-through; URL -> yt-dlp download)"
```

---

## Task 2: `resolve_transcript` acquires before Whisper

**Files:**
- Modify: `src/video_summarizer/transcribe.py`
- Test: `tests/test_transcribe.py`

- [ ] **Step 1: Update the two existing whisper-path resolve tests to inject `acquire_fn`, and add two new tests**

In `tests/test_transcribe.py`, change `test_resolve_falls_back_to_whisper_when_no_subs` so its fakes match the new signatures and it injects `acquire_fn`. Replace the existing function body with:

```python
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
```

Replace `test_resolve_local_file_skips_subtitle_fetch` body with:

```python
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
```

Then append two new tests at the end of the file:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_transcribe.py -k resolve -v`
Expected: FAIL — `resolve_transcript() got an unexpected keyword argument 'acquire_fn'`

- [ ] **Step 3: Modify `resolve_transcript` and add the import**

In `src/video_summarizer/transcribe.py`, add to the import block (near `from .errors import ConfigError, StageError`):

```python
from .acquire import acquire_media
```

Replace the existing `resolve_transcript` function with:

```python
def resolve_transcript(source: str, is_url: bool, workdir, whisper_backend: str,
                       model: str, lang: str = "en", run_fn=subprocess.run,
                       fetch_fn=fetch_subtitles, acquire_fn=None,
                       extract_fn=extract_audio, transcribe_fn=transcribe_audio) -> dict:
    """Cheapest source first: subtitles (URLs only) -> acquire media -> Whisper.

    `acquire_fn` is a zero-arg callable returning a local media path; it defaults
    to acquiring `source` via `acquire_media`. The CLI injects a memoized closure
    so the download is shared with the visual stage. The returned transcript
    carries a 'lang' field (actual subtitle language, else the `lang` hint)."""
    if is_url:
        subs = fetch_fn(source, workdir, run_fn=run_fn, lang=lang)
        if subs is not None:
            return subs
    if acquire_fn is None:
        media = acquire_media(source, is_url, workdir, run_fn=run_fn)
    else:
        media = acquire_fn()
    audio = extract_fn(media, workdir, run_fn=run_fn)
    result = transcribe_fn(audio, backend=whisper_backend, model=model, run_fn=run_fn)
    result.setdefault("lang", lang)
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_transcribe.py -v`
Expected: PASS (all transcribe tests, including the 4 resolve tests)

- [ ] **Step 5: Commit**

```bash
git add src/video_summarizer/transcribe.py tests/test_transcribe.py
git commit -m "feat: resolve_transcript acquires local media before Whisper"
```

---

## Task 3: CLI shares one download across Whisper + visual

**Files:**
- Modify: `src/video_summarizer/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py`:

```python
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
    monkeypatch.setattr(cli, "summarize", lambda *a, **k: {"summary": "s", "chapters": []})
    monkeypatch.setattr(cli, "make_gemini_client", lambda: object())
    monkeypatch.setattr(cli, "probe_duration", lambda *a, **k: "00:30")
    monkeypatch.setattr(cli, "today_str", lambda: "2026-06-16")
    monkeypatch.setenv("GEMINI_API_KEY", "x")

    code = cli.main(["https://r2.example/x.mp4", "--visual", "--out", str(tmp_path)])
    assert code == 0
    assert calls["n"] == 1                          # downloaded exactly once
    assert captured["video_path"] == "/local/media.mp4"  # visual got the local path
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli.py::test_cli_downloads_media_once_for_whisper_and_visual -v`
Expected: FAIL — `AttributeError: <module 'video_summarizer.cli'> does not have the attribute 'acquire_media'` (the import/closure don't exist yet)

- [ ] **Step 3: Modify `cli.py`**

Add to the import block in `src/video_summarizer/cli.py` (with the other `from .` imports):

```python
from .acquire import acquire_media
```

Inside `main`, locate the `with tempfile.TemporaryDirectory() as workdir:` block. Immediately after that line, add the memoized closure:

```python
    with tempfile.TemporaryDirectory() as workdir:
        _media = {}

        def get_media():
            if "path" not in _media:
                _media["path"] = acquire_media(args.source, is_url, workdir)
            return _media["path"]
```

Pass `acquire_fn=get_media` to the existing `resolve_transcript` call (add the keyword argument):

```python
            transcript = resolve_transcript(
                args.source, is_url=is_url, workdir=workdir,
                whisper_backend=args.whisper_backend, model=args.whisper_model,
                lang=args.lang, acquire_fn=get_media)
```

Change the visual call from `args.source` to `get_media()`:

```python
        visual = None
        if args.visual:
            try:
                visual = visual_notes(get_media(), backend="gemini-pro", client=client)
            except Exception as e:
                print(f"warning: visual notes failed: {e}", file=sys.stderr)
                exit_code = 1
```

- [ ] **Step 4: Run test to verify it passes, then the full suite**

Run: `.venv/bin/python -m pytest tests/test_cli.py::test_cli_downloads_media_once_for_whisper_and_visual -v`
Expected: PASS

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (all tests across the suite; the existing CLI tests still pass — local-source visual tests resolve `get_media()` to the local path with no download, and the no-visual URL test never calls `get_media`)

- [ ] **Step 5: Commit**

```bash
git add src/video_summarizer/cli.py tests/test_cli.py
git commit -m "feat: CLI shares one media download across Whisper and --visual"
```

---

## Task 4: Document the prerequisite

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the prerequisites line in README.md**

In `README.md`, find the line under "## Install" that reads:

```
Requires on PATH: `yt-dlp` (URLs), `ffmpeg`, and a Whisper binary (`whisper.cpp`).
```

Replace it with:

```
Requires on PATH: `yt-dlp` (URLs), `ffmpeg`, and a Whisper binary (`whisper.cpp`).

For URL sources with **no subtitles**, the Whisper fallback downloads the media
with `yt-dlp` first. Direct media URLs (e.g. public R2 `.mp4` links) and
Bilibili work out of the box; **YouTube** video downloads additionally need a
JavaScript runtime on PATH (`node`, `deno`, or `bun`) for yt-dlp.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: note yt-dlp media download + YouTube JS-runtime prerequisite"
```

---

## Self-Review Notes

- **Spec coverage:** `acquire.py`/`acquire_media` (Task 1); `resolve_transcript` acquires before Whisper (Task 2); CLI memoized single download + visual uses local path (Task 3); error handling via `StageError` (Task 1 raises; existing CLI stage contracts unchanged — transcript `StageError` → exit 1, visual caught → exit 1); README prerequisite incl. YouTube JS-runtime (Task 4). Live R2 smoke tests are run post-merge during verification, not unit tasks.
- **Signature consistency:** `acquire_media(source, is_url, workdir, run_fn)` defined in Task 1 and called identically in Task 2 (default branch) and Task 3 (`get_media`). `acquire_fn` is a zero-arg callable everywhere: Task 2's `resolve_transcript` calls `acquire_fn()`, Task 3's `get_media` takes no args.
- **No network in unit tests:** every `run_fn`/`acquire_fn`/stage function is injected or monkeypatched. The only real `acquire_media` reachable in existing CLI tests is for the local `movie.mp4` source (`is_url=False` → pass-through, no `run_fn` call).
