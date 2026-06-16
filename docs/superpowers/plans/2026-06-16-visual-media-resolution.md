# Visual Pass Media Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `--media-resolution {low,default}` CLI flag (default `low`) that makes the opt-in `--visual` Gemini Pro video pass run at LOW media resolution (~3× cheaper), while letting a user opt back to the API default for text/chart-heavy videos.

**Architecture:** No new modules. The Stage 3 visual backend (`visual.py`) gains a `media_resolution` parameter; when `"low"` it attaches `GenerateContentConfig(media_resolution=MEDIA_RESOLUTION_LOW)` to the Gemini call, and when `"default"` it passes no config (byte-equivalent to today). `cli.py` adds the flag, threads it into the visual call, and shows it in `--dry-run`.

**Tech Stack:** Python 3.11+, `pytest`, `google-genai` (`types.MediaResolution`). Clients are injected — tests never hit the network.

**Spec:** `docs/superpowers/specs/2026-06-16-visual-media-resolution-design.md`

---

## File Structure

- `src/video_summarizer/visual.py` — Modify: `_gemini_pro_backend` and `visual_notes` gain `media_resolution`; backend builds the SDK config when `low`.
- `src/video_summarizer/cli.py` — Modify: add `--media-resolution` flag, thread into the `visual_notes(...)` call, append `media_res=` to the dry-run plan string.
- `tests/test_visual.py` — Modify: fakes accept `media_resolution`; add low/default config tests.
- `tests/test_cli.py` — Modify: add threading + default tests.

**Parameter contract:** `media_resolution: str` is one of `"low"` or `"default"`, flowing CLI → `visual_notes` → `_gemini_pro_backend`.

---

## Task 1: Visual backend honors media resolution

**Files:**
- Modify: `src/video_summarizer/visual.py`
- Test: `tests/test_visual.py`

- [ ] **Step 1: Replace `tests/test_visual.py` entirely with the new contract**

```python
import pytest
from video_summarizer.visual import visual_notes, VISUALIZERS
from video_summarizer.errors import ConfigError


def test_default_visualizer_registered():
    assert "gemini-pro" in VISUALIZERS


def test_visual_notes_dispatches_to_backend():
    def fake(video_path, client, media_resolution):
        return {"notes": ["a chart on screen", "title card"]}

    result = visual_notes("movie.mp4", backend="fake", client=object(),
                          registry={"fake": fake})
    assert result["notes"] == ["a chart on screen", "title card"]


def test_visual_notes_forwards_media_resolution():
    captured = {}

    def fake(video_path, client, media_resolution):
        captured["media_resolution"] = media_resolution
        return {"notes": []}

    visual_notes("movie.mp4", backend="fake", client=object(),
                 media_resolution="default", registry={"fake": fake})
    assert captured["media_resolution"] == "default"


def test_visual_notes_default_media_resolution_is_low():
    captured = {}

    def fake(video_path, client, media_resolution):
        captured["media_resolution"] = media_resolution
        return {"notes": []}

    visual_notes("movie.mp4", backend="fake", client=object(),
                 registry={"fake": fake})
    assert captured["media_resolution"] == "low"


def test_visual_notes_unknown_backend_raises_config_error():
    with pytest.raises(ConfigError):
        visual_notes("movie.mp4", backend="nope", client=None, registry={})


def _fake_client(captured):
    class FakeFiles:
        def upload(self, file):
            return "uploaded-handle"

    class FakeModels:
        def generate_content(self, model, contents, config=None):
            captured["config"] = config
            captured["model"] = model
            class R:
                text = "note one\nnote two"
            return R()

    class FakeClient:
        files = FakeFiles()
        models = FakeModels()

    return FakeClient()


def test_gemini_pro_backend_low_sets_low_resolution_config():
    from video_summarizer.visual import _gemini_pro_backend
    from google.genai import types
    captured = {}

    result = _gemini_pro_backend("movie.mp4", client=_fake_client(captured),
                                 media_resolution="low")
    assert captured["config"] is not None
    assert captured["config"].media_resolution == types.MediaResolution.MEDIA_RESOLUTION_LOW
    assert captured["model"] == "gemini-2.5-pro"
    assert result["notes"] == ["note one", "note two"]


def test_gemini_pro_backend_default_passes_no_config():
    from video_summarizer.visual import _gemini_pro_backend
    captured = {}

    _gemini_pro_backend("movie.mp4", client=_fake_client(captured),
                        media_resolution="default")
    assert captured["config"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_visual.py -q`
Expected: FAIL — `visual_notes`/`_gemini_pro_backend` do not accept `media_resolution`, and the backend does not set a config.

- [ ] **Step 3: Rewrite `src/video_summarizer/visual.py` entirely with this content**

```python
"""Stage 3 (opt-in): on-screen visual notes via Gemini Pro video-native.

Backends take (video_path, client, media_resolution) and return {'notes': [str]}.
This is the only token-heavy stage; the CLI runs it only when --visual is set.
LOW media resolution (~66 tokens/frame vs ~258) makes the video pass ~3x cheaper.
"""

from .errors import ConfigError, StageError

_PROMPT = (
    "Watch this video and list concise bullet notes about what appears ON SCREEN "
    "(visible text, charts, scenes, key visuals) that the audio alone would miss. "
    "Respond with one note per line, no numbering."
)


def _gemini_pro_backend(video_path: str, client, media_resolution: str = "low") -> dict:
    uploaded = client.files.upload(file=video_path)
    config = None
    if media_resolution == "low":
        from google.genai import types

        config = types.GenerateContentConfig(
            media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW,
        )
    resp = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=[uploaded, _PROMPT],
        config=config,
    )
    notes = [line.strip("-• ").strip() for line in resp.text.splitlines() if line.strip()]
    return {"notes": notes}


VISUALIZERS = {"gemini-pro": _gemini_pro_backend}


def visual_notes(video_path: str, backend: str, client,
                 media_resolution: str = "low", registry=None) -> dict:
    registry = VISUALIZERS if registry is None else registry
    fn = registry.get(backend)
    if fn is None:
        raise ConfigError(f"unknown visual backend: {backend}")
    return fn(video_path, client=client, media_resolution=media_resolution)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_visual.py -q`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Commit**

```bash
git add src/video_summarizer/visual.py tests/test_visual.py
git commit -m "feat: visual pass honors media_resolution (default low, ~3x cheaper)"
```

---

## Task 2: CLI `--media-resolution` flag + wiring

**Files:**
- Modify: `src/video_summarizer/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Append two failing tests to `tests/test_cli.py`**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cli.py -k media_resolution -q`
Expected: FAIL — `--media-resolution` is an unrecognized argument; and `cli.main` does not pass `media_resolution` to `visual_notes` (the `fake_visual` positional arg is unfilled → TypeError).

- [ ] **Step 3: Edit `src/video_summarizer/cli.py` (three edits)**

(a) Add the flag in the argparse block, right after the `--lang` argument (currently `cli.py:65-66`) and before `--dry-run`:

```python
    p.add_argument("--media-resolution", choices=["low", "default"], default="low",
                   help="resolution for the --visual video pass; 'low' is ~3x cheaper")
```

(b) Append a `media_res=` token to the dry-run plan string. Change the current last line of the `plan` f-string (`cli.py:80`) from:

```python
                f"summary={args.summary_backend}:{args.summary_model} out={args.out}")
```

to:

```python
                f"summary={args.summary_backend}:{args.summary_model} "
                f"media_res={args.media_resolution} out={args.out}")
```

(c) Thread the flag into the visual call (`cli.py:127`). Change:

```python
                visual = visual_notes(get_media(), backend="gemini-pro", client=client)
```

to:

```python
                visual = visual_notes(get_media(), backend="gemini-pro", client=client,
                                      media_resolution=args.media_resolution)
```

- [ ] **Step 4: Run the full suite to verify everything passes**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (ALL tests across ALL files). The pre-existing dry-run test (`test_cli_dry_run_reports_language`) still passes — it only asserts `lang=` / `whisper_lang=` substrings, which are unchanged; the new `media_res=` token is additive.

- [ ] **Step 5: Commit**

```bash
git add src/video_summarizer/cli.py tests/test_cli.py
git commit -m "feat: --media-resolution flag (default low) for the visual pass"
```

---

## Task 3: README touch-up

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the visual-notes bullet**

In `README.md`, under "How it works (cheap-first)", replace this exact line:

```markdown
3. **Visual notes** — opt-in (`--visual`) Gemini Pro video pass. Off by default.
```

with:

```markdown
3. **Visual notes** — opt-in (`--visual`) Gemini Pro video pass. Off by default.
   Runs at low media resolution to keep cost down; pass `--media-resolution
   default` for full-resolution frames when on-screen text or charts matter.
```

(Read `README.md` first to confirm the exact current wording; adapt the match if it differs slightly, but produce the replacement text above.)

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README documents --media-resolution"
```

---

## Self-Review

- **Spec coverage:** backend `media_resolution` param + LOW config when low + no config when default (Task 1); `visual_notes` forwarding with default `low` (Task 1); `--media-resolution` flag with `choices=["low","default"]` default `low` (Task 2); threaded into visual call (Task 2); dry-run surfacing (Task 2); README (Task 3). Error contract unchanged (Task 1 keeps `ConfigError` for unknown backend; CLI's existing `except Exception` is untouched).
- **Type consistency:** `media_resolution` is a `str` (`"low"`/`"default"`) everywhere — CLI flag (`choices`), `visual_notes` param, `_gemini_pro_backend` param, and all test fakes use the same name and values. The fake-client `generate_content(self, model, contents, config=None)` signature matches the real call `generate_content(model=..., contents=..., config=config)`.
- **Placeholder scan:** none — every code step shows complete content.
- **Compat note:** `"default"` → `config=None` reproduces today's exact call; only the default flag value (`low`) changes out-of-the-box behavior, which is the intent.
