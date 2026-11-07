"""Mixer: microfone real + sons -> dispositivo de saida (cabo virtual)."""
import threading
from collections import deque

import numpy as np
import sounddevice as sd

from .codec import SR, decode
from .i18n import t

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


class _Channel:
    """Um som carregado com posicao propria. Toca apenas o trecho [start, end)."""
    __slots__ = ("data", "pos", "start", "end", "gain", "playing")

    def __init__(self, data, gain):
        self.data = data
        self.pos = self.start = 0
        self.end = len(data)
        self.gain = gain
        self.playing = False


class Engine:
    def __init__(self):
        self.lock = threading.Lock()
        self.channels = {}  # id (slot ou "clip") -> _Channel
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

    def invalidate(self, path):
        self.cache.pop(str(path), None)

    # ---- canais ----
    def set_sound(self, cid, path, gain=1.0):
        """Carrega (decodifica se preciso) e associa ao canal, parado. Retorna a duracao em s."""
        data = self.load(path)
        with self.lock:
            self.channels[cid] = _Channel(data, gain)
        return len(data) / SR

    def remove(self, cid):
        with self.lock:
            self.channels.pop(cid, None)

    def rekey(self, old, new):
        """Passa o canal para outro id sem interromper o som."""
        with self.lock:
            if old in self.channels:
                self.channels[new] = self.channels.pop(old)

    def has(self, cid):
        return cid in self.channels

    def _solo(self, cid):
        """So um som por vez: para todos os outros canais (chamar com o lock)."""
        for other, ch in self.channels.items():
            if other is not cid and (ch.playing or ch.pos != ch.start):
                ch.playing = False
                ch.pos = ch.start

    def play(self, cid):
        """Se ja estiver tocando, recomeca; senao continua de onde parou."""
        with self.lock:
            ch = self.channels.get(cid)
            if ch is None:
                return False
            if ch.playing or not ch.start <= ch.pos < ch.end:
                ch.pos = ch.start
            self._solo(cid)
            ch.playing = True
            return True

    def toggle(self, cid):
        """Tocando -> para; senao toca (continua se estava pausado). Retorna se ficou tocando ou None."""
        with self.lock:
            ch = self.channels.get(cid)
            if ch is None:
                return None
            if ch.playing:
                ch.playing = False
                ch.pos = ch.start
                return False
            if not ch.start <= ch.pos < ch.end:
                ch.pos = ch.start
            self._solo(cid)
            ch.playing = True
            return True

    def pause(self, cid):
        """Alterna pausa/continuar (nao faz nada se estiver parado no inicio)."""
        with self.lock:
            ch = self.channels.get(cid)
            if ch and (ch.playing or ch.pos != ch.start):
                if not ch.playing:
                    self._solo(cid)
                ch.playing = not ch.playing

    def stop(self, cid):
        with self.lock:
            ch = self.channels.get(cid)
            if ch:
                ch.playing = False
                ch.pos = ch.start

    def stop_all(self):
        with self.lock:
            for ch in self.channels.values():
                ch.playing = False
                ch.pos = ch.start

    def seek(self, cid, seconds):
        with self.lock:
            ch = self.channels.get(cid)
            if ch:
                ch.pos = min(max(int(seconds * SR), ch.start), ch.end - 1)

    def set_gain(self, cid, gain):
        with self.lock:
            ch = self.channels.get(cid)
            if ch:
                ch.gain = gain

    def set_range(self, cid, start_s, end_s):
        with self.lock:
            ch = self.channels.get(cid)
            if ch:
                n = len(ch.data)
                ch.start = min(max(int(start_s * SR), 0), n - 1)
                ch.end = min(max(int(end_s * SR), ch.start + 1), n)
                if not ch.start <= ch.pos < ch.end:
                    ch.pos = ch.start

    def state(self, cid):
        """(posicao_s, duracao_total_s, tocando) ou None."""
        ch = self.channels.get(cid)
        if ch is None:
            return None
        return ch.pos / SR, len(ch.data) / SR, ch.playing

    # ---- streams ----
    def open(self, mic_idx, out_idx, mon_idx):
        self.close()
        if out_idx is None:
            raise RuntimeError(t("select_output"))
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
            self.close()
            raise

    def close(self):
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
            for ch in self.channels.values():
                if not ch.playing:
                    continue
                n = min(frames, ch.end - ch.pos)
                mix[:n] += ch.data[ch.pos:ch.pos + n] * ch.gain
                ch.pos += n
                if ch.pos >= ch.end:
                    ch.playing = False
                    ch.pos = ch.start
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
