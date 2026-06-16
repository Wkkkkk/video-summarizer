import pytest
from video_summarizer.acquire import acquire_media
from video_summarizer.errors import StageError


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
    assert "https://r2.example/x.mp4" in cmd
    assert "-f" in cmd  # a format selector is passed


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
