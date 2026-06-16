# Richer Summary Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single shallow `gemini-flash` summary blurb with a richer, structured summary (TL;DR + key points + takeaways + chapters) produced by a stronger model via the SDK's native structured output, with the model overridable from the CLI.

**Architecture:** No new modules. The change stays inside the existing Stage 2 backend registry. `summarize.py` gets a richer prompt, an expanded JSON output schema, native structured output, and a `model` parameter; the backend is renamed `gemini-flash` → `gemini`. `render.py` lays out the four-part analysis. `cli.py` adds a `--summary-model` flag (default `gemini-2.5-pro`), updates the default `--summary-backend` to `gemini`, threads the model through, and updates the failure fallback.

**Tech Stack:** Python 3.11+, `pytest`, `google-genai` (Gemini, structured output via `types.GenerateContentConfig`). Tests inject fake clients/backends — no network.

**Spec:** `docs/superpowers/specs/2026-06-16-richer-summary-design.md`

---

## File Structure

- `src/video_summarizer/summarize.py` — Modify: new `_PROMPT`, `SUMMARY_SCHEMA`, `_lang_instruction`, `_gemini_backend` (renamed, takes `model`, uses structured output), `SUMMARIZERS` key `gemini`, `summarize(...)` gains `model`.
- `src/video_summarizer/render.py` — Modify: `render_markdown` emits Summary (tldr) + Key points + Takeaways + Chapters.
- `src/video_summarizer/cli.py` — Modify: `--summary-model` flag, default `--summary-backend=gemini`, pass `model`, new fallback dict shape.
- `tests/test_summarize.py` — Modify: new analysis shape, renamed backend/registry key, `model` forwarding, structured-output config accepted by fake client.
- `tests/test_render.py` — Modify: assert the new sections render.
- `tests/test_cli.py` — Modify: `--summary-model` accepted; fallback assertions still hold.

**Analysis dict contract** (produced by Stage 2, consumed by `render.py` and the CLI fallback):

```python
{
    "tldr": str,                 # 2-3 sentence overview
    "key_points": [str],
    "takeaways": [str],
    "chapters": [{"time": "MM:SS", "title": str}],
}
```

---

## Task 1: Expand the summarizer (schema, prompt, model param, rename)

**Files:**
- Modify: `src/video_summarizer/summarize.py`
- Test: `tests/test_summarize.py`

- [ ] **Step 1: Replace `tests/test_summarize.py` with the new contract**

```python
import pytest
from video_summarizer.summarize import summarize, SUMMARIZERS, _extract_json
from video_summarizer.errors import ConfigError, StageError as _StageError


def test_default_summarizer_registered():
    assert "gemini" in SUMMARIZERS


def test_summarize_dispatches_to_backend():
    def fake(transcript_text, client, lang, model):
        return {"tldr": "it is about X", "key_points": ["a"], "takeaways": ["b"],
                "chapters": [{"time": "00:00", "title": "Intro"}]}

    result = summarize("some transcript", backend="fake", client=object(),
                       lang="en", registry={"fake": fake})
    assert result["tldr"] == "it is about X"
    assert result["key_points"] == ["a"]
    assert result["takeaways"] == ["b"]
    assert result["chapters"][0]["title"] == "Intro"


def test_summarize_forwards_model_to_backend():
    captured = {}

    def fake(transcript_text, client, lang, model):
        captured["model"] = model
        return {"tldr": "", "key_points": [], "takeaways": [], "chapters": []}

    summarize("t", backend="fake", client=object(), lang="en",
              model="gemini-flash-latest", registry={"fake": fake})
    assert captured["model"] == "gemini-flash-latest"


def test_summarize_default_model_is_pro():
    captured = {}

    def fake(transcript_text, client, lang, model):
        captured["model"] = model
        return {"tldr": "", "key_points": [], "takeaways": [], "chapters": []}

    summarize("t", backend="fake", client=object(), lang="en",
              registry={"fake": fake})
    assert captured["model"] == "gemini-2.5-pro"


def test_summarize_unknown_backend_raises_config_error():
    with pytest.raises(ConfigError):
        summarize("t", backend="nope", client=None, lang="en", registry={})


def test_extract_json_raises_stage_error_on_malformed_json():
    with pytest.raises(_StageError):
        _extract_json('prefix {not: valid json,,} suffix')


def test_extract_json_raises_stage_error_when_no_object():
    with pytest.raises(_StageError):
        _extract_json('no json here at all')


def test_gemini_backend_writes_in_requested_language_and_uses_model():
    from video_summarizer.summarize import _gemini_backend
    captured = {}

    class FakeModels:
        def generate_content(self, model, contents, config=None):
            captured["contents"] = contents
            captured["model"] = model
            captured["config"] = config
            class R:
                text = ('{"tldr": "s", "key_points": ["k1"], '
                        '"takeaways": ["t1"], "chapters": []}')
            return R()

    class FakeClient:
        models = FakeModels()

    result = _gemini_backend("hello transcript", client=FakeClient(),
                             lang="zh-Hans", model="gemini-2.5-pro")
    assert "zh-Hans" in captured["contents"]
    assert "hello transcript" in captured["contents"]
    assert captured["model"] == "gemini-2.5-pro"
    assert captured["config"] is not None        # structured output requested
    assert result["tldr"] == "s"
    assert result["key_points"] == ["k1"]
    assert result["takeaways"] == ["t1"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_summarize.py -q`
Expected: FAIL — `"gemini" in SUMMARIZERS` is False, `_gemini_backend` is not importable, and `summarize` does not accept `model`.

- [ ] **Step 3: Rewrite `src/video_summarizer/summarize.py`**

```python
"""Stage 2: summary + chapters from transcript text via a pluggable text LLM.

Backends take (transcript_text, client, lang, model) and return
{'tldr': str, 'key_points': [str], 'takeaways': [str],
 'chapters': [{'time': 'MM:SS', 'title': str}]}.
The Gemini client is injected so tests never call the network.
"""

import json

from .errors import ConfigError, StageError

_PROMPT = (
    "You are summarizing a video transcript. Respond with ONLY a JSON object "
    'with keys "tldr" (a 2-3 sentence overview string), "key_points" (a list of '
    "strings covering the substantive points made), \"takeaways\" (a list of "
    "strings with the actionable or memorable conclusions), and \"chapters\" (a "
    'list of {"time": "MM:SS", "title": string}).'
)

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "tldr": {"type": "string"},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "takeaways": {"type": "array", "items": {"type": "string"}},
        "chapters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "time": {"type": "string"},
                    "title": {"type": "string"},
                },
            },
        },
    },
}


def _lang_instruction(lang: str) -> str:
    """Tell the model to write its output in the transcript's language."""
    return (' Write the "tldr", every "key_points" entry, every "takeaways" '
            'entry, and every chapter "title" in this language '
            f"(BCP-47 code): {lang}. Transcript follows:\n\n")


def _extract_json(text: str) -> dict:
    """Pull the first {...} JSON object out of an LLM response."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise StageError("summarizer returned no JSON object")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise StageError(f"summarizer returned invalid JSON: {e}") from e


def _gemini_backend(transcript_text: str, client, lang: str,
                    model: str = "gemini-2.5-pro") -> dict:
    from google.genai import types

    resp = client.models.generate_content(
        model=model,
        contents=_PROMPT + _lang_instruction(lang) + transcript_text,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SUMMARY_SCHEMA,
        ),
    )
    data = _extract_json(resp.text)
    return {
        "tldr": data.get("tldr", ""),
        "key_points": data.get("key_points", []),
        "takeaways": data.get("takeaways", []),
        "chapters": data.get("chapters", []),
    }


SUMMARIZERS = {"gemini": _gemini_backend}


def summarize(transcript_text: str, backend: str, client, lang: str,
              model: str = "gemini-2.5-pro", registry=None) -> dict:
    registry = SUMMARIZERS if registry is None else registry
    fn = registry.get(backend)
    if fn is None:
        raise ConfigError(f"unknown summary backend: {backend}")
    return fn(transcript_text, client=client, lang=lang, model=model)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_summarize.py -q`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Commit**

```bash
git add src/video_summarizer/summarize.py tests/test_summarize.py
git commit -m "feat: structured summary (tldr/key_points/takeaways) via stronger model"
```

---

## Task 2: Render the four-part analysis

**Files:**
- Modify: `src/video_summarizer/render.py`
- Test: `tests/test_render.py`

- [ ] **Step 1: Replace the two `render_markdown` tests in `tests/test_render.py`**

Keep the two `slugify` tests unchanged. Replace `test_render_markdown_without_visual_omits_section` and `test_render_markdown_with_visual_includes_section` with:

```python
def test_render_markdown_without_visual_omits_section():
    md = render_markdown(
        title="Talk", source="https://x/v", duration="12:00", date="2026-06-16",
        transcript={"text": "hello", "segments": [{"start": 0.0, "text": "hello"}], "source": "subtitles"},
        analysis={"tldr": "a talk about X", "key_points": ["point one"],
                  "takeaways": ["do this"],
                  "chapters": [{"time": "00:00", "title": "Start"}]},
        visual=None,
    )
    assert "# Talk" in md
    assert "transcript-source: subtitles" in md
    assert "## Summary" in md and "a talk about X" in md
    assert "### Key points" in md and "- point one" in md
    assert "### Takeaways" in md and "- do this" in md
    assert "## Chapters" in md and "00:00 — Start" in md
    assert "## Visual notes" not in md
    assert "## Transcript" in md and "[00:00] hello" in md


def test_render_markdown_empty_lists_show_none():
    md = render_markdown(
        title="Talk", source="movie.mp4", duration="01:00", date="2026-06-16",
        transcript={"text": "hi", "segments": [], "source": "whisper:small"},
        analysis={"tldr": "", "key_points": [], "takeaways": [], "chapters": []},
        visual=None,
    )
    assert "### Key points\n_(none)_" in md
    assert "### Takeaways\n_(none)_" in md
    assert "## Chapters\n_(none)_" in md


def test_render_markdown_with_visual_includes_section():
    md = render_markdown(
        title="Talk", source="movie.mp4", duration="01:00", date="2026-06-16",
        transcript={"text": "hi", "segments": [{"start": 0.0, "text": "hi"}], "source": "whisper:small"},
        analysis={"tldr": "s", "key_points": [], "takeaways": [], "chapters": []},
        visual={"notes": ["chart on screen"]},
    )
    assert "## Visual notes" in md
    assert "- chart on screen" in md
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_render.py -q`
Expected: FAIL — current `render_markdown` reads `analysis["summary"]`, so `### Key points` / `### Takeaways` / `a talk about X` are absent.

- [ ] **Step 3: Rewrite `src/video_summarizer/render.py`**

```python
"""Assemble the final markdown document and compute the output filename."""

import re


def slugify(title: str) -> str:
    s = title.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "untitled"


def _fmt_seconds(secs: float) -> str:
    total = int(secs)
    return f"{total // 60:02d}:{total % 60:02d}"


def _bulleted(lines, items):
    """Append `- item` for each item, or `_(none)_` when the list is empty."""
    if not items:
        lines.append("_(none)_")
        return
    for item in items:
        lines.append(f"- {item}")


def render_markdown(title, source, duration, date, transcript, analysis, visual) -> str:
    lines = [
        f"# {title}",
        f"_{source} · {duration} · {date} · transcript-source: {transcript['source']}_",
        "",
        "## Summary",
        analysis.get("tldr", ""),
        "",
        "### Key points",
    ]
    _bulleted(lines, analysis.get("key_points", []))
    lines += ["", "### Takeaways"]
    _bulleted(lines, analysis.get("takeaways", []))
    lines += ["", "## Chapters"]
    chapters = analysis.get("chapters", [])
    if not chapters:
        lines.append("_(none)_")
    for ch in chapters:
        lines.append(f"- {ch['time']} — {ch['title']}")
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_render.py -q`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Commit**

```bash
git add src/video_summarizer/render.py tests/test_render.py
git commit -m "feat: render structured summary sections (key points, takeaways)"
```

---

## Task 3: CLI `--summary-model` flag + wiring

**Files:**
- Modify: `src/video_summarizer/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Add a failing test to `tests/test_cli.py`**

Append this test (it relies on the existing `_patch_stages` helper):

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cli.py -k summary_model -q`
Expected: FAIL — `cli.main` does not pass `model` to `summarize` (the `fake_summary` positional `model` arg is unfilled → `TypeError`), and `--summary-model` is an unrecognized argument.

- [ ] **Step 3: Edit `src/video_summarizer/cli.py`**

Change the default summary backend (line ~61) and add the model flag right after it:

```python
    p.add_argument("--summary-backend", default="gemini")
    p.add_argument("--summary-model", default="gemini-2.5-pro",
                   help="model for the summary backend (e.g. gemini-flash-latest for cheap)")
```

Update the `summarize(...)` call to pass the model:

```python
        try:
            analysis = summarize(transcript["text"], backend=args.summary_backend,
                                 client=client, lang=transcript.get("lang", lang),
                                 model=args.summary_model)
        except ConfigError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        except Exception as e:
            print(f"warning: summary failed: {e}", file=sys.stderr)
            analysis = {"tldr": "_(summary failed)_", "key_points": [],
                        "takeaways": [], "chapters": []}
            exit_code = 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_cli.py -q`
Expected: PASS (all tests in the file, including the pre-existing ones — the failure fallback still renders `_(summary failed)_` under `## Summary`).

- [ ] **Step 5: Commit**

```bash
git add src/video_summarizer/cli.py tests/test_cli.py
git commit -m "feat: --summary-model flag (default gemini-2.5-pro); default backend 'gemini'"
```

---

## Task 4: Full suite + README touch-up

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (all tests across all files).

- [ ] **Step 2: Update the README summary description**

In `README.md`, update the Stage 2 bullet under "How it works (cheap-first)" to reflect the structured output and stronger default model. Replace the existing line:

```markdown
2. **Summary + chapters** — a cheap text LLM (`gemini-flash`) over the transcript.
```

with:

```markdown
2. **Summary + chapters** — a structured pass (TL;DR + key points + takeaways +
   chapters) over the transcript, by default `gemini-2.5-pro`. Override with
   `--summary-model gemini-flash-latest` for a cheaper run.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README reflects structured summary + --summary-model"
```

---

## Self-Review

- **Spec coverage:** data shape (Task 1 backend + contract block), richer prompt + structured output + model param + rename (Task 1), rendering of all four sections incl. empty-list `_(none)_` (Task 2), `--summary-model` flag + default backend `gemini` + threaded model + new fallback shape (Task 3), README (Task 4). `_extract_json` kept as defensive fallback (Task 1). Error contract unchanged: `ConfigError`→exit 2, generic/`StageError`→exit 1 (Task 3, pre-existing tests still pass).
- **Type consistency:** analysis dict `{tldr, key_points, takeaways, chapters}` is produced by `_gemini_backend`/`summarize` (Task 1), consumed by `render_markdown` via `.get()` defaults (Task 2), and matched by the CLI fallback (Task 3). Backend signature `(transcript_text, client, lang, model)` is consistent across `summarize`, `_gemini_backend`, and every test fake. Registry key `gemini` consistent across `SUMMARIZERS`, the default `--summary-backend`, and the CLI test assertion.
- **Compat note:** `render_markdown` reads via `.get()`, so the pre-existing CLI test stubs that still return the old `{"summary","chapters"}` shape render without crashing (empty Summary + `_(none)_` sections) and their `"## Summary" in text` assertions still hold. The `"summary"` key is fully removed from real producers.
- **Placeholder scan:** none — every code step shows complete content.
