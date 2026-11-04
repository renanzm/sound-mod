import threading
import time
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from . import config
from .codec import SR
from .engine import Engine, wasapi_devices
from .hotkeys import HotkeyManager, capture_key
from .recorder import LoopbackRecorder, loopback_names
from .widgets import KeyButton, ScrollFrame, Waveform

AUDIO_TYPES = [("Audio", "*.mp3 *.wav *.ogg *.flac *.m4a *.aac *.wma"), ("Todos", "*.*")]
NONE = "(nenhum)"
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
                             lambda kb: app._rebind(kb, set_key), lambda kb: app._unbind(kb, set_key))
        self.file_btn = ctk.CTkButton(p, text="Arquivo...", width=78, command=lambda: app._pick(self))
        self.name = ctk.CTkLabel(p, text=short(Path(slot["path"]).name) or "(sem arquivo)", anchor="w")
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
        self.engine = Engine()
        self.recorder = LoopbackRecorder(self.cfg["clip_seconds"])
        self.hotkeys = HotkeyManager()
        self.rows = []
        self.clip_active = False

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

        self.mic_var = ctk.StringVar(value=self.cfg["mic_device"] or self._default(in_names, "Microfone"))
        self.out_var = ctk.StringVar(value=self.cfg["output_device"] or cable or NONE)
        phones = next((n for n in out_names if "CABLE" not in n), NONE)
        self.mon_var = ctk.StringVar(value=self.cfg["monitor_device"] or phones)
        self.loop_var = ctk.StringVar(value=self.cfg["loopback_device"] or "(alto-falante padrao)")

        rows = [
            ("Microfone real", self.mic_var, [NONE] + in_names),
            ("Saida -> cabo virtual", self.out_var, [NONE] + out_names),
            ("Ouvir sons em (fones)", self.mon_var, [NONE] + out_names),
            ("Capturar audio do PC", self.loop_var, ["(alto-falante padrao)"] + self._safe(loopback_names)),
        ]
        for r, (label, var, values) in enumerate(rows):
            ctk.CTkLabel(dev, text=label, anchor="w").grid(row=r, column=0, padx=10, pady=4, sticky="w")
            ctk.CTkOptionMenu(dev, variable=var, values=values, dynamic_resizing=False
                              ).grid(row=r, column=1, padx=10, pady=4, sticky="ew")

        opts = ctk.CTkFrame(dev, fg_color="transparent")
        opts.grid(row=4, column=0, columnspan=2, sticky="ew", padx=6, pady=(4, 8))
        self.mix_var = ctk.BooleanVar(value=self.cfg["mix_mic"])
        self.monitor_var = ctk.BooleanVar(value=self.cfg["monitor"])
        ctk.CTkCheckBox(opts, text="Misturar meu microfone", variable=self.mix_var,
                        command=self._apply_live).pack(side="left", padx=8)
        ctk.CTkCheckBox(opts, text="Ouvir os sons", variable=self.monitor_var,
                        command=self._apply_live).pack(side="left", padx=8)
        ctk.CTkLabel(opts, text="Volume geral").pack(side="left", padx=(16, 4))
        self.vol_slider = ctk.CTkSlider(opts, from_=0, to=1, width=120, command=lambda v: self._apply_live())
        self.vol_slider.set(self.cfg["master_volume"])
        self.vol_slider.pack(side="left")
        ctk.CTkButton(opts, text="Aplicar / Reiniciar", width=140, command=self._start_all
                      ).pack(side="right", padx=8)

        if not self.cable_found:
            ctk.CTkLabel(
                self, text_color="#e6a23c", wraplength=780, justify="left",
                text="Cabo virtual nao encontrado. Instale o VB-CABLE (vb-audio.com/Cable), reinicie o app e "
                     "use 'CABLE Output' como microfone no Discord/jogo.",
            ).grid(row=1, column=0, sticky="w", padx=14, pady=2)

        # sons
        box = ctk.CTkFrame(self)
        box.grid(row=2, column=0, sticky="nsew", padx=12, pady=6)
        box.grid_columnconfigure(0, weight=1)
        box.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(box, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 0))
        ctk.CTkLabel(head, text="Sons", font=ctk.CTkFont(size=15, weight="bold")).pack(side="left", padx=6)
        ctk.CTkLabel(head, text="▶ toca/para  ·  ✎ muda a tecla  ·  ⌫ remove a tecla  ·  um som por vez", text_color="gray60").pack(side="left", padx=10)
        ctk.CTkButton(head, text="+ Adicionar som", width=130, command=self._add_slot).pack(side="right")
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
        ctk.CTkLabel(clip, text="Salvar ultimos").grid(row=0, column=0, padx=(10, 4), pady=8)
        self.secs = ctk.CTkEntry(clip, width=40)
        self.secs.insert(0, str(self.cfg["clip_seconds"]))
        self.secs.grid(row=0, column=1, padx=2)
        ctk.CTkLabel(clip, text="seg").grid(row=0, column=2, padx=(2, 6))
        self.save_key = self._cfg_key_button(clip, "●", "save_clip_key", self._save_clip)
        self.save_key.grid(row=0, column=3, padx=(0, 16))
        ctk.CTkLabel(clip, text="Clipe").grid(row=0, column=4, padx=(0, 4))
        self.clip_key = self._cfg_key_button(clip, "▶", "play_clip_key", self._toggle_clip)
        self.clip_key.grid(row=0, column=5, padx=(0, 4))
        ctk.CTkButton(clip, text="⏸", width=30, command=lambda: self.engine.pause(CLIP)).grid(row=0, column=6, padx=2)
        ctk.CTkButton(clip, text="■", width=30, command=lambda: self.engine.stop(CLIP)).grid(row=0, column=7, padx=2)
        ctk.CTkLabel(clip, text="Parar tudo").grid(row=0, column=9, padx=(0, 4))
        self.stop_key = self._cfg_key_button(clip, "■", "stop_key", self.engine.stop_all)
        self.stop_key.grid(row=0, column=10, padx=(0, 10))
        self.wave = Waveform(clip, self._clip_range, self._clip_seek)
        self.wave.grid(row=1, column=0, columnspan=11, sticky="ew", padx=10, pady=(0, 4))
        ctk.CTkLabel(clip, text_color="gray60", text="Arraste as alcas laranjas para escolher o trecho que toca; "
                                                     "clique na onda para mudar a posicao.").grid(
            row=2, column=0, columnspan=11, sticky="w", padx=10, pady=(0, 6))

        self.status = ctk.CTkLabel(self, text="Pronto.", anchor="w")
        self.status.grid(row=4, column=0, sticky="ew", padx=14, pady=(2, 10))

    def _cfg_key_button(self, parent, icon, cfg_key, action):
        set_key = lambda k: self.cfg.__setitem__(cfg_key, k)
        return KeyButton(parent, icon, self.cfg[cfg_key], action,
                         lambda kb: self._rebind(kb, set_key), lambda kb: self._unbind(kb, set_key))

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

    @staticmethod
    def _default(names, hint):
        return next((n for n in names if hint.lower() in n.lower()), NONE)

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
        path = filedialog.askopenfilename(filetypes=AUDIO_TYPES)
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
                self._say(f"Carregado: {Path(path).name}")
            return True
        except Exception as e:
            self._say(f"Erro ao carregar {Path(path).name}: {e}")
            return False

    def _play_slot(self, row, toggle=False):
        """▶: toca (recomeca se ja tocava). Hotkey/botao da tecla (toggle): toca ou, se ja tocava, para."""
        name = Path(row.slot["path"]).name
        if not name:
            return self._say("Esse slot nao tem arquivo.")
        if not self.engine.running:
            return self._say("Engine parada: escolha a saida e clique em Aplicar.")
        playing = self.engine.toggle(row) if toggle else self.engine.play(row)
        if playing is not None:
            return self._say(f"Tocando: {name}" if playing else f"Parado: {name}")

        def work():  # ainda nao carregado
            if self._load_slot(row, quiet=True) and self.engine.play(row):
                self._say(f"Tocando: {name}")
        threading.Thread(target=work, daemon=True).start()

    def _toggle_slot(self, row):
        self._play_slot(row, toggle=True)

    def _rebind(self, kb, setter):
        kb.capturing()
        self.hotkeys.clear()

        def work():
            try:
                key = capture_key()
            except Exception:
                key = ""
            self.after(0, lambda: self._rebound(kb, setter, key))

        threading.Thread(target=work, daemon=True).start()

    def _rebound(self, kb, setter, key):
        setter(key)
        kb.set_key(key)
        self._register_hotkeys()
        config.save(self.cfg)

    def _unbind(self, kb, setter):
        self._rebound(kb, setter, "")
        self._say("Tecla removida.")

    # ---------- clipe ----------
    def _save_clip(self):
        def work():
            try:
                dur = self.recorder.save(config.CLIP_PATH)
            except Exception as e:
                return self._say(f"Erro ao salvar clipe: {e}")
            if self._load_clip(reset_trim=True):
                self._say(f"Clipe salvo ({dur:.1f}s): {config.CLIP_PATH.name}")
        threading.Thread(target=work, daemon=True).start()

    def _load_clip(self, reset_trim):
        """Roda em thread: decodifica o clipe e manda a GUI mostrar a forma de onda."""
        try:
            self.engine.invalidate(config.CLIP_PATH)
            self.engine.set_sound(CLIP, config.CLIP_PATH)
            data = self.engine.load(config.CLIP_PATH)
        except Exception as e:
            self._say(f"Erro ao abrir clipe: {e}")
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
            return self._say("Ainda nao ha clipe salvo.")
        if not self.engine.running:
            return self._say("Engine parada: escolha a saida e clique em Aplicar.")
        self._say("Tocando clipe" if self.engine.toggle(CLIP) else "Clipe parado")

    # ---------- engine ----------
    def _apply_live(self):
        self.engine.mix_mic = self.mix_var.get()
        self.engine.monitor = self.monitor_var.get()
        self.engine.master = float(self.vol_slider.get())

    def _idx(self, items, name):
        return next((i for i, n in items if n == name), None)

    def _start_all(self):
        self._apply_live()
        self.cfg["mic_device"] = self.mic_var.get()
        self.cfg["output_device"] = self.out_var.get()
        self.cfg["monitor_device"] = self.mon_var.get()
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

        msgs = []
        out, mon = self.out_var.get(), self.mon_var.get()
        if out != NONE and "CABLE" not in out:
            msgs.append("AVISO: a saida deve ser o cabo virtual (CABLE Input)")
        if mon == out or "CABLE" in mon:
            # monitor no cabo duplica os sons no microfone (eco) e voce nao ouve nada
            msgs.append("monitor desligado: escolha seus fones em 'Ouvir sons em'")
            mon = NONE
        try:
            self.engine.open(self._idx(self.ins, self.mic_var.get()),
                             self._idx(self.outs, out),
                             self._idx(self.outs, mon))
            msgs.append("audio ligado")
        except Exception as e:
            msgs.append(f"audio: {e}")
        try:
            self.recorder.start(self.cfg["loopback_device"])
            msgs.append("gravacao do PC ligada")
        except Exception as e:
            msgs.append(f"loopback: {e}")

        self._register_hotkeys()
        config.save(self.cfg)
        for row in self.rows:
            if row.slot["path"] and not self.engine.has(row):
                threading.Thread(target=self._load_slot, args=(row, True), daemon=True).start()
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
            self._say("Tecla invalida: " + "; ".join(errors))

    def _close(self):
        try:
            self.cfg["master_volume"] = float(self.vol_slider.get())
            config.save(self.cfg)
        finally:
            self.hotkeys.clear()
            self.engine.close()
            self.recorder.stop()
            self.destroy()
