"""Assemble the final markdown document and compute the output filename."""

import re


def slugify(title: str) -> str:
    s = title.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "untitled"


def _fmt_seconds(secs: float) -> str:
    total = int(secs)
    return f"{total // 60:02d}:{total % 60:02d}"


def _bulleted(lines, items):
    """Append `- item` for each item, or `_(none)_` when the list is empty."""
    if not items:
        lines.append("_(none)_")
        return
    for item in items:
        lines.append(f"- {item}")


def render_markdown(title, source, duration, date, transcript, analysis, visual) -> str:
    lines = [
        f"# {title}",
        f"_{source} · {duration} · {date} · transcript-source: {transcript['source']}_",
        "",
        "## Summary",
        analysis.get("tldr", ""),
        "",
        "### Key points",
    ]
    _bulleted(lines, analysis.get("key_points", []))
    lines += ["", "### Takeaways"]
    _bulleted(lines, analysis.get("takeaways", []))
    lines += ["", "## Chapters"]
    chapters = analysis.get("chapters", [])
    if not chapters:
        lines.append("_(none)_")
    for ch in chapters:
        lines.append(f"- {ch['time']} — {ch['title']}")
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
