# Media acquisition for the Whisper fallback — Design

_Date: 2026-06-16_

## Problem

When a source has no usable subtitles, `resolve_transcript` falls back to
Whisper by calling `extract_audio(source)` — which runs `ffmpeg -i <source>`.
That works for a local file or a direct media URL, but **fails for a yt-dlp
*site* URL** (YouTube/Bilibili): `ffmpeg` cannot read a watch-page URL, so it
errors with `ffmpeg audio extraction failed` and the run exits 1.

Real-world sources are: **local MP4 files**, **public R2 HTTPS links**
(direct `.mp4`), and **YouTube/Bilibili URLs**. The fallback must turn any of
these into a local media file before Whisper (and before the `--visual`
Gemini upload, which has the same latent bug — it currently uploads
`args.source`, which fails for any URL).

## Approach (A1): unified yt-dlp acquisition, lazy + memoized

A single acquisition step maps any source to a **local media path**:

- **Local path** (`is_url` false) → return `source` unchanged.
- **Any URL** → download with `yt-dlp` into the temp workdir. yt-dlp's generic
  extractor downloads direct media (public R2 `.mp4` links) just as well as
  YouTube/Bilibili, so this is one code path for all three source types. No
  credentials are needed (R2 objects are public HTTPS).

It runs **only when media is actually needed** — i.e. no subtitles were found,
or `--visual` was requested — and is **memoized** so a single download serves
both the Whisper and visual stages. Subtitle-only runs never download media.

**Known prerequisite:** downloading YouTube *video streams* needs a JavaScript
runtime (`node`/`deno`/`bun`) for yt-dlp. This only affects the rare case of a
YouTube video with no captions; Bilibili and direct R2 links are unaffected.
Documented in the README, not enforced in code.

## Components

### New: `src/video_summarizer/acquire.py`
```
acquire_media(source: str, is_url: bool, workdir, run_fn=subprocess.run) -> str
```
- `is_url` false → return `source`.
- else → `yt-dlp -f "b/bv*+ba" -o "<workdir>/media.%(ext)s" -- <source>` via
  `run_fn`; on non-zero exit raise `StageError`; glob `<workdir>/media.*`,
  return the first match; if none, raise `StageError`.
- Format `b/bv*+ba` prefers a single pre-merged file (typical for direct R2
  `.mp4` and Bilibili) and merges video+audio only when needed — giving a file
  usable by both Whisper (audio) and `--visual` (video).

### Changed: `transcribe.py` — `resolve_transcript`
The Whisper branch acquires a local media path before extracting audio:
```
media = acquire_fn()                 # memoized; defaults to acquire_media(source, is_url, workdir)
audio = extract_fn(media, workdir, run_fn=run_fn)
```
`acquire_fn` is an injected zero-arg callable (default builds one bound to
`acquire_media(source, is_url, workdir, run_fn)`), so tests inject a stub and
the CLI injects a memoized closure. The subtitle branch is unchanged and never
acquires.

### Changed: `cli.py` — one download shared by Whisper + visual
A memoized `get_media()` closure (downloads at most once) is passed into
`resolve_transcript` as `acquire_fn` and reused for the visual stage. The
visual stage calls `visual_notes(get_media(), ...)` instead of
`visual_notes(args.source, ...)`, fixing `--visual` for URL sources.

### Unchanged: source detection
`http(s)://` prefix → URL; otherwise local. Public R2 links are HTTPS and
download via yt-dlp like any other URL.

## Data flow

```
source ──▶ resolve_transcript
            ├─ is_url? ──▶ fetch_subtitles ──(found)──▶ transcript {source:"subtitles"}
            └─ no subs / local ──▶ get_media() ──▶ extract_audio ──▶ Whisper ──▶ transcript {source:"whisper:…"}
cli: if --visual ──▶ visual_notes(get_media())     # reuses the same local file; no second download
```

## Error handling

- `acquire_media` download failure or no file → `StageError`.
- In the transcript stage a `StageError` is fatal → exit 1 (no transcript, no
  output) — same as today's transcript-stage contract.
- In the visual stage it's caught and degraded → exit 1 with a partial file
  (transcript + summary, no visual section) — same as today's visual contract.

## Testing

Unit (injected `run_fn` / `acquire_fn`; no network, no real binaries):
- `acquire_media`: local pass-through (no `run_fn` call); URL → builds the
  yt-dlp command and returns the globbed `media.*`; raises `StageError` when
  yt-dlp exits non-zero or writes no file.
- `resolve_transcript`: Whisper branch invokes `acquire_fn` and feeds its
  result to `extract_fn`; subtitle branch never calls `acquire_fn`.
- `cli`: when both Whisper and `--visual` need media, `get_media()` downloads
  exactly once (assert the acquire stub is called a single time); visual
  receives the local media path, not the URL.

Live smoke tests (real yt-dlp + Whisper, public R2 fixtures — these have **no
subtitles**, so they exercise the new fallback directly):
- `https://pub-7fae8d6805af4dc6a5b2a9988274addf.r2.dev/video/043792e262bd4d31bae17c2a3e748fb2-Software_engineering_at_the_tipping_point.mp4`
  (English) → download → Whisper (`base.en`) → Flash summary.
- `https://pub-7fae8d6805af4dc6a5b2a9988274addf.r2.dev/video/6f39c0d706344d569d20a7fd44ec85f8-___OpenAI_________Agent_______________.mp4`
  (English).
- `https://pub-7fae8d6805af4dc6a5b2a9988274addf.r2.dev/video/bilibili-20260615-BV1YGVY6nE4n-…prompt链模式.mp4`
  (Chinese) — note: transcribing this well needs a multilingual Whisper model
  (e.g. `--whisper-model base`/`small`), not `base.en`. Out of scope for this
  change; flagged for the test run.

## Non-goals

- Private/authenticated R2 (S3 credentials/boto3) — sources are public HTTPS.
- Audio-only download optimization — a single full-media download is reused for
  both stages; the marginal bandwidth is acceptable for a personal tool.
- Caching downloads across runs — each run uses a fresh temp dir.
