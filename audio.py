"""ffmpeg helpers. Audio stays in memory: it is piped through ffmpeg, never
written to a temp file."""
import logging
import subprocess

# ffmpeg is handed untrusted bytes, so bound how long it may run.
FFMPEG_TIMEOUT_SEC = 120

# Compact speech encoding for sending your recording to Google: mono, 16 kHz,
# 32 kbps constant bitrate. 45 minutes is ~11 MB, and the constant bitrate
# lets us compute duration from the byte count.
MP3_BITRATE = 32_000
MP3_MIME = "audio/mp3"

log = logging.getLogger(__name__)


def _run(args: list[str], data: bytes) -> bytes:
    # -protocol_whitelist pipe: the input is untrusted, and some demuxers (HLS,
    # concat) follow file/URL references embedded in the stream. Without this a
    # crafted upload could make ffmpeg read local files or reach the network.
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error",
           "-protocol_whitelist", "pipe", *args]
    try:
        result = subprocess.run(cmd, input=data, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=FFMPEG_TIMEOUT_SEC)
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg is not installed. Install it (e.g. `brew install ffmpeg`).") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("ffmpeg timed out on that recording; it may be corrupt.") from exc
    if result.returncode != 0:
        # stderr can echo details of the input and environment: log, don't return.
        log.warning("ffmpeg exited %s: %s", result.returncode,
                    result.stderr.decode(errors="ignore").strip())
        raise RuntimeError("Could not read that recording; it may be corrupt or in an unsupported format.")
    return result.stdout


def to_mp3(data: bytes) -> bytes:
    """Transcode any browser recording to compact mono speech MP3."""
    return _run(["-i", "pipe:0", "-vn", "-ac", "1", "-ar", "16000",
                 "-b:a", str(MP3_BITRATE), "-f", "mp3", "pipe:1"], data)


def mp3_duration_s(mp3: bytes) -> float:
    return len(mp3) * 8 / MP3_BITRATE


def split_mp3(mp3: bytes, chunk_s: int) -> list[tuple[float, bytes]]:
    """Split into (start_seconds, chunk) pieces of at most `chunk_s` seconds."""
    total = mp3_duration_s(mp3)
    if total <= chunk_s:
        return [(0.0, mp3)]
    chunks = []
    start = 0
    while start < total:
        piece = _run(["-i", "pipe:0", "-ss", str(start), "-t", str(chunk_s),
                      "-c", "copy", "-f", "mp3", "pipe:1"], mp3)
        if piece:
            chunks.append((float(start), piece))
        start += chunk_s
    return chunks
