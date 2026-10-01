"""synth_params list schemas, groove slots, and that every module compiles."""

import glob
import json
import os
import py_compile
import shutil
import tempfile
import unittest

import fakes

import groove
import synth_params


class SchemaTest(unittest.TestCase):
    def check_schema(self, schema):
        keys = [entry["key"] for entry in schema]
        self.assertEqual(len(keys), len(set(keys)), "duplicate keys")
        for entry in schema:
            self.assertNotIn("page", entry)
            self.assertNotIn("pad", entry)
            self.assertEqual(len(entry["label"]), 4, entry["label"])
        self.assertEqual(schema[-1]["kind"], "action", "RST must be last")
        self.assertEqual([e["kind"] for e in schema].count("action"), 1)

    def test_voice_schema(self):
        self.check_schema(synth_params.PARAM_SCHEMA)
        self.assertEqual([e["label"] for e in synth_params.PARAM_SCHEMA],
                         ["AMP ", "WAVE", "ATK ", "DEC ", "SUS ", "REL ", "CUT ",
                          "RES ", "LFOR", "LFOD", "LDST", "RING", "DTUN", "RST "])

    def test_drum_schema(self):
        self.check_schema(synth_params.DRUM_PARAM_SCHEMA)
        self.assertEqual([e["label"] for e in synth_params.DRUM_PARAM_SCHEMA],
                         ["AMP ", "TUNE", "ATK ", "DEC ", "TONE", "SNAP", "RST "])

    def test_step_value(self):
        amp = synth_params.PARAM_SCHEMA[0]
        self.assertAlmostEqual(synth_params.step_value(amp, 0.5, 1), 0.55)
        self.assertEqual(synth_params.step_value(amp, 1.0, 1), 1.0)
        wave = synth_params.PARAM_SCHEMA[1]
        self.assertEqual(synth_params.step_value(wave, 3, 1), 0)


class GrooveSlotTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="grooves-").replace("\\", "/")
        self._saved_dir = groove._DIR
        groove._DIR = self.dir + "/grooves"

    def tearDown(self):
        groove._DIR = self._saved_dir
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_sixteen_slots_independent_of_pads(self):
        self.assertEqual(groove.NUM_SLOTS, 16)

    def test_last_slot_round_trip(self):
        self.assertEqual(groove.used_slots(), 0)
        groove.save(15, {"bpm": 99})
        self.assertEqual(groove.used_slots(), 1 << 15)
        self.assertTrue(os.path.exists(groove._DIR + "/slot16.json"))
        self.assertEqual(groove.load(15)["bpm"], 99)

    def test_old_slot_files_still_found(self):
        os.mkdir(groove._DIR)
        with open(groove._DIR + "/slot3.json", "w") as f:
            json.dump({"v": 1}, f)
        self.assertEqual(groove.used_slots(), 1 << 2)


class CompileTest(unittest.TestCase):
    def test_every_module_compiles(self):
        files = glob.glob(os.path.join(fakes.ROOT, "*.py"))
        self.assertTrue(files)
        out = tempfile.mkdtemp()
        try:
            for path in files:
                py_compile.compile(path, cfile=os.path.join(out, "x.pyc"), doraise=True)
        finally:
            shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
