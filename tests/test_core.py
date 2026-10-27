import ctypes
import socket
import tempfile
import time
import unittest

from hax7700_widget.core import (
    EpcIdList,
    EpcIdSt,
    PendingHax7700Decoder,
    ScanSession,
    TcpDeactivatorListener,
    format_epc_bytes,
    normalize_epc,
)


class StandaloneWidgetTests(unittest.TestCase):
    def test_abi_struct_sizes_match_hax_7k_adapt_h(self):
        self.assertEqual(ctypes.sizeof(EpcIdSt), 18)
        self.assertEqual(ctypes.sizeof(EpcIdList), 612)

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
