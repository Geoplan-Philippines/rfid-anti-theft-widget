"""Core EPC session counter, TCP listener/client, and optional Windows x86 card_7k.dll SDK driver."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import socket
import threading
import time
import uuid

EPC_BYTES = 12


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def format_epc_bytes(buffer: bytes | bytearray | memoryview) -> str | None:
    """Format a 12-byte EPC buffer as 24 uppercase hex characters, rejecting all-zero buffers."""
    if not isinstance(buffer, (bytes, bytearray, memoryview)) or len(buffer) < EPC_BYTES:
        return None
    raw = bytes(buffer[:EPC_BYTES])
    if not any(raw):
        return None
    return raw.hex().upper()


def normalize_epc(raw: str | None) -> str | None:
    """Normalize hex EPC text (2..24 hex chars, even length, non-zero)."""
    if not isinstance(raw, str):
        return None
    cleaned = raw.strip().replace(" ", "").replace("-", "").replace(":", "").upper()
    if not cleaned or len(cleaned) > 24 or len(cleaned) % 2 != 0:
        return None
    try:
        data = bytes.fromhex(cleaned)
    except ValueError:
        return None
    if not any(data):
        return None
    return cleaned


def local_ipv4_addresses() -> list[str]:
    """Return active non-loopback IPv4 addresses, prioritizing 169.254.x.x link-local."""
    found: list[str] = []
    seen: set[str] = set()
    for target in ("169.254.68.93", "10.255.255.255", "192.168.1.1"):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect((target, 80))
            ip = sock.getsockname()[0]
            if ip and not ip.startswith("127.") and ip not in seen:
                seen.add(ip)
                found.append(ip)
        except OSError:
            pass
        finally:
            sock.close()
    return sorted(found, key=lambda ip: (0 if ip.startswith("169.254.") else 1, ip))


class ScanSession:
    """Counts each unique EPC once per session and ignores repeat reads of the same tag."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._seen: set[str] = set()
        self._items: list[dict] = []
        self._total_reads = 0
        self._last_epc: str | None = None
        self._last_source = "idle"
        self._started_at = utc_now()

    def observe(self, epc: str | None = None, source: str = "scanner") -> dict:
        if epc is None and source == "demo":
            normalized = "E200" + uuid.uuid4().hex[:20].upper()
        else:
            normalized = normalize_epc(epc)
            if not normalized:
                raise ValueError("EPC must be 2–24 non-zero hexadecimal characters.")
        with self._lock:
            self._total_reads += 1
            self._last_epc = normalized
            self._last_source = source
            is_new = normalized not in self._seen
            if is_new:
                self._seen.add(normalized)
                self._items.append(
                    {
                        "epc": normalized,
                        "first_seen_at": utc_now(),
                        "source": source,
                    }
                )
            snap = self.snapshot()
            snap["is_new"] = is_new
            return snap

    def reset(self) -> dict:
        with self._lock:
            self._seen.clear()
            self._items.clear()
            self._total_reads = 0
            self._last_epc = None
            self._last_source = "idle"
            self._started_at = utc_now()
            return self.snapshot()

    def snapshot(self) -> dict:
        with self._lock:
            unique = len(self._items)
            return {
                "unique_count": unique,
                "total_reads": self._total_reads,
                "repeat_reads": self._total_reads - unique,
                "last_epc": self._last_epc,
                "last_source": self._last_source,
                "started_at": self._started_at,
                "items": list(reversed(self._items)),
            }


class PendingHax7700Decoder:
    """Placeholder decoder until HAX7700 / RFID7700 raw wire framing is supplied.

    Never guesses or fabricates EPCs from unverified TCP/serial bytes.
    """

    ready = False

    def reset(self) -> None:
        pass

    def feed(self, _chunk: bytes) -> list[str]:
        return []


# --- Native Windows x86 card_7k.dll ABI definitions (from hax_7k_adapt.h) ---


class EpcIdSt(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("len", ctypes.c_ushort),
        ("pc", ctypes.c_ushort),
        ("id", ctypes.c_ubyte * 12),
        ("crc", ctypes.c_ushort),
    ]


class EpcIdList(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("sn", ctypes.c_ubyte * 32),
        ("size", ctypes.c_int),
        ("epcs", EpcIdSt * 32),
    ]


PORT_CONNECTING_CB = ctypes.CFUNCTYPE(None, ctypes.c_char_p)
PORT_CLOSING_CB = ctypes.CFUNCTYPE(None, ctypes.c_char_p)
OUTPUT_TAGS_CB = ctypes.CFUNCTYPE(None, ctypes.c_char_p, EpcIdList)


class IAsynchronousMessage(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("port_connecting", PORT_CONNECTING_CB),
        ("port_closing", PORT_CLOSING_CB),
        ("output_tags", OUTPUT_TAGS_CB),
    ]


@dataclass
class ListenerState:
    running: bool = False
    scanning: bool = True
    mode: str = "listen"
    status_text: str = "Stopped"
    peer: str = ""
    bytes_received: int = 0
    connections: int = 0
    sdk_active: bool = False
    capture_file: str = ""
    last_error: str = ""


class TcpDeactivatorListener:
    """Standalone background listener for the HAX7700 Deactivator.

    - On 32-bit Windows when `card_7k.dll` is present in `sdk_dir`, can optionally
      use `card_7k.dll` (`open_tcp_server` + `start_auto_read(200)`) to poll the
      HAX7700 and decode 12-byte EPCs via `output_tags`.
    - Otherwise runs a direct Python TCP server on `0.0.0.0:9090` (where the HAX7700's
      internal USR-TCP232-E2 at `169.254.68.93` connects in automatically) or connects
      as a TCP client to `169.254.68.93:26`.
    """

    def __init__(
        self,
        session: ScanSession,
        capture_dir: str | Path = "captures",
        decoder: PendingHax7700Decoder | None = None,
    ) -> None:
        self.session = session
        self.capture_dir = Path(capture_dir)
        self.decoder = decoder or PendingHax7700Decoder()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sockets: list[socket.socket] = []
        self._scanning = True
        self._state = ListenerState()
        # Keep ctypes callbacks rooted for the lifetime of any SDK session
        self._sdk_dll = None
        self._sdk_callbacks: IAsynchronousMessage | None = None

    def set_scanning(self, enabled: bool) -> None:
        """Enable or pause tag counting without dropping the underlying TCP/SDK connection."""
        with self._lock:
            self._scanning = bool(enabled)
            self._state.scanning = self._scanning

    def is_scanning(self) -> bool:
        with self._lock:
            return self._scanning

    def state(self) -> ListenerState:
        with self._lock:
            return ListenerState(**self._state.__dict__)

    def start_tcp(
        self,
        mode: str = "listen",
        host: str = "0.0.0.0",
        port: int = 9090,
        peer_filter: str = "169.254.68.93",
    ) -> None:
        self.stop()
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        capture_path = self.capture_dir / f"hax7700-{stamp}.jsonl"
        self._stop = threading.Event()
        with self._lock:
            self._state = ListenerState(
                running=True,
                scanning=self._scanning,
                mode=mode,
                status_text=(
                    f"Listening on {host}:{port} for HAX7700"
                    if mode == "listen"
                    else f"Connecting to {host}:{port}…"
                ),
                capture_file=str(capture_path),
            )
        self._thread = threading.Thread(
            target=self._run_tcp,
            args=(mode, host, port, peer_filter.strip(), capture_path, self._stop),
            daemon=True,
        )
        self._thread.start()

    def _run_tcp(
        self,
        mode: str,
        host: str,
        port: int,
        peer_filter: str,
        capture_path: Path,
        stop: threading.Event,
    ) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        with self._lock:
            self._sockets = [sock]
        try:
            with capture_path.open("a", encoding="utf-8") as log_file:
                if mode == "listen":
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    sock.bind((host, port))
                    sock.listen(4)
                    sock.settimeout(0.3)
                    while not stop.is_set():
                        try:
                            peer, addr = sock.accept()
                        except socket.timeout:
                            continue
                        except OSError:
                            break
                        peer_ip, peer_port = addr[0], addr[1]
                        peer_label = f"{peer_ip}:{peer_port}"
                        if peer_filter and peer_ip != peer_filter and peer_ip != "127.0.0.1":
                            peer.close()
                            continue
                        with self._lock:
                            self._sockets.append(peer)
                            self._state.connections += 1
                            self._state.peer = peer_label
                            self._state.status_text = f"HAX7700 connected ({peer_label})"
                        log_file.write(
                            json.dumps({"at": utc_now(), "event": "connected", "peer": peer_label}) + "\n"
                        )
                        log_file.flush()
                        self._read_stream(peer, peer_label, log_file, stop)
                        with self._lock:
                            if not stop.is_set():
                                self._state.peer = ""
                                self._state.status_text = f"Listening on {host}:{port} (peer closed)"
                else:
                    sock.settimeout(3.0)
                    sock.connect((host, port))
                    peer_label = f"{host}:{port}"
                    with self._lock:
                        self._state.connections = 1
                        self._state.peer = peer_label
                        self._state.status_text = f"Connected to {peer_label}"
                    log_file.write(
                        json.dumps({"at": utc_now(), "event": "connected", "peer": peer_label}) + "\n"
                    )
                    log_file.flush()
                    self._read_stream(sock, peer_label, log_file, stop)
        except Exception as err:
            if not stop.is_set():
                with self._lock:
                    self._state.last_error = str(err)
                    self._state.status_text = f"Error: {err}"
        finally:
            with self._lock:
                for s in self._sockets:
                    try:
                        s.close()
                    except OSError:
                        pass
                self._sockets.clear()
                self._state.running = False
                if stop.is_set():
                    self._state.status_text = "Stopped"

    def _read_stream(
        self,
        stream: socket.socket,
        peer_label: str,
        log_file,
        stop: threading.Event,
    ) -> None:
        stream.settimeout(0.3)
        while not stop.is_set():
            try:
                chunk = stream.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                log_file.write(
                    json.dumps({"at": utc_now(), "event": "closed", "peer": peer_label}) + "\n"
                )
                log_file.flush()
                break
            with self._lock:
                self._state.bytes_received += len(chunk)
            log_file.write(
                json.dumps(
                    {
                        "at": utc_now(),
                        "event": "rx",
                        "peer": peer_label,
                        "bytes": len(chunk),
                        "hex": chunk.hex(" ").upper(),
                    }
                )
                + "\n"
            )
            log_file.flush()
            if self.is_scanning():
                for epc in self.decoder.feed(chunk):
                    self.session.observe(epc, source="lan")
        try:
            stream.close()
        except OSError:
            pass

    def start_windows_sdk(self, sdk_dir: str | Path, host: str = "0.0.0.0", port: int = 9090, poll_ms: int = 50) -> None:
        """Start the 32-bit Windows card_7k.dll listener + fast synchronous EPC poll loop."""
        if platform.system() != "Windows" or ctypes.sizeof(ctypes.c_void_p) != 4:
            raise RuntimeError("card_7k.dll requires 32-bit (x86) Python on Windows.")
        self.stop()
        sdk_path = Path(sdk_dir).resolve()
        dll_file = sdk_path / "card_7k.dll"
        if not dll_file.is_file():
            raise FileNotFoundError(f"card_7k.dll not found in {sdk_path}")

        # Tune common.dll CConfigMgr INI parameters to minimize inter-command network wait times
        fast_ini = (
            "[config]\n"
            "net_send_data_wait_time=5\n"
            "net_time_out=120\n"
            "time_out=80\n"
            "com_send_data_wait_time=5\n"
        )
        for ini_dir in (sdk_path, Path(__import__("sys").executable).resolve().parent):
            try:
                (ini_dir / "config.ini").write_text(fast_ini, encoding="ascii")
            except OSError:
                pass

        if hasattr(os := __import__("os"), "add_dll_directory"):
            os.add_dll_directory(str(sdk_path))
        dll = ctypes.CDLL(str(dll_file))

        dll.open_tcp_server.argtypes = [ctypes.c_char_p, ctypes.c_uint, IAsynchronousMessage]
        dll.open_tcp_server.restype = ctypes.c_int
        dll.close_tcp_server.argtypes = []
        dll.close_tcp_server.restype = None
        dll.read_epc_id.argtypes = [ctypes.c_char_p, ctypes.POINTER(EpcIdList)]
        dll.read_epc_id.restype = ctypes.c_int
        dll.start_auto_read.argtypes = [ctypes.c_int]
        dll.start_auto_read.restype = None
        dll.stop_auto_read.argtypes = []
        dll.stop_auto_read.restype = None

        def _ingest_tag_list(tag_list: EpcIdList) -> None:
            if not self.is_scanning():
                return
            count = max(0, min(32, int(tag_list.size)))
            for idx in range(count):
                entry = tag_list.epcs[idx]
                epc = format_epc_bytes(bytes(entry.id))
                if epc:
                    self.session.observe(epc, source="sdk")

        @PORT_CONNECTING_CB
        def on_connecting(conn_id: bytes | None) -> None:
            peer = (conn_id or b"").decode("latin1", errors="replace")
            with self._lock:
                self._state.connections += 1
                self._state.peer = peer
                self._state.status_text = f"SDK connected ({peer})"

        @PORT_CLOSING_CB
        def on_closing(conn_id: bytes | None) -> None:
            peer = (conn_id or b"").decode("latin1", errors="replace")
            with self._lock:
                self._state.peer = ""
                self._state.status_text = f"SDK peer closed ({peer})"

        @OUTPUT_TAGS_CB
        def on_tags(_conn_id: bytes | None, tag_list: EpcIdList) -> None:
            _ingest_tag_list(tag_list)

        callbacks = IAsynchronousMessage(on_connecting, on_closing, on_tags)
        rc = dll.open_tcp_server(host.encode("ascii"), int(port), callbacks)
        if rc != 0:
            raise RuntimeError(f"card_7k.dll open_tcp_server failed with hax_error_code={rc}")

        stop_event = threading.Event()

        def _fast_poll_worker() -> None:
            tag_list = EpcIdList()
            while not stop_event.is_set():
                with self._lock:
                    peer = self._state.peer
                if not peer:
                    time.sleep(0.02)
                    continue
                tag_list.size = 0
                try:
                    dll.read_epc_id(peer.encode("latin1"), ctypes.byref(tag_list))
                    if tag_list.size > 0:
                        _ingest_tag_list(tag_list)
                except Exception:
                    time.sleep(0.05)
                    continue
                time.sleep(0.005)

        poll_thread = threading.Thread(target=_fast_poll_worker, daemon=True)
        with self._lock:
            self._stop = stop_event
            self._thread = poll_thread
            self._sdk_dll = dll
            self._sdk_callbacks = callbacks
            self._state = ListenerState(
                running=True,
                scanning=self._scanning,
                mode="sdk",
                sdk_active=True,
                status_text=f"SDK fast-polling on {host}:{port}",
            )
        poll_thread.start()

    def stop(self) -> None:
        with self._lock:
            self._stop.set()
            for s in list(self._sockets):
                try:
                    s.close()
                except OSError:
                    pass
            sdk = self._sdk_dll
            self._sdk_dll = None
            thread = self._thread
            self._thread = None
        if sdk is not None:
            try:
                sdk.stop_auto_read()
            finally:
                sdk.close_tcp_server()
            with self._lock:
                self._sdk_callbacks = None
                self._state.running = False
                self._state.sdk_active = False
                self._state.status_text = "Stopped"
        if thread and thread.is_alive():
            thread.join(timeout=1.5)
