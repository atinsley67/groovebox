"""game_scores.py: ECHO's top 10 -- placing a score, and the file."""

import json
import os
import shutil
import tempfile
import unittest

import fakes  # noqa: F401  (sets up the paths)

from echo import game_scores
from echo.game_scores import empty, insert, rank_for


def board(*scores):
    return {"top": [[f"P{i:<3}", s] for i, s in enumerate(scores)], "last": "AAAA"}


class RankTest(unittest.TestCase):
    def test_an_empty_board_takes_any_score(self):
        self.assertEqual(rank_for(empty(), 1), 0)

    def test_nothing_for_nothing(self):
        self.assertIsNone(rank_for(empty(), 0))

    def test_its_place(self):
        b = board(900, 500, 100)
        self.assertEqual(rank_for(b, 1000), 0)
        self.assertEqual(rank_for(b, 600), 1)
        self.assertEqual(rank_for(b, 50), 3)

    def test_a_tie_goes_below(self):
        self.assertEqual(rank_for(board(900, 500, 100), 500), 2)

    def test_a_full_board(self):
        full = board(*range(1000, 0, -100))            # 1000 .. 100
        self.assertIsNone(rank_for(full, 100))
        self.assertIsNone(rank_for(full, 50))
        self.assertEqual(rank_for(full, 150), 9)

    def test_insert_drops_the_bottom_and_remembers_the_name(self):
        full = board(*range(1000, 0, -100))
        insert(full, 0, "ALEX", 2000)
        self.assertEqual(len(full["top"]), game_scores.SIZE)
        self.assertEqual(full["top"][0], ["ALEX", 2000])
        self.assertEqual(full["top"][-1][1], 200)      # 100 fell off
        self.assertEqual(full["last"], "ALEX")


class FileTest(unittest.TestCase):
    def setUp(self):
        self.dir   = tempfile.mkdtemp(prefix="echo-")
        self.saved = game_scores._PATH
        game_scores._PATH = os.path.join(self.dir, "echo_scores.json")

    def tearDown(self):
        game_scores._PATH = self.saved
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, data):
        with open(game_scores._PATH, "w") as f:
            f.write(data if isinstance(data, str) else json.dumps(data))

    def test_none_yet(self):
        self.assertEqual(game_scores.load(), empty())

    def test_save_and_load(self):
        b = board(900, 500)
        insert(b, 1, "ZED ", 700)
        game_scores.save(b)
        self.assertEqual(game_scores.load(), b)
        game_scores.save(b)                            # over the old one
        self.assertEqual(game_scores.load(), b)
        self.assertFalse(os.path.exists(game_scores._PATH + ".tmp"))

    def test_corrupt_reads_as_empty(self):
        self.write("{not json")
        self.assertEqual(game_scores.load(), empty())
        self.write([1, 2, 3])
        self.assertEqual(game_scores.load(), empty())

    def test_odd_entries_are_cleaned_or_dropped(self):
        self.write({"top": [["alex", 300], ["toolong", 900], ["X", "lots"],
                            ["neg", -5], "junk", ["ok", 100]] + [["P", 50]] * 12,
                    "last": "bob"})
        top = game_scores.load()
        self.assertEqual(top["top"][:3], [["TOOL", 900], ["ALEX", 300], ["OK  ", 100]])
        self.assertEqual(len(top["top"]), game_scores.SIZE)
        self.assertEqual(top["last"], "BOB ")

    def test_names_keep_to_the_letters(self):
        self.assertEqual(game_scores.clean_name("a-b"), "A B ")


if __name__ == "__main__":
    unittest.main()
