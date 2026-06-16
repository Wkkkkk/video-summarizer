"""Stage 2: summary + chapters from transcript text via a pluggable text LLM.

Backends take (transcript_text, client, lang) and return
{'summary': str, 'chapters': [{'time': 'MM:SS', 'title': str}]}.
The Gemini client is injected so tests never call the network.
"""

import json

from .errors import ConfigError, StageError

_PROMPT = (
    "You are summarizing a video transcript. Respond with ONLY a JSON object "
    'with keys "summary" (a 3-5 sentence string) and "chapters" (a list of '
    '{"time": "MM:SS", "title": string}).'
)


def _lang_instruction(lang: str) -> str:
    """Tell the model to write its output in the transcript's language."""
    return (f' Write the "summary" and every chapter "title" in this language '
            f"(BCP-47 code): {lang}. Transcript follows:\n\n")


def _extract_json(text: str) -> dict:
    """Pull the first {...} JSON object out of an LLM response."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise StageError("summarizer returned no JSON object")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise StageError(f"summarizer returned invalid JSON: {e}") from e


def _gemini_flash_backend(transcript_text: str, client, lang: str) -> dict:
    resp = client.models.generate_content(
        model="gemini-flash-latest",
        contents=_PROMPT + _lang_instruction(lang) + transcript_text,
    )
    data = _extract_json(resp.text)
    return {"summary": data.get("summary", ""), "chapters": data.get("chapters", [])}


SUMMARIZERS = {"gemini-flash": _gemini_flash_backend}


def summarize(transcript_text: str, backend: str, client, lang: str,
              registry=None) -> dict:
    registry = SUMMARIZERS if registry is None else registry
    fn = registry.get(backend)
    if fn is None:
        raise ConfigError(f"unknown summary backend: {backend}")
    return fn(transcript_text, client=client, lang=lang)
