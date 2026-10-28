"""Captura continua do audio do PC (WASAPI loopback) com buffer dos ultimos N segundos.

Usa leitura por polling em thread (sem stream_callback): o callback C do PyAudioWPatch
travou no Python 3.15 durante os testes.
"""
import threading
import time
from collections import deque

import numpy as np
import pyaudiowpatch as pyaudio

from .codec import encode_mp3

CHUNK = 1024


def loopback_names():
    p = pyaudio.PyAudio()
    try:
        return [d["name"] for d in p.get_loopback_device_info_generator()]
    finally:
        p.terminate()


class LoopbackRecorder:
    def __init__(self, seconds=5):
        self.seconds = seconds
        self.lock = threading.Lock()
        self.chunks = deque()
        self.frames = 0
        self.rate = 48000
        self.channels = 2
        self._pa = None
        self._stream = None
        self._thread = None
        self._run = False

    def start(self, device_name=None):
        self.stop()
        pa = pyaudio.PyAudio()
        try:
            dev = None
            if device_name:
                dev = next((d for d in pa.get_loopback_device_info_generator()
                            if d["name"] == device_name), None)
            if dev is None:
                dev = pa.get_default_wasapi_loopback()
            self.rate = int(dev["defaultSampleRate"])
            self.channels = int(dev["maxInputChannels"])
            self._stream = pa.open(
                format=pyaudio.paInt16, channels=self.channels, rate=self.rate, input=True,
                input_device_index=dev["index"], frames_per_buffer=CHUNK)
            self._pa = pa
        except Exception:
            pa.terminate()
            raise
        with self.lock:
            self.chunks.clear()
            self.frames = 0
        self._run = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._run = False
        if self._thread is not None:
            self._thread.join(timeout=1)
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
        if self._pa is not None:
            self._pa.terminate()
        self._stream = self._pa = self._thread = None

    def _loop(self):
        stream = self._stream
        while self._run:
            try:
                avail = stream.get_read_available()
                if avail < CHUNK:
                    time.sleep(0.01)
                    continue
                data = stream.read(avail, exception_on_overflow=False)
            except Exception:
                break
            arr = np.frombuffer(data, dtype=np.int16).reshape(-1, self.channels).copy()
            with self.lock:
                self.chunks.append(arr)
                self.frames += len(arr)
                limit = int(self.seconds * self.rate)
                while self.frames - len(self.chunks[0]) >= limit:
                    self.frames -= len(self.chunks.popleft())

    def save(self, out_path):
        """Salva os ultimos N segundos em mp3. Retorna a duracao em segundos."""
        with self.lock:
            if not self.chunks:
                raise RuntimeError("Nada gravado ainda (sem audio tocando no PC).")
            pcm = np.concatenate(list(self.chunks))
        pcm = pcm[-int(self.seconds * self.rate):]
        encode_mp3(pcm, self.rate, self.channels, out_path)
        return len(pcm) / self.rate
