import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "main.py"
SPEC = importlib.util.spec_from_file_location("rdds_skyspy_emulator", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load Sky-Spy emulator")
emulator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(emulator)


class EmulatorDiagnosticsTests(unittest.TestCase):
    def test_all_documented_fault_modes_are_accepted(self) -> None:
        for mode in ("normal", "silent", "malformed", "disconnect"):
            with self.subTest(mode=mode):
                self.assertEqual(mode, emulator.validate_fault_mode(mode))

    def test_unknown_fault_mode_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            emulator.validate_fault_mode("packet-loss-magic")

    def test_normal_detection_remains_valid(self) -> None:
        detection = emulator.detection(1)
        self.assertEqual("skyspy/1.1", detection["format_version"])
        self.assertEqual("SKYSPY-EMULATED-01", detection["basic_id"])
        self.assertIn("drone_lat", detection)


if __name__ == "__main__":
    unittest.main()
