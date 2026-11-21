import queue
import re
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
import numpy as np

from . import config, i18n, theme, voice
from .codec import SR, encode_mp3
from .engine import Engine, wasapi_devices
from .hotkeys import HotkeyManager, capture_key
from .i18n import t
from .recorder import LoopbackRecorder, loopback_names
from .widgets import EffectGrid, KeyButton, ScrollFrame, StatusPill, Waveform

AUDIO_GLOB = "*.mp3 *.wav *.ogg *.flac *.m4a *.aac *.wma"
LEGACY_NONE = "(nenhum)"  # config.json antigos guardavam o texto em vez de ""
CLIP = "clip"  # id do canal do clipe no engine
SIDEBAR = 340


def mmss(t):
    return f"{int(t // 60)}:{int(t % 60):02d}"


def short(name, n=30):
    return name if len(name) <= n else name[:n - 1] + "…"


def card(master, **kwargs):
    return ctk.CTkFrame(master, fg_color=theme.CARD, corner_radius=theme.RADIUS_CARD, border_width=1,
                        border_color=theme.BORDER, **kwargs)


def title(master, text, size=17):
    return ctk.CTkLabel(master, text=text, font=theme.display(size, "bold"), anchor="w")


def caption(master, text, **kwargs):
    return ctk.CTkLabel(master, text=text, font=theme.font(12), text_color=theme.MUTED, anchor="w", **kwargs)


class SlotRow:
    """Linha de um som (um 'cartao' na lista). O proprio objeto e o id do canal no engine."""

    def __init__(self, app, slot):
        self.app, self.slot = app, slot
        self.dur = 0.0
        self.drag_until = 0.0
        self.active = False
        f = self.frame = ctk.CTkFrame(app.list, fg_color=theme.ITEM, corner_radius=14, border_width=1,
                                      border_color=theme.ITEM)
        f.grid_columnconfigure(2, weight=1)
        set_key = lambda k: slot.__setitem__("key", k)
        self.key = KeyButton(f, "▶", slot["key"], lambda: app._toggle_slot(self),
                             lambda kb: app._rebind(kb, set_key), lambda kb: app._clear_key(kb, set_key))
        self.file_btn = theme.icon_button(f, theme.FOLDER, lambda: app._pick(self), color=theme.ITEM_HOVER,
                                          hover=theme.DIM)
        self.name = ctk.CTkLabel(f, text=short(Path(slot["path"]).name) or t("no_file"), anchor="w",
                                 font=theme.font(13, "bold"),
                                 text_color=theme.TEXT if slot["path"] else theme.MUTED)
        self.time = ctk.CTkLabel(f, text="-:-- / -:--", width=78, text_color=theme.MUTED, font=theme.font(12))
        self.progress = ctk.CTkSlider(f, from_=0, to=1, width=140, height=16, command=self._seek)
        self.progress.set(0)
        self.vol_icon = ctk.CTkLabel(f, text=theme.VOLUME, font=theme.icons(12), text_color=theme.MUTED, width=16)
        self.vol = ctk.CTkSlider(f, from_=0, to=1.5, width=76, height=16, command=self._volume,
                                 progress_color=theme.MUTED)
        self.vol.set(slot["volume"])
        self.play_btn = theme.icon_button(f, theme.PLAY, lambda: app._play_slot(self), color=theme.ITEM_HOVER,
                                          hover=theme.DIM)
        self.pause_btn = theme.icon_button(f, theme.PAUSE, lambda: app.engine.pause(self), color=theme.ITEM_HOVER,
                                           hover=theme.DIM)
        self.stop_btn = theme.icon_button(f, theme.STOP, lambda: app.engine.stop(self), color=theme.ITEM_HOVER,
                                          hover=theme.DIM)
        self.rm_btn = theme.icon_button(f, theme.DELETE, lambda: app._remove_slot(self), color="transparent",
                                        hover=theme.DANGER_SOFT, text_color=theme.DANGER)
        widgets = [self.key, self.file_btn, self.name, self.time, self.progress, self.vol_icon, self.vol,
                   self.play_btn, self.pause_btn, self.stop_btn, self.rm_btn]
        for c, w in enumerate(widgets):
            left = 10 if c == 0 else (2 if w in (self.vol, self.pause_btn, self.stop_btn) else 8)
            w.grid(row=0, column=c, padx=(left, 10 if w is self.rm_btn else 0), pady=8,
                   sticky="ew" if w is self.name else "")

    def grid(self, r):
        self.frame.grid(row=r, column=0, sticky="ew", pady=4)

    def destroy(self):
        self.frame.destroy()

    def set_name(self, path):
        self.name.configure(text=short(Path(path).name), text_color=theme.TEXT)

    def _seek(self, v):
        self.drag_until = time.monotonic() + 0.4
        self.app.engine.seek(self, float(v))

    def _volume(self, v):
        self.slot["volume"] = float(v)
        self.app.engine.set_gain(self, float(v))

    def tick(self):
        st = self.app.engine.state(self)
        if st is None:
            pos, dur, playing = 0.0, 0.0, False
            self.time.configure(text="-:-- / -:--")
        else:
            pos, dur, playing = st
            self.time.configure(text=f"{mmss(pos)} / {mmss(dur)}")
        if dur != self.dur:
            self.dur = dur
            self.progress.configure(to=max(dur, 0.01))
        if time.monotonic() > self.drag_until:
            self.progress.set(pos)
        if playing != self.active:
            self.active = playing
            self.key.set_active(playing)
            self.frame.configure(border_color=theme.GREEN if playing else theme.ITEM)


class App(ctk.CTk):
    def __init__(self):
        theme.set_app_id()
        theme.apply_colors()
        super().__init__()
        theme.load_fonts(self)
        self.title("Sound Mod")
        self.geometry("1320x850")
        self.minsize(1200, 780)
        try:
            self.iconbitmap(str(theme.ICON))
        except tk.TclError:
            pass
        self.after(50, lambda: theme.style_titlebar(self))

        self.cfg = config.load()
        i18n.set_language(self.cfg["language"])
        self.engine = Engine()
        self.recorder = LoopbackRecorder(self.cfg["clip_seconds"])
        self.hotkeys = HotkeyManager()
        self.rows = []
        self.clip_active = False
        self.capturing_key = False
        # threads nunca mexem no Tk: enfileiram aqui e o _tick executa na thread da janela.
        # (No Python 3.15, after() chamado de outra thread antes do mainloop lanca RuntimeError.)
        self.ui_queue = queue.SimpleQueue()

        self.engine.set_voice(self.cfg["voice_effect"])
        self.ins, self.outs = wasapi_devices()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(200, self._start_all)
        self.after(100, self._tick)
        if config.CLIP_PATH.exists():
            threading.Thread(target=self._load_clip, args=(False,), daemon=True).start()

    # ---------- construcao da UI ----------
    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0, minsize=SIDEBAR)
        self.grid_rowconfigure(2, weight=1)

        self._build_header()

        in_names = [n for _, n in self.ins]
        out_names = [n for _, n in self.outs]
        cable = next((n for n in out_names if "CABLE Input" in n), None)
        self.cable_found = cable is not None
        if not self.cable_found:
            ctk.CTkLabel(self, text_color=theme.WARN, wraplength=1100, justify="left", text=t("no_cable"),
                         font=theme.font(12)).grid(row=1, column=0, columnspan=2, sticky="w", padx=24, pady=(0, 6))

        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=2, column=0, sticky="nsew", padx=(20, 8), pady=(0, 8))
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(0, weight=1)
        side = ctk.CTkFrame(self, fg_color="transparent", width=SIDEBAR)
        side.grid(row=2, column=1, sticky="nsew", padx=(8, 20), pady=(0, 8))
        side.grid_columnconfigure(0, weight=1)

        self._build_sounds(main)
        self._build_clip(main)
        self._build_devices(side, in_names, out_names, cable)
        self._build_voice(side)

        self.status = ctk.CTkLabel(self, text=t("ready"), anchor="w", font=theme.font(12), text_color=theme.MUTED)
        self.status.grid(row=3, column=0, columnspan=2, sticky="ew", padx=24, pady=(0, 12))

    def _build_header(self):
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, columnspan=2, sticky="ew", padx=20, pady=(16, 12))
        head.grid_columnconfigure(2, weight=1)
        scale = ctk.ScalingTracker.get_window_scaling(self)
        size = min((32, 48, 64), key=lambda s: abs(s - 34 * scale))
        self._logo = tk.PhotoImage(file=str(theme.ASSETS / f"logo-{size}.png"))
        tk.Label(head, image=self._logo, bg=theme.BG, bd=0).grid(row=0, column=0, rowspan=2, padx=(4, 12))
        title(head, "Sound Mod", 22).grid(row=0, column=1, sticky="sw")
        caption(head, t("tagline")).grid(row=1, column=1, sticky="nw")

        right = ctk.CTkFrame(head, fg_color="transparent")
        right.grid(row=0, column=3, rowspan=2, sticky="e")
        self.pill = StatusPill(right)
        self.pill.grid(row=0, column=0, padx=(0, 10))
        self.lang_var = ctk.StringVar(value=i18n.LANGUAGES[i18n.current()])
        ctk.CTkOptionMenu(right, variable=self.lang_var, values=list(i18n.LANGUAGES.values()), width=124,
                          height=34, corner_radius=17, command=self._on_language).grid(row=0, column=1, padx=(0, 10))
        stop = ctk.CTkFrame(right, fg_color=theme.DANGER_SOFT, corner_radius=20)
        stop.grid(row=0, column=2)
        ctk.CTkLabel(stop, text=t("stop_all"), font=theme.font(12, "bold"), text_color=theme.TEXT
                     ).grid(row=0, column=0, padx=(14, 6), pady=4)
        self.stop_key = self._cfg_key_button(stop, "■", "stop_key", self.engine.stop_all, color=theme.DANGER)
        self.stop_key.grid(row=0, column=1, padx=(0, 6), pady=4)

    def _build_sounds(self, parent):
        box = card(parent)
        box.grid(row=0, column=0, sticky="nsew", pady=(0, 12))
        box.grid_columnconfigure(0, weight=1)
        box.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(box, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 6))
        head.grid_columnconfigure(1, weight=1)
        title(head, t("sounds")).grid(row=0, column=0, sticky="w")
        caption(head, t("sounds_hint")).grid(row=0, column=1, sticky="w", padx=14)
        ctk.CTkButton(head, text=f"{t('add_sound')}", height=34, corner_radius=17, font=theme.font(13, "bold"),
                      command=self._add_slot, **theme.primary()).grid(row=0, column=2, sticky="e")
        scroll = ScrollFrame(box)
        scroll.grid(row=1, column=0, sticky="nsew", padx=(14, 10), pady=(4, 14))
        self.list = scroll.inner
        self.list.grid_columnconfigure(0, weight=1)
        for s in self.cfg["slots"]:
            self._add_row(s)

    def _build_clip(self, parent):
        clip = card(parent)
        clip.grid(row=1, column=0, sticky="ew")
        clip.grid_columnconfigure(0, weight=1)
        head = ctk.CTkFrame(clip, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 8))
        head.grid_columnconfigure(1, weight=1)
        title(head, t("clip_title")).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(head, text=t("save_as_sound"), height=34, corner_radius=17, font=theme.font(13, "bold"),
                      command=self._save_as_sound, **theme.primary()).grid(row=0, column=2, sticky="e")

        bar = ctk.CTkFrame(clip, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=18)
        caption(bar, t("save_last")).grid(row=0, column=0, padx=(0, 6))
        self.secs = ctk.CTkEntry(bar, width=44, height=32, justify="center")
        self.secs.insert(0, str(self.cfg["clip_seconds"]))
        self.secs.grid(row=0, column=1)
        caption(bar, t("seconds")).grid(row=0, column=2, padx=(6, 10))
        self.save_key = self._cfg_key_button(bar, "●", "save_clip_key", self._save_clip)
        self.save_key.grid(row=0, column=3, padx=(0, 22))
        caption(bar, t("clip")).grid(row=0, column=4, padx=(0, 6))
        self.clip_key = self._cfg_key_button(bar, "▶", "play_clip_key", self._toggle_clip)
        self.clip_key.grid(row=0, column=5, padx=(0, 6))
        theme.icon_button(bar, theme.PAUSE, lambda: self.engine.pause(CLIP)).grid(row=0, column=6, padx=2)
        theme.icon_button(bar, theme.STOP, lambda: self.engine.stop(CLIP)).grid(row=0, column=7, padx=2)

        wave_box = ctk.CTkFrame(clip, fg_color=theme.ITEM, corner_radius=14)
        wave_box.grid(row=2, column=0, sticky="ew", padx=18, pady=(12, 6))
        wave_box.grid_columnconfigure(0, weight=1)
        self.wave = Waveform(wave_box, self._clip_range, self._clip_seek)
        self.wave.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        caption(clip, t("clip_hint")).grid(row=3, column=0, sticky="w", padx=20, pady=(0, 14))

    def _build_devices(self, parent, in_names, out_names, cable):
        dev = card(parent)
        dev.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        dev.grid_columnconfigure(0, weight=1)
        title(dev, t("devices")).grid(row=0, column=0, sticky="w", padx=18, pady=(14, 2))

        none = t("none")
        mic = next((n for n in in_names if "micro" in n.lower()), none)
        phones = next((n for n in out_names if "CABLE" not in n), none)
        self.mic_var = ctk.StringVar(value=self._saved_device("mic_device", mic))
        self.out_var = ctk.StringVar(value=self._saved_device("output_device", cable or none))
        self.mon_var = ctk.StringVar(value=self._saved_device("monitor_device", phones))
        self.loop_var = ctk.StringVar(value=self.cfg["loopback_device"] or t("default_speaker"))
        rows = [
            (t("mic"), self.mic_var, [none] + in_names),
            (t("output"), self.out_var, [none] + out_names),
            (t("monitor"), self.mon_var, [none] + out_names),
            (t("loopback"), self.loop_var, [t("default_speaker")] + self._safe(loopback_names)),
        ]
        r = 1
        for label, var, values in rows:
            caption(dev, label).grid(row=r, column=0, sticky="w", padx=20, pady=(4, 1))
            ctk.CTkOptionMenu(dev, variable=var, values=values, dynamic_resizing=False, height=30,
                              font=theme.font(12)).grid(row=r + 1, column=0, sticky="ew", padx=18)
            r += 2

        self.mix_var = ctk.BooleanVar(value=self.cfg["mix_mic"])
        self.monitor_var = ctk.BooleanVar(value=self.cfg["monitor"])
        for var, key in ((self.mix_var, "mix_mic"), (self.monitor_var, "hear_sounds")):
            ctk.CTkSwitch(dev, text=t(key), variable=var, command=self._apply_live, font=theme.font(13)
                          ).grid(row=r, column=0, sticky="w", padx=20, pady=(10 if key == "mix_mic" else 4, 0))
            r += 1
        vol = ctk.CTkFrame(dev, fg_color="transparent")
        vol.grid(row=r, column=0, sticky="ew", padx=20, pady=(10, 0))
        vol.grid_columnconfigure(1, weight=1)
        caption(vol, t("master_volume")).grid(row=0, column=0, padx=(0, 10))
        self.vol_slider = ctk.CTkSlider(vol, from_=0, to=1, height=16, command=lambda v: self._apply_live())
        self.vol_slider.set(self.cfg["master_volume"])
        self.vol_slider.grid(row=0, column=1, sticky="ew")
        ctk.CTkButton(dev, text=t("apply"), height=38, corner_radius=19, font=theme.font(13, "bold"),
                      command=self._start_all, **theme.primary()).grid(row=r + 1, column=0, sticky="ew",
                                                                     padx=18, pady=(12, 14))

    def _build_voice(self, parent):
        box = card(parent)
        box.grid(row=1, column=0, sticky="ew")
        box.grid_columnconfigure(0, weight=1)
        title(box, t("voice")).grid(row=0, column=0, sticky="w", padx=18, pady=(14, 6))
        current = self.cfg["voice_effect"] if self.cfg["voice_effect"] in voice.EFFECTS else "normal"
        self.fx_grid = EffectGrid(box, [(name, t(f"fx_{name}")) for name in voice.EFFECTS], current,
                                  self._on_voice)
        self.fx_grid.grid(row=1, column=0, sticky="ew", padx=15)
        self.hear_self_var = ctk.BooleanVar(value=self.cfg["hear_self"])
        ctk.CTkSwitch(box, text=t("hear_self"), variable=self.hear_self_var, command=self._apply_live,
                      font=theme.font(13)).grid(row=2, column=0, sticky="w", padx=20, pady=(10, 14))

    def _cfg_key_button(self, parent, icon, cfg_key, action, color=theme.ITEM_HOVER):
        set_key = lambda k: self.cfg.__setitem__(cfg_key, k)
        return KeyButton(parent, icon, self.cfg[cfg_key], action,
                         lambda kb: self._rebind(kb, set_key), lambda kb: self._clear_key(kb, set_key),
                         color=color)

    def _add_row(self, slot):
        row = SlotRow(self, slot)
        row.grid(len(self.rows))
        self.rows.append(row)
        return row

    # ---------- acoes ----------
    @staticmethod
    def _safe(fn):
        try:
            return fn()
        except Exception:
            return []

    def _saved_device(self, key, default):
        value = self.cfg[key]
        if value is None:
            return default
        return value if value and value != LEGACY_NONE else t("none")

    def _post(self, fn):
        """Executa fn na thread da janela (seguro para chamar de qualquer thread)."""
        self.ui_queue.put(fn)

    def _set_status(self, msg):
        # uma linha so: mensagens de erro do ffmpeg tem varias e esticariam a janela
        msg = " ".join(str(msg).split())
        self.status.configure(text=msg if len(msg) <= 180 else msg[:179] + "…")

    def _say(self, msg):
        self._post(lambda: self._set_status(msg))

    def _tick(self):
        self.after(100, self._tick)  # reagenda antes: um erro abaixo nao pode parar as atualizacoes
        while True:
            try:
                fn = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception as e:
                self.report_callback_exception(type(e), e, e.__traceback__)
        for row in self.rows:
            row.tick()
        st = self.engine.state(CLIP)
        playing = bool(st and st[2])
        self.wave.set_pos(st[0] if st else None)
        if playing != self.clip_active:
            self.clip_active = playing
            self.clip_key.set_active(playing)
        self.pill.set(self.engine.running)

    def _add_slot(self):
        paths = filedialog.askopenfilenames(filetypes=[(t("audio_files"), AUDIO_GLOB), (t("all_files"), "*.*")])
        for path in paths:
            self._add_sound(path)
        if paths:
            self._register_hotkeys()
            config.save(self.cfg)
            self._say(t("sounds_added", n=len(paths)))

    def _add_sound(self, path):
        """Usa o primeiro slot sem arquivo (mantem a tecla dele) ou cria um slot novo."""
        row = next((r for r in self.rows if not r.slot["path"]), None)
        if row is None:
            slot = {"key": "", "path": "", "volume": 1.0}
            self.cfg["slots"].append(slot)
            row = self._add_row(slot)
        row.slot["path"] = path
        row.set_name(path)
        self.engine.invalidate(config.resolve(path))
        threading.Thread(target=self._load_slot, args=(row, True), daemon=True).start()
        return row

    def _remove_slot(self, row):
        self.cfg["slots"].remove(row.slot)
        self.engine.remove(row)
        row.destroy()
        self.rows.remove(row)
        for r, other in enumerate(self.rows):
            other.grid(r)
        self._register_hotkeys()

    def _pick(self, row):
        path = filedialog.askopenfilename(filetypes=[(t("audio_files"), AUDIO_GLOB), (t("all_files"), "*.*")])
        if not path:
            return
        row.slot["path"] = path
        row.set_name(path)
        self.engine.invalidate(config.resolve(path))
        threading.Thread(target=self._load_slot, args=(row,), daemon=True).start()

    def _load_slot(self, row, quiet=False):
        path = row.slot["path"]
        if not config.resolve(path).exists():
            self._say(t("file_missing", name=Path(path).name))
            return False
        try:
            self.engine.set_sound(row, config.resolve(path), row.slot["volume"])
            if not quiet:
                self._say(t("loaded", name=Path(path).name))
            return True
        except Exception as e:
            self._say(t("load_error", name=Path(path).name, e=e))
            return False

    def _play_slot(self, row, toggle=False):
        """▶: toca (recomeca se ja tocava). Hotkey/botao da tecla (toggle): toca ou, se ja tocava, para."""
        name = Path(row.slot["path"]).name
        if not name:
            return self._say(t("slot_empty"))
        if not self.engine.running:
            return self._say(t("engine_stopped"))
        playing = self.engine.toggle(row) if toggle else self.engine.play(row)
        if playing is not None:
            return self._say(t("playing" if playing else "stopped", name=name))

        def work():  # ainda nao carregado
            if self._load_slot(row, quiet=True) and self.engine.play(row):
                self._say(t("playing", name=name))
        threading.Thread(target=work, daemon=True).start()

    def _toggle_slot(self, row):
        self._play_slot(row, toggle=True)

    def _rebind(self, kb, setter):
        kb.capturing()
        self.capturing_key = True
        self.hotkeys.clear()

        def work():
            try:
                key = capture_key()
            except Exception:
                key = ""
            self._post(lambda: self._rebound(kb, setter, key))

        threading.Thread(target=work, daemon=True).start()

    def _rebound(self, kb, setter, key):
        self.capturing_key = False
        self._set_key(kb, setter, key)

    def _set_key(self, kb, setter, key):
        setter(key)
        kb.set_key(key)
        self._register_hotkeys()
        config.save(self.cfg)

    def _clear_key(self, kb, setter):
        self._set_key(kb, setter, "")
        self._say(t("key_removed"))

    # ---------- idioma ----------
    def _on_language(self, label):
        lang = next(code for code, name in i18n.LANGUAGES.items() if name == label)
        if lang != i18n.current():
            # adiado: o menu nao pode ser destruido dentro do proprio callback
            self.after(10, lambda: self._change_language(lang))

    def _change_language(self, lang):
        """Recria a janela no novo idioma; os canais passam para as novas linhas e o som nao para."""
        if self.capturing_key:
            self.lang_var.set(i18n.LANGUAGES[i18n.current()])
            return self._say(t("finish_key_first"))
        self._read_ui()
        self.cfg["language"] = lang
        i18n.set_language(lang)
        old_rows = self.rows
        for w in self.winfo_children():
            w.destroy()
        self.rows = []
        self.clip_active = False
        self._build()
        for old, new in zip(old_rows, self.rows):
            self.engine.rekey(old, new)
        if self.engine.has(CLIP):
            self._show_clip(self.engine.load(config.CLIP_PATH), False)
        self._register_hotkeys()
        self._load_missing()
        config.save(self.cfg)

    # ---------- clipe ----------
    def _save_clip(self):
        def work():
            try:
                dur = self.recorder.save(config.CLIP_PATH)
            except Exception as e:
                return self._say(t("clip_save_error", e=e))
            if self._load_clip(reset_trim=True):
                self._say(t("clip_saved", dur=dur, name=config.CLIP_PATH.name))
        threading.Thread(target=work, daemon=True).start()

    def _load_clip(self, reset_trim):
        """Roda em thread: decodifica o clipe e manda a GUI mostrar a forma de onda."""
        try:
            self.engine.invalidate(config.CLIP_PATH)
            self.engine.set_sound(CLIP, config.CLIP_PATH)
            data = self.engine.load(config.CLIP_PATH)
        except Exception as e:
            self._say(t("clip_open_error", e=e))
            return False
        self._post(lambda: self._show_clip(data, reset_trim))
        return True

    def _show_clip(self, data, reset_trim):
        if reset_trim:
            self.cfg["clip_trim"] = None
        start, end = self.cfg["clip_trim"] or (None, None)
        self.wave.set_audio(data, SR, start, end)
        self.engine.set_range(CLIP, self.wave.start, self.wave.end)

    def _clip_range(self, start, end):
        self.cfg["clip_trim"] = [round(start, 3), round(end, 3)]
        self.engine.set_range(CLIP, start, end)
        config.save(self.cfg)

    def _clip_seek(self, t):
        self.engine.seek(CLIP, t)
        self.wave.set_pos(t)

    def _save_as_sound(self):
        """Grava o trecho escolhido do clipe em sounds/<nome>.mp3 e adiciona como um som."""
        if not self.engine.has(CLIP):
            return self._say(t("no_clip_saved"))
        default = time.strftime("clip-%Y%m%d-%H%M%S")
        dialog = ctk.CTkInputDialog(text=t("sound_name"), title=t("save_sound_title"))
        name = dialog.get_input()
        if name is None:
            return  # cancelado
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip(" .") or default
        start, end = self.wave.start, self.wave.end
        data = self.engine.load(config.CLIP_PATH)

        def work():
            try:
                config.SOUNDS_DIR.mkdir(exist_ok=True)
                target = config.SOUNDS_DIR / f"{name}.mp3"
                n = 2
                while target.exists():
                    target = config.SOUNDS_DIR / f"{name} ({n}).mp3"
                    n += 1
                part = data[int(start * SR):int(end * SR)]
                encode_mp3((np.clip(part, -1, 1) * 32767).astype(np.int16), SR, 2, target)
            except Exception as e:
                return self._say(t("sound_save_error", e=e))
            # relativo a pasta do programa: continua valendo se a pasta for copiada/atualizada
            rel = target.relative_to(config.ROOT).as_posix()
            self._post(lambda: self._sound_saved(rel))
        threading.Thread(target=work, daemon=True).start()

    def _sound_saved(self, rel):
        self._add_sound(rel)
        self._register_hotkeys()
        config.save(self.cfg)
        self._say(t("sound_saved", name=Path(rel).name))

    def _toggle_clip(self):
        if not self.engine.has(CLIP):
            return self._say(t("no_clip_saved"))
        if not self.engine.running:
            return self._say(t("engine_stopped"))
        self._say(t("clip_playing" if self.engine.toggle(CLIP) else "clip_stopped"))

    # ---------- engine ----------
    def _on_voice(self, name):
        self.cfg["voice_effect"] = name
        self.engine.set_voice(name)
        config.save(self.cfg)
        self._say(t("voice_on", name=t(f"fx_{name}")))

    def _apply_live(self):
        self.engine.hear_self = self.hear_self_var.get()
        self.engine.mix_mic = self.mix_var.get()
        self.engine.monitor = self.monitor_var.get()
        self.engine.master = float(self.vol_slider.get())

    def _idx(self, items, name):
        return next((i for i, n in items if n == name), None)

    def _read_ui(self):
        """Copia para o cfg o que esta nos controles da janela."""
        none = t("none")
        self.cfg["mic_device"] = "" if self.mic_var.get() == none else self.mic_var.get()
        self.cfg["output_device"] = "" if self.out_var.get() == none else self.out_var.get()
        self.cfg["monitor_device"] = "" if self.mon_var.get() == none else self.mon_var.get()
        loop = self.loop_var.get()
        self.cfg["loopback_device"] = None if loop.startswith("(") else loop
        self.cfg["mix_mic"] = self.mix_var.get()
        self.cfg["hear_self"] = self.hear_self_var.get()
        self.cfg["monitor"] = self.monitor_var.get()
        self.cfg["master_volume"] = float(self.vol_slider.get())
        try:
            secs = max(1, min(60, int(self.secs.get())))
        except ValueError:
            secs = 5
        self.cfg["clip_seconds"] = secs
        self.recorder.seconds = secs

    def _load_missing(self):
        for row in self.rows:
            if row.slot["path"] and not self.engine.has(row):
                threading.Thread(target=self._load_slot, args=(row, True), daemon=True).start()

    def _start_all(self):
        self._apply_live()
        self._read_ui()

        msgs = []
        none = t("none")
        out, mon = self.out_var.get(), self.mon_var.get()
        if out != none and "CABLE" not in out:
            msgs.append(t("warn_output"))
        if mon != none and (mon == out or "CABLE" in mon):
            # monitor no cabo duplica os sons no microfone (eco) e voce nao ouve nada
            msgs.append(t("monitor_off"))
            mon = none
        try:
            self.engine.open(self._idx(self.ins, self.mic_var.get()),
                             self._idx(self.outs, out),
                             self._idx(self.outs, mon))
            msgs.append(t("audio_on"))
        except Exception as e:
            msgs.append(t("audio_error", e=e))
        try:
            self.recorder.start(self.cfg["loopback_device"])
            msgs.append(t("capture_on"))
        except Exception as e:
            msgs.append(t("capture_error", e=e))

        self._register_hotkeys()
        config.save(self.cfg)
        self._load_missing()
        self._set_status(" | ".join(msgs))

    def _register_hotkeys(self):
        mapping = [(row.slot["key"], (lambda row=row: self._toggle_slot(row))) for row in self.rows]
        mapping += [
            (self.cfg["save_clip_key"], self._save_clip),
            (self.cfg["play_clip_key"], self._toggle_clip),
            (self.cfg["stop_key"], self.engine.stop_all),
        ]
        errors = self.hotkeys.register(mapping)
        if errors:
            self._say(t("invalid_key", keys="; ".join(errors)))

    def _close(self):
        try:
            self.cfg["master_volume"] = float(self.vol_slider.get())
            config.save(self.cfg)
        finally:
            self.hotkeys.clear()
            self.engine.close()
            self.recorder.stop()
            self.destroy()
