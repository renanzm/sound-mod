import threading
import time
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from . import config, i18n
from .codec import SR
from .engine import Engine, wasapi_devices
from .hotkeys import HotkeyManager, capture_key
from .i18n import t
from .recorder import LoopbackRecorder, loopback_names
from .widgets import KeyButton, ScrollFrame, Waveform

AUDIO_GLOB = "*.mp3 *.wav *.ogg *.flac *.m4a *.aac *.wma"
LEGACY_NONE = "(nenhum)"  # config.json antigos guardavam o texto em vez de ""
CLIP = "clip"  # id do canal do clipe no engine


def mmss(t):
    return f"{int(t // 60)}:{int(t % 60):02d}"


def short(name, n=28):
    return name if len(name) <= n else name[:n - 1] + "…"


class SlotRow:
    """Linha de um som. O proprio objeto e o id do canal no engine."""

    def __init__(self, app, slot):
        self.app, self.slot = app, slot
        self.dur = 0.0
        self.drag_until = 0.0
        self.active = False
        p = app.list
        set_key = lambda k: slot.__setitem__("key", k)
        self.key = KeyButton(p, "▶", slot["key"], lambda: app._toggle_slot(self),
                             lambda kb: app._rebind(kb, set_key), lambda kb: app._clear_key(kb, set_key))
        self.file_btn = ctk.CTkButton(p, text=t("file"), width=78, command=lambda: app._pick(self))
        self.name = ctk.CTkLabel(p, text=short(Path(slot["path"]).name) or t("no_file"), anchor="w")
        self.time = ctk.CTkLabel(p, text="-:-- / -:--", width=84, text_color="gray70")
        self.progress = ctk.CTkSlider(p, from_=0, to=1, width=170, command=self._seek)
        self.progress.set(0)
        self.vol = ctk.CTkSlider(p, from_=0, to=1.5, width=90, command=self._volume)
        self.vol.set(slot["volume"])
        self.play_btn = ctk.CTkButton(p, text="▶", width=30, command=lambda: app._play_slot(self))
        self.pause_btn = ctk.CTkButton(p, text="⏸", width=30, command=lambda: app.engine.pause(self))
        self.stop_btn = ctk.CTkButton(p, text="■", width=30, command=lambda: app.engine.stop(self))
        self.rm_btn = ctk.CTkButton(p, text="✕", width=30, fg_color="#7a2b2b", hover_color="#a33",
                                    command=lambda: app._remove_slot(self))
        self.widgets = [self.key, self.file_btn, self.name, self.time, self.progress, self.vol,
                        self.play_btn, self.pause_btn, self.stop_btn, self.rm_btn]

    def grid(self, r):
        for c, w in enumerate(self.widgets):
            w.grid(row=r, column=c, padx=(4, 2) if c else (4, 6), pady=3,
                   sticky="ew" if w is self.name else "")

    def destroy(self):
        for w in self.widgets:
            w.destroy()

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


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title("Sound Mod")
        self.geometry("1040x780")
        self.minsize(940, 620)

        self.cfg = config.load()
        i18n.set_language(self.cfg["language"])
        self.engine = Engine()
        self.recorder = LoopbackRecorder(self.cfg["clip_seconds"])
        self.hotkeys = HotkeyManager()
        self.rows = []
        self.clip_active = False
        self.capturing_key = False

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
        self.grid_rowconfigure(2, weight=1)

        dev = ctk.CTkFrame(self)
        dev.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        dev.grid_columnconfigure(1, weight=1)

        in_names = [n for _, n in self.ins]
        out_names = [n for _, n in self.outs]
        cable = next((n for n in out_names if "CABLE Input" in n), None)
        self.cable_found = cable is not None

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
        for r, (label, var, values) in enumerate(rows):
            ctk.CTkLabel(dev, text=label, anchor="w").grid(row=r, column=0, padx=10, pady=4, sticky="w")
            ctk.CTkOptionMenu(dev, variable=var, values=values, dynamic_resizing=False
                              ).grid(row=r, column=1, padx=10, pady=4, sticky="ew")

        opts = ctk.CTkFrame(dev, fg_color="transparent")
        opts.grid(row=4, column=0, columnspan=2, sticky="ew", padx=6, pady=(4, 8))
        self.mix_var = ctk.BooleanVar(value=self.cfg["mix_mic"])
        self.monitor_var = ctk.BooleanVar(value=self.cfg["monitor"])
        ctk.CTkCheckBox(opts, text=t("mix_mic"), variable=self.mix_var,
                        command=self._apply_live).pack(side="left", padx=8)
        ctk.CTkCheckBox(opts, text=t("hear_sounds"), variable=self.monitor_var,
                        command=self._apply_live).pack(side="left", padx=8)
        ctk.CTkLabel(opts, text=t("master_volume")).pack(side="left", padx=(16, 4))
        self.vol_slider = ctk.CTkSlider(opts, from_=0, to=1, width=120, command=lambda v: self._apply_live())
        self.vol_slider.set(self.cfg["master_volume"])
        self.vol_slider.pack(side="left")
        ctk.CTkButton(opts, text=t("apply"), width=140, command=self._start_all
                      ).pack(side="right", padx=8)
        self.lang_var = ctk.StringVar(value=i18n.LANGUAGES[i18n.current()])
        ctk.CTkOptionMenu(opts, variable=self.lang_var, values=list(i18n.LANGUAGES.values()), width=110,
                          command=self._on_language).pack(side="right", padx=8)

        if not self.cable_found:
            ctk.CTkLabel(
                self, text_color="#e6a23c", wraplength=780, justify="left", text=t("no_cable"),
            ).grid(row=1, column=0, sticky="w", padx=14, pady=2)

        # sons
        box = ctk.CTkFrame(self)
        box.grid(row=2, column=0, sticky="nsew", padx=12, pady=6)
        box.grid_columnconfigure(0, weight=1)
        box.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(box, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 0))
        ctk.CTkLabel(head, text=t("sounds"), font=ctk.CTkFont(size=15, weight="bold")).pack(side="left", padx=6)
        ctk.CTkLabel(head, text=t("sounds_hint"), text_color="gray60").pack(side="left", padx=10)
        ctk.CTkButton(head, text=t("add_sound"), width=130, command=self._add_slot).pack(side="right")
        scroll = ScrollFrame(box)
        scroll.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
        self.list = scroll.inner
        self.list.grid_columnconfigure(2, weight=1)
        for s in self.cfg["slots"]:
            self._add_row(s)

        # clipe do audio do PC
        clip = ctk.CTkFrame(self)
        clip.grid(row=3, column=0, sticky="ew", padx=12, pady=6)
        clip.grid_columnconfigure(8, weight=1)
        ctk.CTkLabel(clip, text=t("save_last")).grid(row=0, column=0, padx=(10, 4), pady=8)
        self.secs = ctk.CTkEntry(clip, width=40)
        self.secs.insert(0, str(self.cfg["clip_seconds"]))
        self.secs.grid(row=0, column=1, padx=2)
        ctk.CTkLabel(clip, text=t("seconds")).grid(row=0, column=2, padx=(2, 6))
        self.save_key = self._cfg_key_button(clip, "●", "save_clip_key", self._save_clip)
        self.save_key.grid(row=0, column=3, padx=(0, 16))
        ctk.CTkLabel(clip, text=t("clip")).grid(row=0, column=4, padx=(0, 4))
        self.clip_key = self._cfg_key_button(clip, "▶", "play_clip_key", self._toggle_clip)
        self.clip_key.grid(row=0, column=5, padx=(0, 4))
        ctk.CTkButton(clip, text="⏸", width=30, command=lambda: self.engine.pause(CLIP)).grid(row=0, column=6, padx=2)
        ctk.CTkButton(clip, text="■", width=30, command=lambda: self.engine.stop(CLIP)).grid(row=0, column=7, padx=2)
        ctk.CTkLabel(clip, text=t("stop_all")).grid(row=0, column=9, padx=(0, 4))
        self.stop_key = self._cfg_key_button(clip, "■", "stop_key", self.engine.stop_all)
        self.stop_key.grid(row=0, column=10, padx=(0, 10))
        self.wave = Waveform(clip, self._clip_range, self._clip_seek)
        self.wave.grid(row=1, column=0, columnspan=11, sticky="ew", padx=10, pady=(0, 4))
        ctk.CTkLabel(clip, text_color="gray60", text=t("clip_hint")).grid(
            row=2, column=0, columnspan=11, sticky="w", padx=10, pady=(0, 6))

        self.status = ctk.CTkLabel(self, text=t("ready"), anchor="w")
        self.status.grid(row=4, column=0, sticky="ew", padx=14, pady=(2, 10))

    def _cfg_key_button(self, parent, icon, cfg_key, action):
        set_key = lambda k: self.cfg.__setitem__(cfg_key, k)
        return KeyButton(parent, icon, self.cfg[cfg_key], action,
                         lambda kb: self._rebind(kb, set_key), lambda kb: self._clear_key(kb, set_key))

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

    def _say(self, msg):
        self.after(0, lambda: self.status.configure(text=msg))

    def _tick(self):
        for row in self.rows:
            row.tick()
        st = self.engine.state(CLIP)
        playing = bool(st and st[2])
        self.wave.set_pos(st[0] if st else None)
        if playing != self.clip_active:
            self.clip_active = playing
            self.clip_key.set_active(playing)
        self.after(100, self._tick)

    def _add_slot(self):
        slot = {"key": "", "path": "", "volume": 1.0}
        self.cfg["slots"].append(slot)
        self._add_row(slot)

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
        row.name.configure(text=short(Path(path).name))
        self.engine.invalidate(path)
        threading.Thread(target=self._load_slot, args=(row,), daemon=True).start()

    def _load_slot(self, row, quiet=False):
        path = row.slot["path"]
        try:
            self.engine.set_sound(row, path, row.slot["volume"])
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
            self.after(0, lambda: self._rebound(kb, setter, key))

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
        self.after(0, lambda: self._show_clip(data, reset_trim))
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

    def _toggle_clip(self):
        if not self.engine.has(CLIP):
            return self._say(t("no_clip_saved"))
        if not self.engine.running:
            return self._say(t("engine_stopped"))
        self._say(t("clip_playing" if self.engine.toggle(CLIP) else "clip_stopped"))

    # ---------- engine ----------
    def _apply_live(self):
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
        self.status.configure(text=" | ".join(msgs))

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
