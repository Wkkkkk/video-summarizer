# video-summarizer — usage

Turns a video (local file, direct media URL, or any yt-dlp site URL) into one
markdown file: YAML frontmatter + summary + key points + takeaways + chapters +
full timestamped transcript. Pipeline is cheap-first: reuse subtitles if present,
else download + Whisper transcribe, then an LLM summary pass.

## Install
- `pipx install video-summarizer` (repo: github.com/Wkkkkk/video-summarizer)
- Native deps on PATH (NOT pip-installable): `ffmpeg`, `yt-dlp`,
  a Whisper binary (`whisper-cli` / whisper.cpp). YouTube *downloads* also need a
  JS runtime (`node`/`deno`/`bun`); subtitle-only runs don't.
- A Whisper model file must exist at `models/ggml-<model>.bin` (default model
  `small` → `models/ggml-small.bin`). `base` = multilingual, `base.en` = English-only.
- One API key (env var): `GEMINI_API_KEY` (default backend) or `ANTHROPIC_API_KEY`
  (for `--summary-backend claude`).

## Basic use
    video-summarizer "<source>"                       # → ./analyses/<slug>.md
    video-summarizer ./talk.mp4 --out ./notes
    video-summarizer "<url>" --dry-run                # print the plan, do nothing

## Flags
- `source`                  local file | direct media URL | yt-dlp site URL (positional)
- `--out DIR`               output dir (default ./analyses)
- `--title "..."`           override title (H1 + frontmatter + filename). For yt-dlp
                            site URLs the real title is auto-fetched from metadata;
                            pass this only to override or for ugly direct-media URLs.
- `--summary-backend NAME`  `gemini` (default) or `claude`
- `--summary-model ID`      defaults per backend: gemini-2.5-pro / claude-opus-4-8
                            (e.g. `gemini-flash-latest` for cheap)
- `--lang CODE`             prefer this subtitle lang + force Whisper lang; omit to auto-detect
- `--whisper-model NAME`    default `small`; use `base` for multilingual auto-detect
                            (NOT `base.en` for non-English audio)
- `--whisper-backend NAME`  default `whisper.cpp`
- `--visual`                opt-in Gemini Pro on-screen/visual pass (Gemini-only, costs more)
- `--media-resolution low|default`   visual-pass resolution (default low, ~3x cheaper)
- `--cookies-from-browser BROWSER`   read cookies for yt-dlp (e.g. `chrome`) — needed
                            for login/risk-controlled sites (some Bilibili videos → HTTP 412)
- `--cookies PATH`          yt-dlp cookies.txt file (alternative to the above)

## Output
`./<out>/<slug>.md` — slug from the title (Unicode kept; collisions get `-2`, `-3`…).
Frontmatter: `title, source, duration, date, transcript_source`. Summary/chapters
are written in the transcript's detected language.

## Exit codes
- 0 success · 1 partial (e.g. summary failed but transcript written — read it anyway)
- 2 config/usage error (missing key/dep, unknown backend — read the stderr message)

## Backend behavior
- `gemini` (default) uses google-genai; `claude` uses the Anthropic SDK (structured output).
- If the Gemini summary errors/rate-limits AND `ANTHROPIC_API_KEY` is set, it
  auto-falls back to Claude instead of degrading to transcript-only.

## Gotchas learned in practice
- Bilibili / login-gated videos returning **HTTP 412** → add `--cookies-from-browser chrome`.
- "whisper.cpp transcription failed" usually means the model file is missing — confirm
  `models/ggml-<model>.bin` exists (default expects `small`).
- A Chinese *title* doesn't mean Chinese *audio*; Whisper auto-detects and transcribes
  the spoken language verbatim (no translation).

## Use as a Claude Code plugin
A plugin wrapping this CLI lives in `plugin/`; the repo root is a plugin marketplace.

    /plugin marketplace add Wkkkkk/video-summarizer
    /plugin install video-summarizer@video-summarizer
    /video-summarizer:summarize-video <video file or URL>
