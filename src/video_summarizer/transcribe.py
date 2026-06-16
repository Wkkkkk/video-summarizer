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


def fetch_subtitles(url: str, workdir, run_fn=subprocess.run) -> dict | None:
    """Try to download subtitles/auto-captions for `url`. Returns a transcript
    dict (with source='subtitles') or None if no subtitle track was produced."""
    out_tmpl = os.path.join(str(workdir), "sub")
    cmd = [
        "yt-dlp", "--write-subs", "--write-auto-subs",
        "--sub-format", "vtt", "--sub-langs", "en.*,en",
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
    return parsed
