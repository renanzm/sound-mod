"""Identidade visual: paleta, fontes, icones (glifos) e ajustes de janela do Windows.

Estilo: painéis escuros em tom carvao quente, cantos bem arredondados, laranja como cor de
destaque e verde para o que esta tocando. Todas as cores da interface vem daqui.
"""
import ctypes
import tkinter.font as tkfont
from pathlib import Path

import customtkinter as ctk

ASSETS = Path(__file__).resolve().parent / "assets"
ICON = ASSETS / "icon.ico"

# ---- paleta ----
BG = "#171615"            # fundo da janela
CARD = "#211F1D"          # paineis
ITEM = "#2A2826"          # linhas, botoes neutros, campos
ITEM_HOVER = "#36332F"
BORDER = "#363330"
TEXT = "#F4F1EE"
MUTED = "#A39D97"
DIM = "#5F5A55"
ACCENT = "#FF6A3D"        # laranja de destaque
ACCENT_HOVER = "#FF845E"
ACCENT_SOFT = "#3A2419"
GREEN = "#3FCB6B"         # tocando / ligado
GREEN_HOVER = "#5AD683"
DANGER = "#E5484D"
DANGER_SOFT = "#3A2223"
WARN = "#FFB03D"

RADIUS_CARD = 18
RADIUS = 10

# ---- glifos da fonte de icones do Windows (Segoe Fluent Icons / MDL2 Assets) ----
PLAY = ""
PAUSE = ""
STOP = ""
EDIT = ""
CLEAR = ""
DELETE = ""
FOLDER = ""
ADD = ""
SAVE = ""
MIC = ""
VOLUME = ""
HEADPHONES = ""

_fonts = {"text": "Segoe UI", "display": "Segoe UI", "icons": "Segoe MDL2 Assets"}


def apply_colors():
    """Ajusta o tema padrao do customtkinter. Chamar antes de criar a janela."""
    ctk.set_appearance_mode("dark")
    th = ctk.ThemeManager.theme

    def put(widget, **values):
        for key, value in values.items():
            th[widget][key] = [value, value] if isinstance(value, str) and value != "transparent" else value

    put("CTk", fg_color=BG)
    put("CTkToplevel", fg_color=BG)
    put("CTkFrame", fg_color=CARD, top_fg_color=ITEM, border_color=BORDER, corner_radius=RADIUS_CARD)
    put("CTkButton", fg_color=ITEM, hover_color=ITEM_HOVER, border_color=BORDER, text_color=TEXT,
        text_color_disabled=DIM, corner_radius=RADIUS)
    put("CTkLabel", text_color=TEXT)
    put("CTkEntry", fg_color=ITEM, border_color=BORDER, text_color=TEXT, corner_radius=RADIUS, border_width=1)
    put("CTkCheckBox", fg_color=ACCENT, hover_color=ACCENT_HOVER, border_color=DIM, text_color=TEXT)
    put("CTkSwitch", fg_color=BORDER, progress_color=ACCENT, button_color=TEXT, button_hover_color="#FFFFFF",
        text_color=TEXT)
    put("CTkSlider", fg_color=BORDER, progress_color=ACCENT, button_color=TEXT, button_hover_color="#FFFFFF")
    put("CTkOptionMenu", fg_color=ITEM, button_color=ITEM, button_hover_color=ITEM_HOVER, text_color=TEXT,
        corner_radius=RADIUS)
    put("CTkScrollbar", button_color=ITEM_HOVER, button_hover_color=DIM)
    put("DropdownMenu", fg_color=CARD, hover_color=ITEM_HOVER, text_color=TEXT)


def load_fonts(root):
    """Escolhe as fontes instaladas (Windows 11 tem Segoe UI Variable e Segoe Fluent Icons)."""
    families = set(tkfont.families(root))
    _fonts["text"] = next((f for f in ("Segoe UI Variable Text", "Segoe UI") if f in families), "TkDefaultFont")
    _fonts["display"] = next((f for f in ("Segoe UI Variable Display", "Segoe UI") if f in families),
                             _fonts["text"])
    _fonts["icons"] = next((f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if f in families),
                           _fonts["text"])
    ctk.ThemeManager.theme["CTkFont"]["family"] = _fonts["text"]
    ctk.ThemeManager.theme["CTkFont"]["size"] = 13


def font(size=13, weight="normal"):
    return ctk.CTkFont(family=_fonts["text"], size=size, weight=weight)


def display(size=20, weight="bold"):
    return ctk.CTkFont(family=_fonts["display"], size=size, weight=weight)


def icons(size=14):
    return ctk.CTkFont(family=_fonts["icons"], size=size)


def set_app_id():
    """Faz a barra de tarefas usar o icone do app (e nao o do python.exe) ao rodar do codigo."""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("renanzm.SoundMod")
    except (AttributeError, OSError):
        pass


def style_titlebar(window):
    """Barra de titulo na cor do fundo (Windows 11; ignorado em versoes que nao suportam)."""
    def rgb(h):
        return int(h[1:3], 16) | int(h[3:5], 16) << 8 | int(h[5:7], 16) << 16

    try:
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        for attr, color in ((35, BG), (36, TEXT), (34, BG)):  # legenda, texto, borda
            value = ctypes.c_int(rgb(color))
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
    except (AttributeError, OSError):
        pass


def primary(**kwargs):
    """Argumentos de um botao de destaque (laranja)."""
    return dict(fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="#FFFFFF", **kwargs)


def icon_button(master, glyph, command, size=32, color=ITEM, hover=ITEM_HOVER, text_color=TEXT, glyph_size=13):
    return ctk.CTkButton(master, text=glyph, width=size, height=size, corner_radius=RADIUS, fg_color=color,
                         hover_color=hover, text_color=text_color, font=icons(glyph_size), command=command)
