"""Core EPC session counter, SQLite item store (sold: true/false), RS232/TCP HAX7700 Pad listener, and HAX7000 RFID Gate controller (SDK 2.1.2.0)."""

from __future__ import annotations

from collections import deque
import ctypes
from dataclasses import dataclass, field
from datetime import datetime, timezone
import glob
import json
import os
from pathlib import Path
import platform
import select
import socket
import sqlite3
import threading
import time
import uuid

EPC_BYTES = 12

# --- HAX-7000 SDK 2.1.2.0 Error Codes (from hax_7k_sdk.h) ---
DEVICE_OK = 0
DEVICE_ERR_INVALID_PARAM = 1
DEVICE_ERR_BUFFER_TOO_SMALL = 2
DEVICE_ERR_PACK_FAILED = 3
DEVICE_ERR_UNPACK_FAILED = 4
DEVICE_ERR_FLAG_FAIL = 10
DEVICE_ERR_FLAG_ABNORMAL = 12
DEVICE_ERR_FLAG_DUPLICATE = 13
DEVICE_ERR_FLAG_UNKNOWN = 14
DEVICE_ERR_NETWORK = 20

PACKET_BUF_SIZE = 256
EPC_BUF_SIZE = 10240
JSON_BUF_SIZE = 10240
REPLY_TIMEOUT_SEC = 5.0


def device_error_text(code: int) -> str:
    """Return human-readable description for a hax_7k_sdk.h device_error_code."""
    mapping = {
        DEVICE_OK: "ok",
        DEVICE_ERR_INVALID_PARAM: "invalid param",
        DEVICE_ERR_BUFFER_TOO_SMALL: "buffer too small",
        DEVICE_ERR_PACK_FAILED: "pack failed",
        DEVICE_ERR_UNPACK_FAILED: "unpack failed (header/length/crc)",
        DEVICE_ERR_FLAG_FAIL: "device flag=0 (fail)",
        DEVICE_ERR_FLAG_ABNORMAL: "device flag=2 (abnormal)",
        DEVICE_ERR_FLAG_DUPLICATE: "device flag=3 (duplicate)",
        DEVICE_ERR_FLAG_UNKNOWN: "device flag unknown",
        DEVICE_ERR_NETWORK: "epc verify: server unreachable",
    }
    return mapping.get(code, f"unknown ({code})")


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


def parse_epc_json_payload(raw_json: str | bytes) -> list[dict]:
    """Parse JSON returned by Device_UnPackEpcId, e.g. [{"ant_id":1,"epc_id":"E2000017..."}]."""
    if isinstance(raw_json, bytes):
        text = raw_json.split(b"\x00", 1)[0].decode("utf-8", errors="replace").strip()
    else:
        text = str(raw_json).split("\x00", 1)[0].strip()
    if not text:
        return []
    parsed = json.loads(text)
    if not isinstance(parsed, list):
        return []
    results: list[dict] = []
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        epc = normalize_epc(str(entry.get("epc_id") or entry.get("epc") or ""))
        if not epc:
            continue
        try:
            ant_id = int(entry.get("ant_id", 1))
        except (TypeError, ValueError):
            ant_id = 1
        results.append({"ant_id": ant_id, "epc_id": epc})
    return results


def detect_serial_ports() -> list[str]:
    """Detect available RS232 serial ports on Linux (/dev/ttyUSB*, /dev/ttyACM*) or Windows (COM1..COM32)."""
    if platform.system() == "Windows":
        ports: list[str] = []
        kernel32 = ctypes.windll.kernel32
        for i in range(1, 33):
            name = f"COM{i}"
            target_buf = ctypes.create_unicode_buffer(256)
            if kernel32.QueryDosDeviceW(name, target_buf, 256) != 0:
                ports.append(name)
        return ports
    found = sorted(glob.glob("/dev/ttyUSB*")) + sorted(glob.glob("/dev/ttyACM*"))
    return found


class RawSerialPort:
    """Zero-dependency cross-platform RS232 serial port wrapper (115200 8N1) for Linux and Windows."""

    def __init__(self, port: str, baudrate: int = 115200) -> None:
        self.port = port
        self.baudrate = baudrate
        self._fd: int | None = None
        self._handle: int | None = None
        self._open()

    def _open(self) -> None:
        if platform.system() == "Windows":
            self._open_windows()
        else:
            self._open_posix()

    def _open_posix(self) -> None:
        import termios

        fd = os.open(self.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            attrs = termios.tcgetattr(fd)
            baud_map = {
                9600: termios.B9600,
                19200: termios.B19200,
                38400: termios.B38400,
                57600: termios.B57600,
                115200: termios.B115200,
            }
            bconst = baud_map.get(self.baudrate, termios.B115200)
            attrs[0] = 0  # iflag
            attrs[1] = 0  # oflag
            attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL  # cflag: 8N1
            attrs[3] = 0  # lflag (raw)
            attrs[4] = bconst  # ispeed
            attrs[5] = bconst  # ospeed
            attrs[6][termios.VMIN] = 0
            attrs[6][termios.VTIME] = 0
            termios.tcsetattr(fd, termios.TCSANOW, attrs)
            termios.tcflush(fd, termios.TCIOFLUSH)
            self._fd = fd
        except Exception:
            os.close(fd)
            raise

    def _open_windows(self) -> None:
        kernel32 = ctypes.windll.kernel32
        GENERIC_READ = 0x80000000
        GENERIC_WRITE = 0x40000000
        OPEN_EXISTING = 3
        INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

        device_path = self.port if self.port.startswith("\\\\.\\") else f"\\\\.\\{self.port}"
        handle = kernel32.CreateFileW(
            device_path,
            GENERIC_READ | GENERIC_WRITE,
            0,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
        if handle == INVALID_HANDLE_VALUE or handle == 0:
            err = kernel32.GetLastError()
            raise OSError(f"Cannot open serial port {self.port} (WinError {err})")

        class DCB(ctypes.Structure):
            _fields_ = [
                ("DCBlength", ctypes.c_uint32),
                ("BaudRate", ctypes.c_uint32),
                ("fFlags", ctypes.c_uint32),
                ("wReserved", ctypes.c_uint16),
                ("XonLim", ctypes.c_uint16),
                ("XoffLim", ctypes.c_uint16),
                ("ByteSize", ctypes.c_ubyte),
                ("Parity", ctypes.c_ubyte),
                ("StopBits", ctypes.c_ubyte),
                ("XonChar", ctypes.c_char),
                ("XoffChar", ctypes.c_char),
                ("ErrorChar", ctypes.c_char),
                ("EofChar", ctypes.c_char),
                ("EvtChar", ctypes.c_char),
                ("wReserved1", ctypes.c_uint16),
            ]

        dcb = DCB()
        dcb.DCBlength = ctypes.sizeof(DCB)
        if kernel32.GetCommState(handle, ctypes.byref(dcb)) == 0:
            kernel32.CloseHandle(handle)
            raise OSError(f"GetCommState failed on {self.port}")
        dcb.BaudRate = self.baudrate
        dcb.fFlags = 0x0001  # fBinary = 1
        dcb.ByteSize = 8
        dcb.Parity = 0  # NOPARITY
        dcb.StopBits = 0  # ONESTOPBIT
        if kernel32.SetCommState(handle, ctypes.byref(dcb)) == 0:
            kernel32.CloseHandle(handle)
            raise OSError(f"SetCommState failed on {self.port}")
        kernel32.PurgeComm(handle, 0x000F)
        self._handle = handle

    def send_all(self, data: bytes) -> bool:
        if not data:
            return True
        if platform.system() == "Windows":
            if self._handle is None:
                return False
            kernel32 = ctypes.windll.kernel32
            written = ctypes.c_uint32(0)
            ok = kernel32.WriteFile(self._handle, data, len(data), ctypes.byref(written), None)
            return bool(ok and written.value == len(data))
        if self._fd is None:
            return False
        total = 0
        while total < len(data):
            _, wlist, _ = select.select([], [self._fd], [], 2.0)
            if not wlist:
                return False
            n = os.write(self._fd, data[total:])
            if n <= 0:
                return False
            total += n
        return True

    def recv_once(self, buf_size: int, timeout_sec: float = 0.3) -> bytes:
        """Read one serial frame/packet; coalesces bytes arriving within 35ms after first byte."""
        if platform.system() == "Windows":
            if self._handle is None:
                raise OSError("Serial port closed")
            kernel32 = ctypes.windll.kernel32

            class COMMTIMEOUTS(ctypes.Structure):
                _fields_ = [
                    ("ReadIntervalTimeout", ctypes.c_uint32),
                    ("ReadTotalTimeoutMultiplier", ctypes.c_uint32),
                    ("ReadTotalTimeoutConstant", ctypes.c_uint32),
                    ("WriteTotalTimeoutMultiplier", ctypes.c_uint32),
                    ("WriteTotalTimeoutConstant", ctypes.c_uint32),
                ]

            ms = max(50, int(timeout_sec * 1000))
            timeouts = COMMTIMEOUTS(35, 0, ms, 0, 2000)
            kernel32.SetCommTimeouts(self._handle, ctypes.byref(timeouts))
            buf = ctypes.create_string_buffer(buf_size)
            read_bytes = ctypes.c_uint32(0)
            ok = kernel32.ReadFile(self._handle, buf, buf_size, ctypes.byref(read_bytes), None)
            if not ok:
                raise OSError("ReadFile failed on serial port")
            if read_bytes.value == 0:
                raise socket.timeout("Serial read timeout")
            return buf.raw[: read_bytes.value]

        if self._fd is None:
            raise OSError("Serial port closed")
        rlist, _, _ = select.select([self._fd], [], [], timeout_sec)
        if not rlist:
            raise socket.timeout("Serial read timeout")
        chunks: list[bytes] = []
        total = 0
        while total < buf_size:
            try:
                part = os.read(self._fd, buf_size - total)
            except BlockingIOError:
                part = b""
            if part:
                chunks.append(part)
                total += len(part)
            r_more, _, _ = select.select([self._fd], [], [], 0.035)
            if not r_more:
                break
        if not chunks:
            raise socket.timeout("Serial read empty")
        return b"".join(chunks)

    def close(self) -> None:
        if platform.system() == "Windows":
            if self._handle is not None:
                try:
                    ctypes.windll.kernel32.CloseHandle(self._handle)
                except Exception:
                    pass
                self._handle = None
        else:
            if self._fd is not None:
                try:
                    os.close(self._fd)
                except OSError:
                    pass
                self._fd = None


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


@dataclass
class GateDecision:
    """Result of checking gate-scanned EPCs against the SQLite items table."""

    should_alarm: bool
    action: str  # "ALARM", "PASS", or "IGNORE"
    unsold_epcs: list[str] = field(default_factory=list)
    sold_epcs: list[str] = field(default_factory=list)
    unknown_epcs: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass
class GateEvent:
    """Single RFID gate detection + alarm decision record."""

    at: str
    epcs: list[str]
    antennas: list[int]
    should_alarm: bool
    alarm_sent: bool
    alarm_ack: bool
    action: str
    unsold_epcs: list[str]
    sold_epcs: list[str]
    unknown_epcs: list[str]
    summary: str


class ItemDatabase:
    """Thread-safe SQLite store for RFID items (`epc`, `name`, `sold` True/False, `updated_at`).

    Gate decision rule:
    - `sold == False` (0) in table -> Gate WILL ALARM (`Device_PackDeviceAlarm`).
    - `sold == True` (1) in table  -> Customer bought the item; Gate WILL NOT ALARM (`PASS`).
    - Not in table (`unknown`)     -> Ignored; Gate WILL NOT ALARM (`IGNORE`).
    """

    def __init__(self, db_path: str | Path = "items.db") -> None:
        self.db_path = str(db_path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS items (
                    epc TEXT PRIMARY KEY,
                    name TEXT NOT NULL DEFAULT '',
                    sold INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.commit()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        sold_bool = bool(row["sold"])
        return {
            "epc": row["epc"],
            "name": row["name"],
            "sold": sold_bool,
            "gate_action": "NO ALARM (SOLD)" if sold_bool else "ALARM (UNSOLD)",
            "updated_at": row["updated_at"],
        }

    def upsert_item(self, epc: str, sold: bool = False, name: str | None = None) -> dict:
        """Insert or update an item's sold status (and optional name)."""
        normalized = normalize_epc(epc)
        if not normalized:
            raise ValueError("EPC must be 2–24 non-zero hexadecimal characters.")
        now = utc_now()
        sold_int = 1 if sold else 0
        with self._lock:
            existing = self._conn.execute(
                "SELECT epc, name, sold, updated_at FROM items WHERE epc = ?",
                (normalized,),
            ).fetchone()
            if existing is None:
                if not name:
                    count = self._conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
                    item_name = f"Item #{count + 1}"
                else:
                    item_name = name.strip()
                self._conn.execute(
                    "INSERT INTO items (epc, name, sold, updated_at) VALUES (?, ?, ?, ?)",
                    (normalized, item_name, sold_int, now),
                )
            else:
                item_name = name.strip() if (name is not None and name.strip()) else existing["name"]
                self._conn.execute(
                    "UPDATE items SET name = ?, sold = ?, updated_at = ? WHERE epc = ?",
                    (item_name, sold_int, now, normalized),
                )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT epc, name, sold, updated_at FROM items WHERE epc = ?",
                (normalized,),
            ).fetchone()
            return self._row_to_dict(row)

    def set_sold(self, epc: str, sold: bool) -> dict | None:
        """Update `sold` (`True` or `False`) for an existing EPC."""
        normalized = normalize_epc(epc)
        if not normalized:
            return None
        now = utc_now()
        with self._lock:
            cur = self._conn.execute(
                "UPDATE items SET sold = ?, updated_at = ? WHERE epc = ?",
                (1 if sold else 0, now, normalized),
            )
            self._conn.commit()
            if cur.rowcount == 0:
                return None
            row = self._conn.execute(
                "SELECT epc, name, sold, updated_at FROM items WHERE epc = ?",
                (normalized,),
            ).fetchone()
            return self._row_to_dict(row) if row else None

    def toggle_sold(self, epc: str) -> dict | None:
        """Flip `sold` between `True` and `False` for an existing EPC."""
        normalized = normalize_epc(epc)
        if not normalized:
            return None
        now = utc_now()
        with self._lock:
            row = self._conn.execute(
                "SELECT sold FROM items WHERE epc = ?",
                (normalized,),
            ).fetchone()
            if row is None:
                return None
            new_sold = 0 if row["sold"] else 1
            self._conn.execute(
                "UPDATE items SET sold = ?, updated_at = ? WHERE epc = ?",
                (new_sold, now, normalized),
            )
            self._conn.commit()
            updated = self._conn.execute(
                "SELECT epc, name, sold, updated_at FROM items WHERE epc = ?",
                (normalized,),
            ).fetchone()
            return self._row_to_dict(updated) if updated else None

    def get_item(self, epc: str) -> dict | None:
        normalized = normalize_epc(epc)
        if not normalized:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT epc, name, sold, updated_at FROM items WHERE epc = ?",
                (normalized,),
            ).fetchone()
            return self._row_to_dict(row) if row else None

    def list_items(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT epc, name, sold, updated_at FROM items ORDER BY updated_at DESC, epc ASC"
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def set_all_sold(self, sold: bool) -> int:
        now = utc_now()
        with self._lock:
            cur = self._conn.execute(
                "UPDATE items SET sold = ?, updated_at = ?",
                (1 if sold else 0, now),
            )
            self._conn.commit()
            return cur.rowcount

    def delete_item(self, epc: str) -> bool:
        normalized = normalize_epc(epc)
        if not normalized:
            return False
        with self._lock:
            cur = self._conn.execute("DELETE FROM items WHERE epc = ?", (normalized,))
            self._conn.commit()
            return cur.rowcount > 0

    def clear_items(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM items")
            self._conn.commit()

    def counts(self) -> dict:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            sold_count = self._conn.execute("SELECT COUNT(*) FROM items WHERE sold = 1").fetchone()[0]
            unsold_count = total - sold_count
            return {"total": total, "sold": sold_count, "unsold": unsold_count}

    def evaluate_gate_epcs(self, epcs: list[str]) -> GateDecision:
        """Evaluate EPCs read by the RFID Gate and decide whether to trigger the gate alarm."""
        normalized_list: list[str] = []
        seen: set[str] = set()
        for raw in epcs:
            norm = normalize_epc(raw)
            if norm and norm not in seen:
                seen.add(norm)
                normalized_list.append(norm)

        unsold_epcs: list[str] = []
        sold_epcs: list[str] = []
        unknown_epcs: list[str] = []

        with self._lock:
            for epc in normalized_list:
                row = self._conn.execute(
                    "SELECT sold FROM items WHERE epc = ?",
                    (epc,),
                ).fetchone()
                if row is None:
                    unknown_epcs.append(epc)
                elif bool(row["sold"]):
                    sold_epcs.append(epc)
                else:
                    unsold_epcs.append(epc)

        if unsold_epcs:
            return GateDecision(
                should_alarm=True,
                action="ALARM",
                unsold_epcs=unsold_epcs,
                sold_epcs=sold_epcs,
                unknown_epcs=unknown_epcs,
                summary=f"ALARM! Unsold item(s): {', '.join(unsold_epcs)}",
            )
        if sold_epcs:
            return GateDecision(
                should_alarm=False,
                action="PASS",
                unsold_epcs=[],
                sold_epcs=sold_epcs,
                unknown_epcs=unknown_epcs,
                summary=f"PASS (No Alarm) — Sold item(s): {', '.join(sold_epcs)}",
            )
        return GateDecision(
            should_alarm=False,
            action="IGNORE",
            unsold_epcs=[],
            sold_epcs=[],
            unknown_epcs=unknown_epcs,
            summary=(
                f"IGNORED (No Alarm) — Unknown EPC(s): {', '.join(unknown_epcs)}"
                if unknown_epcs
                else "No valid EPCs in packet"
            ),
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class ScanSession:
    """Counts each unique EPC once per session and ignores repeat reads of the same tag."""

    def __init__(self, item_db: ItemDatabase | None = None, pad_mode: str = "register_unsold") -> None:
        self._lock = threading.RLock()
        self._seen: set[str] = set()
        self._items: list[dict] = []
        self._total_reads = 0
        self._last_epc: str | None = None
        self._last_source = "idle"
        self._started_at = utc_now()
        self.item_db = item_db
        self._pad_mode = pad_mode if pad_mode in ("register_unsold", "checkout_sold") else "register_unsold"

    def set_pad_mode(self, mode: str) -> None:
        """Set how Pad scans update the items table: 'register_unsold' (sold=False) or 'checkout_sold' (sold=True)."""
        if mode not in ("register_unsold", "checkout_sold"):
            raise ValueError("pad_mode must be 'register_unsold' or 'checkout_sold'")
        with self._lock:
            self._pad_mode = mode

    def get_pad_mode(self) -> str:
        with self._lock:
            return self._pad_mode

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
            pad_mode = self._pad_mode
            db = self.item_db
            snap = self.snapshot()
            snap["is_new"] = is_new

        if db is not None:
            sold_flag = pad_mode == "checkout_sold"
            db.upsert_item(normalized, sold=sold_flag)

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
                "pad_mode": self._pad_mode,
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


# --- Native Windows x86 card_7k.dll ABI definitions (from hax_7k_adapt.h & hax_7k_sdk.h) ---


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


class DeviceAlarmConfig(ctypes.Structure):
    """Matches `struct device_alarm_config` in `hax_7k_sdk.h` (4 bytes)."""

    _pack_ = 1
    _fields_ = [
        ("channel_1", ctypes.c_ubyte),
        ("channel_2", ctypes.c_ubyte),
        ("channel_3", ctypes.c_ubyte),
        ("channel_4", ctypes.c_ubyte),
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


class HaxGatePacketCodec:
    """Binds the pure packet-level C exports (`Device_Pack*` / `Device_UnPack*`) from `card_7k.dll` v2.1.2.0.

    Note: `hax_7k_sdk.h` declares these 5 functions with `HAX_7K_CALL` (`__stdcall` on Windows),
    so `ctypes.WinDLL` is used on 32-bit Windows to avoid `__cdecl`/`__stdcall` stack mismatch.
    """

    def __init__(self, sdk_dir: str | Path | None = None) -> None:
        self.sdk_dir = Path(sdk_dir).resolve() if sdk_dir else None
        self._dll = None
        self.sdk_loaded = False
        self.last_error = ""
        if self.sdk_dir is not None:
            self.try_load(self.sdk_dir)

    def try_load(self, sdk_dir: str | Path) -> bool:
        sdk_path = Path(sdk_dir).resolve()
        self.sdk_dir = sdk_path
        if platform.system() != "Windows" or ctypes.sizeof(ctypes.c_void_p) != 4:
            self.last_error = "card_7k.dll requires 32-bit (x86) Python on Windows."
            return False
        dll_file = sdk_path / "card_7k.dll"
        if not dll_file.is_file():
            self.last_error = f"card_7k.dll not found in {sdk_path}"
            return False
        try:
            if hasattr(os, "add_dll_directory"):
                os.add_dll_directory(str(sdk_path))
            win_dll = ctypes.WinDLL(str(dll_file))

            win_dll.Device_PackServerControl.argtypes = [
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_ubyte),
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_int),
            ]
            win_dll.Device_PackServerControl.restype = ctypes.c_int

            win_dll.Device_UnPackServerControl.argtypes = [
                ctypes.POINTER(ctypes.c_ubyte),
                ctypes.c_int,
            ]
            win_dll.Device_UnPackServerControl.restype = ctypes.c_int

            win_dll.Device_PackDeviceAlarm.argtypes = [
                ctypes.POINTER(DeviceAlarmConfig),
                ctypes.POINTER(ctypes.c_ubyte),
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_int),
            ]
            win_dll.Device_PackDeviceAlarm.restype = ctypes.c_int

            win_dll.Device_UnPackDeviceAlarm.argtypes = [
                ctypes.POINTER(ctypes.c_ubyte),
                ctypes.c_int,
            ]
            win_dll.Device_UnPackDeviceAlarm.restype = ctypes.c_int

            win_dll.Device_UnPackEpcId.argtypes = [
                ctypes.POINTER(ctypes.c_ubyte),
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_int),
            ]
            win_dll.Device_UnPackEpcId.restype = ctypes.c_int

            self._dll = win_dll
            self.sdk_loaded = True
            self.last_error = ""
            return True
        except Exception as err:
            self.last_error = str(err)
            self._dll = None
            self.sdk_loaded = False
            return False

    def pack_server_control(self, value: int = 1) -> tuple[int, bytes]:
        if not self.sdk_loaded or self._dll is None:
            return DEVICE_ERR_PACK_FAILED, b""
        buf = (ctypes.c_ubyte * PACKET_BUF_SIZE)()
        out_len = ctypes.c_int(0)
        ret = int(self._dll.Device_PackServerControl(int(value), buf, PACKET_BUF_SIZE, ctypes.byref(out_len)))
        if ret != DEVICE_OK or out_len.value <= 0:
            return ret, b""
        return DEVICE_OK, bytes(buf[: out_len.value])

    def unpack_server_control(self, reply: bytes) -> int:
        if not self.sdk_loaded or self._dll is None:
            return DEVICE_ERR_UNPACK_FAILED
        if not reply:
            return DEVICE_ERR_INVALID_PARAM
        buf = (ctypes.c_ubyte * len(reply)).from_buffer_copy(reply)
        return int(self._dll.Device_UnPackServerControl(buf, len(reply)))

    def pack_device_alarm(
        self,
        channel_1: int = 1,
        channel_2: int = 1,
        channel_3: int = 1,
        channel_4: int = 1,
    ) -> tuple[int, bytes]:
        if not self.sdk_loaded or self._dll is None:
            return DEVICE_ERR_PACK_FAILED, b""
        cfg = DeviceAlarmConfig(
            int(bool(channel_1)),
            int(bool(channel_2)),
            int(bool(channel_3)),
            int(bool(channel_4)),
        )
        buf = (ctypes.c_ubyte * PACKET_BUF_SIZE)()
        out_len = ctypes.c_int(0)
        ret = int(self._dll.Device_PackDeviceAlarm(ctypes.byref(cfg), buf, PACKET_BUF_SIZE, ctypes.byref(out_len)))
        if ret != DEVICE_OK or out_len.value <= 0:
            return ret, b""
        return DEVICE_OK, bytes(buf[: out_len.value])

    def unpack_device_alarm(self, reply: bytes) -> int:
        if not self.sdk_loaded or self._dll is None:
            return DEVICE_ERR_UNPACK_FAILED
        if not reply:
            return DEVICE_ERR_INVALID_PARAM
        buf = (ctypes.c_ubyte * len(reply)).from_buffer_copy(reply)
        return int(self._dll.Device_UnPackDeviceAlarm(buf, len(reply)))

    def unpack_epc_id(self, data: bytes) -> tuple[int, list[dict]]:
        """Decrypt and parse an incoming gate EPC packet into [{'ant_id': 1, 'epc_id': '...'}]."""
        if not self.sdk_loaded or self._dll is None:
            return DEVICE_ERR_UNPACK_FAILED, []
        if not data:
            return DEVICE_ERR_INVALID_PARAM, []
        in_buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        json_size = JSON_BUF_SIZE
        json_buf = ctypes.create_string_buffer(json_size)
        json_len = ctypes.c_int(0)
        ret = int(self._dll.Device_UnPackEpcId(in_buf, len(data), json_buf, json_size, ctypes.byref(json_len)))
        if ret == DEVICE_ERR_BUFFER_TOO_SMALL and json_len.value > json_size:
            json_size = int(json_len.value) + 16
            json_buf = ctypes.create_string_buffer(json_size)
            ret = int(self._dll.Device_UnPackEpcId(in_buf, len(data), json_buf, json_size, ctypes.byref(json_len)))
        if ret != DEVICE_OK:
            return ret, []
        raw_text = json_buf.raw[: max(0, json_len.value)]
        try:
            return DEVICE_OK, parse_epc_json_payload(raw_text)
        except Exception:
            return DEVICE_ERR_UNPACK_FAILED, []


@dataclass
class GateState:
    running: bool = False
    host: str = "0.0.0.0"
    port: int = 9000
    serial_port: str = ""
    status_text: str = "Stopped"
    peer: str = ""
    server_control_active: bool = False
    sdk_loaded: bool = False
    bytes_received: int = 0
    connections: int = 0
    alarm_count: int = 0
    pass_count: int = 0
    ignore_count: int = 0
    last_epc: str = ""
    last_action: str = "IDLE"
    last_summary: str = "Waiting for RFID Gate connection..."
    capture_file: str = ""
    last_error: str = ""


class RfidGateController:
    """RS232 Serial & TCP Server controller for the HAX-7000 / HAX9370AMRFID Gate (SDK 2.1.2.0).

    Supports both:
    - **RS232 Serial (`115200 8N1`)**: `/dev/ttyUSB0` on Linux or `COMx` on Windows.
    - **TCP Server (`0.0.0.0:9000`)**: for `USR-TCP232-E2` Ethernet/Wi-Fi gate modules.

    Protocol flow per `hax_7k_sdk.h` and `7k_gate_demo.cpp`:
    1. Sends `Device_PackServerControl(1)` and verifies `Device_UnPackServerControl(reply) == DEVICE_OK`.
    2. Gate streams EPC packets (`Device_UnPackEpcId` -> `[{"ant_id":1,"epc_id":"..."}]`).
    3. If `register_when_scanning` is True (user clicked `Start Scanning`), registers new EPCs into `ItemDatabase` (`Sold = False`).
    4. Otherwise checks each EPC in `ItemDatabase`:
       - `sold == False` (unsold item): Sends `Device_PackDeviceAlarm({1,1,1,1})` -> Gate ALARMS!
       - `sold == True` (customer bought item): Does NOT send alarm -> Gate stays silent (`PASS`)!
       - Unknown EPC (not in table): Does NOT send alarm (`IGNORE`)!
    """

    def __init__(
        self,
        item_db: ItemDatabase,
        sdk_dir: str | Path | None = None,
        capture_dir: str | Path = "captures",
        codec: HaxGatePacketCodec | None = None,
        session: ScanSession | None = None,
    ) -> None:
        self.item_db = item_db
        self.session = session
        self.capture_dir = Path(capture_dir)
        self.codec = codec or HaxGatePacketCodec(sdk_dir=sdk_dir)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._serial_thread: threading.Thread | None = None
        self._sockets: list[socket.socket] = []
        self._serial: RawSerialPort | None = None
        self._register_mode = False
        self._events: deque[GateEvent] = deque(maxlen=100)
        self._state = GateState(sdk_loaded=self.codec.sdk_loaded)

    def set_register_mode(self, enabled: bool) -> None:
        """When True ('Start Scanning' clicked), tags read by the Gate are added to `ItemDatabase` as Unsold (`Sold=False`)."""
        with self._lock:
            self._register_mode = bool(enabled)

    def is_register_mode(self) -> bool:
        with self._lock:
            return self._register_mode

    def state(self) -> GateState:
        with self._lock:
            return GateState(**self._state.__dict__)

    def recent_events(self) -> list[GateEvent]:
        with self._lock:
            return list(self._events)

    def simulate_gate_read(self, epcs: list[str], ant_id: int = 1) -> GateEvent:
        """Evaluate a list of EPCs against `ItemDatabase` and record the GateEvent."""
        decision = self.item_db.evaluate_gate_epcs(epcs)
        norm_epcs = [normalize_epc(e) for e in epcs]
        valid_epcs = [e for e in norm_epcs if e]
        event = GateEvent(
            at=utc_now(),
            epcs=valid_epcs,
            antennas=[ant_id] * len(valid_epcs),
            should_alarm=decision.should_alarm,
            alarm_sent=decision.should_alarm,
            alarm_ack=decision.should_alarm,
            action=decision.action,
            unsold_epcs=decision.unsold_epcs,
            sold_epcs=decision.sold_epcs,
            unknown_epcs=decision.unknown_epcs,
            summary=decision.summary,
        )
        with self._lock:
            self._events.appendleft(event)
            if valid_epcs:
                self._state.last_epc = valid_epcs[0]
            self._state.last_action = decision.action
            self._state.last_summary = decision.summary
            if decision.action == "ALARM":
                self._state.alarm_count += 1
            elif decision.action == "PASS":
                self._state.pass_count += 1
            else:
                self._state.ignore_count += 1
        return event

    def start(self, host: str = "0.0.0.0", port: int = 9000, serial_port: str | None = None) -> None:
        self.stop()
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        capture_path = self.capture_dir / f"hax-gate-{stamp}.jsonl"
        self._stop = threading.Event()
        ready = threading.Event()

        if serial_port is None:
            detected = detect_serial_ports()
            serial_port = detected[0] if detected else ""

        with self._lock:
            self._state = GateState(
                running=True,
                host=host,
                port=port,
                serial_port=serial_port or "",
                sdk_loaded=self.codec.sdk_loaded,
                status_text=f"Listening on {host}:{port}",
                last_summary="Gate Status: Waiting for tag...",
                capture_file=str(capture_path),
            )
        self._thread = threading.Thread(
            target=self._run_server,
            args=(host, int(port), capture_path, self._stop, ready),
            daemon=True,
        )
        self._thread.start()
        ready.wait(timeout=1.0)

        if serial_port:
            self._serial_thread = threading.Thread(
                target=self._run_serial,
                args=(serial_port, capture_path, self._stop),
                daemon=True,
            )
            self._serial_thread.start()

    @staticmethod
    def _send_all(sock: socket.socket, data: bytes) -> bool:
        try:
            sock.sendall(data)
            return True
        except OSError:
            return False

    @staticmethod
    def _recv_once(sock: socket.socket, buf_size: int, timeout_sec: float | None) -> bytes:
        sock.settimeout(timeout_sec)
        return sock.recv(buf_size)

    def _step_server_control_io(self, send_fn, recv_fn, peer_label: str, log_file) -> bool:
        ret, packet = self.codec.pack_server_control(1)
        if ret != DEVICE_OK or not packet:
            with self._lock:
                self._state.last_error = f"Device_PackServerControl failed: {device_error_text(ret)}"
            return False
        log_file.write(
            json.dumps(
                {
                    "at": utc_now(),
                    "event": "tx_server_control",
                    "peer": peer_label,
                    "bytes": len(packet),
                    "hex": packet.hex(" ").upper(),
                }
            )
            + "\n"
        )
        log_file.flush()
        if not send_fn(packet):
            return False
        try:
            reply = recv_fn(PACKET_BUF_SIZE, REPLY_TIMEOUT_SEC)
        except OSError:
            with self._lock:
                self._state.last_error = f"No server_control reply from {peer_label}"
            return False
        if not reply:
            return False
        with self._lock:
            self._state.bytes_received += len(reply)
        log_file.write(
            json.dumps(
                {
                    "at": utc_now(),
                    "event": "rx_server_control_reply",
                    "peer": peer_label,
                    "bytes": len(reply),
                    "hex": reply.hex(" ").upper(),
                }
            )
            + "\n"
        )
        log_file.flush()
        unpack_ret = self.codec.unpack_server_control(reply)
        if unpack_ret != DEVICE_OK:
            with self._lock:
                self._state.last_error = f"Device_UnPackServerControl: {device_error_text(unpack_ret)}"
            return False
        return True

    def _step_device_alarm_io(self, send_fn, recv_fn, peer_label: str, log_file) -> bool:
        ret, packet = self.codec.pack_device_alarm(1, 1, 1, 1)
        if ret != DEVICE_OK or not packet:
            with self._lock:
                self._state.last_error = f"Device_PackDeviceAlarm failed: {device_error_text(ret)}"
            return False
        log_file.write(
            json.dumps(
                {
                    "at": utc_now(),
                    "event": "tx_device_alarm",
                    "peer": peer_label,
                    "bytes": len(packet),
                    "hex": packet.hex(" ").upper(),
                }
            )
            + "\n"
        )
        log_file.flush()
        if not send_fn(packet):
            return False
        try:
            reply = recv_fn(PACKET_BUF_SIZE, REPLY_TIMEOUT_SEC)
        except OSError:
            with self._lock:
                self._state.last_error = f"No device_alarm reply from {peer_label}"
            return False
        if not reply:
            return False
        with self._lock:
            self._state.bytes_received += len(reply)
        log_file.write(
            json.dumps(
                {
                    "at": utc_now(),
                    "event": "rx_device_alarm_reply",
                    "peer": peer_label,
                    "bytes": len(reply),
                    "hex": reply.hex(" ").upper(),
                }
            )
            + "\n"
        )
        log_file.flush()
        unpack_ret = self.codec.unpack_device_alarm(reply)
        if unpack_ret != DEVICE_OK:
            with self._lock:
                self._state.last_error = f"Device_UnPackDeviceAlarm: {device_error_text(unpack_ret)}"
            return False
        return True

    def _process_epc_packet(self, chunk: bytes, send_fn, recv_fn, peer_label: str, log_file) -> None:
        if not self.codec.sdk_loaded:
            return
        ret, parsed_entries = self.codec.unpack_epc_id(chunk)
        if ret != DEVICE_OK:
            with self._lock:
                self._state.last_error = f"Device_UnPackEpcId: {device_error_text(ret)}"
            return
        if not parsed_entries:
            return

        epcs = [entry["epc_id"] for entry in parsed_entries]
        antennas = [entry["ant_id"] for entry in parsed_entries]

        # If user clicked "Start Scanning", register the scanned tags into the table as Unsold (Sold=False)
        if self.is_register_mode():
            for epc in epcs:
                if self.session is not None:
                    self.session.observe(epc, source="gate")
                else:
                    self.item_db.upsert_item(epc, sold=False)
            with self._lock:
                self._state.last_epc = epcs[0]
                self._state.last_action = "REGISTERED"
                self._state.last_summary = f"Scanned & Added Tag: {epcs[0]} (Sold = False)"
            return

        decision = self.item_db.evaluate_gate_epcs(epcs)
        alarm_sent = False
        alarm_ack = False
        if decision.should_alarm:
            alarm_sent = True
            alarm_ack = self._step_device_alarm_io(send_fn, recv_fn, peer_label, log_file)

        event = GateEvent(
            at=utc_now(),
            epcs=epcs,
            antennas=antennas,
            should_alarm=decision.should_alarm,
            alarm_sent=alarm_sent,
            alarm_ack=alarm_ack,
            action=decision.action,
            unsold_epcs=decision.unsold_epcs,
            sold_epcs=decision.sold_epcs,
            unknown_epcs=decision.unknown_epcs,
            summary=decision.summary,
        )
        log_file.write(
            json.dumps(
                {
                    "at": event.at,
                    "event": "gate_decision",
                    "peer": peer_label,
                    "epcs": epcs,
                    "action": decision.action,
                    "should_alarm": decision.should_alarm,
                    "alarm_ack": alarm_ack,
                    "unsold_epcs": decision.unsold_epcs,
                    "sold_epcs": decision.sold_epcs,
                    "unknown_epcs": decision.unknown_epcs,
                }
            )
            + "\n"
        )
        log_file.flush()

        with self._lock:
            self._events.appendleft(event)
            self._state.last_epc = epcs[0]
            self._state.last_action = decision.action
            self._state.last_summary = decision.summary
            if decision.action == "ALARM":
                self._state.alarm_count += 1
            elif decision.action == "PASS":
                self._state.pass_count += 1
            else:
                self._state.ignore_count += 1

    def _run_serial(self, port_name: str, capture_path: Path, stop: threading.Event) -> None:
        peer_label = f"RS232:{port_name}"
        while not stop.is_set():
            try:
                ser = RawSerialPort(port_name, baudrate=115200)
            except PermissionError:
                with self._lock:
                    self._state.last_error = f"Permission denied on {port_name} (run: sudo chmod 666 {port_name})"
                    self._state.status_text = f"RS232 {port_name} (Permission Denied)"
                time.sleep(1.5)
                continue
            except OSError as err:
                with self._lock:
                    self._state.last_error = str(err)
                time.sleep(1.5)
                continue

            with self._lock:
                self._serial = ser
                self._state.connections += 1
                self._state.peer = peer_label
                self._state.last_error = ""
                self._state.status_text = f"RS232 Connected ({port_name})"

            try:
                with capture_path.open("a", encoding="utf-8") as log_file:
                    log_file.write(
                        json.dumps({"at": utc_now(), "event": "serial_opened", "peer": peer_label}) + "\n"
                    )
                    log_file.flush()

                    if self.codec.sdk_loaded:
                        if self._step_server_control_io(ser.send_all, ser.recv_once, peer_label, log_file):
                            with self._lock:
                                self._state.server_control_active = True
                                self._state.status_text = f"Gate Active ({port_name})"

                    while not stop.is_set():
                        try:
                            chunk = ser.recv_once(EPC_BUF_SIZE, 0.3)
                        except socket.timeout:
                            continue
                        except OSError:
                            break
                        if not chunk:
                            continue
                        with self._lock:
                            self._state.bytes_received += len(chunk)
                        log_file.write(
                            json.dumps(
                                {
                                    "at": utc_now(),
                                    "event": "rx_serial",
                                    "peer": peer_label,
                                    "bytes": len(chunk),
                                    "hex": chunk.hex(" ").upper(),
                                }
                            )
                            + "\n"
                        )
                        log_file.flush()
                        self._process_epc_packet(chunk, ser.send_all, ser.recv_once, peer_label, log_file)
            finally:
                ser.close()
                with self._lock:
                    self._serial = None
                    if not stop.is_set() and self._state.peer == peer_label:
                        self._state.peer = ""
                        self._state.server_control_active = False

    def _serve_gate_client(
        self,
        client: socket.socket,
        peer_label: str,
        log_file,
        stop: threading.Event,
    ) -> None:
        send_fn = lambda data: self._send_all(client, data)
        recv_fn = lambda sz, to: self._recv_once(client, sz, to)

        if self.codec.sdk_loaded:
            if not self._step_server_control_io(send_fn, recv_fn, peer_label, log_file):
                return
            with self._lock:
                self._state.server_control_active = True
                self._state.status_text = f"Gate Active ({peer_label})"

        while not stop.is_set():
            try:
                chunk = self._recv_once(client, EPC_BUF_SIZE, 0.3)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                break
            with self._lock:
                self._state.bytes_received += len(chunk)
            log_file.write(
                json.dumps(
                    {
                        "at": utc_now(),
                        "event": "rx_epc_packet",
                        "peer": peer_label,
                        "bytes": len(chunk),
                        "hex": chunk.hex(" ").upper(),
                    }
                )
                + "\n"
            )
            log_file.flush()
            self._process_epc_packet(chunk, send_fn, recv_fn, peer_label, log_file)

    def _run_server(
        self,
        host: str,
        port: int,
        capture_path: Path,
        stop: threading.Event,
        ready: threading.Event | None = None,
    ) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        with self._lock:
            self._sockets = [sock]
        try:
            with capture_path.open("a", encoding="utf-8") as log_file:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((host, port))
                sock.listen(4)
                sock.settimeout(0.3)
                if ready is not None:
                    ready.set()
                while not stop.is_set():
                    try:
                        client, addr = sock.accept()
                    except socket.timeout:
                        continue
                    except OSError:
                        break
                    peer_label = f"{addr[0]}:{addr[1]}"
                    with self._lock:
                        self._sockets.append(client)
                        self._state.connections += 1
                        self._state.peer = peer_label
                        self._state.server_control_active = False
                        self._state.status_text = f"Gate connected ({peer_label})"
                    log_file.write(
                        json.dumps({"at": utc_now(), "event": "gate_connected", "peer": peer_label}) + "\n"
                    )
                    log_file.flush()
                    try:
                        self._serve_gate_client(client, peer_label, log_file, stop)
                    finally:
                        try:
                            client.close()
                        except OSError:
                            pass
                        with self._lock:
                            if not stop.is_set() and self._state.peer == peer_label:
                                self._state.peer = ""
                                self._state.server_control_active = False
                                self._state.status_text = f"Listening on {host}:{port} (gate closed)"
        except Exception as err:
            if not stop.is_set():
                with self._lock:
                    self._state.last_error = str(err)
                    self._state.status_text = f"Gate Error: {err}"
        finally:
            if ready is not None:
                ready.set()
            with self._lock:
                for s in self._sockets:
                    try:
                        s.close()
                    except OSError:
                        pass
                self._sockets.clear()
                self._state.running = False
                self._state.server_control_active = False
                if stop.is_set():
                    self._state.status_text = "Stopped"

    def stop(self) -> None:
        with self._lock:
            self._stop.set()
            for s in list(self._sockets):
                try:
                    s.close()
                except OSError:
                    pass
            ser = self._serial
            self._serial = None
            thread = self._thread
            self._thread = None
            ser_thread = self._serial_thread
            self._serial_thread = None
        if ser is not None:
            ser.close()
        if thread and thread.is_alive():
            thread.join(timeout=1.5)
        if ser_thread and ser_thread.is_alive():
            ser_thread.join(timeout=1.5)


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
      use `card_7k.dll` (`open_tcp_server` + `read_epc_id`) to poll the
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
        ready = threading.Event()
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
            args=(mode, host, port, peer_filter.strip(), capture_path, self._stop, ready),
            daemon=True,
        )
        self._thread.start()
        if mode == "listen":
            ready.wait(timeout=1.0)

    def _run_tcp(
        self,
        mode: str,
        host: str,
        port: int,
        peer_filter: str,
        capture_path: Path,
        stop: threading.Event,
        ready: threading.Event | None = None,
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
                    if ready is not None:
                        ready.set()
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
            if ready is not None:
                ready.set()
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

        if hasattr(os, "add_dll_directory"):
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
