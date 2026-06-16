# Runbook — running video-summarizer on test data

Step-by-step for exercising the CLI on real inputs, with the expected output
called out for each step.

## Setup (once per shell)

```bash
cd /Users/kunwu/Workspace/playground/video-summarizer
set -a; source .env; set +a          # loads GEMINI_API_KEY
```

Prerequisites: `whisper-cli`, `yt-dlp`, `ffmpeg` on PATH; a multilingual Whisper
model at `models/ggml-base.bin` (auto-detect needs a multilingual model — **not**
the English-only `base.en`); `GEMINI_API_KEY` in `.env`.

Real runs need network access.

## What every run produces

- **File:** `./analyses/<slug>.md` (the source title, slugified). `analyses/` is
  gitignored, so outputs don't clutter the repo.
- **Contents:** a metadata line —
  `source · duration · date · transcript-source: <subtitles | whisper:MODEL>` —
  then `## Summary`, `## Chapters` (timestamped), `## Transcript`, and
  `## Visual notes` *only* if `--visual` was passed.
- **Exit codes:** `0` full success · `1` partial (e.g. summary failed → transcript
  still written) · `2` config/usage error.

---

## Step 1 — Dry run (instant, no network, no API)

Confirms wiring and shows the language fields.

```bash
.venv/bin/video-summarizer "demo.mp4" --dry-run
.venv/bin/video-summarizer "demo.mp4" --dry-run --lang ZH
```

**Output:** no file written, exit `0`, one plan line each, e.g.:

```
DRY RUN — would run:
  source=demo.mp4 is_url=False visual=False whisper=whisper.cpp:small lang=en whisper_lang=auto summary=gemini:gemini-2.5-pro out=./analyses
```

The second prints `lang=ZH whisper_lang=ZH` (the backend lowercases to `zh` at
real run time).

## Step 2 — Live Chinese fixture, auto-detect (the headline case)

No subtitles → downloads via yt-dlp → Whisper auto-detects the spoken language.
Use the multilingual `base` model.

```bash
.venv/bin/video-summarizer \
  "https://pub-7fae8d6805af4dc6a5b2a9988274addf.r2.dev/video/bilibili-20260615-BV1YGVY6nE4n-%E8%AE%B2%E9%80%8F_Agentic_design_patterns_%E7%B3%BB%E5%88%97_1_21_%E5%88%AB%E5%86%8D%E7%94%A8%E9%95%BF%E6%8F%90%E7%A4%BA%E8%AF%8D%E4%BA%86_10%E5%88%86%E9%92%9F%E5%AD%A6%E4%BC%9Aprompt%E9%93%BE%E6%A8%A1%E5%BC%8F.mp4" \
  --whisper-model base --out ./analyses
```

**Output:** a `.md` in `./analyses/`, metadata showing
`12:25 · … · transcript-source: whisper:base`. Transcript in **Chinese**;
Summary + Chapters in **Chinese** too (this is the fix — language matches
end-to-end). Takes a minute or two (download + transcription). Exit `0` on
success; **exit `1` with an empty Summary if Gemini returns 503** — that's a
transient demand-spike outage, not a bug; just re-run.

## Step 3 — Local file (fastest real transcription path)

Any local `.mp4`/`.mov`/audio file — no download step.

```bash
.venv/bin/video-summarizer /path/to/your-video.mp4 --whisper-model base --out ./analyses
```

**Output:** same structure; `transcript-source: whisper:base`. Add `--lang en`
(or another code) to force the language instead of auto-detecting.

## Step 4 — Force a language explicitly

```bash
.venv/bin/video-summarizer /path/to/clip.mp4 --lang zh --whisper-model base --out ./analyses
```

**Output:** Whisper transcribes as `zh` (no detection step); summary/chapters in
Chinese.

## Step 5 (optional) — YouTube URL

Uses subtitles if present (fast, no Whisper); otherwise falls back to download +
Whisper, which additionally needs a JS runtime (`node`/`deno`/`bun`) on PATH for
yt-dlp.

```bash
.venv/bin/video-summarizer "https://www.youtube.com/watch?v=<id>" --out ./analyses
```

**Output:** if subtitles exist, `transcript-source: subtitles` and the summary
follows the subtitle language; otherwise `whisper:<model>`.

> Quote the URL with **plain** double quotes — don't backslash-escape `?` or `=`.
> `"…/watch\?v\=ID"` passes literal backslashes to yt-dlp, which then can't parse
> the video and fails with `no media file produced`. Use `"…/watch?v=ID"`.

---

## Inspect the result

```bash
ls -t analyses/*.md | head -1                       # newest output
sed -n '1,12p' "$(ls -t analyses/*.md | head -1)"   # metadata + Summary + start of Chapters
```

## Notes

- The two English R2 fixtures from earlier testing return **404** (deleted) —
  only the Bilibili URL in Step 2 is live.
- `--visual` (Gemini Pro video pass) needs a billing-enabled Gemini project:
  `gemini-2.5-pro` is `limit:0` on the free tier (429 RESOURCE_EXHAUSTED). On a
  billing-enabled project the full pipeline runs to exit `0` with a populated
  `## Visual notes` section. The visual backend uploads the video and polls the
  Files API until it is `ACTIVE` before the model call (Gemini processes uploads
  asynchronously; using the handle too early fails with 400 FAILED_PRECONDITION).
- The Gemini models (`gemini-2.5-pro`, `gemini-flash-latest`, …) are hosted — no
  local download. Only the Whisper `models/ggml-*.bin` files are local.
