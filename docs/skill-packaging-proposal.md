# Proposal: ship `video-summarizer` as a Claude Code skill + distributable package

**Status:** Phases 0/2/3 done on `feat/skill-packaging`; Phase 1 needs only the PyPI upload (your credentials). · **Branch context:** the two `feat/frontmatter` bug fixes are merged to `main`; this work is on `feat/skill-packaging`.
**Audience:** an agent picking this up cold — no prior conversation context assumed.

## Done so far (on `feat/skill-packaging`)

- **Phase 0** ✅ — `python -m build` succeeds in a clean venv with the SPDX `license = "Apache-2.0"` string (no fallback needed). Wheel + sdist build and `twine check` passes.
- **Phase 1** — wheel smoke-tested (installs in a fresh venv, console script works); artifacts built and `twine check`ed. **Remaining: the actual `twine upload`** (needs your PyPI credentials — not done autonomously).
- **Phase 2** ✅ — Claude Code plugin in `plugin/` + marketplace at `.claude-plugin/marketplace.json`; `plugin/skills/summarize-video/SKILL.md` wraps the CLI and adds Q&A. Manifest schemas verified against current `code.claude.com` docs. **Remaining: interactive local test** (`/plugin marketplace add <local path>` → install → run end-to-end against a real URL) — can't be run non-interactively.
- **Phase 3** ✅ — `_anthropic_backend` (`SUMMARIZERS["claude"]`, `claude-opus-4-8`) + `--summary-backend claude`, backend-aware default model, and automatic Gemini→Claude fallback. TDD'd; suite green (100 tests).

**Open questions, resolved:** plugin lives in an in-repo `plugin/` subdirectory; the skill installs the CLI only with user consent (never silently); PyPI-vs-TestPyPI left to you at upload time.

## TL;DR

Turn this repo into two shippable artifacts so others can use it:

1. **Engine** — the existing `video-summarizer` Python CLI, published to **PyPI** (`pipx install video-summarizer`).
2. **Skill** — a thin **Claude Code plugin** (a `SKILL.md`) that bootstraps + calls the CLI, then adds a conversational "ask questions about the video" layer. Distributed via a **plugin marketplace** (git repo), the same channel the `watch-youtube` skill on mcpmarket uses.

The skill is *instructions*, not a library — it shells out to the CLI rather than duplicating its code. Optionally add a **Claude summary backend** (Path 2 below) so the bundle doesn't force a `GEMINI_API_KEY` on Claude Code users.

## Background

- **`video-summarizer`** (this repo): a deterministic Python CLI. Pipeline = yt-dlp subtitles → Whisper fallback → Gemini summary/chapters → one markdown file with YAML frontmatter. Handles local files, direct media URLs, and any yt-dlp site. Entry point `video_summarizer.cli:main`; summary backends are pluggable via a registry (`src/video_summarizer/summarize.py` → `SUMMARIZERS = {"gemini": _gemini_backend}`, selected with `--summary-backend`).
- **`watch-youtube`** (mcpmarket skill that prompted this): a Claude Code **agent skill** — markdown prompt instructions telling the agent to pull a transcript and summarize/answer questions conversationally using the agent's own model. YouTube-only, no Whisper fallback, no batch output.
- **Key distinction:** a skill cannot be `import`ed as a fallback *inside* the CLI. The productive integration is the reverse — a skill that *wraps* the CLI (the CLI is the deterministic engine; the skill adds interaction). That is "Path 1" and the basis of this proposal.

## Goal

Let a third party install and use this on their own machine through standard Claude Code channels, with the CLI doing the heavy lifting and the skill providing the front door + Q&A.

---

## Work plan

### Phase 0 — Prerequisite fix (blocks the wheel build)
- [ ] In `pyproject.toml`, the `[project]` table uses the SPDX string `license = "Apache-2.0"`, which requires `setuptools>=77` to build. The pinned build requirement must guarantee that. Confirm `[build-system].requires = ["setuptools>=77"]` (already present) actually resolves at build time; the failure seen during development was an *older* setuptools in the active env. Verify `python -m build` (or `pip wheel .`) succeeds in a clean env. If broader compatibility is wanted, fall back to the table form `license = {text = "Apache-2.0"}`.
- [ ] Confirm `python -m build` produces a valid wheel + sdist.

### Phase 1 — Publish the engine to PyPI
- [ ] Smoke-test the built wheel in a fresh venv: `pip install dist/*.whl`, then `video-summarizer --dry-run <url>`.
- [ ] Document the runtime deps clearly in packaging metadata / README: `ffmpeg`, `yt-dlp`, a Whisper binary (`whisper-cli`), and `GEMINI_API_KEY`. These are **not** pip-installable Python deps — they must be on PATH. (For YouTube/most talks, subtitles are used and the Whisper binary is not exercised.)
- [ ] Publish to PyPI (or TestPyPI first). Project URLs already point at `github.com/Wkkkkk/video-summarizer`.

### Phase 2 — Build the plugin (the skill bundle)
- [ ] Scaffold a Claude Code plugin. Expected shape (VERIFY exact manifest schema against current Claude Code skill-authoring tooling — e.g. the `write-a-skill` / `skill-creator` skills — before committing to field names):
  - `.claude-plugin/plugin.json` — plugin manifest (name, version, description, entry to the skill).
  - `skills/<name>/SKILL.md` — the skill itself.
  - `.claude-plugin/marketplace.json` — marketplace manifest so others can `/plugin marketplace add <repo>` then install.
- [ ] `SKILL.md` behavior:
  1. Detect the engine: `command -v video-summarizer`. If missing, instruct/run `pipx install video-summarizer` (and surface the native-dep requirements: ffmpeg/yt-dlp/Whisper/`GEMINI_API_KEY`).
  2. Run `video-summarizer <source> --out <dir> [--title ...]`.
  3. Read the produced markdown (frontmatter + summary + chapters + transcript).
  4. Add the value the CLI lacks: answer the user's questions about the video, re-frame/condense on demand, optionally persist insights. No extra model cost — the markdown already exists.
- [ ] Decide where the plugin lives: same repo (subdirectory) or a dedicated repo. Recommendation: a subdirectory (`plugin/`) in this repo so versions stay in lockstep, unless a separate release cadence is wanted.
- [ ] Test locally: add the marketplace from a local path, install, run the skill end-to-end against a real URL.

### Phase 3 (optional, recommended) — Claude summary backend
Reduces the bundle's external requirements and answers the original "fallback" ask.
- [ ] Add `"claude": _anthropic_backend` to `SUMMARIZERS` in `summarize.py`, returning the same dict shape `{tldr, key_points, takeaways, chapters}`. Mirror `_gemini_backend`; use structured outputs and `claude-opus-4-8` (or `claude-haiku-4-5` for cheap). Use the `claude-api` skill for correct SDK usage and current model IDs.
- [ ] Wire it through the CLI (`--summary-backend claude`) and as a **fallback** when the Gemini backend errors/rate-limits (today the CLI degrades all the way to transcript-only on summary failure — a second backend is a softer landing).
- [ ] TDD it like the recent bug fixes: tests in `tests/test_summarize.py` mirroring the existing Gemini-backend tests, with the client injected so no network calls.

---

## Known state / things already done (context for the picker-upper)

Two bug fixes landed on `feat/frontmatter` (uncommitted at time of writing), both TDD'd, full suite green (94 tests):
- `cli.py` — duration now ffprobes the local media path when available and falls back to the last transcript cue's timestamp otherwise (was `??:??` for URLs because ffprobe ran on the URL string). New helper `_duration_from_segments`.
- `cli.py` — added `if __name__ == "__main__": raise SystemExit(main())` so `python -m video_summarizer.cli` works (was a silent no-op; only the installed console script ran `main`).

## Portability ceiling (set expectations)

The skill text is fully portable; the *capability* depends on native deps (ffmpeg, yt-dlp, Whisper binary, Gemini key). "Others can use it" = others who can install those. Phase 3 (Claude backend) is the main lever to shrink that requirement for Claude Code users.

## Open questions / to verify

- Exact Claude Code plugin + marketplace manifest schema and field names (verify against current tooling, do not hand-wave).
- Plugin location: in-repo subdirectory vs. separate repo.
- Whether to publish to PyPI directly or TestPyPI first.
- Whether the skill should auto-run `pipx install` or only instruct the user (consent/safety).

## Pointers

- CLI + orchestration: `src/video_summarizer/cli.py`
- Summary backends (the registry to extend in Phase 3): `src/video_summarizer/summarize.py`
- Transcript pipeline: `src/video_summarizer/transcribe.py`
- Packaging metadata + the setuptools blocker: `pyproject.toml`
- Tests + conventions to mirror: `tests/test_cli.py`, `tests/test_render.py`
- Usage + native-dep docs: `README.md`
