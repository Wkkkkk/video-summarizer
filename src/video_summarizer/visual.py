"""Stage 3 (opt-in): on-screen visual notes via Gemini Pro video-native.

Backends take (video_path, client, media_resolution) and return {'notes': [str]}.
This is the only token-heavy stage; the CLI runs it only when --visual is set.
LOW media resolution (~66 tokens/frame vs ~258) makes the video pass ~3x cheaper.
"""

from .errors import ConfigError, StageError

_PROMPT = (
    "Watch this video and list concise bullet notes about what appears ON SCREEN "
    "(visible text, charts, scenes, key visuals) that the audio alone would miss. "
    "Respond with one note per line, no numbering."
)


def _gemini_pro_backend(video_path: str, client, media_resolution: str = "low") -> dict:
    uploaded = client.files.upload(file=video_path)
    config = None
    if media_resolution == "low":
        from google.genai import types

        config = types.GenerateContentConfig(
            media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW,
        )
    resp = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=[uploaded, _PROMPT],
        config=config,
    )
    notes = [line.strip("-• ").strip() for line in resp.text.splitlines() if line.strip()]
    return {"notes": notes}


VISUALIZERS = {"gemini-pro": _gemini_pro_backend}


def visual_notes(video_path: str, backend: str, client,
                 media_resolution: str = "low", registry=None) -> dict:
    registry = VISUALIZERS if registry is None else registry
    fn = registry.get(backend)
    if fn is None:
        raise ConfigError(f"unknown visual backend: {backend}")
    return fn(video_path, client=client, media_resolution=media_resolution)
