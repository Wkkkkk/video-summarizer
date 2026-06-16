# Visual Pass Media Resolution — Design Spec

**Date:** 2026-06-16
**Status:** Approved (pending spec review)

## Goal

Cut the cost of the opt-in `--visual` Gemini Pro video pass. Gemini tokenizes
video at ~258 tokens/frame at default resolution; its LOW media-resolution mode
uses ~66 tokens/frame, roughly a 3× reduction in input tokens (the visual pass is
the most expensive call in the pipeline — ~$0.22 of a ~$0.24 10-minute run).

Expose this as a CLI flag `--media-resolution {low,default}` defaulting to `low`,
so the cheap path is the default but a user can bump back to the model's default
resolution when a video is text- or chart-heavy (LOW downsamples frames and can
miss fine on-screen text — the very thing visual notes capture).

## Out of scope

- A `--visual-model` flag (separately discussed; not bundled here).
- Changing the summary stage or any non-visual behavior.
- Any resolution tier other than `low` and the API default (no MEDIUM/HIGH knob).

## Architecture

No new modules. The change touches the Stage 3 visual backend and the CLI that
drives it.

- `src/video_summarizer/visual.py` — `_gemini_pro_backend` and `visual_notes`
  gain a `media_resolution` parameter; the backend sets the SDK config when
  `low`.
- `src/video_summarizer/cli.py` — new `--media-resolution` flag, threaded into
  the visual call; surfaced in the `--dry-run` plan string.
- Tests: `tests/test_visual.py`, `tests/test_cli.py`.

## Visual backend (`visual.py`)

`_gemini_pro_backend` gains `media_resolution: str = "low"`:

```python
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
```

- `media_resolution == "low"` → build a `GenerateContentConfig` carrying
  `MEDIA_RESOLUTION_LOW`. `types` is imported lazily inside the function, matching
  the pattern established in `summarize.py`.
- `media_resolution == "default"` → `config` stays `None`, so the call is
  byte-equivalent to today's behavior (the API applies its own default
  resolution). Passing `config=None` to `generate_content` is equivalent to
  omitting it.

`visual_notes` gains `media_resolution="low"` and forwards it:

```python
def visual_notes(video_path: str, backend: str, client,
                 media_resolution: str = "low", registry=None) -> dict:
    registry = VISUALIZERS if registry is None else registry
    fn = registry.get(backend)
    if fn is None:
        raise ConfigError(f"unknown visual backend: {backend}")
    return fn(video_path, client=client, media_resolution=media_resolution)
```

## CLI (`cli.py`)

- Add the argument (near the other backend/model flags):

```python
    p.add_argument("--media-resolution", choices=["low", "default"], default="low",
                   help="resolution for the --visual video pass; 'low' is ~3x cheaper")
```

- Thread it into the visual call:

```python
                visual = visual_notes(get_media(), backend="gemini-pro",
                                      client=client,
                                      media_resolution=args.media_resolution)
```

- Surface it in the `--dry-run` plan string (append a `media_res=` token), e.g.
  `... summary=gemini:gemini-2.5-pro media_res=low out=./analyses`.

## Error handling

Unchanged. `visual_notes` still raises `ConfigError` for an unknown backend; the
CLI's existing `except Exception` around the visual stage still isolates a visual
failure to a warning + exit 1, with the rest of the document written.

## Testing

All clients/backends are injected — no network.

- `tests/test_visual.py`:
  - Update the existing fake-backend signatures to accept `media_resolution`
    (the dispatch and unknown-backend tests).
  - Add a test that `_gemini_pro_backend` with `media_resolution="low"` passes a
    non-`None` `config` whose `media_resolution` is `MEDIA_RESOLUTION_LOW`, using
    a fake client whose `files.upload` and `models.generate_content` record args.
  - Add a test that `media_resolution="default"` passes `config=None` (no
    media-resolution requested).
- `tests/test_cli.py`:
  - Add a test that `--media-resolution default` threads through to
    `visual_notes` (capture the kwarg via a fake), and that omitting the flag
    yields `"low"`.

## Self-review notes

- **Blast radius:** `media_resolution` flows CLI → `visual_notes` →
  `_gemini_pro_backend`; signatures updated together. No other module reads it.
- **Backward-compat:** `"default"` reproduces current behavior exactly
  (`config=None`); only the *default flag value* changes the out-of-the-box
  behavior to the cheaper path, which is the intent.
- **Pattern consistency:** lazy `from google.genai import types`, injected
  client, and the `choices=`/`default=` flag style all match existing code.
