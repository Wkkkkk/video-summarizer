from video_summarizer.render import slugify, render_markdown


def test_slugify_ascii_lowercase_hyphen():
    assert slugify("My Great Video!") == "my-great-video"
    assert slugify("  spaces   and--dashes ") == "spaces-and-dashes"


def test_render_markdown_without_visual_omits_section():
    md = render_markdown(
        title="Talk", source="https://x/v", duration="12:00", date="2026-06-16",
        transcript={"text": "hello", "segments": [{"start": 0.0, "text": "hello"}], "source": "subtitles"},
        analysis={"summary": "a talk", "chapters": [{"time": "00:00", "title": "Start"}]},
        visual=None,
    )
    assert "# Talk" in md
    assert "transcript-source: subtitles" in md
    assert "## Summary" in md and "a talk" in md
    assert "## Chapters" in md and "00:00 — Start" in md
    assert "## Visual notes" not in md
    assert "## Transcript" in md and "[00:00] hello" in md


def test_render_markdown_with_visual_includes_section():
    md = render_markdown(
        title="Talk", source="movie.mp4", duration="01:00", date="2026-06-16",
        transcript={"text": "hi", "segments": [{"start": 0.0, "text": "hi"}], "source": "whisper:small"},
        analysis={"summary": "s", "chapters": []},
        visual={"notes": ["chart on screen"]},
    )
    assert "## Visual notes" in md
    assert "- chart on screen" in md


def test_slugify_falls_back_to_untitled_for_non_ascii():
    assert slugify("日本語のタイトル") == "untitled"
    assert slugify("!!!") == "untitled"
