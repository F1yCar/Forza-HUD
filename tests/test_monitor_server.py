import ast
import importlib.util
import inspect
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]


class MonitorServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, cwd)
        env = patch.dict(os.environ, {"FORZA_DATA_DIR": str(self.data)})
        env.start()
        self.addCleanup(env.stop)
        spec = importlib.util.spec_from_file_location("monitor_under_test", ROOT / "monitor_server.py")
        self.server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.server)
        self.client = TestClient(self.server.app)
        self.addCleanup(self.client.close)

    def lap_file(self, name="Track/Car/lap.csv", content="DistanceTraveled,CurrentLapTime\n0,0\n100,1\n"):
        path = Path(self.server.BASTLAP_DIR) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_pages_work_outside_project_directory(self):
        for url in ("/", "/obs", "/replay", "/setup"):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertIn("text/html", response.headers["content-type"])

    def test_assets_keep_original_urls(self):
        for filename in ("黑high.png", "白high.png", "Steering Wheel.png"):
            with self.subTest(filename=filename):
                response = self.client.get("/" + filename)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["content-type"], "image/png")

    def test_database_paths_use_data_directory(self):
        (self.data / "fm_cars.json").write_text('{"42": "Test car"}', encoding="utf-8")
        self.server.load_dbs()
        self.assertEqual(self.server.fm_db, {"42": "Test car"})
        self.assertEqual(Path(self.server.BASTLAP_DIR), self.data.resolve() / "bastlap")

    def test_lap_download(self):
        path = self.lap_file()
        response = self.client.get("/data/Track/Car/lap.csv")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, path.read_text(encoding="utf-8"))

    def test_lap_download_cannot_escape_data_directory(self):
        target = self.root / "outside.csv"
        target.write_text("private", encoding="utf-8")
        response = self.client.get("/data/" + str(target))
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("private", response.text)

    def test_symlink_cannot_escape_data_directory(self):
        target = self.root / "outside.csv"
        target.write_text("private", encoding="utf-8")
        link = Path(self.server.BASTLAP_DIR) / "link.csv"
        link.symlink_to(target)
        self.assertEqual(self.client.get("/data/link.csv").status_code, 400)

    def test_delete_cannot_escape_data_directory(self):
        target = Path(self.server.BASTLAP_DIR).parent / "outside.csv"
        target.write_text("keep", encoding="utf-8")
        response = self.client.request("DELETE", "/api/laps", json={"path": "../outside.csv"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(target.read_text(encoding="utf-8"), "keep")

    def test_lap_delete_and_listing(self):
        path = self.lap_file()
        self.lap_file("temp_lap/hidden.csv")
        self.assertEqual(self.client.get("/api/laps").json()["files"], ["Track/Car/lap.csv"])
        response = self.client.request("DELETE", "/api/laps", json={"path": "Track/Car/lap.csv"})
        self.assertEqual(response.json(), {"success": True})
        self.assertFalse(path.exists())

    def test_project_directory_name_does_not_filter_laps(self):
        self.server.BASTLAP_DIR = str(self.data / "SESSION_temp_lap_project" / "bastlap")
        self.lap_file("Track/Car/Track_Car_01-00.000.csv")
        files = self.client.get("/api/laps").json()["files"]
        self.assertEqual(files, ["Track/Car/Track_Car_01-00.000.csv"])
        self.assertEqual(self.server.load_historical_reference("Track", "Car"), 60)

    def test_lap_endpoint_does_not_serve_internal_json(self):
        (Path(self.server.BASTLAP_DIR) / "strategies.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self.client.get("/data/strategies.json").status_code, 404)

    def test_setup_round_trip(self):
        response = self.client.post("/api/setups/save", json={"setup_name": "Test", "save_type": "saves", "setup_data": {"spring": 42}})
        self.assertTrue(response.json()["success"])
        self.assertEqual(self.client.get("/api/setups/load", params={"file": "Test.json", "type": "saves"}).json(), {"spring": 42})

    def test_setup_cleanup_uses_relative_names(self):
        target = Path(self.server.SETUPS_TEMP_DIR) / "old.json"
        target.write_text("{}", encoding="utf-8")
        os.utime(target, (0, 0))
        expired = self.client.get("/api/setups/check_temp").json()["expired"]
        self.assertEqual(expired[0]["path"], "old.json")
        response = self.client.post("/api/setups/clean_temp", json={"files": expired})
        self.assertEqual(response.json()["deleted"], 1)
        self.assertFalse(target.exists())

    def test_setup_cleanup_rejects_traversal_before_deleting(self):
        inside = Path(self.server.SETUPS_TEMP_DIR) / "inside.json"
        outside = Path(self.server.SETUPS_DIR) / "outside.json"
        inside.write_text("{}", encoding="utf-8")
        outside.write_text("{}", encoding="utf-8")
        response = self.client.post("/api/setups/clean_temp", json={"files": [{"path": "inside.json"}, {"path": "../outside.json"}]})
        self.assertEqual(response.status_code, 400)
        self.assertTrue(inside.exists())
        self.assertTrue(outside.exists())

    def test_fh5_shifted_fields(self):
        raw = bytearray(324)
        struct.pack_into("<f", raw, 256, 50.0)
        struct.pack_into("<B", raw, 319, 4)
        self.assertEqual(self.server.get_packet_value({"Speed": 999}, raw, "Speed"), 50.0)
        self.assertEqual(self.server.get_packet_value({"Gear": 999}, raw, "Gear"), 4)

    def test_fh5_unavailable_fields_do_not_fall_back(self):
        raw = bytearray(324)
        for field in ("TireWear_FL", "TireWear_FR", "TireWear_RL", "TireWear_RR", "TrackOrdinal"):
            with self.subTest(field=field):
                self.assertIsNone(self.server.get_packet_value({field: 123}, raw, field, None))

    def test_fm_fields(self):
        raw = bytearray(331)
        struct.pack_into("<f", raw, 311, 0.25)
        struct.pack_into("<i", raw, 327, 530)
        self.assertEqual(self.server.get_packet_value({}, raw, "TireWear_FL"), 0.25)
        self.assertEqual(self.server.get_packet_value({}, raw, "TrackOrdinal"), 530)

    def test_session_recordings_are_not_renamed_as_laps(self):
        session = self.lap_file("Track/Car/SESSION_FM_20260418_105619.csv")
        self.server.save_lap_data_thread("Track", "Car", 60, [{"DistanceTraveled": 0, "CurrentLapTime": 0}])
        self.assertTrue(session.exists())
        session2 = self.lap_file("Track/Car/SESSION_FM_20260418_111046.csv")
        self.server.run_startup_cleanup()
        self.assertTrue(session.exists())
        self.assertTrue(session2.exists())
        self.assertFalse(list(session.parent.glob("SESSION_*LastBastLap.csv")))

    def test_listener_does_not_migrate_files_on_startup(self):
        tree = ast.parse(inspect.getsource(self.server.udp_listener))
        calls = [node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
        self.assertNotIn("run_startup_cleanup", calls)

    def test_fuel_debrief_uses_percent(self):
        rows = [{"Fuel": 0.6, "LapNumber": 1}] * 499 + [{"Fuel": 0.2, "LapNumber": 1}]
        report = self.server.analyze_race_data(rows)
        self.assertEqual(report[0]["level"], "warning")
        self.assertIn("20.0%", report[0]["phys"])

    def test_unsafe_names_do_not_create_parent_paths(self):
        for name in ("", ".", ".."):
            with self.subTest(name=name):
                self.assertNotIn(self.server.safe_filename(name), ("", ".", ".."))


if __name__ == "__main__":
    unittest.main()
