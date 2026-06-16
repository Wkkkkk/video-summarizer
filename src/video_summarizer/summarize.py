"""Stage 2: summary + chapters from transcript text via a pluggable text LLM.

Backends take (transcript_text, client, lang, model) and return
{'tldr': str, 'key_points': [str], 'takeaways': [str],
 'chapters': [{'time': 'MM:SS', 'title': str}]}.
The Gemini client is injected so tests never call the network.
"""

import json

from .errors import ConfigError, StageError

_PROMPT = (
    "You are summarizing a video transcript. Respond with ONLY a JSON object "
    'with keys "tldr" (a 2-3 sentence overview string), "key_points" (a list of '
    "strings covering the substantive points made), \"takeaways\" (a list of "
    "strings with the actionable or memorable conclusions), and \"chapters\" (a "
    'list of {"time": "MM:SS", "title": string}).'
)

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "tldr": {"type": "string"},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "takeaways": {"type": "array", "items": {"type": "string"}},
        "chapters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "time": {"type": "string"},
                    "title": {"type": "string"},
                },
            },
        },
    },
}


def _lang_instruction(lang: str) -> str:
    """Tell the model to write its output in the transcript's language."""
    return (' Write the "tldr", every "key_points" entry, every "takeaways" '
            'entry, and every chapter "title" in this language '
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


def _gemini_backend(transcript_text: str, client, lang: str,
                    model: str = "gemini-2.5-pro") -> dict:
    from google.genai import types

    resp = client.models.generate_content(
        model=model,
        contents=_PROMPT + _lang_instruction(lang) + transcript_text,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SUMMARY_SCHEMA,
        ),
    )
    data = _extract_json(resp.text)
    return {
        "tldr": data.get("tldr", ""),
        "key_points": data.get("key_points", []),
        "takeaways": data.get("takeaways", []),
        "chapters": data.get("chapters", []),
    }


SUMMARIZERS = {"gemini": _gemini_backend}


def summarize(transcript_text: str, backend: str, client, lang: str,
              model: str = "gemini-2.5-pro", registry=None) -> dict:
    registry = SUMMARIZERS if registry is None else registry
    fn = registry.get(backend)
    if fn is None:
        raise ConfigError(f"unknown summary backend: {backend}")
    return fn(transcript_text, client=client, lang=lang, model=model)
