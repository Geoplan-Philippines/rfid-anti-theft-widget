import ctypes
import json
import socket
import tempfile
import time
import unittest

from hax7700_widget.core import (
    DEVICE_OK,
    DeviceAlarmConfig,
    EpcIdList,
    EpcIdSt,
    ItemDatabase,
    PendingHax7700Decoder,
    RfidGateController,
    ScanSession,
    TcpDeactivatorListener,
    format_epc_bytes,
    normalize_epc,
    parse_epc_json_payload,
)


class FakeGateCodec:
    """Deterministic fake for HaxGatePacketCodec to test full TCP Gate protocol flow."""

    sdk_loaded = True

    def pack_server_control(self, value: int = 1) -> tuple[int, bytes]:
        return DEVICE_OK, f"SC_REQ:{value}".encode("ascii")

    def unpack_server_control(self, reply: bytes) -> int:
        return DEVICE_OK if reply == b"SC_ACK" else 10

    def pack_device_alarm(
        self,
        channel_1: int = 1,
        channel_2: int = 1,
        channel_3: int = 1,
        channel_4: int = 1,
    ) -> tuple[int, bytes]:
        return DEVICE_OK, f"ALARM_REQ:{channel_1}{channel_2}{channel_3}{channel_4}".encode("ascii")

    def unpack_device_alarm(self, reply: bytes) -> int:
        return DEVICE_OK if reply == b"ALARM_ACK" else 10

    def unpack_epc_id(self, data: bytes) -> tuple[int, list[dict]]:
        return DEVICE_OK, parse_epc_json_payload(data)


class StandaloneWidgetTests(unittest.TestCase):
    def test_abi_struct_sizes_match_sdk_headers(self):
        self.assertEqual(ctypes.sizeof(EpcIdSt), 18)
        self.assertEqual(ctypes.sizeof(EpcIdList), 612)
        self.assertEqual(ctypes.sizeof(DeviceAlarmConfig), 4)

    def test_format_and_normalize_epc(self):
        self.assertIsNone(format_epc_bytes(b"\x00" * 12))
        self.assertEqual(
            format_epc_bytes(bytes.fromhex("3034257BF400B78000040001")),
            "3034257BF400B78000040001",
        )
        self.assertEqual(
            normalize_epc("3034-257b-f400-b780-0004-0001"),
            "3034257BF400B78000040001",
        )
        self.assertIsNone(normalize_epc("000000000000000000000000"))

    def test_parse_epc_json_payload(self):
        raw = b'[{"ant_id":1,"epc_id":"e2000017221101441890abcd"}]\x00'
        parsed = parse_epc_json_payload(raw)
        self.assertEqual(parsed, [{"ant_id": 1, "epc_id": "E2000017221101441890ABCD"}])

    def test_scan_session_counts_unique_and_ignores_repeats(self):
        session = ScanSession()
        s1 = session.observe("3034257BF400B78000040001", "scanner")
        self.assertTrue(s1["is_new"])
        self.assertEqual(s1["unique_count"], 1)
        self.assertEqual(s1["repeat_reads"], 0)

        s2 = session.observe("3034257bf400b78000040001", "scanner")
        self.assertFalse(s2["is_new"])
        self.assertEqual(s2["unique_count"], 1)
        self.assertEqual(s2["repeat_reads"], 1)
        self.assertEqual(s2["total_reads"], 2)

        session.reset()
        self.assertEqual(session.snapshot()["unique_count"], 0)

    def test_item_database_and_gate_alarm_decisions(self):
        db = ItemDatabase(":memory:")
        try:
            epc_unsold = "E20000172211014418900001"
            epc_sold = "E20000172211014418900002"
            epc_unknown = "E20000172211014418909999"

            item1 = db.upsert_item(epc_unsold, sold=False, name="Denim Jacket")
            self.assertFalse(item1["sold"])

            item2 = db.upsert_item(epc_sold, sold=True, name="Sneakers")
            self.assertTrue(item2["sold"])

            # 1) Unsold item -> MUST ALARM
            d_unsold = db.evaluate_gate_epcs([epc_unsold])
            self.assertTrue(d_unsold.should_alarm)
            self.assertEqual(d_unsold.action, "ALARM")
            self.assertEqual(d_unsold.unsold_epcs, [epc_unsold])

            # 2) Sold item -> MUST NOT ALARM (customer bought it)
            d_sold = db.evaluate_gate_epcs([epc_sold])
            self.assertFalse(d_sold.should_alarm)
            self.assertEqual(d_sold.action, "PASS")
            self.assertEqual(d_sold.sold_epcs, [epc_sold])

            # 3) Unknown item -> MUST NOT ALARM (ignored)
            d_unknown = db.evaluate_gate_epcs([epc_unknown])
            self.assertFalse(d_unknown.should_alarm)
            self.assertEqual(d_unknown.action, "IGNORE")
            self.assertEqual(d_unknown.unknown_epcs, [epc_unknown])

            # 4) Toggle unsold item -> sold=True -> now PASSES without alarm
            toggled = db.toggle_sold(epc_unsold)
            self.assertTrue(toggled["sold"])
            d_after_checkout = db.evaluate_gate_epcs([epc_unsold])
            self.assertFalse(d_after_checkout.should_alarm)
            self.assertEqual(d_after_checkout.action, "PASS")
        finally:
            db.close()

    def test_pad_scan_modes_register_vs_checkout(self):
        db = ItemDatabase(":memory:")
        try:
            session = ScanSession(item_db=db, pad_mode="register_unsold")
            epc = "3034257BF400B78000040001"

            # Scan in register_unsold mode -> sold is False
            session.observe(epc, source="sdk")
            self.assertFalse(db.get_item(epc)["sold"])

            # Switch Pad to checkout_sold mode -> scanning marks sold=True
            session.set_pad_mode("checkout_sold")
            session.observe(epc, source="sdk")
            self.assertTrue(db.get_item(epc)["sold"])
        finally:
            db.close()

    def test_rfid_gate_controller_tcp_handshake_and_conditional_alarm(self):
        db = ItemDatabase(":memory:")
        epc_unsold = "E20000172211014418900001"
        epc_sold = "E20000172211014418900002"
        db.upsert_item(epc_unsold, sold=False, name="Unpaid Bag")
        db.upsert_item(epc_sold, sold=True, name="Paid Shirt")

        with tempfile.TemporaryDirectory() as tmp:
            gate = RfidGateController(item_db=db, capture_dir=tmp, codec=FakeGateCodec())
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
            probe.close()

            gate.start(host="127.0.0.1", port=port)
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=2.0) as client:
                    client.settimeout(2.0)
                    # Step 1: Receive ServerControl packet and reply SC_ACK
                    sc_req = client.recv(256)
                    self.assertEqual(sc_req, b"SC_REQ:1")
                    client.sendall(b"SC_ACK")

                    for _ in range(30):
                        if gate.state().server_control_active:
                            break
                        time.sleep(0.02)
                    self.assertTrue(gate.state().server_control_active)

                    # Step 2: Gate reports a SOLD item -> server must NOT send ALARM_REQ
                    sold_pkt = json.dumps([{"ant_id": 1, "epc_id": epc_sold}]).encode("utf-8")
                    client.sendall(sold_pkt)
                    for _ in range(30):
                        if gate.state().pass_count == 1:
                            break
                        time.sleep(0.02)
                    self.assertEqual(gate.state().pass_count, 1)
                    self.assertEqual(gate.state().alarm_count, 0)

                    # Step 3: Gate reports an UNSOLD item -> server MUST send ALARM_REQ:1111
                    unsold_pkt = json.dumps([{"ant_id": 2, "epc_id": epc_unsold}]).encode("utf-8")
                    client.sendall(unsold_pkt)
                    alarm_req = client.recv(256)
                    self.assertEqual(alarm_req, b"ALARM_REQ:1111")
                    client.sendall(b"ALARM_ACK")

                    for _ in range(30):
                        if gate.state().alarm_count == 1:
                            break
                        time.sleep(0.02)
                    self.assertEqual(gate.state().alarm_count, 1)
                    self.assertEqual(gate.state().last_action, "ALARM")
            finally:
                gate.stop()
                db.close()

    def test_listener_scanning_toggle(self):
        session = ScanSession()
        listener = TcpDeactivatorListener(session=session)
        self.assertTrue(listener.is_scanning())
        listener.set_scanning(False)
        self.assertFalse(listener.is_scanning())
        self.assertFalse(listener.state().scanning)
        listener.set_scanning(True)
        self.assertTrue(listener.is_scanning())
        self.assertTrue(listener.state().scanning)

    def test_tcp_listener_accepts_hax7700_connection(self):
        session = ScanSession()
        with tempfile.TemporaryDirectory() as tmp:
            listener = TcpDeactivatorListener(session=session, capture_dir=tmp)
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
            probe.close()

            listener.start_tcp(mode="listen", host="127.0.0.1", port=port, peer_filter="127.0.0.1")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=2.0) as client:
                    client.sendall(b"\x55\xaa\x01\x02")
                    for _ in range(30):
                        if listener.state().bytes_received >= 4:
                            break
                        time.sleep(0.05)
                    self.assertEqual(listener.state().bytes_received, 4)
                    self.assertTrue(listener.state().peer.startswith("127.0.0.1:"))
            finally:
                listener.stop()

    def test_pending_decoder_never_fabricates_epcs(self):
        decoder = PendingHax7700Decoder()
        self.assertFalse(decoder.ready)
        self.assertEqual(decoder.feed(b"\x11\x22\x33"), [])


if __name__ == "__main__":
    unittest.main()
