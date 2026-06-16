from video_summarizer.transcribe import parse_vtt

VTT = """WEBVTT

00:00:00.000 --> 00:00:02.000
Hello world

00:00:02.000 --> 00:00:05.000
this is a test
"""


def test_parse_vtt_extracts_segments_and_text():
    result = parse_vtt(VTT)
    assert result["segments"] == [
        {"start": 0.0, "text": "Hello world"},
        {"start": 2.0, "text": "this is a test"},
    ]
    assert result["text"] == "Hello world this is a test"


def test_parse_vtt_strips_cue_tags_and_blank_lines():
    vtt = "WEBVTT\n\n00:00:01.500 --> 00:00:03.000\n<c>Tagged</c> line\n"
    result = parse_vtt(vtt)
    assert result["segments"] == [{"start": 1.5, "text": "Tagged line"}]


def test_parse_vtt_decodes_html_entities():
    vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nTom &amp; Jerry &#39;run&#39;\n"
    result = parse_vtt(vtt)
    assert result["segments"] == [{"start": 0.0, "text": "Tom & Jerry 'run'"}]


def test_parse_vtt_handles_hours_in_timestamp():
    vtt = "WEBVTT\n\n01:02:03.500 --> 01:02:05.000\nlate cue\n"
    result = parse_vtt(vtt)
    assert result["segments"] == [{"start": 3723.5, "text": "late cue"}]


import os
from video_summarizer.transcribe import fetch_subtitles


def test_fetch_subtitles_returns_transcript_when_vtt_written(tmp_path):
    vtt_path = tmp_path / "sub.en.vtt"

    def fake_run(cmd, **kwargs):
        vtt_path.write_text(
            "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhi there\n", encoding="utf-8"
        )
        class R: returncode = 0
        return R()

    result = fetch_subtitles("https://example.com/v", tmp_path, run_fn=fake_run)
    assert result is not None
    assert result["source"] == "subtitles"
    assert result["text"] == "hi there"


def test_fetch_subtitles_returns_none_when_no_vtt(tmp_path):
    def fake_run(cmd, **kwargs):
        class R: returncode = 0
        return R()

    assert fetch_subtitles("https://example.com/v", tmp_path, run_fn=fake_run) is None
