# Richer Summary Output — Design Spec

**Date:** 2026-06-16
**Status:** Approved (pending spec review)

## Goal

Improve the quality of the Stage 2 summary output. Today the summarizer makes a
single `gemini-flash-latest` call with a thin prompt that returns a 3–5 sentence
blurb plus chapters. Three problems to fix:

1. **Too shallow** — a 3–5 sentence blob loses important detail.
2. **Weak model/prompt** — `gemini-flash` with a minimal prompt under-performs.
3. **Long videos** — depth degrades on long transcripts.

We accept more cost/latency for quality. We are **not** changing the grounding
strategy (no timestamp citation work). Chosen approach: **better single pass** —
a stronger model, a richer structured prompt, and the SDK's native structured
output. (Map-reduce was considered and deferred.)

## Out of scope

- Map-reduce / chunking of long transcripts (deferred; single pass relies on the
  model's large context window).
- Timestamp grounding / citation of claims.
- A second selectable summary backend (the existing registry still allows one to
  be added later, but this spec ships exactly one backend).

## Architecture

No new modules. The change stays inside the existing three-stage pipeline and the
Stage 2 backend registry. Affected units:

- `src/video_summarizer/summarize.py` — new prompt, expanded output schema,
  native structured output, model is now a parameter.
- `src/video_summarizer/render.py` — render the expanded analysis shape.
- `src/video_summarizer/cli.py` — new `--summary-model` flag; threaded into the
  backend; updated failure-fallback dict.
- Tests: `tests/test_summarize.py`, `tests/test_render.py`, `tests/test_cli.py`.

## Data shape change

The **analysis** dict produced by Stage 2 changes from:

```python
{"summary": str, "chapters": [{"time": "MM:SS", "title": str}]}
```

to:

```python
{
    "tldr": str,                 # 2-3 sentence overview
    "key_points": [str],         # the substantive points made
    "takeaways": [str],          # actionable / memorable conclusions
    "chapters": [{"time": "MM:SS", "title": str}],
}
```

All four text-bearing fields are written in the transcript's language (the
existing `--lang` instruction applies to `tldr`, every `key_points` entry, every
`takeaways` entry, and every chapter `title`).

## Summarizer (`summarize.py`)

### Prompt

Rewrite `_PROMPT` to ask for the four-part structured object. Keep the existing
`_lang_instruction(lang)` mechanism and ensure its wording covers all text
fields, not just "summary" and chapter titles.

### Structured output

Replace reliance on the brittle "find the first `{...}`" parse with the
`google-genai` native structured output:

```python
from google.genai import types

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

resp = client.models.generate_content(
    model=model,
    contents=_PROMPT + _lang_instruction(lang) + transcript_text,
    config=types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=SUMMARY_SCHEMA,
    ),
)
```

`_extract_json` is **kept** as a defensive fallback (a fake/older client may
still return a non-strict JSON string) and continues to raise `StageError` on
missing or invalid JSON.

### Model is a parameter

The backend signature gains a `model` parameter:

```python
def _gemini_backend(transcript_text, client, lang, model="gemini-2.5-pro") -> dict
```

`summarize(...)` gains a `model` parameter (default `"gemini-2.5-pro"`) and passes
it through to the backend. The registry key is **renamed** from `"gemini-flash"`
to the model-agnostic key `"gemini"` so the name no longer implies a specific
model; `cli.py`'s default `--summary-backend` updates to `"gemini"`.

The backend reads `tldr`/`key_points`/`takeaways`/`chapters` from the parsed JSON
with `.get(...)` defaults (`""` for `tldr`, `[]` for the lists) so a partial
model response never crashes rendering.

## Rendering (`render.py`)

`render_markdown` reads the new analysis shape and emits:

```markdown
## Summary
<tldr>

### Key points
- <point>

### Takeaways
- <takeaway>

## Chapters
- 00:00 — <title>
```

Empty-list handling: if `key_points` / `takeaways` / `chapters` are empty, render
`_(none)_` under that heading (matching the existing chapters behavior). If
`tldr` is empty, the Summary body is blank but the heading still renders.

## CLI (`cli.py`)

- Add `--summary-model` (default `"gemini-2.5-pro"`).
- Update default `--summary-backend` to `"gemini"`.
- Pass `model=args.summary_model` into `summarize(...)`.
- The summary-failure fallback dict changes to the new shape:

```python
analysis = {
    "tldr": "_(summary failed)_",
    "key_points": [],
    "takeaways": [],
    "chapters": [],
}
```

Exit-code contract is unchanged: `StageError` from the summarizer → partial doc,
exit 1; `ConfigError` (unknown backend) → exit 2.

## Error handling

Unchanged contract. The backend raises `StageError` when the model returns no
JSON object or invalid JSON. The CLI isolates the failure to a partial document
and exits 1. Unknown backend → `ConfigError` → exit 2.

## Testing

All backends stay injected, so no test touches the network.

- `tests/test_summarize.py`: the registry-dispatch and unknown-backend tests stay
  (update fake backend signatures to accept `model`). Add a test that the default
  `gemini` backend, given a fake client returning structured JSON, returns the
  four keys, and that `model` is forwarded to the client call.
- `tests/test_render.py`: assert the rendered markdown contains `## Summary`, the
  `tldr` text, a `### Key points` bullet, a `### Takeaways` bullet, and the
  `## Chapters` line; assert `_(none)_` appears when a list is empty.
- `tests/test_cli.py`: update the patched `summarize` stub and the failure
  fallback assertions to the new analysis shape; confirm `--summary-model` is
  accepted and threaded through.

## Self-review notes

- **Blast radius:** analysis dict shape changes in exactly three producers/
  consumers (`summarize.py` produces, `render.py` + `cli.py` fallback consume),
  all updated together.
- **Backward-compat:** the `"summary"` key is removed; no persisted data depends
  on it (output is regenerated each run), so no migration needed.
- **Cheap-first preserved:** `--summary-model gemini-flash-latest` lets a user
  drop back to the cheap model without code changes.
