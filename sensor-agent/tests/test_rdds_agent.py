import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rdds_agent import Config, Outbox, SensorAgent, parse_skyspy_line


class SkySpyParserTests(unittest.TestCase):
    def test_maps_current_firmware_line(self) -> None:
        line = json.dumps(
            {
                "mac": "AA:BB:CC:DD:EE:FF",
                "rssi": -45,
                "drone_lat": 52.231,
                "drone_long": 21.019,
                "drone_altitude": 120,
                "pilot_lat": 52.226,
                "pilot_long": 21.009,
                "basic_id": "TEST-DRONE-01",
            }
        )
        parsed = parse_skyspy_line(line)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["drone"]["mac"], "aa:bb:cc:dd:ee:ff")
        self.assertEqual(parsed["drone"]["basic_id"], "TEST-DRONE-01")
        self.assertEqual(parsed["drone"]["altitude_m"], 120.0)
        self.assertEqual(parsed["radio"]["rssi"], -45)
        self.assertEqual(parsed["pilot_position"]["longitude"], 21.009)

    def test_ignores_status_and_text_lines(self) -> None:
        self.assertIsNone(parse_skyspy_line('{"status":"scanning"}'))
        self.assertIsNone(parse_skyspy_line("Heartbeat: Drone still in range"))
        self.assertIsNone(parse_skyspy_line('{"heartbeat":true}'))

    def test_accepts_prefix_remote_id_and_no_gps(self) -> None:
        parsed = parse_skyspy_line(
            'debug: {"mac":"02:00:00:00:00:01","remote_id":"RID-01",'
            '"drone_lat":0,"drone_long":0}'
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["drone"]["basic_id"], "RID-01")
        self.assertNotIn("position", parsed["drone"])
        self.assertIsNone(parsed["pilot_position"])

    def test_accepts_forward_compatible_operator_and_motion_fields(self) -> None:
        parsed = parse_skyspy_line(
            '{"mac":"02:00:00:00:00:02","op_id":"OP-02",'
            '"speed":12.5,"heading":91,"transport":"ble"}'
        )
        self.assertEqual(parsed["drone"]["operator_id"], "OP-02")
        self.assertEqual(parsed["drone"]["speed_mps"], 12.5)
        self.assertEqual(parsed["drone"]["heading_deg"], 91.0)
        self.assertEqual(parsed["radio"]["transport"], "ble")


class OutboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.outbox = Outbox(
            Path(self.temporary_directory.name) / "outbox.sqlite3",
            max_messages=2,
        )

    def tearDown(self) -> None:
        self.outbox.close()
        self.temporary_directory.cleanup()

    def test_fifo_acknowledge_and_retry(self) -> None:
        first = self.outbox.enqueue("/first", {"value": 1})
        second = self.outbox.enqueue("/second", {"value": 2})
        self.assertEqual(self.outbox.depth(), 2)
        self.assertEqual(self.outbox.oldest_due(now=10**12).message_id, first)

        self.outbox.retry(first, "offline", 60)
        self.assertIsNone(self.outbox.oldest_due())
        self.outbox.acknowledge(first)
        self.assertEqual(self.outbox.oldest_due(now=10**12).message_id, second)

    def test_dead_letter_preserves_failed_message(self) -> None:
        message_id = self.outbox.enqueue("/invalid", {"value": 1})
        self.outbox.move_to_dead_letter(message_id, "HTTP 422")
        self.assertEqual(self.outbox.depth(), 0)
        self.assertEqual(self.outbox.dead_letter_depth(), 1)


class DeliveryTests(unittest.TestCase):
    def test_retry_then_replay_keeps_payload_and_token(self) -> None:
        received: list[tuple[str, str, dict[str, object]]] = []
        response_codes = [503, 202]

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                received.append(
                    (self.path, self.headers["X-RDDS-Ingest-Token"], payload)
                )
                code = response_codes.pop(0)
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"accepted":true}')

            def log_message(self, _format: str, *_args: object) -> None:
                return

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        with tempfile.TemporaryDirectory() as directory:
            config = Config(
                api_url=f"http://127.0.0.1:{server.server_port}",
                ingest_token="individual-test-token",
                sensor_id="skyspy-test-01",
                display_name="Test receiver",
                source="loop://",
                baud_rate=115200,
                sensor_position=None,
                transport="unknown",
                heartbeat_seconds=10,
                reconnect_seconds=1,
                request_timeout_seconds=2,
                spool_path=Path(directory) / "outbox.sqlite3",
                max_queue_messages=100,
            )
            agent = SensorAgent(config)
            try:
                payload = {"protocol_version": "rdds/1.0", "value": 7}
                agent.outbox.enqueue("/api/test", payload)
                self.assertEqual(agent.flush_outbox(), 0)
                self.assertEqual(agent.outbox.depth(), 1)

                agent.outbox.connection.execute(
                    "UPDATE outbox SET next_attempt_at = 0"
                )
                self.assertEqual(agent.flush_outbox(), 1)
                self.assertEqual(agent.outbox.depth(), 0)
            finally:
                agent.outbox.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

        self.assertEqual(len(received), 2)
        self.assertEqual(received[0], received[1])
        self.assertEqual(received[0][0], "/api/test")
        self.assertEqual(received[0][1], "individual-test-token")


if __name__ == "__main__":
    unittest.main()
