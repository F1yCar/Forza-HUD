import csv
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import URLError
from urllib.request import urlopen

from websockets.sync.client import connect


ROOT = Path(__file__).resolve().parents[1]


def unused_port(kind):
    with socket.socket(socket.AF_INET, kind) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.data = Path(cls.temp.name) / "data"
        cls.data.mkdir()
        for filename in ("fh5_cars.json", "fm_cars.json"):
            (cls.data / filename).write_text('{"42": "Test Car"}', encoding="utf-8")
        (cls.data / "Track_Name.json").write_text('{"530": "Test Track"}', encoding="utf-8")
        cls.old_sessions = cls.data / "bastlap" / "Old Track" / "Old Car"
        cls.old_sessions.mkdir(parents=True)
        for stamp in ("105619", "111046"):
            (cls.old_sessions / f"SESSION_FM_20260418_{stamp}.csv").write_text("original\n", encoding="utf-8")
        cls.web_port = unused_port(socket.SOCK_STREAM)
        cls.udp_port = unused_port(socket.SOCK_DGRAM)
        cls.url = f"http://127.0.0.1:{cls.web_port}"
        env = dict(os.environ, FORZA_DATA_DIR=str(cls.data), FORZA_WEB_HOST="127.0.0.1", FORZA_WEB_PORT=str(cls.web_port), FORZA_UDP_PORT=str(cls.udp_port))
        cls.process = subprocess.Popen(
            [sys.executable, "-B", str(ROOT / "monitor_server.py")],
            cwd=cls.temp.name, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8",
        )
        cls.addClassCleanup(cls.stop_server)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if cls.process.poll() is not None:
                raise AssertionError(cls.process.communicate()[0])
            try:
                with urlopen(cls.url, timeout=0.5) as response:
                    if response.status == 200:
                        return
            except (URLError, TimeoutError):
                time.sleep(0.05)
        raise AssertionError("Server did not become ready")

    @classmethod
    def stop_server(cls):
        cls.process.terminate()
        try:
            output = cls.process.communicate(timeout=5)[0]
        except subprocess.TimeoutExpired:
            cls.process.kill()
            output = cls.process.communicate()[0]
        if "Traceback" in output or "ERROR:" in output:
            raise AssertionError(output)

    def receive_until(self, ws, predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            packet = json.loads(ws.recv(timeout=2))
            if predicate(packet):
                return packet
        self.fail("Expected telemetry state was not received")

    def send_packet(self, game):
        raw = bytearray(331 if game == "FM" else 324)
        shift = 0 if game == "FM" else 12
        struct.pack_into("<i", raw, 0, 1)
        struct.pack_into("<f", raw, 8, 8000)
        struct.pack_into("<f", raw, 16, 6000)
        struct.pack_into("<i", raw, 212, 42)
        struct.pack_into("<f", raw, 244 + shift, 50)
        struct.pack_into("<f", raw, 276 + shift, 0.75)
        struct.pack_into("<f", raw, 292 + shift, 10)
        struct.pack_into("<B", raw, 307 + shift, 4)
        if game == "FM":
            struct.pack_into("<f", raw, 311, 0.25)
            struct.pack_into("<i", raw, 327, 530)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(raw, ("127.0.0.1", self.udp_port))

    def test_http_pages_and_original_sessions(self):
        for route in ("/", "/obs", "/replay", "/setup"):
            with self.subTest(route=route), urlopen(self.url + route, timeout=2) as response:
                self.assertEqual(response.status, 200)
                self.assertIn("text/html", response.headers["Content-Type"])
        self.assertEqual(sorted(p.name for p in self.old_sessions.iterdir()), ["SESSION_FM_20260418_105619.csv", "SESSION_FM_20260418_111046.csv"])
        for path in self.old_sessions.iterdir():
            self.assertEqual(path.read_text(encoding="utf-8"), "original\n")

    def test_udp_websocket_and_session_recording(self):
        with connect(f"ws://127.0.0.1:{self.web_port}/ws", open_timeout=3) as ws:
            self.send_packet("FM")
            packet = self.receive_until(ws, lambda p: p.get("Car") == "Test Car" and p.get("Mode") == "FM")
            self.assertEqual(packet["Speed"], 180)
            self.assertEqual(packet["Gear"], "4")
            self.assertEqual(packet["Fuel"], 75)
            self.assertEqual(packet["Wears"]["fl"], 25)
            self.assertEqual(packet["Track"], "Test Track")
            self.send_packet("FH5")
            packet = self.receive_until(ws, lambda p: p.get("Mode") == "FH5")
            self.assertEqual(packet["Speed"], 180)
            self.assertEqual(packet["Gear"], "4")
            self.assertEqual(packet["Wears"]["fl"], 0)
            ws.send(json.dumps({"cmd": "toggle_session_rec", "val": True}))
            self.receive_until(ws, lambda p: p.get("IsSessionRec") is True)
            self.send_packet("FH5")
            time.sleep(0.1)
            ws.send(json.dumps({"cmd": "toggle_session_rec", "val": False}))
            self.receive_until(ws, lambda p: p.get("IsSessionRec") is False)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            files = list((self.data / "bastlap" / "FH5" / "Test Car").glob("SESSION_*.csv"))
            if files:
                with files[0].open(encoding="utf-8", newline="") as stream:
                    rows = list(csv.DictReader(stream))
                if rows:
                    self.assertEqual(rows[0]["Mode"], "FH5")
                    self.assertEqual(float(rows[0]["Speed"]), 50)
                    self.assertEqual(float(rows[0]["TireWear_FL"]), 0)
                    return
            time.sleep(0.05)
        self.fail("Session recording was not saved")


if __name__ == "__main__":
    unittest.main()
