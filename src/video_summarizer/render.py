"""Assemble the final markdown document and compute the output filename."""

import os
import re

import yaml

_MAX_SLUG_LEN = 80


def slugify(title: str) -> str:
    """Lowercase, collapse punctuation/whitespace runs to single hyphens, cap
    length. Unicode letters/digits are preserved so non-English titles (the tool
    transcribes non-English audio) keep a meaningful name instead of "untitled"."""
    s = re.sub(r"[^\w]+", "-", title.strip().lower(), flags=re.UNICODE)
    s = s.strip("-")
    if len(s) > _MAX_SLUG_LEN:
        s = s[:_MAX_SLUG_LEN].rstrip("-")
    return s or "untitled"


def unique_path(out_dir: str, slug: str, ext: str = ".md") -> str:
    """Path for `slug+ext` in `out_dir` that does not yet exist, appending
    `-2`, `-3`, … only on collision so an earlier analysis is never overwritten."""
    candidate = os.path.join(out_dir, f"{slug}{ext}")
    n = 2
    while os.path.exists(candidate):
        candidate = os.path.join(out_dir, f"{slug}-{n}{ext}")
        n += 1
    return candidate


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


def _frontmatter(title, source, duration, date, transcript_source) -> str:
    """YAML frontmatter block, vault-ready. Keys are emitted in a fixed order;
    empty/None values are dropped (never `null`). `safe_dump` quotes scalars that
    would otherwise change type — e.g. a `12:25` duration that YAML 1.1 would read
    as the base-60 int 745."""
    meta = {
        "title": title,
        "source": source,
        "duration": duration,
        "date": date,
        "collected_at": date,
        "interaction_time": date,
        "transcript_source": transcript_source,
    }
    meta = {k: v for k, v in meta.items() if v not in (None, "")}
    body = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).rstrip("\n")
    return f"---\n{body}\n---"


def render_markdown(title, source, duration, date, transcript, analysis, visual) -> str:
    lines = [
        _frontmatter(title, source, duration, date, transcript.get("source")),
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
        lines.append(f"- {ch.get('time', '??:??')} — {ch.get('title', '')}")
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
