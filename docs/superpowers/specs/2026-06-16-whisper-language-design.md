# Whisper transcription language fix — Design

_Date: 2026-06-16_

## Problem

When a source has no usable subtitles, `resolve_transcript` falls back to
Whisper. `_whisper_cpp_backend` invokes `whisper-cli` **without a `-l` language
flag**, so whisper.cpp uses its `en` default and mis-transcribes non-English
audio (observed: Chinese audio partly auto-translated to English, with looping).

Even after transcription is fixed, a second mismatch remains: the summary stage
reads `transcript.get("lang", args.lang)`, where `args.lang` defaults to `en`.
So a correctly-transcribed Chinese transcript would still get an **English
summary** — the "language not matching" complaint, moved one stage downstream.

A complete fix must (a) transcribe in the right language and (b) propagate the
spoken language to the summary stage.

## Approach (A): thread a separate `whisper_lang`, capture detection

`--lang` today conflates two concerns. Split them:

- **`lang`** — subtitle preference and summary-language *fallback*. Default `en`.
- **`whisper_lang`** — the transcription language passed to whisper.cpp.
  Default `auto`; set to the explicit `--lang` code when the user provides one.

In `auto` mode the backend parses whisper-cli's `auto-detected language: xx`
line and sets the transcript's `lang` to the detected code, so the summary is
written in the spoken language. On a parse miss it leaves `lang` unset and the
caller's `setdefault` applies the `en` fallback.

This is the only approach that makes both stages match for an **un-flagged**
non-English video (the symptom). The cost is parsing one line of whisper-cli
output, with a safe fallback.

## Components

### Changed: `transcribe.py`

`_whisper_cpp_backend(audio_path, run_fn, model, lang="auto")`
- Normalize BCP-47 to the primary subtag: `code = lang.split("-")[0]` for an
  explicit code (`zh-Hans` → `zh`, `en-US` → `en`); `auto` passes through
  unchanged.
- Add `-l <code>` to the `whisper-cli` command.
- After reading the `.txt` output, determine the transcript language:
  - explicit code (`code != "auto"`) → `detected = code`.
  - `auto` → search `(proc.stdout or "") + (proc.stderr or "")` with
    `r"auto-detected language:\s*([a-z]{2,3})"`; `detected` = the captured code
    or `None`.
- Set `result["lang"] = detected` only when `detected` is truthy (parse miss →
  no `lang` key).

`transcribe_audio(audio_path, backend, model, lang="auto", registry=None, run_fn=...)`
- Thread `lang` to the backend: `fn(audio_path, run_fn=run_fn, model=model, lang=lang)`.
- Still stamps `result["source"] = f"whisper:{model}"`.

`resolve_transcript(..., lang="en", whisper_lang="auto", ...)`
- Subtitle branch unchanged (uses `lang` for `fetch_subtitles`).
- Whisper branch: `transcribe_fn(audio, backend=whisper_backend, model=model, lang=whisper_lang, run_fn=run_fn)`.
- Keep `result.setdefault("lang", lang)` as the fallback when detection missed.

### Changed: `cli.py`

- `--lang` default changes from `"en"` to `None`.
- After parsing args:
  ```python
  lang = args.lang or "en"            # subtitle preference + summary fallback
  whisper_lang = args.lang or "auto"  # transcription language
  ```
- `resolve_transcript(..., lang=lang, whisper_lang=whisper_lang, acquire_fn=get_media)`.
- The summary call is already `lang=transcript.get("lang", args.lang)`; update
  the fallback to the computed `lang` (`transcript.get("lang", lang)`).
- Optional: include the language in the `--dry-run` plan line.

### Changed: `README.md`

One note: `-l auto` detection requires a multilingual Whisper model
(`--whisper-model small` or `base`), not the English-only `base.en`.

## Data flow

```
--lang absent ─▶ lang="en", whisper_lang="auto"
--lang zh     ─▶ lang="zh", whisper_lang="zh"

resolve_transcript
  ├─ is_url & subtitles found ─▶ transcript {lang: <subtitle lang>}   (unchanged)
  └─ no subs / local ─▶ acquire ─▶ extract_audio ─▶ Whisper(-l whisper_lang)
                                     ├─ auto: parse "auto-detected language: zh" ─▶ lang="zh"
                                     └─ explicit: lang=<code>
summarize(lang=transcript.get("lang", lang))   # Chinese transcript ⇒ Chinese summary
```

## Error handling

- Detection-parse miss → no `lang` key → `setdefault` applies the `en` fallback
  (or the explicit `--lang`). No failure.
- Backend non-zero exit → `StageError` (unchanged) → fatal in the transcript
  stage (exit 1).
- Exit-code contracts unchanged across all stages.

## Testing

Unit (injected `run_fn` / stubs; no network, no real binaries):
- `_whisper_cpp_backend`:
  - explicit `lang="zh-Hans"` → command contains `-l zh`; `result["lang"] == "zh"`.
  - explicit `lang="en"` → command contains `-l en`; `result["lang"] == "en"`.
  - `lang="auto"` with stub output containing `auto-detected language: ja` →
    command contains `-l auto`; `result["lang"] == "ja"`.
  - `lang="auto"` with no detection line → command contains `-l auto`; no
    `"lang"` key in the result.
- `transcribe_audio`: passes `lang` through to the backend (stub asserts the
  received `lang`).
- `resolve_transcript`:
  - Whisper branch with `whisper_lang="auto"` and a backend stub returning
    `lang="zh"` → result `lang == "zh"` (hint does not override).
  - backend stub returning no `lang` → `setdefault` applies the `lang` hint.
- `cli`: `--lang` absent → `resolve_transcript` receives `lang="en"`,
  `whisper_lang="auto"`; `--lang zh` → `lang="zh"`, `whisper_lang="zh"`.

Live smoke (real yt-dlp + Whisper, public R2 fixture, multilingual model):
- Chinese Bilibili R2 `.mp4` (no subtitles) with `--whisper-model base` and no
  `--lang` → auto-detects `zh` → Chinese transcript **and** Chinese summary.

## Non-goals

- Translating transcripts/summaries to a different target language (`--translate`
  stays off; we transcribe in the spoken language).
- Mapping every BCP-47 region/script variant — primary-subtag truncation is
  sufficient for whisper.cpp's ISO 639-1 codes.
- Enforcing model/language compatibility in code (English-only models ignore
  `-l`); documented in the README instead.
