# video-summarizer

Turn a video (local file, direct URL, or yt-dlp site URL) into one structured
markdown file — transcript + summary + chapters, plus opt-in on-screen visual
notes. Read the markdown to summarize and ask questions about the video.

## How it works (cheap-first)

1. **Transcript** — reuse `yt-dlp` subtitles if present; else extract audio with
   `ffmpeg` and transcribe with Whisper (`whisper.cpp` by default).
2. **Summary + chapters** — a structured pass (TL;DR + key points + takeaways +
   chapters) over the transcript, by default `gemini-2.5-pro`. Override with
   `--summary-model gemini-flash-latest` for a cheaper run, or
   `--summary-backend claude` to summarize with Claude (`claude-opus-4-8` by
   default; needs `ANTHROPIC_API_KEY`). If the Gemini summary errors or
   rate-limits and `ANTHROPIC_API_KEY` is set, the run automatically falls back
   to Claude rather than degrading to a transcript-only file.
3. **Visual notes** — opt-in (`--visual`) Gemini Pro video pass. Off by default.
   Runs at low media resolution to keep cost down; pass `--media-resolution
   default` for full-resolution frames when on-screen text or charts matter.

The summary and chapters are written in the **transcript's own language**: when
subtitles are used, that subtitle language wins; otherwise Whisper auto-detects
the spoken language and the summary follows it. Pass `--lang <code>` to prefer a
subtitle language and force the Whisper transcription language (e.g. `--lang zh`).

> Auto-detection needs a **multilingual** Whisper model (`--whisper-model small`
> or `base`), not the English-only `base.en`.

## Install

```bash
pip install -e ".[dev]"
cp .env.example .env   # add GEMINI_API_KEY
set -a; source .env; set +a
```

Requires on PATH: `yt-dlp` (URLs), `ffmpeg`, and a Whisper binary (`whisper.cpp`).

For URL sources with **no subtitles**, the Whisper fallback downloads the media
with `yt-dlp` first. Direct media URLs (e.g. public R2 `.mp4` links) and
Bilibili work out of the box; **YouTube** video downloads additionally need a
JavaScript runtime on PATH (`node`, `deno`, or `bun`) for yt-dlp.

## Usage

```bash
video-summarizer "https://www.youtube.com/watch?v=..."        # transcript + summary + chapters
video-summarizer ./talk.mp4 --visual                          # + on-screen visual notes
video-summarizer ./clip.mp4 --title "My Clean Title"          # override the derived title
video-summarizer ./talk.mp4 --dry-run                         # show the plan, do nothing
```

Each `.md` opens with YAML frontmatter (`title`, `source`, `duration`, `date`,
`transcript_source`) so the file is vault-ready — point `--out` at an Obsidian
folder and the notes are queryable. The title is derived from the source by
default; pass `--title` when the source is a metadata-less URL (it drives the H1,
the frontmatter, and the filename slug).

Output: `./analyses/<slug>.md` (slug from the title; Unicode titles kept,
clashes get a `-2`, `-3`, … suffix rather than overwriting). Exit codes: `0`
success, `1` partial (e.g. summary failed but transcript written), `2`
config/usage error.

## Test

```bash
python3 -m pytest -q
```
