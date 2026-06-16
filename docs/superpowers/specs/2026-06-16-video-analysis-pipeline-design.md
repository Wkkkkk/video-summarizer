# video-summarizer — Design

_Date: 2026-06-16_

## Purpose

A small, affordable, easy-to-extend CLI that turns a video (local file, direct
media URL, or any yt-dlp-supported site URL) into **one structured markdown
file** — transcript + summary + chapters, plus on-screen visual notes when
explicitly requested. The markdown is then used to summarize and to ask
questions about the video afterward (read directly by a coding agent such as
Claude Code).

This is a standalone project, not part of the `publish-video` plugin. It may
later be invoked by that plugin as a post-publish step (see Phase 2), but it
has no dependency on it.

## Principles

- **Cheap-first, escalate only when needed.** The free/local path (existing
  subtitles, local Whisper) is the default. The only paid-by-the-minute or
  token-heavy step — video understanding — is opt-in.
- **Easy to extend.** Each stage resolves its work through a small backend
  registry (`name -> function`). Adding a transcription engine, a summarizer,
  or a visual analyzer is "one function + one dict entry."
- **Testable without network or GPU.** Every backend takes an injected client
  or `run_fn`, so unit tests never shell out or hit an API.

## Pipeline (three stages, cheap-first)

### Stage 1 — Transcript (cheapest source wins)
1. **Subtitles via yt-dlp** (URL sources only):
   `yt-dlp --write-subs --write-auto-subs --sub-format vtt --skip-download`.
   If a subtitle/auto-caption track exists, parse it to text + timestamps and
   use it. Free and instant.
2. **Whisper on extracted audio** (fallback, and the only path for local files):
   `ffmpeg -i <video> -ar 16000 -ac 1 audio.wav` → Whisper backend → text +
   segment timestamps.

The chosen source is recorded in the output (`subtitles` vs `whisper:<model>`).

### Stage 2 — Summary + chapters (always runs, text-only)
Feed the transcript **text** (no video/audio tokens) to a summarizer backend,
which returns `{ summary: str, chapters: [{ time, title }] }`.

### Stage 3 — On-screen visual notes (opt-in: `--visual`)
Only when `--visual` is passed: a Gemini Pro video-native pass produces notes on
what appears on screen (visible text, scenes, key visuals). This is the single
expensive step and is **off by default**.

## Pluggable backends (registry pattern)

```python
WHISPER_BACKENDS = {"whisper.cpp": ..., "openai-whisper": ...}  # default: whisper.cpp
SUMMARIZERS      = {"gemini-flash": ...}                        # default: gemini-flash
VISUALIZERS      = {"gemini-pro": ...}                          # used only with --visual
```

- **Transcription default:** `whisper.cpp` (free, offline, fast). `openai-whisper`
  selectable; a hosted-API backend is a future addition.
- **Summary default:** `gemini-flash` (cheap, fast, text-only; uses the same
  `GEMINI_API_KEY` as the visual stage). Other backends (Claude, local) addable.
- **Visual:** `gemini-pro` video-native.

## Module layout (clean standalone repo)

```
video-summarizer/
  README.md
  pyproject.toml            # deps + console entry point `video-summarizer`
  .env.example
  .gitignore                # ignores .env, analyses/, audio temp, __pycache__
  src/video_summarizer/
    __init__.py
    cli.py                  # argparse + orchestration (the tiering logic)
    transcribe.py           # Stage 1: subtitle fetch + Whisper backends
    summarize.py            # Stage 2: text-LLM summarizer backends
    visual.py               # Stage 3: Gemini Pro video (opt-in)
    render.py               # assemble the markdown document
  tests/
    test_transcribe.py
    test_summarize.py
    test_cli.py             # orchestration: subs-present, subs-absent→whisper, --visual on/off
  analyses/                 # default output dir (gitignored)
```

Each module has one clear job and a well-defined interface; `cli.py` is the only
component that knows about all three stages.

## CLI

```bash
video-summarizer <source> [options]
  <source>            local file, direct media URL, or yt-dlp site URL
  --visual            run the opt-in Gemini Pro visual-notes pass (default: off)
  --out DIR           output directory (default: ./analyses)
  --whisper-backend   transcription backend (default: whisper.cpp)
  --summary-backend   summary backend (default: gemini-flash)
  --lang LANG         language hint for transcription/summary
  --dry-run           print the resolved plan; no API calls, no writes
```

## Output — one markdown per video at `<out>/<id>-<slug>.md`

```markdown
# <title>
_source · duration · date · transcript-source: subtitles | whisper:small_

## Summary
…

## Chapters
- 00:00 — …
- 03:12 — …

## Visual notes        ← only present when --visual was passed
- …

## Transcript
[00:00] …
```

The agent (or user) reads this file to summarize and to answer questions. No
separate Q&A program in v1.

## Configuration

- **Env:** `GEMINI_API_KEY` — required for the default summarizer and for
  `--visual`. Not required if a local summary backend is selected and `--visual`
  is off. Loaded from a `.env` file (`set -a; source .env; set +a`), gitignored.
- **PATH tools:** `yt-dlp` (URL sources), `ffmpeg` (audio extraction), a Whisper
  binary (`whisper.cpp` or `openai-whisper`).

## Error handling

- Stages are isolated. No subtitles → fall through to Whisper. A failed summary
  still writes a transcript-only file with a warning. A failed `--visual` pass
  still writes the rest.
- Missing required tool or key → clear stderr message + **exit 2**.
- Exit codes: **0** all good, **1** partial (some stage failed but output
  written), **2** config/usage error before any work.

## Testing

- Inject `run_fn` for `yt-dlp`/`ffmpeg`/`whisper` and fake LLM clients — no
  network, no GPU, no real binaries.
- Cover: subtitles-present path, subtitles-absent → Whisper path, `--visual`
  on/off, markdown rendering, and exit-code behavior on missing tools.

## Phase 2 (out of scope for v1)

- Optional integration: the `publish-video` plugin shells out to
  `video-summarizer` after publishing, reusing the already-downloaded local file
  to avoid a re-download. Specced separately when wanted.
- Possible later additions: hosted Whisper backend, cross-video RAG over the
  `analyses/` folder, Cloud Vision keyframe entities (the parked "Lens" layer).

## Non-goals

- HLS/DASH or signed delivery (not this tool's concern).
- A built-in interactive Q&A chat (Q&A is done by the coding agent reading the
  markdown).
- Always sending the full video to a model (video is the exception, via
  `--visual`, never the default).
