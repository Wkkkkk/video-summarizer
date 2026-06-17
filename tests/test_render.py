import os

import yaml

from video_summarizer.render import slugify, unique_path, render_markdown


def _frontmatter(md):
    """Parse the leading `--- ... ---` YAML block; return (dict, body)."""
    assert md.startswith("---\n"), "document must open with a frontmatter block"
    _, fm, body = md.split("---\n", 2)
    return yaml.safe_load(fm), body


def test_slugify_ascii_lowercase_hyphen():
    assert slugify("My Great Video!") == "my-great-video"
    assert slugify("  spaces   and--dashes ") == "spaces-and-dashes"


def test_slugify_preserves_unicode_titles():
    # Non-Latin scripts are kept (the tool transcribes non-English audio), with
    # punctuation/whitespace collapsed to hyphens — not flattened to "untitled".
    assert slugify("深度学习教程 第一讲") == "深度学习教程-第一讲"
    assert slugify("日本語のタイトル") == "日本語のタイトル"
    assert slugify("Émile — café résumé") == "émile-café-résumé"


def test_slugify_falls_back_to_untitled_when_empty():
    assert slugify("!!!") == "untitled"
    assert slugify("   ") == "untitled"


def test_slugify_caps_length():
    slug = slugify("word " * 100)
    assert len(slug) <= 80
    assert not slug.endswith("-")


def test_unique_path_returns_plain_name_when_free(tmp_path):
    assert unique_path(str(tmp_path), "talk") == os.path.join(str(tmp_path), "talk.md")


def test_unique_path_counts_up_to_avoid_overwrite(tmp_path):
    open(os.path.join(str(tmp_path), "talk.md"), "w").close()
    assert unique_path(str(tmp_path), "talk") == os.path.join(str(tmp_path), "talk-2.md")
    open(os.path.join(str(tmp_path), "talk-2.md"), "w").close()
    assert unique_path(str(tmp_path), "talk") == os.path.join(str(tmp_path), "talk-3.md")


def test_render_markdown_without_visual_omits_section():
    md = render_markdown(
        title="Talk", source="https://x/v", duration="12:00", date="2026-06-16",
        transcript={"text": "hello", "segments": [{"start": 0.0, "text": "hello"}], "source": "subtitles"},
        analysis={"tldr": "a talk about X", "key_points": ["point one"],
                  "takeaways": ["do this"],
                  "chapters": [{"time": "00:00", "title": "Start"}]},
        visual=None,
    )
    assert "# Talk" in md
    assert "transcript-source: subtitles" in md
    assert "## Summary" in md and "a talk about X" in md
    assert "### Key points" in md and "- point one" in md
    assert "### Takeaways" in md and "- do this" in md
    assert "## Chapters" in md and "00:00 — Start" in md
    assert "## Visual notes" not in md
    assert "## Transcript" in md and "[00:00] hello" in md


def test_render_markdown_empty_lists_show_none():
    md = render_markdown(
        title="Talk", source="movie.mp4", duration="01:00", date="2026-06-16",
        transcript={"text": "hi", "segments": [], "source": "whisper:small"},
        analysis={"tldr": "", "key_points": [], "takeaways": [], "chapters": []},
        visual=None,
    )
    assert "### Key points\n_(none)_" in md
    assert "### Takeaways\n_(none)_" in md
    assert "## Chapters\n_(none)_" in md


def test_render_markdown_tolerates_chapter_missing_keys():
    # The summary schema does not mark chapter time/title required, so the model
    # may return a chapter missing a key. Render must not crash a good run.
    md = render_markdown(
        title="Talk", source="movie.mp4", duration="01:00", date="2026-06-16",
        transcript={"text": "hi", "segments": [], "source": "whisper:small"},
        analysis={"tldr": "s", "key_points": [], "takeaways": [],
                  "chapters": [{"title": "No time"}, {"time": "01:00"}, {}]},
        visual=None,
    )
    assert "## Chapters" in md
    assert "No time" in md          # chapter with only a title still renders
    assert "01:00" in md            # chapter with only a time still renders


def test_render_markdown_emits_frontmatter_then_h1_and_body_line():
    md = render_markdown(
        title="My Talk", source="https://x/v.mp4", duration="12:25", date="2026-06-16",
        transcript={"text": "hi", "segments": [], "source": "whisper:base"},
        analysis={"tldr": "s", "key_points": [], "takeaways": [], "chapters": []},
        visual=None,
    )
    fm, body = _frontmatter(md)
    assert fm["title"] == "My Talk"
    assert fm["source"] == "https://x/v.mp4"
    assert fm["transcript_source"] == "whisper:base"
    # H1 and the existing body metadata line are both kept (decision 3).
    assert "# My Talk" in body
    assert "· transcript-source: whisper:base_" in body


def test_render_frontmatter_duration_is_a_string_not_base60_int():
    # YAML 1.1 parses an unquoted 12:25 as the sexagesimal int 745; the emitter
    # must quote it so it round-trips as the string "12:25".
    md = render_markdown(
        title="T", source="movie.mp4", duration="12:25", date="2026-06-16",
        transcript={"text": "hi", "segments": [], "source": "subtitles"},
        analysis={"tldr": "s", "key_points": [], "takeaways": [], "chapters": []},
        visual=None,
    )
    fm, _ = _frontmatter(md)
    assert fm["duration"] == "12:25"


def test_render_frontmatter_preserves_colon_and_unicode_title():
    title = "讲透 Agentic Design Patterns 1/21: Prompt Chaining"
    md = render_markdown(
        title=title, source="movie.mp4", duration="01:00", date="2026-06-16",
        transcript={"text": "hi", "segments": [], "source": "subtitles"},
        analysis={"tldr": "s", "key_points": [], "takeaways": [], "chapters": []},
        visual=None,
    )
    fm, _ = _frontmatter(md)
    assert fm["title"] == title


def test_render_frontmatter_omits_empty_fields_without_null():
    md = render_markdown(
        title="T", source="movie.mp4", duration="", date="2026-06-16",
        transcript={"text": "hi", "segments": [], "source": "subtitles"},
        analysis={"tldr": "s", "key_points": [], "takeaways": [], "chapters": []},
        visual=None,
    )
    fm, _ = _frontmatter(md)
    assert "duration" not in fm        # empty value dropped entirely
    assert "null" not in md.split("---\n", 2)[1]   # never emits a null literal


def test_render_markdown_with_visual_includes_section():
    md = render_markdown(
        title="Talk", source="movie.mp4", duration="01:00", date="2026-06-16",
        transcript={"text": "hi", "segments": [{"start": 0.0, "text": "hi"}], "source": "whisper:small"},
        analysis={"tldr": "s", "key_points": [], "takeaways": [], "chapters": []},
        visual={"notes": ["chart on screen"]},
    )
    assert "## Visual notes" in md
    assert "- chart on screen" in md
