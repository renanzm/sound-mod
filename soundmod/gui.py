import os
import queue
import re
import threading
import time
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
import numpy as np

from . import config, i18n, library, voice
from .codec import SR, encode_mp3
from .engine import Engine, wasapi_devices
from .hotkeys import HotkeyManager, capture_key
from .i18n import t
from .recorder import LoopbackRecorder, loopback_names
from .widgets import KeyButton, ScrollFrame, Waveform

AUDIO_GLOB = "*.mp3 *.wav *.ogg *.flac *.m4a *.aac *.wma"
LEGACY_NONE = "(nenhum)"  # config.json antigos guardavam o texto em vez de ""
CLIP = "clip"  # id do canal do clipe no engine
NAME_COL = 3   # coluna do nome do som na lista (a que estica)
COLUMNS = 12   # colunas de uma linha de som (os cabecalhos de colecao ocupam todas)
GRAY = dict(fg_color=("gray70", "gray30"), hover_color=("gray60", "gray40"))
# rotulos do menu que nao podem virar nome de colecao (em qualquer idioma)
RESERVED = [i18n.TEXTS[lang]["no_collection"] for lang in i18n.TEXTS]


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
        self.move = ctk.CTkFrame(p, fg_color="transparent")
        self.up = ctk.CTkButton(self.move, text="▲", width=24, command=lambda: app._move_slot(self, -1), **GRAY)
        self.up.grid(row=0, column=0)
        self.down = ctk.CTkButton(self.move, text="▼", width=24, command=lambda: app._move_slot(self, 1), **GRAY)
        self.down.grid(row=0, column=1, padx=(2, 0))
        self.key = KeyButton(p, "▶", slot["key"], lambda: app._toggle_slot(self),
                             lambda kb: app._rebind(kb, set_key), lambda kb: app._clear_key(kb, set_key))
        self.file_btn = ctk.CTkButton(p, text=t("file"), width=78, command=lambda: app._pick(self))
        self.name = ctk.CTkLabel(p, text=short(Path(slot["path"]).name) or t("no_file"), anchor="w")
        self.coll = ctk.CTkOptionMenu(p, width=130, dynamic_resizing=False, values=[t("no_collection")],
                                      command=lambda label: app._set_collection(self, label))
        self.time = ctk.CTkLabel(p, text="-:-- / -:--", width=84, text_color="gray70")
        self.progress = ctk.CTkSlider(p, from_=0, to=1, width=150, command=self._seek)
        self.progress.set(0)
        self.vol = ctk.CTkSlider(p, from_=0, to=1.5, width=90, command=self._volume)
        self.vol.set(slot["volume"])
        self.play_btn = ctk.CTkButton(p, text="▶", width=30, command=lambda: app._play_slot(self))
        self.pause_btn = ctk.CTkButton(p, text="⏸", width=30, command=lambda: app.engine.pause(self))
        self.stop_btn = ctk.CTkButton(p, text="■", width=30, command=lambda: app.engine.stop(self))
        self.rm_btn = ctk.CTkButton(p, text="✕", width=30, fg_color="#7a2b2b", hover_color="#a33",
                                    command=lambda: app._remove_slot(self))
        self.widgets = [self.move, self.key, self.file_btn, self.name, self.coll, self.time, self.progress,
                        self.vol, self.play_btn, self.pause_btn, self.stop_btn, self.rm_btn]

    def grid(self, r):
        for c, w in enumerate(self.widgets):
            w.grid(row=r, column=c, padx=(4, 2) if c else (4, 4), pady=3,
                   sticky="ew" if w is self.name else "")

    def hide(self):
        """Some da lista (colecao recolhida); a tecla continua funcionando."""
        for w in self.widgets:
            w.grid_remove()

    def update_place(self, labels, current, can_up, can_down):
        """Menu de colecoes, colecao atual e quais setas de ordem valem."""
        self.coll.configure(values=labels)
        self.coll.set(current)
        self.up.configure(state="normal" if can_up else "disabled")
        self.down.configure(state="normal" if can_down else "disabled")

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


class CollectionHeader(ctk.CTkFrame):
    """Cabecalho de um grupo da lista: nome e quantidade; nas colecoes, recolher, adicionar som,
    mudar de posicao, renomear e apagar. coll None = grupo dos sons sem colecao."""

    def __init__(self, app, coll, count, first=True, last=True):
        super().__init__(app.list, fg_color=("gray80", "gray22"), corner_radius=6)
        bold = ctk.CTkFont(size=13, weight="bold")
        if coll is None:
            ctk.CTkLabel(self, text=f"{t('ungrouped')}  ({count})", font=bold, text_color="gray70"
                         ).pack(side="left", padx=12, pady=3)
            return
        name = coll["name"]
        # adiado: o botao clicado e destruido quando a lista e redesenhada
        later = lambda fn: (lambda: app.after(10, fn))
        ctk.CTkButton(self, text="▸" if coll["collapsed"] else "▾", width=26, **GRAY, font=ctk.CTkFont(size=18),
                      command=later(lambda: app._toggle_collection(name))).pack(side="left", padx=(6, 4), pady=3)
        ctk.CTkLabel(self, text=f"{name}  ({count})", font=bold).pack(side="left", padx=4)
        ctk.CTkButton(self, text="✕", width=28, fg_color="#7a2b2b", hover_color="#a33",
                      command=later(lambda: app._delete_collection(name))).pack(side="right", padx=(2, 6))
        ctk.CTkButton(self, text="✎", width=28, **GRAY,
                      command=later(lambda: app._rename_collection(name))).pack(side="right", padx=2)
        ctk.CTkButton(self, text="▼", width=24, **GRAY, state="disabled" if last else "normal",
                      command=later(lambda: app._move_collection(name, 1))).pack(side="right", padx=2)
        ctk.CTkButton(self, text="▲", width=24, **GRAY, state="disabled" if first else "normal",
                      command=later(lambda: app._move_collection(name, -1))).pack(side="right", padx=2)
        ctk.CTkButton(self, text=t("add_here"), width=70,
                      command=later(lambda: app._add_slot(name))).pack(side="right", padx=(2, 10))

    def place_at(self, r):
        self.grid(row=r, column=0, columnspan=COLUMNS, sticky="ew", padx=4, pady=(10, 2))


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title("Sound Mod")
        self.geometry("1180x780")
        self.minsize(1080, 620)

        self.cfg = config.load()
        i18n.set_language(self.cfg["language"])
        # aviso unico na barra de status quando a config da versao antiga foi importada
        self.notice = t("config_imported", path=config.migrated_from) if config.migrated_from else None
        self.engine = Engine()
        self.recorder = LoopbackRecorder(self.cfg["clip_seconds"])
        self.hotkeys = HotkeyManager()
        self.rows = []
        self.headers = []
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
        ctk.CTkButton(opts, text=t("data_folder"), width=110, command=self._open_data_folder, **GRAY
                      ).pack(side="right", padx=(8, 0))
        self.lang_var = ctk.StringVar(value=i18n.LANGUAGES[i18n.current()])
        ctk.CTkOptionMenu(opts, variable=self.lang_var, values=list(i18n.LANGUAGES.values()), width=110,
                          command=self._on_language).pack(side="right", padx=8)

        fx = ctk.CTkFrame(dev, fg_color="transparent")
        fx.grid(row=5, column=0, columnspan=2, sticky="ew", padx=6, pady=(0, 8))
        ctk.CTkLabel(fx, text=t("voice")).pack(side="left", padx=(8, 6))
        self.fx_names = {t(f"fx_{name}"): name for name in voice.EFFECTS}
        current = self.cfg["voice_effect"] if self.cfg["voice_effect"] in voice.EFFECTS else "normal"
        self.fx_var = ctk.StringVar(value=t(f"fx_{current}"))
        ctk.CTkSegmentedButton(fx, values=list(self.fx_names), variable=self.fx_var,
                               command=self._on_voice).pack(side="left", padx=4)
        self.hear_self_var = ctk.BooleanVar(value=self.cfg["hear_self"])
        ctk.CTkCheckBox(fx, text=t("hear_self"), variable=self.hear_self_var,
                        command=self._apply_live).pack(side="left", padx=12)

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
        ctk.CTkButton(head, text=t("new_collection"), width=130, command=self._new_collection, **GRAY
                      ).pack(side="right", padx=(0, 8))
        scroll = ScrollFrame(box)
        scroll.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
        self.list = scroll.inner
        self.list.grid_columnconfigure(NAME_COL, weight=1)
        self.headers = []
        for s in self.cfg["slots"]:
            self._add_row(s)
        self._layout()

        # clipe do audio do PC
        clip = ctk.CTkFrame(self)
        clip.grid(row=3, column=0, sticky="ew", padx=12, pady=6)
        clip.grid_columnconfigure(9, weight=1)
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
        ctk.CTkButton(clip, text=t("save_as_sound"), width=130, command=self._save_as_sound
                      ).grid(row=0, column=8, padx=(10, 2))
        ctk.CTkLabel(clip, text=t("stop_all")).grid(row=0, column=10, padx=(0, 4))
        self.stop_key = self._cfg_key_button(clip, "■", "stop_key", self.engine.stop_all)
        self.stop_key.grid(row=0, column=11, padx=(0, 10))
        self.wave = Waveform(clip, self._clip_range, self._clip_seek)
        self.wave.grid(row=1, column=0, columnspan=12, sticky="ew", padx=10, pady=(0, 4))
        ctk.CTkLabel(clip, text_color="gray60", text=t("clip_hint")).grid(
            row=2, column=0, columnspan=12, sticky="w", padx=10, pady=(0, 6))

        self.status = ctk.CTkLabel(self, text=t("ready"), anchor="w")
        self.status.grid(row=4, column=0, sticky="ew", padx=14, pady=(2, 10))

    def _cfg_key_button(self, parent, icon, cfg_key, action):
        set_key = lambda k: self.cfg.__setitem__(cfg_key, k)
        return KeyButton(parent, icon, self.cfg[cfg_key], action,
                         lambda kb: self._rebind(kb, set_key), lambda kb: self._clear_key(kb, set_key))

    def _add_row(self, slot):
        """Cria a linha do som no fim de self.rows; quem chama redesenha com _layout()."""
        row = SlotRow(self, slot)
        self.rows.append(row)
        return row

    def _layout(self):
        """Redesenha a lista agrupada por colecao, na ordem de cfg["slots"].

        As linhas (SlotRow) sobrevivem, porque sao os ids dos canais no engine; so os
        cabecalhos sao recriados. Sem nenhuma colecao, a lista fica como era, sem cabecalhos.
        """
        for h in self.headers:
            h.destroy()
        self.headers = []
        order = {id(s): i for i, s in enumerate(self.cfg["slots"])}
        self.rows.sort(key=lambda r: order[id(r.slot)])  # mesma ordem que cfg["slots"]
        by_slot = {id(r.slot): r for r in self.rows}
        cols = self.cfg["collections"]
        labels = [t("no_collection")] + library.names(self.cfg)
        r = 0
        for coll, slots in library.groups(self.cfg):
            if cols and (coll is not None or slots):
                i = library.index(cols, coll) if coll is not None else 0
                h = CollectionHeader(self, coll, len(slots), first=i == 0, last=i == len(cols) - 1)
                h.place_at(r)
                self.headers.append(h)
                r += 1
            hidden = coll is not None and coll["collapsed"]
            for i, s in enumerate(slots):
                row = by_slot[id(s)]
                row.update_place(labels, s["collection"] or t("no_collection"), i > 0, i < len(slots) - 1)
                if hidden:
                    row.hide()
                else:
                    row.grid(r)
                    r += 1

    def _changed(self):
        """Depois de mudar ordem/colecoes: redesenha e salva."""
        self._layout()
        config.save(self.cfg)

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

    def _say(self, msg):
        self._post(lambda: self.status.configure(text=msg))

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

    def _add_slot(self, collection=None):
        """+ Adicionar som (collection None) ou o + da colecao: escolhe arquivos e adiciona."""
        paths = filedialog.askopenfilenames(filetypes=[(t("audio_files"), AUDIO_GLOB), (t("all_files"), "*.*")])
        for path in paths:
            self._add_sound(path, collection)
        if paths:
            if collection and library.find(self.cfg, collection):
                library.set_collapsed(self.cfg, collection, False)
            self._layout()
            self._register_hotkeys()
            config.save(self.cfg)
            self._say(t("sounds_added", n=len(paths)))

    def _add_sound(self, path, collection=None):
        """Usa o primeiro slot sem arquivo do mesmo grupo (mantem a tecla dele) ou cria um slot
        novo no fim do grupo. Quem chama redesenha com _layout()."""
        row = next((r for r in self.rows if not r.slot["path"] and r.slot["collection"] == collection), None)
        if row is None:
            slot = {"key": "", "path": "", "volume": 1.0, "collection": collection}
            self.cfg["slots"].append(slot)
            row = self._add_row(slot)
        row.slot["path"] = path
        row.name.configure(text=short(Path(path).name))
        self.engine.invalidate(config.resolve(path))
        threading.Thread(target=self._load_slot, args=(row, True), daemon=True).start()
        return row

    def _remove_slot(self, row):
        slots = self.cfg["slots"]
        slots.pop(library.index(slots, row.slot))  # por identidade: slots vazios sao iguais (==)
        self.engine.remove(row)
        row.destroy()
        self.rows.remove(row)
        self._layout()
        self._register_hotkeys()
        config.save(self.cfg)

    # ---------- ordem e colecoes ----------
    def _move_slot(self, row, delta):
        if library.move(self.cfg, row.slot, delta):
            self._changed()

    def _set_collection(self, row, label):
        name = None if label == t("no_collection") else label
        if not library.set_collection(self.cfg, row.slot, name):
            return
        if name:
            library.set_collapsed(self.cfg, name, False)  # para o som nao sumir da vista
        self._changed()
        self._say(t("moved_to", sound=Path(row.slot["path"]).name or t("no_file"),
                    name=name or t("ungrouped")))

    def _ask_collection_name(self, title, current=None):
        """Pede o nome; None se cancelou ou se o nome nao serve (a barra de status diz o motivo)."""
        name = ctk.CTkInputDialog(text=t("collection_name"), title=title).get_input()
        if name is None:
            return None
        name, error = library.clean_name(self.cfg, name, current, RESERVED)
        if error:
            self._say(t(f"collection_{error}", name=name))
            return None
        return name

    def _new_collection(self):
        name = self._ask_collection_name(t("new_collection_title"))
        if name:
            library.add_collection(self.cfg, name)
            self._changed()
            self._say(t("collection_created", name=name))

    def _rename_collection(self, old):
        new = self._ask_collection_name(t("rename_collection_title", name=old), current=old)
        if new and new != old:
            library.rename_collection(self.cfg, old, new)
            self._changed()
            self._say(t("collection_renamed", old=old, name=new))

    def _delete_collection(self, name):
        library.delete_collection(self.cfg, name)
        self._changed()
        self._say(t("collection_deleted", name=name))

    def _move_collection(self, name, delta):
        if library.move_collection(self.cfg, name, delta):
            self._changed()

    def _toggle_collection(self, name):
        coll = library.find(self.cfg, name)
        library.set_collapsed(self.cfg, name, not coll["collapsed"])
        self._changed()

    def _open_data_folder(self):
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(config.DATA_DIR)

    def _pick(self, row):
        path = filedialog.askopenfilename(filetypes=[(t("audio_files"), AUDIO_GLOB), (t("all_files"), "*.*")])
        if not path:
            return
        row.slot["path"] = path
        row.name.configure(text=short(Path(path).name))
        self.engine.invalidate(config.resolve(path))
        threading.Thread(target=self._load_slot, args=(row,), daemon=True).start()

    def _load_slot(self, row, quiet=False):
        path = row.slot["path"]
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
                config.SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
                target = config.SOUNDS_DIR / f"{name}.mp3"
                n = 2
                while target.exists():
                    target = config.SOUNDS_DIR / f"{name} ({n}).mp3"
                    n += 1
                part = data[int(start * SR):int(end * SR)]
                encode_mp3((np.clip(part, -1, 1) * 32767).astype(np.int16), SR, 2, target)
            except Exception as e:
                return self._say(t("sound_save_error", e=e))
            # relativo a pasta de dados: continua valendo se ela for copiada para outro PC
            rel = target.relative_to(config.DATA_DIR).as_posix()
            self._post(lambda: self._sound_saved(rel))
        threading.Thread(target=work, daemon=True).start()

    def _sound_saved(self, rel):
        self._add_sound(rel)
        self._layout()
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
    def _on_voice(self, label):
        name = self.fx_names[label]
        self.cfg["voice_effect"] = name
        self.engine.set_voice(name)
        config.save(self.cfg)
        self._say(t("voice_on", name=label))

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

        if self.notice:
            msgs.insert(0, self.notice)
            self.notice = None
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
