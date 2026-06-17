# Proposal: `--title` + always-on frontmatter in video-summarizer

**Status:** implemented (2026-06-17; pyyaml chosen for the YAML emitter)
**Date:** 2026-06-17
**Scope:** `video-summarizer` (primary), `publish-video-plugin` watcher (1 line)

## Goal

Make each video-analysis `.md` **vault-ready** — clean human title and queryable
YAML frontmatter — so that pointing the watcher's output dir at an Obsidian folder
turns the existing fetch → publish → transcribe pipeline into persistent,
searchable memory. No MyNewsCollector dependency, no `write_doc`, no per-action
post-processing.

## Pipeline context

```
publish-video watcher (watcher.py)
  ├─ polls YouTube + Bilibili Watch Later, diffs against seen-state
  ├─ publish_video.py: download → normalize H.264/AAC → upload R2 → public_url
  └─ post-run action "summarize" (watcher_actions.py:89)
        → subprocess: video-summarizer <public_url> --out <dir>
              → whisper.cpp transcript + Gemini summary + chapters → writes <slug>.md
        → parses the printed .md path back
```

`fetch → save → transcribe` already works today. This proposal only improves the
**format** of the transcript file so it doubles as a knowledge note.

## Key constraint that drove the design

When the watcher calls video-summarizer it feeds the **R2 `public_url`** — a plain
`.mp4` with no metadata. So video-summarizer can only derive an ugly slug title
(e.g. `bilibili-20260616-BV1YGVY6nE4n-Agentic_design...`). The **clean** title
lives only in the watcher's yt-dlp listing (`r["title"]`).

Data split:

| Field | video-summarizer | watcher (`r`) |
|---|---|---|
| clean title | ❌ (slug only) | ✅ `r["title"]` |
| duration, date | ✅ | ✅ |
| `transcript_source` (whisper:base) | ✅ structured | ❌ prose only |
| `platform`, `source_id` | ❌ | ✅ |
| `video_url` (= public_url) | ✅ (it *is* the input `source`) | ✅ |

Conclusion: the format belongs in video-summarizer's renderer (reusable for all
callers, structured access to duration/date/transcript-source), and the watcher
just passes the clean title in via a new flag.

## Decisions locked

1. **Rewrite H1** to the clean title.
2. **Frontmatter always-on**, with clean fallbacks (omit empty/None keys; never `null`).
3. **Leave** the body's `_… · transcript-source: …_` metadata line as-is; also lift
   `transcript_source` into frontmatter (free, since it's structured at render time).
4. Frontmatter lives in **`render_markdown`**, not in the watcher action.
5. **`--meta` dropped** — no `platform`/`source_id` in the note (consistent with
   earlier dropping `source_url` and `write_doc`). Can be added later as an
   additive flag if needed.

## Edits

### Edit 1 — `cli.py`: add `--title` (3 lines)

Today `title` is derived once and feeds both the H1 and the filename:

```python
title = _title_from_source(args.source)            # cli.py:76
...
out_path = unique_path(args.out, slugify(title))   # cli.py:142
```

Add the flag and let it override:

```python
p.add_argument("--title", default=None, help="override the derived title")  # near cli.py:57
...
title = args.title or _title_from_source(args.source)                       # cli.py:76
```

**Bonus:** because `title` also drives `slugify(title)` at cli.py:142, `--title`
cleans the **filename** too — watcher output stops being `bilibili-20260616-…`
and becomes a clean-title slug.

### Edit 2 — `render.py`: always-on frontmatter in `render_markdown`

Prepend a frontmatter block before the `# {title}` line (render.py:46). Everything
needed is already in the signature `(title, source, duration, date, transcript,
analysis, visual)` — no new params, no prose parsing:

```yaml
---
title: "<title>"
source: <source>                 # input arg: public_url from watcher, original URL/path standalone
duration: "<duration>"
date: <date>
transcript_source: <transcript['source']>
---
# <title>
_<source> · <duration> · <date> · transcript-source: <...>_   # body line kept (decision 3)
```

- Always-on; omit any key whose value is empty/None.
- `source` doubles as the link-back (R2 `public_url` when watcher-driven).
- Mild, intentional redundancy between frontmatter and the body `_…_` line.

### Edit 3 — watcher `summarize_action`: one line

```python
cmd = [command, r["public_url"], "--out", out_dir, "--title", r["title"]]   # watcher_actions.py:116
```

No `_add_frontmatter`, no file round-trip — the action stays a thin shell-out.

## Correctness gotcha: YAML quoting

`duration` is formatted like `12:25`. In YAML 1.1 an unquoted `12:25` parses as a
**base-60 integer (745)**, and titles can contain `:` / quotes / CJK. The emitter
**must quote** `title` and `duration`.

**OPEN QUESTION — pick one:**
- **`pyyaml` + `yaml.safe_dump`** — robust; same dep MyNewsCollector already uses.
  Adds one small dep (video-summarizer currently only depends on `google-genai`).
  *(Leaning this way for correctness.)*
- **Hand-rolled** quoted-scalar emitter — no new dep, but escaping is on us.

## Tests to update/add

- `render.py`: assert frontmatter block, quoted `duration`, omitted-when-empty
  fields, idempotent shape.
- `cli.py`: `--title` overrides both H1 and filename slug; absent `--title` →
  unchanged behavior.
- watcher: `summarize_one` builds `--title r["title"]` (existing tests inject a
  fake `run_fn`; assert the argv).

## Resulting note (real example)

```yaml
---
title: "讲透 Agentic Design Patterns 系列 1/21 — Prompt Chaining"
source: https://pub-7fae...r2.dev/video/bilibili-...mp4
duration: "12:25"
date: 2026-06-16
transcript_source: whisper:base
---
# 讲透 Agentic Design Patterns 系列 1/21 — Prompt Chaining
_https://pub-7fae...r2.dev/...mp4 · 12:25 · 2026-06-16 · transcript-source: whisper:base_

## Summary
...
```

Set the watcher's `out = "/Users/kunwu/Obsidian/News/videos"` and these land
directly in the vault as queryable, clean-titled notes — no `write_doc`, no
MyNewsCollector dependency.

## Explicitly out of scope

- `write_doc` / `news_collect` integration (contract-preserving: keep writing to `out_dir`).
- `source_url` (original Bilibili/YouTube link) and `--meta` (`platform`/`source_id`).
  Both deferrable as additive changes later.
