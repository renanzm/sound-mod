import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from . import config
from .engine import Engine, wasapi_devices
from .hotkeys import HotkeyManager, capture_key
from .recorder import LoopbackRecorder, loopback_names

AUDIO_TYPES = [("Audio", "*.mp3 *.wav *.ogg *.flac *.m4a *.aac *.wma"), ("Todos", "*.*")]
NONE = "(nenhum)"


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


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title("Sound Mod")
        self.geometry("820x720")
        self.minsize(720, 560)

        self.cfg = config.load()
        self.engine = Engine()
        self.recorder = LoopbackRecorder(self.cfg["clip_seconds"])
        self.hotkeys = HotkeyManager()
        self.slot_rows = []

        self.ins, self.outs = wasapi_devices()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(200, self._start_all)

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

        # slots
        box = ctk.CTkFrame(self)
        box.grid(row=2, column=0, sticky="nsew", padx=12, pady=6)
        box.grid_columnconfigure(0, weight=1)
        box.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(box, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 0))
        ctk.CTkLabel(head, text="Sons", font=ctk.CTkFont(size=15, weight="bold")).pack(side="left", padx=6)
        ctk.CTkButton(head, text="+ Adicionar som", width=130, command=self._add_slot).pack(side="right")
        scroll = ScrollFrame(box)
        scroll.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
        self.list = scroll.inner
        self.list.grid_columnconfigure(2, weight=1)
        for s in self.cfg["slots"]:
            self._slot_row(s)

        # clip
        clip = ctk.CTkFrame(self)
        clip.grid(row=3, column=0, sticky="ew", padx=12, pady=6)
        self.save_key = self._key_button(clip, "Salvar ultimos", "save_clip_key", 0)
        self.play_key = self._key_button(clip, "Tocar clipe", "play_clip_key", 1)
        self.stop_key = self._key_button(clip, "Parar tudo", "stop_key", 2)
        self.secs = ctk.CTkEntry(clip, width=40)
        self.secs.insert(0, str(self.cfg["clip_seconds"]))
        self.secs.grid(row=0, column=6, padx=(10, 2))
        ctk.CTkLabel(clip, text="seg").grid(row=0, column=7, padx=(0, 10))

        self.status = ctk.CTkLabel(self, text="Pronto.", anchor="w")
        self.status.grid(row=4, column=0, sticky="ew", padx=14, pady=(2, 10))

    def _key_button(self, parent, label, cfg_key, col):
        ctk.CTkLabel(parent, text=label).grid(row=0, column=col * 2, padx=(10, 4), pady=8)
        btn = ctk.CTkButton(parent, text=self.cfg[cfg_key].upper() or "-", width=90)
        btn.configure(command=lambda: self._rebind(btn, lambda k: self.cfg.__setitem__(cfg_key, k)))
        btn.grid(row=0, column=col * 2 + 1, padx=(0, 6))
        return btn

    def _slot_row(self, slot):
        r = len(self.slot_rows)
        key_btn = ctk.CTkButton(self.list, text=slot["key"].upper() or "-", width=80)
        key_btn.configure(command=lambda: self._rebind(key_btn, lambda k: slot.__setitem__("key", k)))
        key_btn.grid(row=r, column=0, padx=4, pady=3)
        ctk.CTkButton(self.list, text="Arquivo...", width=80,
                      command=lambda: self._pick(slot, name_lbl)).grid(row=r, column=1, padx=4)
        name_lbl = ctk.CTkLabel(self.list, text=Path(slot["path"]).name or "(sem arquivo)", anchor="w")
        name_lbl.grid(row=r, column=2, padx=4, sticky="ew")
        vol = ctk.CTkSlider(self.list, from_=0, to=1.5, width=100,
                            command=lambda v: slot.__setitem__("volume", float(v)))
        vol.set(slot["volume"])
        vol.grid(row=r, column=3, padx=4)
        ctk.CTkButton(self.list, text="▶", width=32, command=lambda: self._play_slot(slot)
                      ).grid(row=r, column=4, padx=2)
        rm = ctk.CTkButton(self.list, text="✕", width=32, fg_color="#7a2b2b", hover_color="#a33")
        rm.configure(command=lambda: self._remove_slot(slot))
        rm.grid(row=r, column=5, padx=2)
        self.slot_rows.append((slot, [key_btn, name_lbl, vol, rm]))

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

    def _add_slot(self):
        slot = {"key": "", "path": "", "volume": 1.0}
        self.cfg["slots"].append(slot)
        self._slot_row(slot)

    def _remove_slot(self, slot):
        self.cfg["slots"].remove(slot)
        for s, widgets in self.slot_rows:
            if s is slot:
                for w in widgets:
                    w.destroy()
        self.slot_rows = [(s, w) for s, w in self.slot_rows if s is not slot]
        # os widgets restantes mantem a posicao na grid; reorganiza
        for r, (_, widgets) in enumerate(self.slot_rows):
            for w in widgets:
                w.grid_configure(row=r)
        self._register_hotkeys()

    def _pick(self, slot, label):
        path = filedialog.askopenfilename(filetypes=AUDIO_TYPES)
        if not path:
            return
        slot["path"] = path
        label.configure(text=Path(path).name)
        self.engine.invalidate(path)
        threading.Thread(target=self._preload, args=(path,), daemon=True).start()

    def _preload(self, path, quiet=False):
        try:
            self.engine.load(path)
            if not quiet:
                self._say(f"Carregado: {Path(path).name}")
        except Exception as e:
            self._say(f"Erro ao carregar {Path(path).name}: {e}")

    def _play_slot(self, slot):
        if not slot["path"]:
            return self._say("Esse slot nao tem arquivo.")
        threading.Thread(target=self._play_path, args=(slot["path"], slot["volume"]), daemon=True).start()

    def _play_path(self, path, vol):
        if not self.engine.running:
            return self._say("Engine parada: escolha a saida e clique em Aplicar.")
        try:
            self.engine.play(path, vol)
            self._say(f"Tocando: {Path(path).name}")
        except Exception as e:
            self._say(f"Erro ao tocar: {e}")

    def _rebind(self, btn, setter):
        btn.configure(text="pressione...", state="disabled")
        self.hotkeys.clear()

        def work():
            try:
                key = capture_key()
            except Exception:
                key = ""
            self.after(0, lambda: self._rebound(btn, setter, key))

        threading.Thread(target=work, daemon=True).start()

    def _rebound(self, btn, setter, key):
        setter(key)
        btn.configure(text=key.upper() or "-", state="normal")
        self._register_hotkeys()

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
            self.engine.start(self._idx(self.ins, self.mic_var.get()),
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
        for s in self.cfg["slots"]:
            if s["path"]:
                threading.Thread(target=self._preload, args=(s["path"], True), daemon=True).start()
        self.status.configure(text=" | ".join(msgs))

    def _register_hotkeys(self):
        mapping = [(s["key"], (lambda s=s: self._play_slot(s))) for s in self.cfg["slots"]]
        mapping += [
            (self.cfg["save_clip_key"], self._save_clip),
            (self.cfg["play_clip_key"], self._play_clip),
            (self.cfg["stop_key"], self.engine.stop_all),
        ]
        errors = self.hotkeys.register(mapping)
        if errors:
            self._say("Tecla invalida: " + "; ".join(errors))

    def _save_clip(self):
        def work():
            try:
                dur = self.recorder.save(config.CLIP_PATH)
                self.engine.invalidate(config.CLIP_PATH)
                self._say(f"Clipe salvo ({dur:.1f}s): {config.CLIP_PATH.name}")
            except Exception as e:
                self._say(f"Erro ao salvar clipe: {e}")
        threading.Thread(target=work, daemon=True).start()

    def _play_clip(self):
        if not config.CLIP_PATH.exists():
            return self._say("Ainda nao ha clipe salvo.")
        threading.Thread(target=self._play_path, args=(str(config.CLIP_PATH), 1.0), daemon=True).start()

    def _close(self):
        try:
            self.cfg["master_volume"] = float(self.vol_slider.get())
            config.save(self.cfg)
        finally:
            self.hotkeys.clear()
            self.engine.stop()
            self.recorder.stop()
            self.destroy()
