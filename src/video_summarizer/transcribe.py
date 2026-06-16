"""Stage 1: resolve a transcript, cheapest source first.

Order: yt-dlp subtitles (URL sources) -> ffmpeg audio extraction + Whisper.
All subprocess calls go through an injected `run_fn` (default subprocess.run)
so tests never invoke real binaries.
"""

import glob
import html
import os
import re
import subprocess

from .errors import ConfigError, StageError
from .acquire import acquire_media

_TS = re.compile(r"(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})\s*-->")
_TAG = re.compile(r"<[^>]+>")


def _ts_to_seconds(h, m, s, ms) -> float:
    return (int(h or 0) * 3600) + (int(m) * 60) + int(s) + int(ms) / 1000.0


def parse_vtt(text: str) -> dict:
    """Parse WebVTT into {'segments': [{'start','text'}], 'text': str}."""
    segments = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = _TS.search(lines[i])
        if m:
            start = _ts_to_seconds(*m.groups())
            i += 1
            cue_lines = []
            while i < len(lines) and lines[i].strip():
                cue_lines.append(html.unescape(_TAG.sub("", lines[i])).strip())
                i += 1
            cue = " ".join(p for p in cue_lines if p)
            if cue:
                segments.append({"start": start, "text": cue})
        else:
            i += 1
    return {"segments": segments, "text": " ".join(s["text"] for s in segments)}


def _lang_from_vtt(path: str) -> str:
    """Extract the language code from a yt-dlp subtitle filename like
    'sub.en.vtt' or 'sub.zh-Hans.vtt'. Defaults to 'en'."""
    parts = os.path.basename(path).split(".")
    return parts[-2] if len(parts) >= 3 else "en"


def fetch_subtitles(url: str, workdir, run_fn=subprocess.run,
                    lang: str = "en") -> dict | None:
    """Try to download subtitles/auto-captions for `url` in the preferred
    `lang` (and its regional variants). Returns a transcript dict
    (source='subtitles', lang=<actual subtitle language>) or None if no
    subtitle track was produced."""
    out_tmpl = os.path.join(str(workdir), "sub")
    cmd = [
        "yt-dlp", "--write-subs", "--write-auto-subs",
        "--sub-format", "vtt", "--sub-langs", f"{lang}.*,{lang}",
        "--skip-download", "-o", out_tmpl, "--", url,
    ]
    run_fn(cmd, capture_output=True, text=True)
    vtts = sorted(glob.glob(os.path.join(str(workdir), "*.vtt")))
    if not vtts:
        return None
    with open(vtts[0], encoding="utf-8") as fh:
        parsed = parse_vtt(fh.read())
    if not parsed["text"]:
        return None
    parsed["source"] = "subtitles"
    parsed["lang"] = _lang_from_vtt(vtts[0])
    return parsed


def extract_audio(video_path: str, workdir, run_fn=subprocess.run) -> str:
    """Extract 16kHz mono WAV from a video via ffmpeg. Returns the wav path."""
    out = os.path.join(str(workdir), "audio.wav")
    cmd = ["ffmpeg", "-y", "-i", video_path, "-ar", "16000", "-ac", "1", out]
    proc = run_fn(cmd, capture_output=True, text=True)
    if getattr(proc, "returncode", 0) != 0:
        raise StageError("ffmpeg audio extraction failed")
    return out


def _whisper_cpp_backend(audio_path: str, run_fn, model: str) -> dict:
    """Run whisper.cpp (`whisper-cli`) and read its plain-text output."""
    out_base = audio_path + ".out"
    cmd = ["whisper-cli", "-m", f"models/ggml-{model}.bin",
           "-f", audio_path, "-otxt", "-of", out_base]
    proc = run_fn(cmd, capture_output=True, text=True)
    if getattr(proc, "returncode", 0) != 0:
        raise StageError("whisper.cpp transcription failed")
    with open(out_base + ".txt", encoding="utf-8") as fh:
        text = fh.read().strip()
    return {"segments": [{"start": 0.0, "text": text}], "text": text}


WHISPER_BACKENDS = {"whisper.cpp": _whisper_cpp_backend}


def transcribe_audio(audio_path: str, backend: str, model: str,
                     registry=None, run_fn=subprocess.run) -> dict:
    """Dispatch to a Whisper backend; stamps source='whisper:<model>'."""
    registry = WHISPER_BACKENDS if registry is None else registry
    fn = registry.get(backend)
    if fn is None:
        raise ConfigError(f"unknown whisper backend: {backend}")
    result = fn(audio_path, run_fn=run_fn, model=model)
    result["source"] = f"whisper:{model}"
    return result


def resolve_transcript(source: str, is_url: bool, workdir, whisper_backend: str,
                       model: str, lang: str = "en", run_fn=subprocess.run,
                       fetch_fn=fetch_subtitles, acquire_fn=None,
                       extract_fn=extract_audio, transcribe_fn=transcribe_audio) -> dict:
    """Cheapest source first: subtitles (URLs only) -> acquire media -> Whisper.

    `acquire_fn` is a zero-arg callable returning a local media path; it defaults
    to acquiring `source` via `acquire_media`. The CLI injects a memoized closure
    so the download is shared with the visual stage. The returned transcript
    carries a 'lang' field (actual subtitle language, else the `lang` hint)."""
    if is_url:
        subs = fetch_fn(source, workdir, run_fn=run_fn, lang=lang)
        if subs is not None:
            return subs
    if acquire_fn is None:
        media = acquire_media(source, is_url, workdir, run_fn=run_fn)
    else:
        media = acquire_fn()
    audio = extract_fn(media, workdir, run_fn=run_fn)
    result = transcribe_fn(audio, backend=whisper_backend, model=model, run_fn=run_fn)
    result.setdefault("lang", lang)
    return result
