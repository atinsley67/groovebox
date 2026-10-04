"""
Groove slots on the CIRCUITPY drive -- the menu's SAVE / LOAD.

A groove is everything needed to pick a session back up: BPM, sync mode,
the sequencer pattern, every committed loop layer, which instrument each
layer has, every sound edit and every channel volume (code.py's
capture_groove builds it from each module's own snapshot). One JSON file
per slot, /grooves/slot1.json .. slot16.json -- readable from a computer
too.

Pure file I/O: this module knows nothing about what's inside a groove.
Writing needs boot.py's storage.remount(); without it every save fails
with a read-only error, which error_label() turns into "RO  ".

Versions ("v" in the file): 1 = the 8-pad layout, where a melodic layer's
pad n was note n; 2 = the 16-pad grid, notes rising from the bottom left.
load() hands back either -- code.py's apply_groove converts a v1.
"""

import json
import os

# The menu's slot labels ("S03*") have room for two digits, so at most 99.
NUM_SLOTS = 16

VERSION  = 2
_READS   = (1, 2)   # versions load() accepts
_DIR     = "/grooves"

# OSError codes CircuitPython raises for these (its errno module doesn't
# reliably define the names).
_EROFS  = 30   # drive not remounted writable (boot.py)
_ENOSPC = 28


def _name(slot):
    return f"slot{slot + 1}.json"


def _path(slot):
    return f"{_DIR}/{_name(slot)}"


def used_slots():
    """Bitmask of slots holding a saved groove (bit n = slot n)."""
    try:
        names = os.listdir(_DIR)
    except OSError:
        return 0   # no /grooves yet: nothing saved
    mask = 0
    for slot in range(NUM_SLOTS):
        if _name(slot) in names:
            mask |= 1 << slot
    return mask


def save(slot, data):
    """Write `data` (code.py's capture_groove() dict) to `slot`. Written to
    a temp file first, so a failed write (drive full, read-only) never
    clobbers what the slot already held. Raises OSError."""
    try:
        os.listdir(_DIR)
    except OSError:
        os.mkdir(_DIR)
    path = _path(slot)
    tmp  = path + ".tmp"
    record = dict(data)
    record["v"] = VERSION
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
        os.remove(path)
    except OSError:
        pass
    os.rename(tmp, path)


def load(slot):
    """Read a slot back. Raises OSError (missing/unreadable) or ValueError
    (corrupt, or not a groove file this code understands)."""
    with open(_path(slot)) as f:
        data = json.load(f)
    if not isinstance(data, dict) or data.get("v") not in _READS:
        raise ValueError("not a groove version this code reads")
    return data


def error_label(exc):
    """4-char display text for a save/load failure."""
    code = exc.args[0] if isinstance(exc, OSError) and exc.args else None
    if code == _EROFS:
        return "RO  "
    if code == _ENOSPC:
        return "FULL"
    return "ERR "
