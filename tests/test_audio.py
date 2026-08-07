import subprocess
import pytest
import audio


def test_transcode_calls_ffmpeg_and_returns_stdout(monkeypatch):
    captured = {}

    class FakeCompleted:
        returncode = 0
        stdout = b"RIFFWAVEDATA"
        stderr = b""

    def fake_run(cmd, input, stdout, stderr, timeout):
        captured["cmd"] = cmd
        captured["input"] = input
        captured["timeout"] = timeout
        return FakeCompleted()

    monkeypatch.setattr(subprocess, "run", fake_run)
    out = audio.transcode_to_wav(b"rawbytes")
    assert out == b"RIFFWAVEDATA"
    assert captured["cmd"][0] == "ffmpeg"
    assert captured["input"] == b"rawbytes"
    assert captured["timeout"] == audio.FFMPEG_TIMEOUT_SEC


def test_transcode_restricts_protocols(monkeypatch):
    # Untrusted input: ffmpeg must not be able to follow file/URL references
    # embedded in a crafted stream.
    captured = {}

    class FakeCompleted:
        returncode = 0
        stdout = b"WAV"
        stderr = b""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return FakeCompleted()

    monkeypatch.setattr(subprocess, "run", fake_run)
    audio.transcode_to_wav(b"x")
    cmd = captured["cmd"]
    assert "-protocol_whitelist" in cmd
    assert cmd[cmd.index("-protocol_whitelist") + 1] == "pipe"


def test_transcode_timeout_raises(monkeypatch):
    def fake_run(*a, **k):
        raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="timed out"):
        audio.transcode_to_wav(b"x")


def test_transcode_failure_does_not_leak_stderr(monkeypatch):
    class FakeCompleted:
        returncode = 1
        stdout = b""
        stderr = b"/home/someone/secret/path.webm: Invalid data"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeCompleted())
    with pytest.raises(RuntimeError) as err:
        audio.transcode_to_wav(b"x")
    assert "secret" not in str(err.value)


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
