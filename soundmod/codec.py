"""Decodifica/codifica audio usando o ffmpeg embutido (imageio-ffmpeg)."""
import subprocess

import imageio_ffmpeg
import numpy as np

from .i18n import t

SR = 48000
_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _ffmpeg():
    return imageio_ffmpeg.get_ffmpeg_exe()


def decode(path):
    """Qualquer formato -> float32 estereo 48 kHz, shape (N, 2)."""
    cmd = [_ffmpeg(), "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"]
    r = subprocess.run(cmd, capture_output=True, creationflags=_NOWIN)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError(r.stderr.decode(errors="replace").strip() or t("decode_failed"))
    return np.frombuffer(r.stdout, dtype=np.float32).reshape(-1, 2).copy()


def encode_mp3(pcm_int16, rate, channels, out_path):
    """PCM int16 intercalado (N, channels) -> mp3."""
    cmd = [_ffmpeg(), "-y", "-v", "error", "-f", "s16le", "-ar", str(rate), "-ac", str(channels),
           "-i", "-", "-codec:a", "libmp3lame", "-q:a", "2", str(out_path)]
    r = subprocess.run(cmd, input=pcm_int16.tobytes(), capture_output=True, creationflags=_NOWIN)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode(errors="replace").strip() or t("encode_failed"))
