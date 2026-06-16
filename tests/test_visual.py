import pytest
from video_summarizer.visual import visual_notes, VISUALIZERS
from video_summarizer.errors import ConfigError


def test_default_visualizer_registered():
    assert "gemini-pro" in VISUALIZERS


def test_visual_notes_dispatches_to_backend():
    def fake(video_path, client): return {"notes": ["a chart on screen", "title card"]}

    result = visual_notes("movie.mp4", backend="fake", client=object(),
                          registry={"fake": fake})
    assert result["notes"] == ["a chart on screen", "title card"]


def test_visual_notes_unknown_backend_raises_config_error():
    with pytest.raises(ConfigError):
        visual_notes("movie.mp4", backend="nope", client=None, registry={})
