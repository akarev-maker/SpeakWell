import logging
import subprocess

WAV_MIME = "audio/wav"

# ffmpeg is handed untrusted bytes, so bound how long it may run. A browser
# recording of any sane length transcodes in well under this; the timeout only
# catches input crafted or corrupt enough to wedge the demuxer.
FFMPEG_TIMEOUT_SEC = 60

log = logging.getLogger(__name__)


def transcode_to_wav(data: bytes) -> bytes:
    """Convert arbitrary input audio bytes to WAV bytes using ffmpeg."""
    # -protocol_whitelist pipe: the input is untrusted, and some demuxers (HLS,
    # concat) follow file/URL references embedded in the stream. Without this a
    # crafted upload could make ffmpeg read local files or reach the network.
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error",
           "-protocol_whitelist", "pipe",
           "-i", "pipe:0", "-f", "wav", "pipe:1"]
    try:
        result = subprocess.run(
            cmd, input=data,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=FFMPEG_TIMEOUT_SEC,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "ffmpeg is not installed. Install it (e.g. `brew install ffmpeg`)."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "ffmpeg timed out transcoding that recording — the audio may be "
            "corrupt or in an unsupported format."
        ) from exc
    if result.returncode != 0:
        # ffmpeg's stderr can echo details of the input and the server's
        # environment, so log it for the operator instead of returning it.
        log.warning(
            "ffmpeg exited %s: %s",
            result.returncode, result.stderr.decode(errors="ignore").strip(),
        )
        raise RuntimeError(
            "Could not transcode that recording — the audio may be corrupt or "
            "in an unsupported format."
        )
    return result.stdout
