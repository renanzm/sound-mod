"""Efeitos de voz em tempo real para o microfone.

Cada efeito e um objeto chamavel: recebe um bloco mono float32 (qualquer tamanho) e devolve
um bloco do mesmo tamanho. Guarda o proprio estado entre blocos e roda dentro do callback de
audio, entao so usa numpy vetorizado (nada de loops por amostra).
"""
import numpy as np

from .codec import SR

EFFECTS = ["normal", "deep", "high", "robot", "ogre", "autotune", "echo", "radio", "alien"]


class PitchShifter:
    """Muda o tom com uma linha de atraso lida por dois cursores em contrafase.

    O atraso de cada cursor varia de 0 a `window` amostras a uma taxa (1 - razao), entao a
    leitura anda na velocidade `razao`. As janelas sin^2 dos dois cursores somam 1, o que
    esconde o salto quando um cursor volta ao inicio. Latencia media: window/2.
    """

    SIZE = 1 << 14

    def __init__(self, ratio=1.0, window=2048):
        self.ratio = ratio
        self.window = window
        self.buf = np.zeros(self.SIZE, np.float32)
        self.written = 0
        self.phase = 0.0

    def __call__(self, x, ratio=None):
        n = len(x)
        k = np.arange(n)
        self.buf[(self.written + k) % self.SIZE] = x
        r0, r1 = self.ratio, self.ratio if ratio is None else ratio
        self.ratio = r1
        rate = r0 + (r1 - r0) * (k + 1) / n  # razao interpolada dentro do bloco (sem estalos)
        phase = (self.phase + np.cumsum((1.0 - rate) / self.window)) % 1.0
        self.phase = float(phase[-1])
        now = self.written + k
        out = np.zeros(n, np.float32)
        for offset in (0.0, 0.5):
            p = (phase + offset) % 1.0
            pos = now - (p * self.window + 1.0)  # +1: nunca le alem da amostra atual
            i = np.floor(pos).astype(np.int64)
            frac = (pos - i).astype(np.float32)
            a = self.buf[i % self.SIZE]
            b = self.buf[(i + 1) % self.SIZE]
            out += (a + (b - a) * frac) * (np.sin(np.pi * p) ** 2).astype(np.float32)
        self.written += n
        return out


class FIR:
    """Filtro FIR com memoria entre blocos."""

    def __init__(self, taps):
        self.h = taps.astype(np.float32)
        self.tail = np.zeros(len(taps) - 1, np.float32)

    def __call__(self, x):
        z = np.concatenate([self.tail, x])
        self.tail = z[len(z) - len(self.tail):]
        return np.convolve(z, self.h, mode="valid").astype(np.float32)


def lowpass(fc, taps=101):
    m = np.arange(taps) - (taps - 1) / 2
    h = np.sinc(2 * fc / SR * m) * np.hamming(taps)
    return h / h.sum()


def bandpass(lo, hi, taps=161):
    return lowpass(hi, taps) - lowpass(lo, taps)


def saturate(x, drive):
    return (np.tanh(drive * x) / np.tanh(drive)).astype(np.float32)


class Echo:
    """Eco com realimentacao. Vetorizado porque o atraso e maior que o bloco."""

    SIZE = 1 << 16

    def __init__(self, delay=0.28, feedback=0.45):
        self.delay = int(delay * SR)
        self.feedback = feedback
        self.buf = np.zeros(self.SIZE, np.float32)
        self.written = 0

    def __call__(self, x):
        k = self.written + np.arange(len(x))
        y = x + self.feedback * self.buf[(k - self.delay) % self.SIZE]
        self.buf[k % self.SIZE] = y
        self.written += len(x)
        return y


class Robot:
    """Robotizacao: STFT com a fase zerada em cada quadro.

    Todos os quadros viram pulsos alinhados, entao a voz sai monotona no tom SR/HOP (~188 Hz)
    mantendo as palavras (envelope espectral). Latencia: um quadro (~21 ms).
    """

    N, HOP = 1024, 256

    def __init__(self):
        self.win = np.hanning(self.N + 1)[:-1].astype(np.float32)  # Hann periodica
        self.frame = np.zeros(self.N, np.float32)
        self.ola = np.zeros(self.N, np.float32)
        self.pending = np.zeros(0, np.float32)
        self.ready = np.zeros(self.N, np.float32)  # pre-enchido = latencia fixa
        # soma de Hann^2 com sobreposicao de 4x = 1.5
        self.norm = 1.0 / 1.5

    def __call__(self, x):
        self.pending = np.concatenate([self.pending, x])
        produced = []
        while len(self.pending) >= self.HOP:
            hop, self.pending = self.pending[:self.HOP], self.pending[self.HOP:]
            self.frame = np.concatenate([self.frame[self.HOP:], hop])
            mag = np.abs(np.fft.rfft(self.frame * self.win))
            pulse = np.fft.fftshift(np.fft.irfft(mag, self.N)).astype(np.float32)
            self.ola += pulse * self.win * self.norm
            produced.append(self.ola[:self.HOP].copy())
            self.ola = np.concatenate([self.ola[self.HOP:], np.zeros(self.HOP, np.float32)])
        if produced:
            self.ready = np.concatenate([self.ready] + produced)
        out, self.ready = self.ready[:len(x)], self.ready[len(x):]
        return out


def detect_pitch(x, fmin=70.0, fmax=1000.0):
    """Frequencia fundamental por autocorrelacao, ou None se for silencio/ruido."""
    x = x - x.mean()
    if float(np.mean(x * x)) < 1e-5:
        return None
    n = len(x)
    spec = np.fft.rfft(x, 2 * n)
    ac = np.fft.irfft(spec * np.conj(spec))[:n]
    lo, hi = int(SR / fmax), min(int(SR / fmin), n - 2)
    # comeca depois da primeira queda abaixo de zero, para nao pegar a cauda do lag 0
    below = np.nonzero(ac[lo:hi] < 0)[0]
    start = lo + (int(below[0]) if len(below) else 0)
    if start >= hi:
        return None
    lag = start + int(np.argmax(ac[start:hi]))
    if ac[lag] < 0.5 * ac[0]:
        return None  # pouco periodico: consoante, ruido
    a, b, c = ac[lag - 1], ac[lag], ac[lag + 1]
    den = a - 2 * b + c
    exact = lag + (0.5 * (a - c) / den if den else 0.0)
    return float(SR / exact)


class Autotune:
    """Puxa a voz para a nota (semitom) mais proxima.

    Com histerese: a nota atual so muda quando a voz se afasta mais de HOLD semitons dela.
    Sem isso, uma voz perto da fronteira entre duas notas fica alternando (soa tremida).
    """

    HOLD = 0.6

    def __init__(self, history=2048, speed=0.6):
        self.shift = PitchShifter(window=1024)
        self.history = np.zeros(history, np.float32)
        self.speed = speed
        self.ratio = 1.0
        self.note = None

    def __call__(self, x):
        self.history = np.concatenate([self.history, x])[-len(self.history):]
        f0 = detect_pitch(self.history)
        target = 1.0
        if f0:
            midi = 69 + 12 * np.log2(f0 / 440.0)
            if self.note is None or abs(midi - self.note) > self.HOLD:
                self.note = round(midi)
            target = 2 ** ((self.note - midi) / 12)
        else:
            self.note = None
        self.ratio += self.speed * (target - self.ratio)
        return self.shift(x, self.ratio)


class Chain:
    def __init__(self, *steps):
        self.steps = steps

    def __call__(self, x):
        for step in self.steps:
            x = step(x)
        return x


class Vibrato:
    """Pitch que oscila (voz de alien)."""

    def __init__(self, ratio=1.3, depth=0.12, rate=5.0):
        self.shift = PitchShifter(window=1536)
        self.ratio, self.depth, self.rate = ratio, depth, rate
        self.t = 0.0

    def __call__(self, x):
        self.t += len(x) / SR
        return self.shift(x, self.ratio + self.depth * np.sin(2 * np.pi * self.rate * self.t))


def make(name):
    """Cria o efeito pelo nome. 'normal' (ou desconhecido) = None, sem processamento."""
    if name == "deep":
        return PitchShifter(0.75)
    if name == "high":
        return PitchShifter(1.45)
    if name == "robot":
        return Robot()
    if name == "ogre":
        return Chain(PitchShifter(0.62), lambda x: saturate(x * 0.6, 2.5), FIR(lowpass(2200)))
    if name == "autotune":
        return Autotune()
    if name == "echo":
        return Echo()
    if name == "radio":
        return Chain(FIR(bandpass(400, 3000, taps=481)), lambda x: saturate(x * 0.8, 2.0))
    if name == "alien":
        return Vibrato()
    return None
