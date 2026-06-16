import pytest
from video_summarizer.summarize import summarize, SUMMARIZERS
from video_summarizer.errors import ConfigError


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
