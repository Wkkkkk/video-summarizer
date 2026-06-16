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


class _FakeFile:
    def __init__(self, name, state):
        self.name = name
        self.state = type("S", (), {"name": state})()


def _fake_client(captured, upload_state="ACTIVE", get_states=None):
    get_states = list(get_states or [])

    class FakeFiles:
        def upload(self, file):
            return _FakeFile("files/abc", upload_state)

        def get(self, name):
            captured["get_calls"] = captured.get("get_calls", 0) + 1
            return _FakeFile(name, get_states.pop(0))

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


def test_gemini_pro_backend_active_immediately_skips_polling():
    from video_summarizer.visual import _gemini_pro_backend
    captured = {}
    sleeps = []

    _gemini_pro_backend("movie.mp4", client=_fake_client(captured, upload_state="ACTIVE"),
                        sleep_fn=sleeps.append)
    assert sleeps == []
    assert captured.get("get_calls", 0) == 0


def test_gemini_pro_backend_waits_until_active():
    from video_summarizer.visual import _gemini_pro_backend
    captured = {}
    sleeps = []

    client = _fake_client(captured, upload_state="PROCESSING",
                          get_states=["PROCESSING", "ACTIVE"])
    result = _gemini_pro_backend("movie.mp4", client=client, sleep_fn=sleeps.append)
    assert result["notes"] == ["note one", "note two"]
    assert captured["get_calls"] == 2
    assert len(sleeps) == 2  # slept before each poll


def test_gemini_pro_backend_failed_upload_raises_stage_error():
    from video_summarizer.visual import _gemini_pro_backend
    from video_summarizer.errors import StageError
    captured = {}

    client = _fake_client(captured, upload_state="FAILED")
    with pytest.raises(StageError):
        _gemini_pro_backend("movie.mp4", client=client, sleep_fn=lambda s: None)


def test_gemini_pro_backend_active_timeout_raises_stage_error():
    from video_summarizer.visual import _gemini_pro_backend
    from video_summarizer.errors import StageError
    captured = {}

    client = _fake_client(captured, upload_state="PROCESSING",
                          get_states=["PROCESSING"] * 100)
    with pytest.raises(StageError):
        _gemini_pro_backend("movie.mp4", client=client, sleep_fn=lambda s: None,
                            active_timeout=4)
