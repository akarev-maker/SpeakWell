import subprocess

WAV_MIME = "audio/wav"


def transcode_to_wav(data: bytes) -> bytes:
    """Convert arbitrary input audio bytes to WAV bytes using ffmpeg."""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error",
           "-i", "pipe:0", "-f", "wav", "pipe:1"]
    try:
        result = subprocess.run(
            cmd, input=data,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "ffmpeg is not installed. Install it (e.g. `brew install ffmpeg`)."
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed to transcode audio: {result.stderr.decode(errors='ignore')}"
        )
    return result.stdout
