"""Acquire a local media file from any source.

Local paths pass through unchanged. URLs — yt-dlp sites (YouTube/Bilibili) or
direct media such as public R2 .mp4 links — are downloaded via yt-dlp into a
working directory. All subprocess calls go through an injected `run_fn` so
tests never invoke real binaries."""

import glob
import os
import subprocess

from .errors import StageError


def acquire_media(source: str, is_url: bool, workdir, run_fn=subprocess.run) -> str:
    """Return a local media path for `source`. Local files pass through; URLs
    are downloaded with yt-dlp into `workdir`. Raises StageError on download
    failure or if no media file is produced."""
    if not is_url:
        return source
    out_tmpl = os.path.join(str(workdir), "media.%(ext)s")
    cmd = ["yt-dlp", "-f", "b/bv*+ba", "-o", out_tmpl, "--", source]
    proc = run_fn(cmd, capture_output=True, text=True)
    if getattr(proc, "returncode", 0) != 0:
        raise StageError(f"media download failed: {source}")
    files = sorted(glob.glob(os.path.join(str(workdir), "media.*")))
    if not files:
        raise StageError(f"no media file produced for {source}")
    return files[0]
