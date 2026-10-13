"""
The code's layout: config.py, code.py and boot.py at the top, everything
else in its package (core, gbox, echo, tools), always imported through it.

A module imported under two names -- `clock` and `core.clock` -- would be
two modules: the fakes' clock patch (and every test's monkeypatching)
would reach one and miss the other. On the device, a stray copy of a
module in the drive's root would never be the one the code runs.
"""

import ast
import os
import sys
import unittest

import fakes

_ROOT_FILES = {"boot.py", "code.py", "config.py"}


def _project_modules():
    """{module name: package} for every module in the packages."""
    names = {}
    for package in fakes.PACKAGES:
        for name in os.listdir(os.path.join(fakes.ROOT, package)):
            if name.endswith(".py") and name != "__init__.py":
                names[name[:-3]] = package
    return names


def _test_files():
    folder = os.path.join(fakes.ROOT, "tests")
    return [os.path.join(folder, name) for name in sorted(os.listdir(folder))
            if name.endswith(".py")]


class LayoutTest(unittest.TestCase):
    def test_only_the_entry_points_and_config_at_the_top(self):
        at_top = {name for name in os.listdir(fakes.ROOT) if name.endswith(".py")}
        self.assertEqual(at_top, _ROOT_FILES)

    def test_every_package_is_one(self):
        for package in fakes.PACKAGES:
            self.assertTrue(os.path.exists(os.path.join(fakes.ROOT, package, "__init__.py")),
                            package)

    def test_no_module_name_is_a_package_name(self):
        """On the device a bare folder can import as a package: a module
        named like one would be shadowed."""
        self.assertFalse(set(_project_modules()) & set(fakes.PACKAGES))

    def test_project_modules_are_always_imported_through_their_package(self):
        modules = _project_modules()
        bare = []
        for path in fakes.sources() + _test_files():
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read(), path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module]
                else:
                    continue
                for name in names:
                    if name.split(".")[0] in modules:
                        bare.append(f"{os.path.relpath(path, fakes.ROOT)}:{node.lineno} {name}")
                    elif "." in name:
                        package, module = name.split(".", 1)
                        if package in fakes.PACKAGES and modules.get(module) != package:
                            bare.append(f"{os.path.relpath(path, fakes.ROOT)}:{node.lineno} {name}")
        self.assertEqual(bare, [], "import project modules as `from <package> import ...`")

    def test_nothing_was_loaded_under_a_bare_name(self):
        # Every test module has been imported by now, so everything they
        # (and the code they load) imported is in sys.modules.
        doubled = [name for name in _project_modules() if name in sys.modules]
        self.assertEqual(doubled, [])


if __name__ == "__main__":
    unittest.main()
