"""Assemble the final markdown document and compute the output filename."""

import re


def slugify(title: str) -> str:
    s = title.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _fmt_seconds(secs: float) -> str:
    total = int(secs)
    return f"{total // 60:02d}:{total % 60:02d}"


def render_markdown(title, source, duration, date, transcript, analysis, visual) -> str:
    lines = [
        f"# {title}",
        f"_{source} · {duration} · {date} · transcript-source: {transcript['source']}_",
        "",
        "## Summary",
        analysis.get("summary", ""),
        "",
        "## Chapters",
    ]
    for ch in analysis.get("chapters", []):
        lines.append(f"- {ch['time']} — {ch['title']}")
    if not analysis.get("chapters"):
        lines.append("_(none)_")
    if visual is not None:
        lines += ["", "## Visual notes"]
        for note in visual.get("notes", []):
            lines.append(f"- {note}")
    lines += ["", "## Transcript"]
    for seg in transcript.get("segments", []):
        lines.append(f"[{_fmt_seconds(seg['start'])}] {seg['text']}")
    if not transcript.get("segments"):
        lines.append(transcript.get("text", ""))
    return "\n".join(lines) + "\n"
