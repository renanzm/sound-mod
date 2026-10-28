import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
CLIPS_DIR = ROOT / "clips"
CLIP_PATH = CLIPS_DIR / "last_clip.mp3"

DEFAULTS = {
    "mic_device": None,        # nome do microfone real
    "output_device": None,     # nome do cabo virtual (CABLE Input)
    "monitor_device": None,    # onde VOCE ouve os sons (fones)
    "loopback_device": None,   # None = alto-falante padrao
    "mix_mic": True,
    "monitor": True,
    "master_volume": 1.0,
    "clip_seconds": 5,
    "save_clip_key": "f5",
    "play_clip_key": "f6",
    "stop_key": "f12",
    "slots": [
        {"key": "f1", "path": "", "volume": 1.0},
        {"key": "f2", "path": "", "volume": 1.0},
        {"key": "f3", "path": "", "volume": 1.0},
        {"key": "f4", "path": "", "volume": 1.0},
    ],
}


def load():
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return cfg


def save(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
