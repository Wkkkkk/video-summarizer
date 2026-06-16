# Whisper Transcription Language Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Whisper transcribe in the spoken language (auto-detect by default, explicit `--lang` override) and propagate that language to the summary stage.

**Architecture:** Split the conflated `--lang` into `lang` (subtitle preference + summary fallback, default `en`) and `whisper_lang` (transcription language, default `auto`). `_whisper_cpp_backend` passes `-l <code>` to `whisper-cli`, normalizing BCP-47 to its primary subtag, and in `auto` mode parses whisper-cli's detected-language line into `result["lang"]` so the summary follows the spoken language.

**Tech Stack:** Python 3.11+, pytest, whisper.cpp (`whisper-cli`). Tests inject `run_fn`/stub callables — no real binaries, no network.

**Setup note:** Run tests with `.venv/bin/python -m pytest` (the repo uses a `.venv`; system Python is externally-managed/PEP 668).

**Reference:** Design spec at `docs/superpowers/specs/2026-06-16-whisper-language-design.md`.

---

### Task 1: `_whisper_cpp_backend` accepts `lang`, emits `-l`, sets/parses transcript language

**Files:**
- Modify: `src/video_summarizer/transcribe.py` (the `_whisper_cpp_backend` function, currently lines 89–99; add a module-level regex near the other compiled patterns ~line 17)
- Test: `tests/test_transcribe.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_transcribe.py` (ensure `import types` and `import re` are present at the top of the file; `_whisper_cpp_backend` is imported from `video_summarizer.transcribe`):

```python
def test_whisper_backend_explicit_lang_normalizes_subtag(tmp_path):
    audio = str(tmp_path / "audio.wav")
    captured = {}

    def run_fn(cmd, capture_output=False, text=True):
        captured["cmd"] = cmd
        of = cmd[cmd.index("-of") + 1]
        with open(of + ".txt", "w", encoding="utf-8") as fh:
            fh.write("你好")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    result = _whisper_cpp_backend(audio, run_fn=run_fn, model="base", lang="zh-Hans")
    cmd = captured["cmd"]
    assert cmd[cmd.index("-l") + 1] == "zh"
    assert result["lang"] == "zh"
    assert result["text"] == "你好"


def test_whisper_backend_auto_parses_detected_language(tmp_path):
    audio = str(tmp_path / "audio.wav")
    captured = {}

    def run_fn(cmd, capture_output=False, text=True):
        captured["cmd"] = cmd
        of = cmd[cmd.index("-of") + 1]
        with open(of + ".txt", "w", encoding="utf-8") as fh:
            fh.write("こんにちは")
        return types.SimpleNamespace(
            returncode=0, stdout="",
            stderr="whisper_full_with_state: auto-detected language: ja (p = 0.98)")

    result = _whisper_cpp_backend(audio, run_fn=run_fn, model="base", lang="auto")
    cmd = captured["cmd"]
    assert cmd[cmd.index("-l") + 1] == "auto"
    assert result["lang"] == "ja"


def test_whisper_backend_auto_parse_miss_leaves_lang_unset(tmp_path):
    audio = str(tmp_path / "audio.wav")

    def run_fn(cmd, capture_output=False, text=True):
        of = cmd[cmd.index("-of") + 1]
        with open(of + ".txt", "w", encoding="utf-8") as fh:
            fh.write("hello")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    result = _whisper_cpp_backend(audio, run_fn=run_fn, model="base", lang="auto")
    assert "lang" not in result
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_transcribe.py -k whisper_backend -v`
Expected: FAIL — `_whisper_cpp_backend()` got an unexpected keyword argument `lang` (current signature has no `lang`).

- [ ] **Step 3: Implement**

In `src/video_summarizer/transcribe.py`, add the detection regex near the top (after the existing `_TAG = re.compile(...)` around line 18):

```python
_DETECT = re.compile(r"auto-detected language:\s*([a-z]{2,3})")
```

Replace the whole `_whisper_cpp_backend` function with:

```python
def _whisper_cpp_backend(audio_path: str, run_fn, model: str,
                         lang: str = "auto") -> dict:
    """Run whisper.cpp (`whisper-cli`) and read its plain-text output.

    `lang` is "auto" (let whisper detect) or a language code; a BCP-47 tag is
    reduced to its primary subtag ("zh-Hans" -> "zh"). With a concrete code the
    result's "lang" is that code; in "auto" mode it is the language whisper
    reports (parsed from its output), or unset if no detection line is found."""
    code = "auto" if not lang or lang == "auto" else lang.split("-")[0]
    out_base = audio_path + ".out"
    cmd = ["whisper-cli", "-m", f"models/ggml-{model}.bin",
           "-l", code, "-f", audio_path, "-otxt", "-of", out_base]
    proc = run_fn(cmd, capture_output=True, text=True)
    if getattr(proc, "returncode", 0) != 0:
        raise StageError("whisper.cpp transcription failed")
    with open(out_base + ".txt", encoding="utf-8") as fh:
        text = fh.read().strip()
    result = {"segments": [{"start": 0.0, "text": text}], "text": text}
    if code != "auto":
        result["lang"] = code
    else:
        out = (getattr(proc, "stdout", "") or "") + (getattr(proc, "stderr", "") or "")
        m = _DETECT.search(out)
        if m:
            result["lang"] = m.group(1)
    return result
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_transcribe.py -k whisper_backend -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/video_summarizer/transcribe.py tests/test_transcribe.py
git commit -m "feat: whisper backend takes lang, emits -l, captures detected language"
```

---

### Task 2: Thread `lang` through `transcribe_audio` and `whisper_lang` through `resolve_transcript`

**Files:**
- Modify: `src/video_summarizer/transcribe.py` (`transcribe_audio` lines 105–114; `resolve_transcript` lines 117–138)
- Test: `tests/test_transcribe.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_transcribe.py` (`transcribe_audio` and `resolve_transcript` are imported from `video_summarizer.transcribe`):

```python
def test_transcribe_audio_threads_lang_to_backend():
    captured = {}

    def fake_backend(audio_path, run_fn, model, lang):
        captured["lang"] = lang
        return {"segments": [], "text": "x"}

    transcribe_audio("a.wav", backend="fake", model="base", lang="zh",
                     registry={"fake": fake_backend})
    assert captured["lang"] == "zh"


def test_resolve_transcript_passes_whisper_lang_and_keeps_detected(tmp_path):
    captured = {}

    def fetch_fn(*a, **k):
        return None

    def acquire_fn():
        return "media.mp4"

    def extract_fn(media, workdir, run_fn):
        return "audio.wav"

    def transcribe_fn(audio, backend, model, lang, run_fn):
        captured["lang"] = lang
        return {"segments": [], "text": "你好", "lang": "zh"}

    result = resolve_transcript(
        "http://x/v.mp4", is_url=True, workdir=str(tmp_path),
        whisper_backend="whisper.cpp", model="base",
        lang="en", whisper_lang="auto",
        fetch_fn=fetch_fn, acquire_fn=acquire_fn,
        extract_fn=extract_fn, transcribe_fn=transcribe_fn)
    assert captured["lang"] == "auto"
    assert result["lang"] == "zh"          # detected wins over the "en" hint


def test_resolve_transcript_falls_back_to_lang_hint_when_undetected(tmp_path):
    def fetch_fn(*a, **k):
        return None

    def acquire_fn():
        return "media.mp4"

    def extract_fn(media, workdir, run_fn):
        return "audio.wav"

    def transcribe_fn(audio, backend, model, lang, run_fn):
        return {"segments": [], "text": "hello"}   # backend reported no lang

    result = resolve_transcript(
        "http://x/v.mp4", is_url=True, workdir=str(tmp_path),
        whisper_backend="whisper.cpp", model="base",
        lang="en", whisper_lang="auto",
        fetch_fn=fetch_fn, acquire_fn=acquire_fn,
        extract_fn=extract_fn, transcribe_fn=transcribe_fn)
    assert result["lang"] == "en"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_transcribe.py -k "threads_lang or whisper_lang or fall_back or falls_back" -v`
Expected: FAIL — `transcribe_audio()`/`resolve_transcript()` got an unexpected keyword argument `lang`/`whisper_lang`.

- [ ] **Step 3: Implement**

In `src/video_summarizer/transcribe.py`, replace `transcribe_audio` with:

```python
def transcribe_audio(audio_path: str, backend: str, model: str,
                     lang: str = "auto", registry=None,
                     run_fn=subprocess.run) -> dict:
    """Dispatch to a Whisper backend; stamps source='whisper:<model>'."""
    registry = WHISPER_BACKENDS if registry is None else registry
    fn = registry.get(backend)
    if fn is None:
        raise ConfigError(f"unknown whisper backend: {backend}")
    result = fn(audio_path, run_fn=run_fn, model=model, lang=lang)
    result["source"] = f"whisper:{model}"
    return result
```

Replace `resolve_transcript` with:

```python
def resolve_transcript(source: str, is_url: bool, workdir, whisper_backend: str,
                       model: str, lang: str = "en", whisper_lang: str = "auto",
                       run_fn=subprocess.run, fetch_fn=fetch_subtitles,
                       acquire_fn=None, extract_fn=extract_audio,
                       transcribe_fn=transcribe_audio) -> dict:
    """Cheapest source first: subtitles (URLs only) -> acquire media -> Whisper.

    `lang` is the subtitle preference and the summary-language fallback.
    `whisper_lang` is the transcription language ("auto" to let whisper detect,
    else a language code). `acquire_fn` is a zero-arg callable returning a local
    media path; it defaults to acquiring `source` via `acquire_media`. The
    returned transcript carries a 'lang' field: the subtitle language, the
    detected/explicit Whisper language, or the `lang` hint as a fallback."""
    if is_url:
        subs = fetch_fn(source, workdir, run_fn=run_fn, lang=lang)
        if subs is not None:
            return subs
    if acquire_fn is None:
        media = acquire_media(source, is_url, workdir, run_fn=run_fn)
    else:
        media = acquire_fn()
    audio = extract_fn(media, workdir, run_fn=run_fn)
    result = transcribe_fn(audio, backend=whisper_backend, model=model,
                           lang=whisper_lang, run_fn=run_fn)
    result.setdefault("lang", lang)
    return result
```

- [ ] **Step 4: Check existing tests and run the full transcribe suite**

Adding `lang` to the backend call may break pre-existing `transcribe_audio`/`resolve_transcript` stubs in `tests/test_transcribe.py` whose fake backend or `transcribe_fn` signatures lack a `lang` parameter. Update any such stub to accept `lang` (e.g. add `lang="auto"` or `lang=None` to its parameter list — it need not use the value). Do not change their assertions.

Run: `.venv/bin/python -m pytest tests/test_transcribe.py -v`
Expected: PASS (all transcribe tests, including the three new ones).

- [ ] **Step 5: Commit**

```bash
git add src/video_summarizer/transcribe.py tests/test_transcribe.py
git commit -m "feat: thread whisper_lang through resolve_transcript and transcribe_audio"
```

---

### Task 3: CLI derives `lang` and `whisper_lang` from `--lang`

**Files:**
- Modify: `src/video_summarizer/cli.py` (`--lang` arg line 63; transcript call lines 92–96; summary fallback line 106)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli.py` (the module is imported as `from video_summarizer import cli` — match the existing import style in that file; if it imports specific names instead, monkeypatch the same module object the existing tests use):

```python
def test_cli_no_lang_uses_auto_whisper_and_en_hint(monkeypatch, tmp_path):
    captured = {}

    def fake_resolve(source, **kwargs):
        captured.update(kwargs)
        return {"segments": [], "text": "hi", "lang": "en"}

    monkeypatch.setattr(cli, "make_gemini_client", lambda: object())
    monkeypatch.setattr(cli, "resolve_transcript", fake_resolve)
    monkeypatch.setattr(cli, "summarize",
                        lambda *a, **k: {"summary": "s", "chapters": []})
    monkeypatch.setattr(cli, "probe_duration", lambda *a, **k: "00:10")

    rc = cli.main([str(tmp_path / "v.mp4"), "--out", str(tmp_path / "out")])
    assert rc == 0
    assert captured["lang"] == "en"
    assert captured["whisper_lang"] == "auto"


def test_cli_explicit_lang_sets_both(monkeypatch, tmp_path):
    captured = {}

    def fake_resolve(source, **kwargs):
        captured.update(kwargs)
        return {"segments": [], "text": "hi", "lang": "zh"}

    monkeypatch.setattr(cli, "make_gemini_client", lambda: object())
    monkeypatch.setattr(cli, "resolve_transcript", fake_resolve)
    monkeypatch.setattr(cli, "summarize",
                        lambda *a, **k: {"summary": "s", "chapters": []})
    monkeypatch.setattr(cli, "probe_duration", lambda *a, **k: "00:10")

    rc = cli.main([str(tmp_path / "v.mp4"), "--lang", "zh",
                   "--out", str(tmp_path / "out")])
    assert rc == 0
    assert captured["lang"] == "zh"
    assert captured["whisper_lang"] == "zh"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cli.py -k "no_lang or explicit_lang" -v`
Expected: FAIL — `KeyError: 'whisper_lang'` (the CLI does not yet pass `whisper_lang`).

- [ ] **Step 3: Implement**

In `src/video_summarizer/cli.py`, change the `--lang` default (line 63) from:

```python
    p.add_argument("--lang", default="en")
```
to:
```python
    p.add_argument("--lang", default=None,
                   help="transcription/summary language; omit to auto-detect")
```

After `args = p.parse_args(argv)` (line 65), add:

```python
    lang = args.lang or "en"            # subtitle preference + summary fallback
    whisper_lang = args.lang or "auto"  # whisper transcription language
```

Update the `resolve_transcript` call (lines 92–96) to pass both:

```python
            transcript = resolve_transcript(
                args.source, is_url=is_url, workdir=workdir,
                whisper_backend=args.whisper_backend, model=args.whisper_model,
                lang=lang, whisper_lang=whisper_lang, acquire_fn=get_media)
```

Update the summary fallback (line 106) from `transcript.get("lang", args.lang)` to:

```python
            analysis = summarize(transcript["text"], backend=args.summary_backend,
                                 client=client, lang=transcript.get("lang", lang))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_cli.py -v`
Expected: PASS (all CLI tests, including the two new ones).

- [ ] **Step 5: Commit**

```bash
git add src/video_summarizer/cli.py tests/test_cli.py
git commit -m "feat: CLI derives lang/whisper_lang from --lang (auto-detect by default)"
```

---

### Task 4: Document the multilingual-model requirement

**Files:**
- Modify: `README.md` (the "How it works" / language paragraph, around lines 14–17, and the Requirements note around line 27)

- [ ] **Step 1: Update the README language paragraph**

In `README.md`, replace the paragraph that currently begins "The summary and chapters are written in the **transcript's own language**…" (lines 14–17) with:

```markdown
The summary and chapters are written in the **transcript's own language**: when
subtitles are used, that subtitle language wins; otherwise Whisper auto-detects
the spoken language and the summary follows it. Pass `--lang <code>` to prefer a
subtitle language and force the Whisper transcription language (e.g. `--lang zh`).

> Auto-detection needs a **multilingual** Whisper model (`--whisper-model small`
> or `base`), not the English-only `base.en`.
```

- [ ] **Step 2: Verify the full suite still passes**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (all tests).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: note multilingual model needed for Whisper auto-detect"
```

---

## Final verification (controller, after all tasks)

- Run the full suite: `.venv/bin/python -m pytest -q` → all green.
- Live smoke (real binaries; needs network + a multilingual model present at
  `models/ggml-base.bin`; run with the Bash sandbox disabled). Source has no
  subtitles, so it exercises the Whisper fallback and auto-detection:

  ```bash
  set -a; source .env; set +a
  video-summarizer \
    "https://pub-7fae8d6805af4dc6a5b2a9988274addf.r2.dev/video/bilibili-20260615-BV1YGVY6nE4n-...prompt%E9%93%BE%E6%A8%A1%E5%BC%8F.mp4" \
    --whisper-model base --out ./analyses
  ```
  Expect: exit 0, `transcript-source: whisper:base`, the transcript in Chinese,
  and a **Chinese** summary/chapters in the output markdown. (Use the exact live
  Bilibili fixture URL from the design spec.)
