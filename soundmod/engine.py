"""Mixer: microfone real + sons -> dispositivo de saida (cabo virtual)."""
import threading
from collections import deque

import numpy as np
import sounddevice as sd

from .codec import SR, decode

BLOCK = 480  # 10 ms
MAX_LAG = SR // 4  # descarta audio acumulado alem de 250 ms


def wasapi_devices():
    """(inputs, outputs) como listas de (indice, nome) na API WASAPI."""
    apis = sd.query_hostapis()
    wasapi = next((i for i, a in enumerate(apis) if "WASAPI" in a["name"]), None)
    ins, outs = [], []
    for i, d in enumerate(sd.query_devices()):
        if d["hostapi"] != wasapi:
            continue
        if d["max_input_channels"] > 0:
            ins.append((i, d["name"]))
        if d["max_output_channels"] > 0:
            outs.append((i, d["name"]))
    return ins, outs


def _extra(index):
    api = sd.query_hostapis(sd.query_devices(index)["hostapi"])["name"]
    return sd.WasapiSettings(auto_convert=True) if "WASAPI" in api else None


class _Voice:
    __slots__ = ("data", "pos", "gain")

    def __init__(self, data, gain):
        self.data, self.pos, self.gain = data, 0, gain


class Engine:
    def __init__(self):
        self.lock = threading.Lock()
        self.voices = []
        self.cache = {}
        self.mic_buf = deque()
        self.mic_frames = 0
        self.mon_buf = deque()
        self.mon_frames = 0
        self.mix_mic = True
        self.monitor = True
        self.master = 1.0
        self.has_monitor = False
        self.streams = []

    # ---- sons ----
    def load(self, path):
        key = str(path)
        if key not in self.cache:
            self.cache[key] = decode(path)
        return self.cache[key]

    def play(self, path, volume=1.0):
        data = self.load(path)
        with self.lock:
            self.voices.append(_Voice(data, volume))

    def stop_all(self):
        with self.lock:
            self.voices.clear()

    def invalidate(self, path):
        self.cache.pop(str(path), None)

    # ---- streams ----
    def start(self, mic_idx, out_idx, mon_idx):
        self.stop()
        if out_idx is None:
            raise RuntimeError("Selecione o dispositivo de saida (cabo virtual).")
        try:
            if mic_idx is not None:
                self.streams.append(sd.InputStream(
                    device=mic_idx, samplerate=SR, channels=1, dtype="float32",
                    blocksize=BLOCK, callback=self._mic_cb, extra_settings=_extra(mic_idx)))
            self.streams.append(sd.OutputStream(
                device=out_idx, samplerate=SR, channels=2, dtype="float32",
                blocksize=BLOCK, callback=self._out_cb, extra_settings=_extra(out_idx)))
            if mon_idx is not None:
                self.streams.append(sd.OutputStream(
                    device=mon_idx, samplerate=SR, channels=2, dtype="float32",
                    blocksize=BLOCK, callback=self._mon_cb, extra_settings=_extra(mon_idx)))
            self.has_monitor = mon_idx is not None
            for s in self.streams:
                s.start()
        except Exception:
            self.stop()
            raise

    def stop(self):
        for s in self.streams:
            try:
                s.stop()
                s.close()
            except Exception:
                pass
        self.streams = []
        self.mic_buf.clear()
        self.mic_frames = 0
        self.mon_buf.clear()
        self.mon_frames = 0

    @property
    def running(self):
        return bool(self.streams)

    # ---- callbacks ----
    def _mic_cb(self, indata, frames, t, status):
        self.mic_buf.append(indata[:, 0].copy())
        self.mic_frames += frames
        while self.mic_frames > MAX_LAG and self.mic_buf:
            self.mic_frames -= len(self.mic_buf.popleft())

    def _render_sounds(self, frames):
        mix = np.zeros((frames, 2), dtype=np.float32)
        with self.lock:
            alive = []
            for v in self.voices:
                n = min(frames, len(v.data) - v.pos)
                mix[:n] += v.data[v.pos:v.pos + n] * v.gain
                v.pos += n
                if v.pos < len(v.data):
                    alive.append(v)
            self.voices = alive
        return mix * self.master

    def _out_cb(self, outdata, frames, t, status):
        mix = self._render_sounds(frames)
        if self.monitor and self.has_monitor:
            self.mon_buf.append(mix.copy())
            self.mon_frames += frames
            while self.mon_frames > MAX_LAG and self.mon_buf:
                self.mon_frames -= len(self.mon_buf.popleft())
        if self.mix_mic:
            mic = np.zeros(frames, dtype=np.float32)
            got = 0
            while got < frames and self.mic_buf:
                chunk = self.mic_buf.popleft()
                n = min(len(chunk), frames - got)
                mic[got:got + n] = chunk[:n]
                got += n
                if n < len(chunk):
                    self.mic_buf.appendleft(chunk[n:])
            self.mic_frames = max(0, self.mic_frames - got)
            mix += mic[:, None]
        np.clip(mix, -1.0, 1.0, out=outdata)

    def _mon_cb(self, outdata, frames, t, status):
        outdata[:] = 0
        got = 0
        while got < frames and self.mon_buf:
            chunk = self.mon_buf.popleft()
            n = min(len(chunk), frames - got)
            outdata[got:got + n] = chunk[:n]
            got += n
            if n < len(chunk):
                self.mon_buf.appendleft(chunk[n:])
        self.mon_frames = max(0, self.mon_frames - got)
