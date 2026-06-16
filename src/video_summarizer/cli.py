"""CLI + orchestration for video-summarizer.

Pipeline: resolve_transcript (Stage 1) -> summarize (Stage 2)
-> visual_notes (Stage 3, only with --visual) -> render markdown to --out.
"""

import argparse
import datetime
import os
import subprocess
import sys
import tempfile

from .acquire import acquire_media
from .errors import ConfigError, StageError
from .render import render_markdown, slugify
from .summarize import summarize
from .transcribe import resolve_transcript
from .visual import visual_notes

_URL_PREFIXES = ("http://", "https://")


def today_str() -> str:
    return datetime.date.today().isoformat()


def probe_duration(source: str, run_fn=subprocess.run) -> str:
    """ffprobe duration as MM:SS; best-effort, returns '??:??' on failure."""
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "default=nw=1:nk=1", source]
    try:
        proc = run_fn(cmd, capture_output=True, text=True)
        secs = int(float(proc.stdout.strip()))
        return f"{secs // 60:02d}:{secs % 60:02d}"
    except Exception:
        return "??:??"


def make_gemini_client():
    """Build a Gemini client from GEMINI_API_KEY. Raises ConfigError if unset."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise ConfigError("GEMINI_API_KEY is required (set it or use a local backend)")
    from google import genai
    return genai.Client(api_key=key)


def _title_from_source(source: str) -> str:
    base = os.path.basename(source.rstrip("/")) or source
    return os.path.splitext(base)[0] or "video"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    p = argparse.ArgumentParser(prog="video-summarizer")
    p.add_argument("source", help="local file, direct URL, or yt-dlp site URL")
    p.add_argument("--visual", action="store_true", help="run opt-in Gemini Pro visual pass")
    p.add_argument("--out", default="./analyses", help="output directory")
    p.add_argument("--whisper-backend", default="whisper.cpp")
    p.add_argument("--summary-backend", default="gemini-flash")
    p.add_argument("--whisper-model", default="small")
    p.add_argument("--lang", default=None,
                   help="transcription/summary language; omit to auto-detect")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    lang = args.lang or "en"            # subtitle preference + summary fallback
    whisper_lang = args.lang or "auto"  # whisper transcription language

    is_url = args.source.startswith(_URL_PREFIXES)
    title = _title_from_source(args.source)

    if args.dry_run:
        plan = (f"source={args.source} is_url={is_url} visual={args.visual} "
                f"whisper={args.whisper_backend}:{args.whisper_model} "
                f"lang={lang} whisper_lang={whisper_lang} "
                f"summary={args.summary_backend} out={args.out}")
        print("DRY RUN — would run:\n  " + plan)
        return 0

    try:
        client = make_gemini_client()
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    exit_code = 0
    with tempfile.TemporaryDirectory() as workdir:
        _media = {}

        def get_media():
            if "path" not in _media:
                _media["path"] = acquire_media(args.source, is_url, workdir)
            return _media["path"]

        try:
            transcript = resolve_transcript(
                args.source, is_url=is_url, workdir=workdir,
                whisper_backend=args.whisper_backend, model=args.whisper_model,
                lang=lang, whisper_lang=whisper_lang, acquire_fn=get_media)
        except ConfigError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        except StageError as e:
            print(f"error: transcript failed: {e}", file=sys.stderr)
            return 1

        try:
            analysis = summarize(transcript["text"], backend=args.summary_backend,
                                 client=client, lang=transcript.get("lang", lang))
        except ConfigError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        except Exception as e:
            print(f"warning: summary failed: {e}", file=sys.stderr)
            analysis = {"summary": "_(summary failed)_", "chapters": []}
            exit_code = 1

        visual = None
        if args.visual:
            try:
                visual = visual_notes(get_media(), backend="gemini-pro", client=client)
            except Exception as e:
                print(f"warning: visual notes failed: {e}", file=sys.stderr)
                exit_code = 1

        md = render_markdown(
            title=title, source=args.source,
            duration=probe_duration(args.source), date=today_str(),
            transcript=transcript, analysis=analysis, visual=visual)

        os.makedirs(args.out, exist_ok=True)
        out_path = os.path.join(args.out, f"{slugify(title)}.md")
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(md)
        print(out_path)

    return exit_code
