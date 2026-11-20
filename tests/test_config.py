import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from soundmod import config

OLD_CONFIG = {
    "stop_key": "f11",
    "slots": [
        {"key": "f3", "path": "C:/Musicas/a.mp3", "volume": 1.5},
        {"key": "", "path": "sounds/salvo.mp3", "volume": 1.0},
    ],
}


class ConfigTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(config.set_dirs, config.APP_DIR, config.DATA_DIR)
        root = Path(tmp.name)
        self.app = root / "app"
        self.data = root / "appdata" / "SoundMod"
        self.app.mkdir()
        config.set_dirs(self.app, self.data)

    def write_old_version(self):
        (self.app / "config.json").write_text(json.dumps(OLD_CONFIG), encoding="utf-8")
        (self.app / "sounds").mkdir()
        (self.app / "sounds" / "salvo.mp3").write_bytes(b"som")
        (self.app / "clips").mkdir()
        (self.app / "clips" / "last_clip.mp3").write_bytes(b"clipe")

    def test_data_dir_is_under_appdata(self):
        with mock.patch.dict(os.environ, {"APPDATA": r"C:\Users\x\AppData\Roaming"}):
            self.assertEqual(config._data_dir(), Path(r"C:\Users\x\AppData\Roaming\SoundMod"))

    def test_fresh_install_uses_defaults(self):
        cfg = config.load()
        self.assertEqual(len(cfg["slots"]), 4)
        self.assertEqual(cfg["collections"], [])
        self.assertIsNone(config.migrated_from)

    def test_migrates_old_config_sounds_and_clip(self):
        self.write_old_version()
        cfg = config.load()
        self.assertEqual(config.migrated_from, self.app)
        self.assertEqual(cfg["stop_key"], "f11")
        self.assertEqual([s["path"] for s in cfg["slots"]], ["C:/Musicas/a.mp3", "sounds/salvo.mp3"])
        self.assertTrue(all(s["collection"] is None for s in cfg["slots"]))
        self.assertEqual((self.data / "sounds" / "salvo.mp3").read_bytes(), b"som")
        self.assertEqual(config.CLIP_PATH.read_bytes(), b"clipe")
        self.assertEqual(config.resolve("sounds/salvo.mp3"), self.data / "sounds" / "salvo.mp3")
        # nada e apagado da pasta antiga
        self.assertTrue((self.app / "config.json").exists())
        self.assertTrue((self.app / "sounds" / "salvo.mp3").exists())

    def test_app_folder_replaced_keeps_everything(self):
        self.write_old_version()
        cfg = config.load()
        cfg["collections"] = [{"name": "Memes", "collapsed": False}]
        cfg["slots"].reverse()
        cfg["slots"][0]["collection"] = "Memes"
        config.save(cfg)

        # atualizacao: a pasta do programa e substituida por uma copia nova, sem config
        for p in sorted(self.app.rglob("*"), reverse=True):
            p.rmdir() if p.is_dir() else p.unlink()
        config.set_dirs(self.app, self.data)
        again = config.load()
        self.assertIsNone(config.migrated_from)
        self.assertEqual(again["collections"], [{"name": "Memes", "collapsed": False}])
        self.assertEqual([(s["path"], s["collection"]) for s in again["slots"]],
                         [("sounds/salvo.mp3", "Memes"), ("C:/Musicas/a.mp3", None)])

    def test_old_config_copied_over_again_does_not_win(self):
        self.write_old_version()
        cfg = config.load()
        cfg["stop_key"] = "f9"
        config.save(cfg)
        config.set_dirs(self.app, self.data)
        self.assertEqual(config.load()["stop_key"], "f9")
        self.assertIsNone(config.migrated_from)

    def test_migration_does_not_overwrite_existing_sounds(self):
        self.write_old_version()
        (self.data / "sounds").mkdir(parents=True)
        (self.data / "sounds" / "salvo.mp3").write_bytes(b"novo")
        config.load()
        self.assertEqual((self.data / "sounds" / "salvo.mp3").read_bytes(), b"novo")

    def test_corrupted_config_is_kept_aside(self):
        self.data.mkdir(parents=True)
        config.CONFIG_PATH.write_text("{quebrado", encoding="utf-8")
        cfg = config.load()
        self.assertEqual(len(cfg["slots"]), 4)
        backups = list(self.data.glob("config-corrompido-*.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "{quebrado")

    def test_save_round_trip(self):
        cfg = config.load()
        cfg["slots"][0]["path"] = "C:/ação.mp3"
        config.save(cfg)
        self.assertFalse(config.CONFIG_PATH.with_suffix(".tmp").exists())
        config.set_dirs(self.app, self.data)
        self.assertEqual(config.load()["slots"][0]["path"], "C:/ação.mp3")


if __name__ == "__main__":
    unittest.main()
