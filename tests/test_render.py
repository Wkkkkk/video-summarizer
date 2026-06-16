from video_summarizer.render import slugify, render_markdown


def test_slugify_ascii_lowercase_hyphen():
    assert slugify("My Great Video!") == "my-great-video"
    assert slugify("  spaces   and--dashes ") == "spaces-and-dashes"


def test_slugify_falls_back_to_untitled_for_non_ascii():
    assert slugify("日本語のタイトル") == "untitled"
    assert slugify("!!!") == "untitled"


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


def test_render_markdown_with_visual_includes_section():
    md = render_markdown(
        title="Talk", source="movie.mp4", duration="01:00", date="2026-06-16",
        transcript={"text": "hi", "segments": [{"start": 0.0, "text": "hi"}], "source": "whisper:small"},
        analysis={"tldr": "s", "key_points": [], "takeaways": [], "chapters": []},
        visual={"notes": ["chart on screen"]},
    )
    assert "## Visual notes" in md
    assert "- chart on screen" in md
