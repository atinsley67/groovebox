"""
Allocation patterns the device pays for and the desktop can't see.

`x in (_PLAYING, _OVERDUB)` builds a new tuple on every test when its items
are names rather than literals: 16 bytes on the device, measured at the
REPL. One in looper.update ran 8 times a pass -- 128 bytes of garbage per
main-loop pass, a collection every second or two while loops played.
`x == _PLAYING or x == _OVERDUB` allocates nothing; a tuple of literals
(`state in ("IDLE", "PLY ")`) is a constant and fine too.

So in the modules on the main loop's per-pass and per-frame paths, a
membership test against a tuple or list must hold only literals.
"""

import ast
import os
import unittest

import fakes  # noqa: F401  (sets up the paths)

# Modules whose code runs every main-loop pass or every light redraw.
_HOT_MODULES = ("looper.py", "arp.py", "sequencer.py", "synth_engine.py",
                "pad_views.py", "display.py", "pixels.py", "hw.py", "clock.py")


def _built_each_time(node):
    """True for a tuple/list display holding anything but literals."""
    return (isinstance(node, (ast.Tuple, ast.List)) and
            not all(isinstance(item, ast.Constant) for item in node.elts))


class MembershipTupleTest(unittest.TestCase):
    def test_no_tuples_of_names_in_hot_modules(self):
        found = []
        for name in _HOT_MODULES:
            path = os.path.join(fakes.ROOT, name)
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read(), name)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Compare):
                    continue
                for op, right in zip(node.ops, node.comparators):
                    if isinstance(op, (ast.In, ast.NotIn)) and _built_each_time(right):
                        found.append(f"{name}:{node.lineno}")
        self.assertEqual(found, [], "use == comparisons instead (see this module's doc)")


if __name__ == "__main__":
    unittest.main()
