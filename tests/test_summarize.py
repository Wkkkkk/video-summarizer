import pytest
from video_summarizer.summarize import summarize, SUMMARIZERS, _extract_json
from video_summarizer.errors import ConfigError, StageError as _StageError


def test_default_summarizer_registered():
    assert "gemini-flash" in SUMMARIZERS


def test_summarize_dispatches_to_backend():
    def fake(transcript_text, client, lang):
        return {"summary": "it is about X", "chapters": [{"time": "00:00", "title": "Intro"}]}

    result = summarize("some transcript", backend="fake", client=object(),
                       lang="en", registry={"fake": fake})
    assert result["summary"] == "it is about X"
    assert result["chapters"][0]["title"] == "Intro"


def test_summarize_unknown_backend_raises_config_error():
    with pytest.raises(ConfigError):
        summarize("t", backend="nope", client=None, lang="en", registry={})


def test_extract_json_raises_stage_error_on_malformed_json():
    with pytest.raises(_StageError):
        _extract_json('prefix {not: valid json,,} suffix')


def test_extract_json_raises_stage_error_when_no_object():
    with pytest.raises(_StageError):
        _extract_json('no json here at all')


def test_gemini_flash_backend_writes_in_requested_language():
    from video_summarizer.summarize import _gemini_flash_backend
    captured = {}

    class FakeModels:
        def generate_content(self, model, contents):
            captured["contents"] = contents
            class R: text = '{"summary": "s", "chapters": []}'
            return R()

    class FakeClient:
        models = FakeModels()

    result = _gemini_flash_backend("hello transcript", client=FakeClient(), lang="zh-Hans")
    assert "zh-Hans" in captured["contents"]
    assert "hello transcript" in captured["contents"]
    assert result["summary"] == "s"
