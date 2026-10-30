import tkinter as tk

import customtkinter as ctk
import numpy as np

ACTIVE = "#2e8b57"  # botao de um som que esta tocando


class ScrollFrame(ctk.CTkFrame):
    """Frame rolavel simples (CTkScrollableFrame trava no Python 3.15)."""

    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        bg = self._apply_appearance_mode(ctk.ThemeManager.theme["CTkFrame"]["fg_color"])
        self.canvas = tk.Canvas(self, highlightthickness=0, bg=bg)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        bar = ctk.CTkScrollbar(self, command=self.canvas.yview)
        bar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=bar.set)
        self.inner = ctk.CTkFrame(self.canvas, fg_color="transparent")
        win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(win, width=e.width))
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._wheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def _wheel(self, e):
        self.canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")


class KeyButton(ctk.CTkFrame):
    """Botao dividido: a parte principal executa a acao, o lapis edita a hotkey."""

    def __init__(self, master, icon, key, on_action, on_edit, width=70):
        super().__init__(master, fg_color="transparent")
        self.icon = icon
        self.normal = ctk.ThemeManager.theme["CTkButton"]["fg_color"]
        self.main = ctk.CTkButton(self, width=width, command=on_action)
        self.main.grid(row=0, column=0)
        self.edit = ctk.CTkButton(self, text="✎", width=26, fg_color=("gray70", "gray30"),
                                  hover_color=("gray60", "gray40"), command=lambda: on_edit(self))
        self.edit.grid(row=0, column=1, padx=(2, 0))
        self.set_key(key)

    def set_key(self, key):
        self.main.configure(text=f"{self.icon} {key.upper() if key else '-'}", state="normal")
        self.edit.configure(state="normal")

    def capturing(self):
        self.main.configure(text="tecla...", state="disabled")
        self.edit.configure(state="disabled")

    def set_active(self, on):
        self.main.configure(fg_color=ACTIVE if on else self.normal)


def fmt(t):
    return f"{int(t // 60)}:{t % 60:04.1f}"


class Waveform(tk.Canvas):
    """Forma de onda do clipe com alcas para escolher o trecho e cursor de reproducao.

    Arrastar as alcas laranjas muda o trecho (on_range(inicio, fim));
    clicar/arrastar no meio move a posicao (on_seek(t)).
    """

    PAD = 8
    GRAB = 8
    BG, WAVE, DIM, SEL, HANDLE, HEAD = "#1e1e1e", "#3b8ed0", "#4a4a4a", "#203548", "#e6a23c", "#ffffff"

    def __init__(self, master, on_range, on_seek, height=84):
        super().__init__(master, height=height, highlightthickness=0, bg=self.BG)
        self.on_range, self.on_seek = on_range, on_seek
        self.peaks = None
        self.dur = self.start = self.end = 0.0
        self.pos = None
        self._drag = None
        self._head = None
        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._motion)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Motion>", self._hover)

    # ---- dados ----
    def set_audio(self, data, rate, start=None, end=None):
        mono = np.abs(data).max(axis=1) if data is not None and len(data) else None
        if mono is None:
            self.peaks, self.dur = None, 0.0
        else:
            k = max(1, len(mono) // 2000)
            self.peaks = mono[:len(mono) // k * k].reshape(-1, k).max(axis=1)
            self.dur = len(mono) / rate
        self.start = min(max(start or 0.0, 0.0), self.dur)
        self.end = self.dur if not end or end > self.dur or end <= self.start else end
        self.pos = None
        self.redraw()

    def set_pos(self, t):
        self.pos = t
        if self._head is None or self.peaks is None:
            return
        if t is None:
            self.itemconfigure(self._head, state="hidden")
        else:
            x = self._x(t)
            self.coords(self._head, x, 0, x, self.winfo_height())
            self.itemconfigure(self._head, state="normal")

    # ---- desenho ----
    def _x(self, t):
        w = max(self.winfo_width() - 2 * self.PAD, 1)
        return self.PAD + (t / self.dur if self.dur else 0) * w

    def _t(self, x):
        w = max(self.winfo_width() - 2 * self.PAD, 1)
        return min(max((x - self.PAD) / w, 0.0), 1.0) * self.dur

    def redraw(self):
        self.delete("all")
        self._head = None
        w, h = self.winfo_width(), self.winfo_height()
        if self.peaks is None or w < 20:
            self.create_text(w / 2, h / 2, fill="gray60", text="Nenhum clipe ainda: pressione a tecla de salvar")
            return
        xs, xe = self._x(self.start), self._x(self.end)
        self.create_rectangle(xs, 0, xe, h, fill=self.SEL, width=0)

        cols = max(int(w - 2 * self.PAD), 1)
        edges = np.linspace(0, len(self.peaks), cols + 1).astype(int)
        edges = np.minimum(edges[:-1], len(self.peaks) - 1)
        amp = np.maximum.reduceat(self.peaks, edges)
        amp = amp / max(float(amp.max()), 1e-3)
        mid, half = h / 2, h / 2 - 14
        for i, a in enumerate(amp):
            x = self.PAD + i
            color = self.WAVE if xs <= x <= xe else self.DIM
            self.create_line(x, mid - a * half - 0.5, x, mid + a * half + 0.5, fill=color)

        for x, t, anchor in ((xs, self.start, "nw"), (xe, self.end, "ne")):
            self.create_line(x, 0, x, h, fill=self.HANDLE, width=2)
            self.create_rectangle(x - 4, h / 2 - 10, x + 4, h / 2 + 10, fill=self.HANDLE, width=0)
            self.create_text(x + (3 if anchor == "nw" else -3), 2, anchor=anchor,
                             fill=self.HANDLE, font=("Segoe UI", 8), text=fmt(t))
        self.create_text(w - self.PAD, h - 2, anchor="se", fill="gray60", font=("Segoe UI", 8),
                         text=f"trecho {self.end - self.start:.1f}s de {self.dur:.1f}s")
        self._head = self.create_line(0, 0, 0, h, fill=self.HEAD, state="hidden")
        self.set_pos(self.pos)

    # ---- mouse ----
    def _which(self, x):
        if self.peaks is None:
            return None
        if abs(x - self._x(self.start)) <= self.GRAB:
            return "start"
        if abs(x - self._x(self.end)) <= self.GRAB:
            return "end"
        return "seek"

    def _hover(self, e):
        self.configure(cursor="sb_h_double_arrow" if self._which(e.x) in ("start", "end") else "hand2")

    def _press(self, e):
        self._drag = self._which(e.x)
        self._motion(e)

    def _motion(self, e):
        t = self._t(e.x)
        if self._drag == "start":
            self.start = min(t, self.end - 0.1)
            self.redraw()
        elif self._drag == "end":
            self.end = max(t, self.start + 0.1)
            self.redraw()
        elif self._drag == "seek":
            self.on_seek(min(max(t, self.start), self.end))

    def _release(self, e):
        if self._drag in ("start", "end"):
            self.on_range(self.start, self.end)
        self._drag = None
