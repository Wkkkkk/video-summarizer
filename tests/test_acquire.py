import subprocess

import pytest
from video_summarizer.acquire import acquire_media
from video_summarizer.errors import StageError


def test_acquire_passes_timeout_to_run_fn(tmp_path):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        (tmp_path / "media.mp4").write_bytes(b"x")
        class R:
            returncode = 0
        return R()

    acquire_media("https://r2.example/x.mp4", is_url=True, workdir=tmp_path, run_fn=fake_run)
    assert captured.get("timeout")  # a positive download timeout is enforced


def test_acquire_raises_stage_error_on_timeout(tmp_path):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 1))

    with pytest.raises(StageError, match="timed out"):
        acquire_media("https://r2.example/x.mp4", is_url=True, workdir=tmp_path, run_fn=fake_run)


def _ok_run_factory(workdir, write=True):
    """Return a fake run_fn that simulates yt-dlp: optionally writes media.mp4
    into workdir and returns a process object with returncode 0."""
    def fake_run(cmd, **kwargs):
        if write:
            (workdir / "media.mp4").write_bytes(b"fake-bytes")
        class R:
            returncode = 0
        return R()
    return fake_run


def test_acquire_local_file_passes_through(tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            returncode = 0
        return R()

    out = acquire_media("/path/movie.mp4", is_url=False, workdir=tmp_path, run_fn=fake_run)
    assert out == "/path/movie.mp4"
    assert calls == []  # local files are never downloaded


def test_acquire_url_downloads_and_returns_local_path(tmp_path):
    out = acquire_media("https://r2.example/x.mp4", is_url=True,
                        workdir=tmp_path, run_fn=_ok_run_factory(tmp_path))
    assert out.endswith("media.mp4")
    assert str(tmp_path) in out


def test_acquire_url_builds_ytdlp_command(tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        (tmp_path / "media.mp4").write_bytes(b"x")
        class R:
            returncode = 0
        return R()

    acquire_media("https://r2.example/x.mp4", is_url=True, workdir=tmp_path, run_fn=fake_run)
    cmd = calls[0]
    assert cmd[0] == "yt-dlp"
    fi = cmd.index("-f")
    assert cmd[fi + 1] == "b/bv*+ba"          # exact format selector
    assert "--" in cmd                          # arg/URL separator present
    assert cmd[-1] == "https://r2.example/x.mp4"  # URL passed last, after --


def test_acquire_raises_stage_error_on_nonzero_exit(tmp_path):
    def fake_run(cmd, **kwargs):
        class R:
            returncode = 1
        return R()

    with pytest.raises(StageError):
        acquire_media("https://r2.example/x.mp4", is_url=True, workdir=tmp_path, run_fn=fake_run)


def test_acquire_raises_stage_error_when_no_file_produced(tmp_path):
    # exit 0 but nothing written
    with pytest.raises(StageError):
        acquire_media("https://r2.example/x.mp4", is_url=True,
                      workdir=tmp_path, run_fn=_ok_run_factory(tmp_path, write=False))


def test_acquire_nonzero_exit_surfaces_ytdlp_error(tmp_path):
    def fake_run(cmd, **kwargs):
        class R:
            returncode = 1
            stdout = ""
            stderr = "WARNING: something\nERROR: Unsupported URL: not-a-real-url"
        return R()

    with pytest.raises(StageError, match="Unsupported URL"):
        acquire_media("not-a-real-url", is_url=True, workdir=tmp_path, run_fn=fake_run)


def test_acquire_no_file_surfaces_ytdlp_output(tmp_path):
    def fake_run(cmd, **kwargs):
        class R:
            returncode = 0
            stdout = ""
            stderr = "ERROR: unable to extract video id"
        return R()  # exit 0 but no media.* written

    with pytest.raises(StageError, match="unable to extract video id"):
        acquire_media("https://youtube.com/watch?v=x", is_url=True,
                      workdir=tmp_path, run_fn=fake_run)


def test_acquire_error_without_stderr_still_raises(tmp_path):
    # stub with no stderr attribute at all must not crash on the detail lookup
    def fake_run(cmd, **kwargs):
        class R:
            returncode = 1
        return R()

    with pytest.raises(StageError, match="media download failed"):
        acquire_media("https://r2.example/x.mp4", is_url=True, workdir=tmp_path, run_fn=fake_run)
