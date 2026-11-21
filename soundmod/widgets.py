import tkinter as tk

import customtkinter as ctk
import numpy as np

from . import theme
from .i18n import t


class ScrollFrame(ctk.CTkFrame):
    """Frame rolavel simples (CTkScrollableFrame trava no Python 3.15)."""

    def __init__(self, master, bg=theme.CARD):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, highlightthickness=0, bg=bg)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        bar = ctk.CTkScrollbar(self, command=self.canvas.yview, width=12)
        bar.grid(row=0, column=1, sticky="ns", padx=(4, 0))
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
    """Botao dividido: a pilula executa a acao, o lapis edita a hotkey e o ⌫ remove a hotkey."""

    def __init__(self, master, icon, key, on_action, on_edit, on_clear, width=74, color=theme.ITEM_HOVER):
        super().__init__(master, fg_color="transparent")
        self.icon = icon
        self.color = color
        self.main = ctk.CTkButton(self, width=width, height=32, corner_radius=16, fg_color=color,
                                  hover_color=theme.DIM, font=theme.font(13, "bold"), command=on_action)
        self.main.grid(row=0, column=0)
        self.edit = theme.icon_button(self, theme.EDIT, lambda: on_edit(self), size=28, color="transparent",
                                      text_color=theme.MUTED, glyph_size=12)
        self.edit.grid(row=0, column=1, padx=(4, 0))
        self.clear = theme.icon_button(self, theme.CLEAR, lambda: on_clear(self), size=28, color="transparent",
                                       text_color=theme.MUTED, glyph_size=12)
        self.clear.grid(row=0, column=2)
        self.set_key(key)

    def set_key(self, key):
        self.main.configure(text=f"{self.icon}  {key.upper() if key else '—'}", state="normal")
        self.edit.configure(state="normal")
        self.clear.configure(state="normal" if key else "disabled")

    def capturing(self):
        self.main.configure(text=t("press_key"), state="disabled")
        self.edit.configure(state="disabled")
        self.clear.configure(state="disabled")

    def set_active(self, on):
        self.main.configure(fg_color=theme.GREEN if on else self.color,
                            hover_color=theme.GREEN_HOVER if on else theme.DIM,
                            text_color="#0F1A12" if on else theme.TEXT)


class EffectGrid(ctk.CTkFrame):
    """Grade de botoes-pilula para escolher um efeito (um selecionado por vez)."""

    def __init__(self, master, options, selected, command, columns=3):
        super().__init__(master, fg_color="transparent")
        self.command = command
        self.buttons = {}
        for c in range(columns):
            self.grid_columnconfigure(c, weight=1, uniform="fx")
        for i, (value, label) in enumerate(options):
            b = ctk.CTkButton(self, text=label, width=60, height=32, corner_radius=16, font=theme.font(13, "bold"),
                              command=lambda v=value: self.select(v, notify=True))
            b.grid(row=i // columns, column=i % columns, padx=3, pady=3, sticky="ew")
            self.buttons[value] = b
        self.select(selected)

    def select(self, value, notify=False):
        self.value = value
        for v, b in self.buttons.items():
            on = v == value
            b.configure(fg_color=theme.ACCENT if on else theme.ITEM,
                        hover_color=theme.ACCENT_HOVER if on else theme.ITEM_HOVER,
                        text_color="#FFFFFF" if on else theme.MUTED)
        if notify:
            self.command(value)


class StatusPill(ctk.CTkFrame):
    """Indicador 'Ao vivo' / 'Parado' com bolinha colorida."""

    def __init__(self, master):
        super().__init__(master, fg_color=theme.ITEM, corner_radius=16, border_width=1, border_color=theme.BORDER)
        self.dot = ctk.CTkLabel(self, text="●", font=theme.font(12), width=10)
        self.dot.grid(row=0, column=0, padx=(12, 4), pady=4)
        self.label = ctk.CTkLabel(self, font=theme.font(12, "bold"))
        self.label.grid(row=0, column=1, padx=(0, 14), pady=4)
        self.on = None

    def set(self, on):
        if on != self.on:
            self.on = on
            self.dot.configure(text_color=theme.GREEN if on else theme.DIM)
            self.label.configure(text=t("live") if on else t("offline"),
                                 text_color=theme.TEXT if on else theme.MUTED)


def fmt(t):
    return f"{int(t // 60)}:{t % 60:04.1f}"


class Waveform(tk.Canvas):
    """Forma de onda do clipe em barras, com alcas para escolher o trecho e cursor de reproducao.

    Arrastar as alcas muda o trecho (on_range(inicio, fim));
    clicar/arrastar no meio move a posicao (on_seek(t)).
    """

    PAD = 12
    GRAB = 10
    STEP = 5  # pixels por barra (barra + espaco)

    def __init__(self, master, on_range, on_seek, height=96, bg=theme.ITEM):
        super().__init__(master, height=height, highlightthickness=0, bg=bg)
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
            self.coords(self._head, x, 6, x, self.winfo_height() - 6)
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
        if self.peaks is None or w < 40:
            self.create_text(w / 2, h / 2, fill=theme.MUTED, font=theme.font(12), text=t("no_clip"))
            return
        xs, xe = self._x(self.start), self._x(self.end)
        bars = max(int((w - 2 * self.PAD) / self.STEP), 1)
        edges = np.linspace(0, len(self.peaks), bars + 1).astype(int)
        edges = np.minimum(edges[:-1], len(self.peaks) - 1)
        amp = np.maximum.reduceat(self.peaks, edges)
        amp = amp / max(float(amp.max()), 1e-3)
        mid, half = h / 2, h / 2 - 18
        for i, a in enumerate(amp):
            x = self.PAD + (i + 0.5) * self.STEP
            color = theme.ACCENT if xs <= x <= xe else theme.DIM
            hh = max(a * half, 1.5)
            self.create_line(x, mid - hh, x, mid + hh, fill=color, width=3, capstyle="round")

        for x, when, anchor in ((xs, self.start, "nw"), (xe, self.end, "ne")):
            self.create_line(x, 6, x, h - 6, fill=theme.TEXT, width=2)
            self.create_oval(x - 6, mid - 6, x + 6, mid + 6, fill=theme.TEXT, outline=theme.ACCENT, width=2)
            self.create_text(x + (5 if anchor == "nw" else -5), 4, anchor=anchor,
                             fill=theme.TEXT, font=theme.font(10, "bold"), text=fmt(when))
        self.create_text(w - self.PAD, h - 4, anchor="se", fill=theme.MUTED, font=theme.font(10),
                         text=t("selection", sel=self.end - self.start, total=self.dur))
        self._head = self.create_line(0, 0, 0, h, fill=theme.WARN, width=2, state="hidden")
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
