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
