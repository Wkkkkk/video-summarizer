import pytest
from video_summarizer.visual import visual_notes, VISUALIZERS
from video_summarizer.errors import ConfigError


def test_default_visualizer_registered():
    assert "gemini-pro" in VISUALIZERS


def test_visual_notes_dispatches_to_backend():
    def fake(video_path, client, media_resolution):
        return {"notes": ["a chart on screen", "title card"]}

    result = visual_notes("movie.mp4", backend="fake", client=object(),
                          registry={"fake": fake})
    assert result["notes"] == ["a chart on screen", "title card"]


def test_visual_notes_forwards_media_resolution():
    captured = {}

    def fake(video_path, client, media_resolution):
        captured["media_resolution"] = media_resolution
        return {"notes": []}

    visual_notes("movie.mp4", backend="fake", client=object(),
                 media_resolution="default", registry={"fake": fake})
    assert captured["media_resolution"] == "default"


def test_visual_notes_default_media_resolution_is_low():
    captured = {}

    def fake(video_path, client, media_resolution):
        captured["media_resolution"] = media_resolution
        return {"notes": []}

    visual_notes("movie.mp4", backend="fake", client=object(),
                 registry={"fake": fake})
    assert captured["media_resolution"] == "low"


def test_visual_notes_unknown_backend_raises_config_error():
    with pytest.raises(ConfigError):
        visual_notes("movie.mp4", backend="nope", client=None, registry={})


def _fake_client(captured):
    class FakeFiles:
        def upload(self, file):
            return "uploaded-handle"

    class FakeModels:
        def generate_content(self, model, contents, config=None):
            captured["config"] = config
            captured["model"] = model
            class R:
                text = "note one\nnote two"
            return R()

    class FakeClient:
        files = FakeFiles()
        models = FakeModels()

    return FakeClient()


def test_gemini_pro_backend_low_sets_low_resolution_config():
    from video_summarizer.visual import _gemini_pro_backend
    from google.genai import types
    captured = {}

    result = _gemini_pro_backend("movie.mp4", client=_fake_client(captured),
                                 media_resolution="low")
    assert captured["config"] is not None
    assert captured["config"].media_resolution == types.MediaResolution.MEDIA_RESOLUTION_LOW
    assert captured["model"] == "gemini-2.5-pro"
    assert result["notes"] == ["note one", "note two"]


def test_gemini_pro_backend_default_passes_no_config():
    from video_summarizer.visual import _gemini_pro_backend
    captured = {}

    _gemini_pro_backend("movie.mp4", client=_fake_client(captured),
                        media_resolution="default")
    assert captured["config"] is None
