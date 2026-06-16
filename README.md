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

Output: `./analyses/<slug>.md`. Exit codes: `0` success, `1` partial (e.g. summary
failed but transcript written), `2` config/usage error.

## Test

```bash
python3 -m pytest -q
```
