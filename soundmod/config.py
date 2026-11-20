import json
import os
import shutil
import sys
import time
from pathlib import Path

from . import library

def _app_dir():
    """Pasta do programa (ao lado do .exe quando empacotado pelo PyInstaller)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _data_dir():
    """Dados do usuario ficam fora da pasta do programa (%APPDATA%\\SoundMod), para uma
    atualizacao (substituir a pasta do programa) nao apagar a configuracao nem os sons salvos."""
    base = os.environ.get("APPDATA")
    return (Path(base) if base else Path.home() / "AppData" / "Roaming") / "SoundMod"


LEGACY_DIRS = ("sounds", "clips")  # versoes antigas guardavam isso (e o config.json) na pasta do programa


def set_dirs(app_dir, data_dir):
    """Define as pastas (chamada ao importar; os testes usam pastas temporarias)."""
    global APP_DIR, DATA_DIR, CONFIG_PATH, CLIPS_DIR, CLIP_PATH, SOUNDS_DIR, LEGACY_CONFIG, migrated_from
    APP_DIR, DATA_DIR = Path(app_dir), Path(data_dir)
    CONFIG_PATH = DATA_DIR / "config.json"
    CLIPS_DIR = DATA_DIR / "clips"
    CLIP_PATH = CLIPS_DIR / "last_clip.mp3"
    SOUNDS_DIR = DATA_DIR / "sounds"  # clipes salvos como som
    LEGACY_CONFIG = APP_DIR / "config.json"
    migrated_from = None  # pasta de onde a configuracao antiga foi importada nesta execucao


set_dirs(_app_dir(), _data_dir())

DEFAULTS = {
    "language": None,          # "pt", "en" ou None = idioma do Windows
    # dispositivos: None = escolher automaticamente, "" = nenhum
    "mic_device": None,        # nome do microfone real
    "output_device": None,     # nome do cabo virtual (CABLE Input)
    "monitor_device": None,    # onde VOCE ouve os sons (fones)
    "loopback_device": None,   # None = alto-falante padrao
    "mix_mic": True,
    "monitor": True,
    "master_volume": 1.0,
    "clip_seconds": 5,
    "voice_effect": "normal",  # ver voice.EFFECTS
    "hear_self": False,        # ouvir a propria voz (com efeito) nos fones
    "clip_trim": None,         # [inicio, fim] em s do trecho do clipe que toca

    "save_clip_key": "f5",
    "play_clip_key": "f6",
    "stop_key": "f12",
    # colecoes na ordem em que aparecem: {"name", "collapsed"}; ver library.py
    "collections": [],
    # a ordem da lista e a ordem na tela; "collection" = nome da colecao ou None
    "slots": [
        {"key": "f1", "path": "", "volume": 1.0, "collection": None},
        {"key": "f2", "path": "", "volume": 1.0, "collection": None},
        {"key": "f3", "path": "", "volume": 1.0, "collection": None},
        {"key": "f4", "path": "", "volume": 1.0, "collection": None},
    ],
}


def migrate_legacy():
    """Copia config.json, sounds/ e clips/ da pasta do programa (versoes antigas) para DATA_DIR.

    So roda quando DATA_DIR ainda nao tem config. Copia sem apagar o original e sem sobrescrever
    nada que ja exista em DATA_DIR. Retorna True se importou.
    """
    global migrated_from
    if CONFIG_PATH.exists() or not LEGACY_CONFIG.is_file():
        return False
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name in LEGACY_DIRS:
        src = APP_DIR / name
        if src.is_dir():
            shutil.copytree(src, DATA_DIR / name, dirs_exist_ok=True,
                            copy_function=_copy_if_missing)
    # config por ultimo: se a copia acima falhar, a proxima execucao tenta de novo
    shutil.copy2(LEGACY_CONFIG, CONFIG_PATH)
    migrated_from = APP_DIR
    return True


def _copy_if_missing(src, dst):
    if not os.path.exists(dst):
        shutil.copy2(src, dst)
    return dst


def load():
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        migrate_legacy()
    except OSError:
        pass  # sem permissao etc.: segue com o que houver
    try:
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    except OSError:
        pass
    except ValueError:
        # arquivo corrompido: guarda uma copia antes que o proximo save grave os padroes por cima
        try:
            shutil.copy2(CONFIG_PATH, CONFIG_PATH.with_name(time.strftime("config-corrompido-%Y%m%d-%H%M%S.json")))
        except OSError:
            pass
    library.normalize(cfg)
    return cfg


def resolve(path):
    """Caminhos relativos (ex.: sons salvos em sounds/) sao relativos a pasta de dados."""
    p = Path(path)
    return p if p.is_absolute() else DATA_DIR / p


def save(cfg):
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    # grava num temporario e troca: uma falha no meio nao deixa o config.json pela metade
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, CONFIG_PATH)
