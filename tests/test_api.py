from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import socket
import tempfile
import threading
import time
import unittest
import uuid

from fake_server import FakeTransactionServer
from hax7700_widget.api import (
    OutboxState,
    Settings,
    TransactionOutbox,
    build_transaction,
    iso_utc,
    load_settings,
    pending_line,
    post_transaction,
    status_line,
    transaction_problem,
)
from hax7700_widget.core import ScanSession, TcpDeactivatorListener
from hax7700_widget.gui import _toggle_scan

REPO = Path(__file__).resolve().parent.parent
ISO_Z = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z")
EPCS = ["30351597B03DAA10A02DD553", "30351597B03DAA10A02DD554", "30351597B03DAA10A02DD555"]


def make_settings(server_url: str = "http://127.0.0.1:9", **overrides) -> Settings:
    values = {"store_code": "MUJI-NUVALI", "device_id": "POS-03-HAX7700", "cashier_name": "Ana"}
    values.update(overrides)
    return Settings(server_url, **values)


def finished_session(epcs=EPCS) -> dict:
    session = ScanSession()
    session.reset()
    for epc in epcs:
        session.observe(epc, source="sdk")
    return session.finish()


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def sale_bytes(body: dict) -> bytes:
    return json.dumps(body).encode("utf-8")


class PayloadTests(unittest.TestCase):
    def test_payload_has_exactly_the_server_fields_as_utc_z_times(self):
        snapshot = {
            "session_id": "7b0c1e0a-3f0c-4a7b-9d57-0a6f7a1d2c11",
            "started_at": "2026-11-02T10:14:05.000+00:00",
            "ended_at": "2026-11-02T18:15:12.250+08:00",
            # Newest first, the way ScanSession.snapshot() returns items
            "items": [
                {"epc": EPCS[1], "first_seen_at": "2026-11-02T10:14:30.123+00:00", "source": "sdk"},
                {"epc": EPCS[0], "first_seen_at": "2026-11-02T10:14:20.000+00:00", "source": "sdk"},
            ],
        }
        self.assertEqual(
            build_transaction(snapshot, make_settings()),
            {
                "clientTransactionId": "7b0c1e0a-3f0c-4a7b-9d57-0a6f7a1d2c11",
                "storeCode": "MUJI-NUVALI",
                "deviceId": "POS-03-HAX7700",
                "cashierName": "Ana",
                "startedAt": "2026-11-02T10:14:05.000Z",
                "endedAt": "2026-11-02T10:15:12.250Z",
                "tags": [
                    {"epc": EPCS[0], "scannedAt": "2026-11-02T10:14:20.000Z"},
                    {"epc": EPCS[1], "scannedAt": "2026-11-02T10:14:30.123Z"},
                ],
            },
        )

    def test_payload_from_a_real_scan_session(self):
        session = ScanSession()
        session_id = session.reset()["session_id"]
        for epc in EPCS + [EPCS[0].lower()]:  # the repeat read must not add a tag
            session.observe(epc, source="sdk")
        snapshot = session.finish()

        body = build_transaction(snapshot, make_settings())

        self.assertEqual(body["clientTransactionId"], session_id)
        self.assertEqual(uuid.UUID(session_id).version, 4)
        self.assertEqual([tag["epc"] for tag in body["tags"]], EPCS)
        first_seen = {item["epc"]: item["first_seen_at"] for item in snapshot["items"]}
        for tag in body["tags"]:
            self.assertEqual(set(tag), {"epc", "scannedAt"})
            self.assertEqual(tag["scannedAt"], iso_utc(first_seen[tag["epc"]]))
            self.assertRegex(tag["scannedAt"], ISO_Z)
            self.assertTrue(body["startedAt"] <= tag["scannedAt"] <= body["endedAt"])
        self.assertRegex(body["startedAt"], ISO_Z)
        self.assertRegex(body["endedAt"], ISO_Z)

    def test_blank_cashier_name_is_left_out(self):
        body = build_transaction(finished_session(), make_settings(cashier_name=None))
        self.assertNotIn("cashierName", body)

    def test_empty_session_builds_no_transaction(self):
        self.assertIsNone(build_transaction(finished_session([]), make_settings()))

    def test_unfinished_session_is_refused(self):
        session = ScanSession()
        session.observe(EPCS[0])
        with self.assertRaises(ValueError):
            build_transaction(session.snapshot(), make_settings())

    def test_transaction_problem_flags_too_many_tags_and_short_epcs(self):
        def body(count, epc_length=24):
            return {"tags": [{"epc": f"{i + 1:0{epc_length}X}", "scannedAt": ""} for i in range(count)]}

        self.assertEqual(transaction_problem(body(200)), "")
        self.assertIn("201 tags", transaction_problem(body(201)))
        self.assertIn("not 24 hex", transaction_problem(body(1, epc_length=8)))


class SettingsTests(unittest.TestCase):
    def load(self, text: str, encoding: str = "utf-8"):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(text, encoding=encoding)
            return load_settings(path)

    def test_valid_settings_and_notepad_bom(self):
        settings, error = self.load(
            '{"serverUrl": "http://192.168.1.10:3000/", "storeCode": " MUJI-NUVALI ", "deviceId": "POS-03"}',
            encoding="utf-8-sig",
        )
        self.assertEqual(error, "")
        self.assertEqual(settings.store_code, "MUJI-NUVALI")
        self.assertIsNone(settings.cashier_name)
        self.assertEqual(settings.transactions_url, "http://192.168.1.10:3000/api/v1/transactions")

    def test_example_file_is_valid(self):
        settings, error = load_settings(REPO / "settings.example.json")
        self.assertEqual(error, "")
        self.assertIsNotNone(settings)

    def test_missing_file_says_what_to_do(self):
        settings, error = load_settings(REPO / "no-such-settings.json")
        self.assertIsNone(settings)
        self.assertIn("not found", error)
        self.assertIn("settings.example.json", error)

    def test_missing_and_invalid_values_have_clear_messages(self):
        cases = {
            '{"serverUrl": "http://x:3000", "storeCode": ""}': "missing storeCode, deviceId",
            '{"serverUrl": "x:3000", "storeCode": "S", "deviceId": "D"}': "http:// or https://",
            '{"serverUrl": "http://x", "storeCode": 12, "deviceId": "D"}': "storeCode must be text",
            '{"serverUrl": "http://x", "storeCode": "%s", "deviceId": "D"}' % ("S" * 121): "longer than 120",
            '{"serverUrl": "http://x", "storeCode": "S",}': "not valid JSON (line 1",
            '["http://x"]': "must be one",
        }
        for text, expected in cases.items():
            with self.subTest(text=text[:40]):
                settings, error = self.load(text)
                self.assertIsNone(settings)
                self.assertIn(expected, error)


class _FixedReply(BaseHTTPRequestHandler):
    """A web server that is not the anti-theft server: a fixed status and an HTML body for every POST."""

    status = 200

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        self.send_response(self.status)
        self.send_header("Location", "/elsewhere")
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<html>hello</html>")

    def log_message(self, *_args):
        pass


class PostTransactionTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeTransactionServer().start()
        self.addCleanup(self.server.stop)
        self.url = self.server.url + "/api/v1/transactions"
        self.body = build_transaction(finished_session(), make_settings())
        self.sale_id = self.body["clientTransactionId"]

    def post(self, body: dict):
        return post_transaction(self.url, sale_bytes(body), body["clientTransactionId"], timeout=5)

    def test_201_then_200_are_both_success(self):
        first = self.post(self.body)
        again = self.post(self.body)
        self.assertEqual((first.outcome, first.status, first.item_count), ("sent", 201, 3))
        self.assertEqual((again.outcome, again.status, again.item_count), ("sent", 200, 3))
        headers = self.server.requests[0]["headers"]
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertNotIn("Authorization", headers)

    def test_400_and_409_are_rejected_without_retry(self):
        self.post(self.body)
        conflict = self.post(dict(self.body, cashierName="Bea"))
        self.assertEqual((conflict.outcome, conflict.status), ("rejected", 409))
        self.assertIn("different body", conflict.reason)

        invalid = self.post(dict(self.body, clientTransactionId=str(uuid.uuid4()), lane="extra"))
        self.assertEqual((invalid.outcome, invalid.status), ("rejected", 400))
        self.assertIn("property lane should not exist", invalid.reason)

    def test_429_and_5xx_are_retried(self):
        self.server.fail_next(429, retry_after=7)
        limited = self.post(self.body)
        self.assertEqual((limited.outcome, limited.status, limited.retry_after), ("retry", 429, 7.0))
        for status in (500, 502, 503):
            with self.subTest(status=status):
                self.server.fail_next(status)
                result = self.post(self.body)
                self.assertEqual((result.outcome, result.status), ("retry", status))

    def test_connection_refused_is_retried(self):
        url = f"http://127.0.0.1:{free_port()}/api/v1/transactions"
        result = post_transaction(url, sale_bytes(self.body), self.sale_id, timeout=5)
        self.assertEqual((result.outcome, result.status, result.reason), ("retry", None, "connection refused"))

    def test_reply_without_our_receipt_or_a_redirect_is_not_success(self):
        for status in (200, 302):
            with self.subTest(status=status):
                handler = type("Handler", (_FixedReply,), {"status": status})
                other = ThreadingHTTPServer(("127.0.0.1", 0), handler)
                threading.Thread(target=other.serve_forever, args=(0.05,), daemon=True).start()
                try:
                    url = f"http://127.0.0.1:{other.server_address[1]}/api/v1/transactions"
                    result = post_transaction(url, sale_bytes(self.body), self.sale_id, timeout=5)
                finally:
                    other.shutdown()
                    other.server_close()
                self.assertEqual((result.outcome, result.status), ("retry", status))


class OutboxTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.pending = Path(tmp.name) / "pending"
        self.server = FakeTransactionServer().start()
        self.addCleanup(self.server.stop)

    def outbox(self, server_url: str | None = None, **settings) -> TransactionOutbox:
        outbox = TransactionOutbox(
            self.pending,
            make_settings(server_url or self.server.url, **settings),
            retry_delays=(0.01,),
            min_request_gap=0,
            timeout=5,
        )
        self.addCleanup(outbox.stop)
        return outbox

    def waiting(self) -> list[Path]:
        return sorted(self.pending.glob("*.json"))

    def rejected(self) -> list[Path]:
        return sorted((self.pending / "rejected").glob("*.json"))

    def test_stop_saves_one_sale_and_201_removes_it(self):
        outbox = self.outbox()
        snapshot = finished_session()
        outbox.submit(snapshot)

        [saved] = self.waiting()
        self.assertEqual(json.loads(saved.read_text("utf-8")), build_transaction(snapshot, outbox.settings))
        self.assertEqual((outbox.state().phase, outbox.state().pending), ("sending", 1))

        result = outbox.send_next()

        self.assertEqual((result.outcome, result.status), ("sent", 201))
        self.assertEqual(self.waiting(), [])
        self.assertEqual(status_line(outbox.state()), ("Sent 3 items", "ok"))
        self.assertEqual(outbox.state().pending, 0)
        [request] = self.server.requests
        self.assertEqual([tag["epc"] for tag in request["json"]["tags"]], EPCS)
        self.assertIsNone(outbox.send_next())

    def test_200_already_stored_also_removes_it(self):
        outbox = self.outbox()
        snapshot = finished_session()
        # An earlier attempt reached the server but its reply was lost
        post_transaction(self.server.url + "/api/v1/transactions", sale_bytes(build_transaction(snapshot, outbox.settings)), snapshot["session_id"])
        outbox.submit(snapshot)

        result = outbox.send_next()

        self.assertEqual((result.outcome, result.status), ("sent", 200))
        self.assertEqual(self.waiting(), [])

    def test_empty_session_is_not_sent(self):
        outbox = self.outbox()
        outbox.submit(finished_session([]))
        self.assertEqual(self.waiting(), [])
        self.assertIsNone(outbox.send_next())
        self.assertEqual(self.server.requests, [])
        self.assertEqual(status_line(outbox.state())[0], "No tags scanned, nothing sent")

    def test_409_is_kept_for_inspection_and_never_retried(self):
        outbox = self.outbox()
        snapshot = finished_session()
        stored_elsewhere = dict(build_transaction(snapshot, outbox.settings), cashierName="Bea")
        post_transaction(self.server.url + "/api/v1/transactions", sale_bytes(stored_elsewhere), snapshot["session_id"])
        outbox.submit(snapshot)

        result = outbox.send_next()

        self.assertEqual((result.outcome, result.status), ("rejected", 409))
        self.assertEqual(self.waiting(), [])
        [kept] = self.rejected()
        self.assertIn("HTTP 409", kept.with_suffix(".error.txt").read_text("utf-8"))
        self.assertIsNone(outbox.send_next())
        self.assertEqual(len(self.server.requests), 2)
        state = outbox.state()
        self.assertEqual((state.pending, state.rejected), (0, 1))
        self.assertTrue(status_line(state)[0].startswith("Not sent: HTTP 409"))
        self.assertEqual(pending_line(state), ("Waiting to send: 0 · Rejected: 1", "error"))

    def test_400_is_kept_for_inspection_and_never_retried(self):
        outbox = self.outbox(store_code="S" * 121)  # the server allows at most 120 characters
        outbox.submit(finished_session())

        result = outbox.send_next()

        self.assertEqual((result.outcome, result.status), ("rejected", 400))
        self.assertIn("storeCode must be shorter than or equal to 120 characters", result.reason)
        self.assertEqual(len(self.rejected()), 1)
        self.assertIsNone(outbox.send_next())
        self.assertEqual(len(self.server.requests), 1)

    def test_429_and_5xx_keep_the_file_and_resend_the_same_body(self):
        outbox = self.outbox()
        for status in (429, 500, 503):
            with self.subTest(status=status):
                self.server.requests.clear()
                self.server.fail_next(status)
                outbox.submit(finished_session())
                [saved] = self.waiting()
                saved_bytes = saved.read_bytes()

                failed = outbox.send_next()

                self.assertEqual((failed.outcome, failed.status), ("retry", status))
                self.assertEqual(self.waiting(), [saved])
                self.assertEqual(saved.read_bytes(), saved_bytes)
                self.assertEqual(outbox.state().phase, "retry")

                retried = outbox.send_next()

                self.assertEqual((retried.outcome, retried.status), ("sent", 201))
                first, second = self.server.requests
                self.assertEqual(first["raw"], saved_bytes)
                self.assertEqual(second["raw"], saved_bytes)
                self.assertEqual(self.waiting(), [])

    def test_connection_error_keeps_the_file_until_the_server_is_back(self):
        port = free_port()
        outbox = self.outbox(f"http://127.0.0.1:{port}")
        outbox.submit(finished_session())
        [saved] = self.waiting()
        saved_bytes = saved.read_bytes()

        failed = outbox.send_next()

        self.assertEqual((failed.outcome, failed.reason), ("retry", "connection refused"))
        self.assertEqual(self.waiting(), [saved])
        text, tone = status_line(outbox.state())
        self.assertTrue(text.startswith("Saved offline, will retry in "), text)
        self.assertEqual(tone, "warn")
        self.assertEqual(pending_line(outbox.state()), ("Waiting to send: 1", "warn"))

        back = FakeTransactionServer(port=port).start()
        self.addCleanup(back.stop)
        self.assertEqual(outbox.send_next().outcome, "sent")
        [request] = back.requests
        self.assertEqual(request["raw"], saved_bytes)
        self.assertEqual(outbox.state().pending, 0)

    def test_retry_waits_at_least_as_long_as_retry_after(self):
        outbox = self.outbox()
        self.server.fail_next(429, retry_after=30)
        outbox.submit(finished_session())
        outbox.send_next()
        self.assertGreaterEqual(outbox.state().retry_at - time.monotonic(), 29)

    def test_pending_sales_survive_a_restart(self):
        offline = self.outbox(f"http://127.0.0.1:{free_port()}")
        snapshot = finished_session()
        offline.submit(snapshot)
        [saved] = self.waiting()
        saved_bytes = saved.read_bytes()
        offline.stop()

        restarted = self.outbox()

        self.assertEqual(restarted.state().pending, 1)
        self.assertEqual(restarted.send_next().outcome, "sent")
        [request] = self.server.requests
        self.assertEqual(request["raw"], saved_bytes)
        self.assertEqual(request["json"]["clientTransactionId"], snapshot["session_id"])
        self.assertEqual(restarted.state().pending, 0)

    def test_too_many_tags_or_a_bad_epc_are_kept_and_not_sent(self):
        outbox = self.outbox()
        cases = {
            "201 tags": [f"{i + 1:024X}" for i in range(201)],
            "not 24 hex": ["E2001234"],  # a valid but short EPC as far as ScanSession is concerned
        }
        for expected, epcs in cases.items():
            with self.subTest(expected=expected):
                outbox.submit(finished_session(epcs))
                self.assertEqual(self.waiting(), [])
                self.assertIn(expected, status_line(outbox.state())[0])
        self.assertEqual(len(self.rejected()), 2)
        self.assertEqual(outbox.state().rejected, 2)
        self.assertIsNone(outbox.send_next())
        self.assertEqual(self.server.requests, [])

    def test_background_sender_retries_by_itself_with_the_same_id(self):
        outbox = self.outbox()
        outbox.start()
        self.server.fail_next(503)
        outbox.submit(finished_session())

        deadline = time.monotonic() + 5
        while outbox.state().pending and time.monotonic() < deadline:
            time.sleep(0.02)

        self.assertEqual(outbox.state().pending, 0)
        self.assertEqual([r["status"] for r in self.server.requests], [503, 201])
        self.assertEqual(self.server.requests[0]["raw"], self.server.requests[1]["raw"])
        self.assertEqual(outbox.state().phase, "sent")

    def test_missing_settings_record_nothing(self):
        outbox = TransactionOutbox(self.pending, None, "settings.json is missing storeCode.")
        outbox.start()
        self.assertFalse(outbox.ready)
        self.assertEqual(status_line(outbox.state()), ("settings.json is missing storeCode.", "error"))
        outbox.submit(finished_session())
        self.assertEqual(self.waiting(), [])
        self.assertIsNone(outbox.send_next())


class CheckoutFlowTests(unittest.TestCase):
    """The Start/Stop handler both the GTK and Tk widgets call."""

    def test_each_stop_sends_exactly_one_sale_and_start_keeps_pending_ones(self):
        server = FakeTransactionServer().start()
        self.addCleanup(server.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        session = ScanSession()
        listener = TcpDeactivatorListener(session=session)
        listener.set_scanning(False)  # the widgets start idle
        outbox = TransactionOutbox(Path(tmp.name), make_settings(server.url), min_request_gap=0)

        _toggle_scan(session, listener, outbox)  # Start Scanning
        sale_id = session.snapshot()["session_id"]
        self.assertTrue(listener.is_scanning())
        for epc in EPCS + [EPCS[1]]:
            session.observe(epc, source="sdk")
        _toggle_scan(session, listener, outbox)  # Stop
        self.assertFalse(listener.is_scanning())
        session.observe("E200AAAABBBBCCCCDDDDEEEE", source="sdk")  # a read racing the Stop is ignored
        self.assertEqual(session.snapshot()["unique_count"], 3)

        _toggle_scan(session, listener, outbox)  # Start Scanning again: the saved sale must survive
        self.assertNotEqual(session.snapshot()["session_id"], sale_id)
        self.assertEqual(outbox.state().pending, 1)

        self.assertEqual(outbox.send_next().outcome, "sent")
        [request] = server.requests
        self.assertEqual(request["json"]["clientTransactionId"], sale_id)
        self.assertEqual([tag["epc"] for tag in request["json"]["tags"]], EPCS)


class StatusLineTests(unittest.TestCase):
    def test_texts_for_each_phase(self):
        self.assertEqual(status_line(OutboxState()), ("", "muted"))
        self.assertEqual(status_line(OutboxState(phase="sending", item_count=1)), ("Sending 1 item...", "busy"))
        self.assertEqual(status_line(OutboxState(phase="sent", item_count=3)), ("Sent 3 items", "ok"))
        self.assertEqual(
            status_line(OutboxState(phase="retry", message="HTTP 503", retry_at=112.2), now=100.0),
            ("Saved offline, will retry in 13s (HTTP 503)", "warn"),
        )
        self.assertEqual(status_line(OutboxState(phase="rejected", message="x")), ("Not sent: x", "error"))
        self.assertEqual(pending_line(OutboxState(pending=0)), ("Waiting to send: 0", "muted"))
        self.assertEqual(pending_line(OutboxState(pending=2)), ("Waiting to send: 2", "warn"))


if __name__ == "__main__":
    unittest.main()
