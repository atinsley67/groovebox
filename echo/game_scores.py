"""
ECHO's top-10 leaderboard, on the CIRCUITPY drive as /echo_scores.json: the
ten best scores with a 4-character name each, best first, and the last name
entered (the next entry starts from it, so a regular player just commits
it).

A board is a dict: {"top": [[name, score], ...], "last": name}. The pure
functions (rank_for, insert) work on it in memory; load and save are the
file I/O, written like groove.py's slots -- to a temp file first, so a
failed write never loses the board already there.
"""

import json
import os

from gbox.groove import error_label   # noqa: F401 -- the game's, too ("RO  ", "FULL")

SIZE     = 10
NAME_LEN = 4
CHARS    = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 "   # a name's letters, in UP order
VERSION  = 1
_PATH    = "/echo_scores.json"


def empty():
    return {"top": [], "last": "A" * NAME_LEN}


def clean_name(name):
    """`name` as NAME_LEN of CHARS: upper case, anything else a space."""
    out = ""
    for ch in str(name).upper()[:NAME_LEN]:
        out += ch if ch in CHARS else " "
    return out + " " * (NAME_LEN - len(out))


def rank_for(board, score):
    """Where `score` would go on the board (0 = the top), or None if it
    doesn't make it. A tie goes below the scores already there."""
    if score <= 0:
        return None
    top = board["top"]
    for i in range(len(top)):
        if score > top[i][1]:
            return i
    return len(top) if len(top) < SIZE else None


def insert(board, rank, name, score):
    """Put `name`'s `score` in at `rank` (from rank_for), dropping whatever
    falls off the bottom, and remember the name for next time."""
    top = board["top"]
    top.insert(rank, [name, score])
    while len(top) > SIZE:
        top.pop()
    board["last"] = name


def load():
    """The board on the drive -- an empty one if there isn't one yet or it
    can't be read. Entries that don't make sense are dropped."""
    board = empty()
    try:
        with open(_PATH) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return board
    if not isinstance(data, dict):
        return board
    top = data.get("top")
    if isinstance(top, list):
        for entry in top:
            if (isinstance(entry, list) and len(entry) == 2 and
                    isinstance(entry[1], int) and entry[1] > 0):
                board["top"].append([clean_name(entry[0]), entry[1]])
    board["top"].sort(key=lambda entry: entry[1], reverse=True)
    while len(board["top"]) > SIZE:
        board["top"].pop()
    if isinstance(data.get("last"), str):
        board["last"] = clean_name(data["last"])
    return board


def save(board):
    """Write the board. Raises OSError (error_label says why)."""
    tmp = _PATH + ".tmp"
    record = {"v": VERSION, "top": board["top"], "last": board["last"]}
    try:
        with open(tmp, "w") as f:
            json.dump(record, f)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    # FAT can't rename onto an existing file.
    try:
        os.remove(_PATH)
    except OSError:
        pass
    os.rename(tmp, _PATH)
