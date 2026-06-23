import subprocess
import pytest
import audio


def test_transcode_calls_ffmpeg_and_returns_stdout(monkeypatch):
    captured = {}

    class FakeCompleted:
        returncode = 0
        stdout = b"RIFFWAVEDATA"
        stderr = b""

    def fake_run(cmd, input, stdout, stderr):
        captured["cmd"] = cmd
        captured["input"] = input
        return FakeCompleted()

    monkeypatch.setattr(subprocess, "run", fake_run)
    out = audio.transcode_to_wav(b"rawbytes")
    assert out == b"RIFFWAVEDATA"
    assert captured["cmd"][0] == "ffmpeg"
    assert captured["input"] == b"rawbytes"


def test_transcode_missing_ffmpeg_raises(monkeypatch):
    def fake_run(*a, **k):
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="ffmpeg"):
        audio.transcode_to_wav(b"x")


def test_transcode_nonzero_exit_raises(monkeypatch):
    class FakeCompleted:
        returncode = 1
        stdout = b""
        stderr = b"boom"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeCompleted())
    with pytest.raises(RuntimeError, match="transcode"):
        audio.transcode_to_wav(b"x")
