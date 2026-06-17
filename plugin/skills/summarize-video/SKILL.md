---
name: summarize-video
description: Summarize a video — a local file, a direct media URL, or any yt-dlp-supported site URL (YouTube, Bilibili, …) — into one structured markdown note (transcript + summary + chapters), then answer questions about it. Use when the user shares a video file/URL and wants a summary, transcript, chapters, notes, or to "ask questions about this video".
---

# Summarize a video

This skill drives the `video-summarizer` CLI (the deterministic engine) and then adds a
conversational layer the CLI lacks: answering questions, reframing, and condensing on demand.

## Workflow

1. **Check the engine is installed.**
   ```bash
   command -v video-summarizer
   ```
   If it prints a path, skip to step 3.

2. **If missing, get consent before installing.** Do not install silently. Tell the user:
   - Install: `pipx install video-summarizer` (or `pipx install git+https://github.com/Wkkkkk/video-summarizer` for the latest).
   - It also needs these on PATH (not pip-installable): **`ffmpeg`**, **`yt-dlp`** (for site URLs), and a **Whisper binary** (`whisper-cli` / whisper.cpp) — Whisper is only exercised for sources with no subtitles.
   - And **one API key**: `ANTHROPIC_API_KEY` (use `--summary-backend claude`) or `GEMINI_API_KEY` (default backend).
   Ask the user to confirm, then run the install command.

3. **Run the engine.** Pick the backend from the available key — prefer Claude when `ANTHROPIC_API_KEY` is set:
   ```bash
   video-summarizer "<source>" --out ./analyses --summary-backend claude
   ```
   - Drop `--summary-backend claude` to use the default Gemini backend (needs `GEMINI_API_KEY`).
   - Add `--title "<clean title>"` when the source is a metadata-less URL (drives the H1 + filename).
   - Add `--visual` only if the user asks about on-screen text/slides/charts (Gemini-only, costs more).
   The CLI prints the path of the written markdown file. Run with `--dry-run` first if you want to show the plan.

4. **Read the produced markdown** at the printed path. It has YAML frontmatter
   (`title`, `source`, `duration`, `date`, `transcript_source`) followed by the summary,
   chapters, and full transcript.

5. **Add the value the CLI can't.** The markdown already exists, so this costs no extra model spend:
   answer the user's questions about the video, re-frame or condense sections on demand, pull quotes
   with their chapter timestamps, or translate. Cite chapter times from the file when relevant.

## Notes

- Exit codes: `0` success, `1` partial (e.g. summary failed, transcript still written — read it anyway), `2` config/usage error (usually a missing key or native dep — surface the stderr message).
- If `--summary-backend claude` is used and `ANTHROPIC_API_KEY` is missing, the run fails with a config error; fall back to suggesting the Gemini backend or setting the key.
- For long videos the run can take a while (download + transcription). Let the user know before starting.
