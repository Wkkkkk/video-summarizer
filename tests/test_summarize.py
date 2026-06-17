import pytest
from video_summarizer.summarize import summarize, SUMMARIZERS, _extract_json
from video_summarizer.errors import ConfigError, StageError as _StageError


def test_default_summarizer_registered():
    assert "gemini" in SUMMARIZERS


def test_claude_summarizer_registered():
    assert "claude" in SUMMARIZERS


def test_summarize_dispatches_to_backend():
    def fake(transcript_text, client, lang, model):
        return {"tldr": "it is about X", "key_points": ["a"], "takeaways": ["b"],
                "chapters": [{"time": "00:00", "title": "Intro"}]}

    result = summarize("some transcript", backend="fake", client=object(),
                       lang="en", registry={"fake": fake})
    assert result["tldr"] == "it is about X"
    assert result["key_points"] == ["a"]
    assert result["takeaways"] == ["b"]
    assert result["chapters"][0]["title"] == "Intro"


def test_summarize_forwards_model_to_backend():
    captured = {}

    def fake(transcript_text, client, lang, model):
        captured["model"] = model
        return {"tldr": "", "key_points": [], "takeaways": [], "chapters": []}

    summarize("t", backend="fake", client=object(), lang="en",
              model="gemini-flash-latest", registry={"fake": fake})
    assert captured["model"] == "gemini-flash-latest"


def test_summarize_default_model_is_pro():
    captured = {}

    def fake(transcript_text, client, lang, model):
        captured["model"] = model
        return {"tldr": "", "key_points": [], "takeaways": [], "chapters": []}

    summarize("t", backend="fake", client=object(), lang="en",
              registry={"fake": fake})
    assert captured["model"] == "gemini-2.5-pro"


def test_summarize_unknown_backend_raises_config_error():
    with pytest.raises(ConfigError):
        summarize("t", backend="nope", client=None, lang="en", registry={})


def test_extract_json_raises_stage_error_on_malformed_json():
    with pytest.raises(_StageError):
        _extract_json('prefix {not: valid json,,} suffix')


def test_extract_json_raises_stage_error_when_no_object():
    with pytest.raises(_StageError):
        _extract_json('no json here at all')


def test_gemini_backend_writes_in_requested_language_and_uses_model():
    from video_summarizer.summarize import _gemini_backend
    captured = {}

    class FakeModels:
        def generate_content(self, model, contents, config=None):
            captured["contents"] = contents
            captured["model"] = model
            captured["config"] = config
            class R:
                text = ('{"tldr": "s", "key_points": ["k1"], '
                        '"takeaways": ["t1"], "chapters": []}')
            return R()

    class FakeClient:
        models = FakeModels()

    result = _gemini_backend("hello transcript", client=FakeClient(),
                             lang="zh-Hans", model="gemini-2.5-pro")
    assert "zh-Hans" in captured["contents"]
    assert "hello transcript" in captured["contents"]
    assert captured["model"] == "gemini-2.5-pro"
    assert captured["config"] is not None        # structured output requested
    assert result["tldr"] == "s"
    assert result["key_points"] == ["k1"]
    assert result["takeaways"] == ["t1"]


def test_claude_backend_writes_in_requested_language_and_uses_model():
    from video_summarizer.summarize import _anthropic_backend
    captured = {}

    class FakeMessages:
        def create(self, model, messages, output_config=None, **kwargs):
            captured["messages"] = messages
            captured["model"] = model
            captured["output_config"] = output_config

            class Block:
                type = "text"
                text = ('{"tldr": "s", "key_points": ["k1"], '
                        '"takeaways": ["t1"], "chapters": []}')

            class R:
                content = [Block()]

            return R()

    class FakeClient:
        messages = FakeMessages()

    result = _anthropic_backend("hello transcript", client=FakeClient(),
                                lang="zh-Hans", model="claude-opus-4-8")
    blob = str(captured["messages"])
    assert "zh-Hans" in blob
    assert "hello transcript" in blob
    assert captured["model"] == "claude-opus-4-8"
    assert captured["output_config"] is not None     # structured output requested
    assert result["tldr"] == "s"
    assert result["key_points"] == ["k1"]
    assert result["takeaways"] == ["t1"]


def test_claude_backend_skips_non_text_blocks():
    from video_summarizer.summarize import _anthropic_backend

    class ThinkingBlock:
        type = "thinking"
        thinking = "deliberating..."

    class TextBlock:
        type = "text"
        text = '{"tldr": "ok", "key_points": [], "takeaways": [], "chapters": []}'

    class FakeMessages:
        def create(self, **kwargs):
            class R:
                content = [ThinkingBlock(), TextBlock()]
            return R()

    class FakeClient:
        messages = FakeMessages()

    result = _anthropic_backend("t", client=FakeClient(), lang="en")
    assert result["tldr"] == "ok"
