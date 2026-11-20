import unittest

from soundmod import library


def slot(path, collection=None, key=""):
    return {"key": key, "path": path, "volume": 1.0, "collection": collection}


def paths(slots):
    return [s["path"] for s in slots]


def view(cfg):
    """Como a tela mostra: [(nome da colecao ou None, [caminhos])]."""
    return [(c["name"] if c else None, paths(ss)) for c, ss in library.groups(cfg)]


class LibraryTest(unittest.TestCase):
    def setUp(self):
        self.cfg = library.normalize({
            "collections": [{"name": "Memes"}, {"name": "Lula", "collapsed": True}],
            "slots": [slot("a"), slot("m1", "Memes"), slot("b"), slot("l1", "Lula"), slot("m2", "Memes")],
        })

    def test_groups_put_ungrouped_first_then_collections_in_order(self):
        self.assertEqual(view(self.cfg), [(None, ["a", "b"]), ("Memes", ["m1", "m2"]), ("Lula", ["l1"])])

    def test_move_swaps_only_within_the_same_collection(self):
        s = self.cfg["slots"]
        b, m2 = s[2], s[4]
        self.assertTrue(library.move(self.cfg, b, -1))
        self.assertTrue(library.move(self.cfg, m2, -1))
        self.assertEqual(view(self.cfg), [(None, ["b", "a"]), ("Memes", ["m2", "m1"]), ("Lula", ["l1"])])

    def test_move_at_the_edge_does_nothing(self):
        before = paths(self.cfg["slots"])
        first, last = self.cfg["slots"][0], self.cfg["slots"][3]
        self.assertFalse(library.move(self.cfg, first, -1))
        self.assertFalse(library.move(self.cfg, last, 1))  # unico da colecao Lula
        self.assertEqual(paths(self.cfg["slots"]), before)

    def test_move_finds_identical_empty_slots_by_identity(self):
        cfg = library.normalize({"collections": [], "slots": [slot(""), slot(""), slot("x")]})
        second = cfg["slots"][1]
        library.move(cfg, second, -1)
        self.assertIs(cfg["slots"][0], second)
        self.assertIsNone(library.neighbor(cfg, second, -1))

    def test_set_collection_puts_sound_at_the_end_of_the_target(self):
        a = self.cfg["slots"][0]
        self.assertTrue(library.set_collection(self.cfg, a, "Memes"))
        self.assertEqual(view(self.cfg)[1], ("Memes", ["m1", "m2", "a"]))
        self.assertFalse(library.set_collection(self.cfg, a, "Memes"))
        self.assertTrue(library.set_collection(self.cfg, a, None))
        self.assertEqual(view(self.cfg)[0], (None, ["b", "a"]))
        with self.assertRaises(KeyError):
            library.set_collection(self.cfg, a, "nao existe")

    def test_rename_updates_the_sounds(self):
        library.rename_collection(self.cfg, "Memes", "Engracados")
        self.assertEqual(view(self.cfg)[1], ("Engracados", ["m1", "m2"]))

    def test_delete_keeps_the_sounds_without_collection(self):
        self.assertEqual(library.delete_collection(self.cfg, "Memes"), 2)
        self.assertEqual(view(self.cfg), [(None, ["a", "b", "m1", "m2"]), ("Lula", ["l1"])])
        self.assertEqual(len(self.cfg["slots"]), 5)

    def test_move_collection(self):
        self.assertTrue(library.move_collection(self.cfg, "Lula", -1))
        self.assertEqual(library.names(self.cfg), ["Lula", "Memes"])
        self.assertFalse(library.move_collection(self.cfg, "Lula", -1))

    def test_collapse(self):
        library.set_collapsed(self.cfg, "Lula", False)
        self.assertFalse(library.find(self.cfg, "Lula")["collapsed"])

    def test_clean_name(self):
        self.assertEqual(library.clean_name(self.cfg, "  Novos   sons "), ("Novos sons", None))
        self.assertEqual(library.clean_name(self.cfg, "   ")[1], "empty")
        self.assertEqual(library.clean_name(self.cfg, "memes")[1], "exists")
        self.assertEqual(library.clean_name(self.cfg, "MEMES", current="Memes"), ("MEMES", None))
        self.assertEqual(library.clean_name(self.cfg, "(sem coleção)", reserved=["(sem coleção)"])[1], "exists")

    def test_normalize_old_config(self):
        cfg = library.normalize({"slots": [{"key": "f1", "path": "x", "volume": 1.0},
                                           {"path": "y", "collection": "Nova"}]})
        self.assertEqual(cfg["collections"], [{"name": "Nova", "collapsed": False}])
        self.assertIsNone(cfg["slots"][0]["collection"])
        self.assertEqual(cfg["slots"][1]["key"], "")
        self.assertEqual(view(cfg), [(None, ["x"]), ("Nova", ["y"])])

    def test_normalize_drops_duplicate_and_blank_collections(self):
        cfg = library.normalize({"collections": ["A", {"name": "A"}, {"name": " "}, 3], "slots": []})
        self.assertEqual(library.names(cfg), ["A"])


if __name__ == "__main__":
    unittest.main()
