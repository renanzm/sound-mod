"""Testes da janela (abre uma janela Tk de verdade por alguns instantes).

Audio, captura e hotkeys globais ficam desligados: so a lista de sons e exercitada.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from soundmod import config, gui, i18n
from soundmod.hotkeys import HotkeyManager


def slot(path, collection=None, key=""):
    return {"key": key, "path": path, "volume": 1.0, "collection": collection}


class GuiTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(config.set_dirs, config.APP_DIR, config.DATA_DIR)
        root = Path(tmp.name)
        (root / "app").mkdir()
        config.set_dirs(root / "app", root / "data")
        for target, attr, value in [
            (gui.App, "_start_all", lambda self: None),
            (gui.App, "_load_missing", lambda self: None),
            (HotkeyManager, "register", lambda self, mapping: []),
        ]:
            p = mock.patch.object(target, attr, value)
            p.start()
            self.addCleanup(p.stop)
        self.apps = []

    def tearDown(self):
        for app in self.apps:
            for job in app.tk.splitlist(app.tk.call("after", "info")):
                app.after_cancel(job)  # evita "invalid command name" de callbacks da janela destruida
            app.destroy()
        i18n.set_language("pt")

    def open(self, cfg):
        config.save({**config.DEFAULTS, "language": "pt", **cfg})
        app = gui.App()
        app.withdraw()
        app.update_idletasks()
        self.apps.append(app)
        return app

    def name_input(self, text):
        return mock.patch.object(gui.ctk.CTkInputDialog, "__init__", lambda self, **kw: None), \
            mock.patch.object(gui.ctk.CTkInputDialog, "get_input", lambda self: text)

    def screen(self, app):
        """O que aparece na lista, de cima para baixo: ("#", cabecalho) e caminhos dos sons visiveis."""
        items = []
        for h in app.headers:
            label = next(w for w in h.winfo_children() if isinstance(w, gui.ctk.CTkLabel))
            items.append((int(h.grid_info()["row"]), "# " + label.cget("text")))
        for r in app.rows:
            if r.key.winfo_manager() == "grid":
                items.append((int(r.key.grid_info()["row"]), r.slot["path"]))
        items.sort()
        self.assertEqual([i for i, _ in items], list(range(len(items))), "linhas da grade fora de ordem")
        return [x for _, x in items]

    def saved(self):
        return json.loads(config.CONFIG_PATH.read_text(encoding="utf-8"))

    def row(self, app, path):
        return next(r for r in app.rows if r.slot["path"] == path)

    def test_without_collections_the_list_looks_like_before(self):
        app = self.open({"slots": [slot("a"), slot("b"), slot("c")]})
        self.assertEqual(self.screen(app), ["a", "b", "c"])
        self.assertEqual(app.headers, [])
        self.assertEqual(str(self.row(app, "a").up.cget("state")), "disabled")
        self.assertEqual(str(self.row(app, "c").down.cget("state")), "disabled")

    def test_move_up_and_down_is_saved(self):
        app = self.open({"slots": [slot("a"), slot("b"), slot("c")]})
        app._move_slot(self.row(app, "c"), -1)
        self.assertEqual(self.screen(app), ["a", "c", "b"])
        app._move_slot(self.row(app, "a"), 1)
        self.assertEqual(self.screen(app), ["c", "a", "b"])
        app._move_slot(self.row(app, "c"), -1)  # ja e o primeiro
        self.assertEqual([s["path"] for s in self.saved()["slots"]], ["c", "a", "b"])
        self.assertEqual([r.slot["path"] for r in app.rows], ["c", "a", "b"])

    def test_collections_create_assign_collapse_rename_delete(self):
        app = self.open({"slots": [slot("a"), slot("b"), slot("c")]})
        init, get = self.name_input("  Memes ")
        with init, get:
            app._new_collection()
        self.assertEqual(self.screen(app), ["# Sem coleção  (3)", "a", "b", "c", "# Memes  (0)"])

        app._set_collection(self.row(app, "a"), "Memes")
        app._set_collection(self.row(app, "c"), "Memes")
        self.assertEqual(self.screen(app), ["# Sem coleção  (1)", "b", "# Memes  (2)", "a", "c"])
        self.assertEqual(self.row(app, "c").coll.get(), "Memes")
        self.assertEqual(self.saved()["collections"], [{"name": "Memes", "collapsed": False}])

        app._move_slot(self.row(app, "c"), -1)
        self.assertEqual(self.screen(app), ["# Sem coleção  (1)", "b", "# Memes  (2)", "c", "a"])

        app._toggle_collection("Memes")
        self.assertEqual(self.screen(app), ["# Sem coleção  (1)", "b", "# Memes  (2)"])
        self.assertTrue(self.saved()["collections"][0]["collapsed"])
        app._toggle_collection("Memes")

        init, get = self.name_input("memes")  # mesmo nome (so muda maiuscula): permitido
        with init, get:
            app._rename_collection("Memes")
        self.assertEqual(self.screen(app)[2], "# memes  (2)")
        self.assertEqual({s["path"]: s["collection"] for s in self.saved()["slots"]},
                         {"a": "memes", "b": None, "c": "memes"})

        app._set_collection(self.row(app, "b"), "memes")  # sem coleção vazio: o cabecalho some
        self.assertEqual(self.screen(app), ["# memes  (3)", "c", "a", "b"])

        app._delete_collection("memes")
        self.assertEqual(self.screen(app), ["c", "a", "b"])
        self.assertEqual(self.saved()["collections"], [])

    def test_invalid_collection_names(self):
        app = self.open({"collections": [{"name": "Memes"}], "slots": [slot("a")]})
        for text in ["   ", "MEMES", "(sem coleção)", "(no collection)"]:
            init, get = self.name_input(text)
            with init, get:
                app._new_collection()
        self.assertEqual(len(app.cfg["collections"]), 1)

    def test_collection_order_buttons(self):
        app = self.open({"collections": [{"name": "A"}, {"name": "B"}],
                         "slots": [slot("x", "A"), slot("y", "B")]})
        self.assertEqual(self.screen(app), ["# A  (1)", "x", "# B  (1)", "y"])
        app._move_collection("B", -1)
        self.assertEqual(self.screen(app), ["# B  (1)", "y", "# A  (1)", "x"])
        self.assertEqual([c["name"] for c in self.saved()["collections"]], ["B", "A"])

    def test_add_sound_into_a_collection(self):
        app = self.open({"collections": [{"name": "A", "collapsed": True}], "slots": [slot("")]})
        with mock.patch.object(gui.filedialog, "askopenfilenames", return_value=("n1.mp3", "n2.mp3")), \
                mock.patch.object(gui.App, "_load_slot", lambda *a: True):
            app._add_slot("A")
        # o slot vazio de fora da colecao nao e usado; a colecao abre para mostrar os sons novos
        self.assertEqual(self.screen(app), ["# Sem coleção  (1)", "", "# A  (2)", "n1.mp3", "n2.mp3"])

    def test_remove_identical_empty_slot_removes_the_right_one(self):
        app = self.open({"slots": [slot(""), slot(""), slot("x")]})
        second = app.rows[1]
        app._remove_slot(second)
        self.assertEqual(len(app.cfg["slots"]), 2)
        self.assertTrue(all(r.slot is s for r, s in zip(app.rows, app.cfg["slots"])))
        self.assertNotIn(second.slot, [s for s in app.cfg["slots"] if s is second.slot])

    def test_language_change_keeps_order_collections_and_channels(self):
        app = self.open({"collections": [{"name": "A"}], "slots": [slot("x"), slot("y", "A"), slot("z", "A")]})
        app._move_slot(self.row(app, "z"), -1)
        rows_before = list(app.rows)
        for r in rows_before:
            app.engine.channels[r] = object()
        app._change_language("en")
        self.assertEqual(self.screen(app), ["# No collection  (1)", "x", "# A  (2)", "z", "y"])
        self.assertEqual(self.row(app, "x").coll.get(), "(no collection)")
        # cada canal passou para a linha nova do mesmo som
        for old, new in zip(rows_before, app.rows):
            self.assertIs(old.slot, new.slot)
            self.assertIn(new, app.engine.channels)

    def test_reopen_keeps_everything(self):
        app = self.open({"slots": [slot("a"), slot("b")]})
        init, get = self.name_input("Grupo")
        with init, get:
            app._new_collection()
        app._set_collection(self.row(app, "a"), "Grupo")
        app._move_slot(self.row(app, "b"), 1)
        app._close()
        self.apps.remove(app)
        again = gui.App()
        again.withdraw()
        self.apps.append(again)
        self.assertEqual(self.screen(again), ["# Sem coleção  (1)", "b", "# Grupo  (1)", "a"])


if __name__ == "__main__":
    unittest.main()
