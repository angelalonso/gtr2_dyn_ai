import tempfile
import unittest
from pathlib import Path

from core_autopilot import AutopilotEngine, FormulaManager
from core_database import CurveDatabase


class TestQuartileTarget(unittest.TestCase):
    def test_band_center_uses_empirical_quartile(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = AutopilotEngine(
                CurveDatabase(str(Path(directory) / "data.db")),
                FormulaManager(CurveDatabase(str(Path(directory) / "formula.db"))),
            )
            settings = {
                "mode": "quartile_band",
                "band": "top_25",
                "min_ai_laps": 1,
                "min_ai_races": 1,
            }
            target = engine.calculate_target_time_from_settings(
                90.0, 100.0, settings, [90.0, 92.0, 94.0, 96.0, 98.0, 100.0], 1
            )
            self.assertAlmostEqual(target, 91.25)

    def test_insufficient_data_falls_back_and_reports_missing_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            db = CurveDatabase(str(Path(directory) / "data.db"))
            engine = AutopilotEngine(db, FormulaManager(db))
            settings = {
                "mode": "quartile_band",
                "band": "third_25",
                "min_ai_laps": 8,
                "min_ai_races": 2,
            }
            target, info = engine.get_target_time_for_combo(
                "Unknown", "GT", "race", 95.0, settings
            )
            self.assertEqual(target, 95.0)
            self.assertFalse(info["active"])
            self.assertEqual(info["needed_laps"], 8)
            self.assertEqual(info["needed_races"], 2)


if __name__ == "__main__":
    unittest.main()
