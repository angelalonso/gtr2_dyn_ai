import tempfile
import unittest
from pathlib import Path

from core_aiw_utils import update_aiw_ratio
from core_data_extraction import RaceData
from core_database import CurveDatabase, connect_database


class TestUrgentSafety(unittest.TestCase):
    def test_incomplete_results_are_not_processable(self):
        data = RaceData(
            track_name="Track",
            user_vehicle="Car",
            user_best_lap_sec=90.0,
            ai_results=[],
        )
        self.assertFalse(data.has_data())
        self.assertIn("missing AI results", data.validation_errors())

    def test_duplicate_result_fingerprint_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            db = CurveDatabase(str(Path(directory) / "data.db"))
            result = {
                "race_id": "result-1",
                "timestamp": "now",
                "track_name": "Track",
                "source_fingerprint": "fingerprint-1",
                "ai_results": [],
            }
            self.assertEqual(db.save_race_session(result), "result-1")
            self.assertIsNone(db.save_race_session(result))

    def test_aiw_update_is_atomic_and_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            aiw = Path(directory) / "track.AIW"
            aiw.write_text(
                "[Waypoint]\nQualRatio = 1.000000\nRaceRatio = 1.000000\n",
                encoding="utf-8",
            )
            self.assertTrue(update_aiw_ratio(aiw, "QualRatio", 1.25))
            self.assertIn("QualRatio = 1.250000", aiw.read_text(encoding="utf-8"))

    def test_database_connection_enables_busy_timeout_and_foreign_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            conn = connect_database(str(Path(directory) / "data.db"))
            self.assertEqual(conn.execute("PRAGMA busy_timeout").fetchone()[0], 30000)
            self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            conn.close()


if __name__ == "__main__":
    unittest.main()
