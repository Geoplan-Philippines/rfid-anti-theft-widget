# AGENT.md — HAX7700 Standalone Python Tag/EPC Counter Widget

Instructions and hardware context for AI coding agents and developers working in this repository.

---

## 1. Mission & Scope

This repository is a **standalone, zero-dependency Python desktop widget** whose sole purpose is to **count unique RFID tags/EPCs scanned on the HAX7700 Deactivator (`RFID7700` board)**:
- Each distinct 12-byte EPC increments the session counter once (`1`, `2`, `3`…).
- Repeat reads of the same EPC within the active session are ignored automatically (`repeat_reads`).
- Clicking **New session** resets the session counter to `0`.
- Keep the application lightweight, self-contained, and standard-library-only (`GTK3` via `gi.repository.Gtk` on Linux; `tkinter` on Windows).

---

## 2. Verified Hardware & Network Context

Read [`docs/HARDWARE-STUDY-HAX7700-HAX9370AMRFID.md`](docs/HARDWARE-STUDY-HAX7700-HAX9370AMRFID.md) before modifying hardware or network logic. Summary of verified facts:

1. **Identity:**
   - **HAX7700** is the desktop glass-pad product SKU (*"HAX7700 RFID Reader and Deactivator"*).
   - **RFID7700** (board code `7700` on `eas-data.net`, plugin `card_7k7.dll` in `CardMonitor`) is the internal UHF RFID controller board inside the HAX7700.
2. **Internal Ethernet Module (`USR-TCP232-E2` at `169.254.68.93`):**
   - MAC address: `38:F4:06:10:5D:43`
   - Host PC static link-local IP on the USB Ethernet adapter: `169.254.68.94/24`
   - **Port 1 (`port0.json`, UART0):** `115200 8N1`, `workmodea=2` (TCP Client), configured to dial `169.254.68.94:9090` (`reconnecttime=60`, so it recycles idle TCP sockets every 60.0s).
   - **Port 2 (`port1.json`, UART1):** `115200 8N1`, `workmodea=4` (TCP Server) listening on `169.254.68.93:26`, plus WebSocket server on `ws://169.254.68.93:6432/`.
   - **HTTP Server Quirk (`webnet 2.0.0`):** Static HTML/JS pages on `http://169.254.68.93/` (`status.html`, `websocket.html`, `js/public.js`) are gzip-compressed in flash and return `404 Not Found` unless `Accept-Encoding: gzip` (`curl --compressed`) is sent.
   - **Live UART Byte Counters:** Switch the active status view via `GET /por.cgi?port=0` (or `port=1`), then read `GET /temp_status.json` (`constatea`, `txcounta`, `rxcounta`). See [`docs/hardware-resources/usr-tcp232-e2-live-snapshot.json`](docs/hardware-resources/usr-tcp232-e2-live-snapshot.json).
3. **Command-Polled Board Behavior:**
   - Live testing with a physical tag on top of the HAX7700 pad confirmed `txcounta: "0 bytes"` and `rxcounta: "0 bytes"` on both UART0 and UART1 when no host poll command is sent.
   - Even when the HAX7700 pad beeps/lights up locally, the `RFID7700` board does **not** transmit unsolicited EPC bytes over UART/Ethernet—it waits for a host inventory-poll command.

---

## 3. Windows vs. Linux Execution Paths

### On Windows (32-bit x86 Python — Full SDK Polling)
- `card_7k.dll` (PE32 i386, v2.0.1.0) and `common.dll` (PE32 i386, v2.0.6.2) are 32-bit Windows DLLs.
- Place `card_7k.dll`, `common.dll`, and the 32-bit MSVC/MFC runtime DLLs (`mfc140.dll`, `msvcp140*.dll`, `vcruntime140*.dll`) into `sdk-win-x86/` (ignored by Git).
- Run `start-windows.bat` (or `py -3-32 -m hax7700_widget`).
- [`TcpDeactivatorListener.start_windows_sdk()`](hax7700_widget/core.py) automatically:
  1. Loads `sdk-win-x86/card_7k.dll` via `ctypes.CDLL`.
  2. Keeps `IAsynchronousMessage` callback delegates (`port_connecting`, `port_closing`, `output_tags`) rooted on `self._sdk_callbacks` for the entire session lifetime (preventing GC collection while native threads invoke callbacks).
  3. Calls `open_tcp_server(b"0.0.0.0", 9090, callbacks)` and `start_auto_read(200)`.
  4. Unpacks the 612-byte `EpcIdList` (`sn[32]`, `int size`, `32 × 18-byte EpcIdSt`) in `output_tags`, formats each 12-byte `id` buffer via `format_epc_bytes()`, and records unique EPCs in `ScanSession`.
- **High-Value Goal When Testing on Windows:** Capture a Wireshark/pcap trace on `169.254.68.94:9090` while `start_auto_read(200)` is polling `169.254.68.93` with a tag on the pad. Extracting the exact poll request bytes and tag response framing will allow us to implement native SDK-free polling in `PendingHax7700Decoder` / `TcpDeactivatorListener` so Linux and 64-bit Windows work without `card_7k.dll`.

### On Linux (`./start.sh` / `python3 -m hax7700_widget`)
- Do **not** attempt to load `common.dll` under Wine: `common.dll` is packed with VMProtect (`.w_v` section) and crashes in `DllMain` under Wine (`EXCEPTION_ILLEGAL_INSTRUCTION` -> `EXCEPTION_ACCESS_VIOLATION` at `0x766C4000`; see [`docs/SDK-LINUX-LOAD-TEST.md`](docs/SDK-LINUX-LOAD-TEST.md)).
- Running `./start.sh` opens the native GTK3 always-on-top counter window and starts the TCP listener on `0.0.0.0:9090` (or connects to `169.254.68.93:26` when **Port 26** is clicked), logging connections and any received bytes to `captures/hax7700-*.jsonl`.

---

## 4. Safety & Code Rules

1. **No Invented Hardware Commands:** Never transmit guessed or fabricated command bytes to `169.254.68.93` or serial ports. Only send verified HAX protocol frames.
2. **Read-Only Tag Operations:** Never call `write_epc_id`, `write_data`, `set_config`, or `enable_alarm` in `card_7k.dll` (note that `docs/sdk-reference/7k_api_demo.cpp` mutates tag/device state and must never be run against production hardware).
3. **No Guessed EPC Decoding:** `PendingHax7700Decoder` must return `[]` until the actual `RFID7700` / `RFID7000` wire framing and CRC (`CCRC` / `CCodingMgr`) are verified from captures or vendor docs.
4. **Native Struct Packing:** Always keep `_pack_ = 1` on `EpcIdSt` (18 bytes), `EpcIdList` (612 bytes), and `IAsynchronousMessage` (12 bytes on x86), verified by `tests/test_core.py`.
5. **Repository Hygiene:** Never commit `.dll`, `.exe`, `captures/`, `__pycache__/`, or device credentials.

---

## 5. Repository Layout & Commands

- `hax7700_widget/core.py` — EPC formatting/normalization, `ItemDatabase` (SQLite `items.db` with `sold: True/False`), `HaxGatePacketCodec` & `RfidGateController` (SDK v2.1.2.0 `Device_PackServerControl` / `Device_UnPackEpcId` / `Device_PackDeviceAlarm`), `ScanSession` deduplication, `TcpDeactivatorListener` (direct TCP + 32-bit Windows `card_7k.dll` ctypes driver), and `EpcIdSt` / `EpcIdList` / `DeviceAlarmConfig` structures.
- `hax7700_widget/gui.py` — Desktop checkout & gate controller UI (`run_gtk_widget` for Linux GTK3, `run_tk_widget` for Windows Tkinter).
- `hax7700_widget/__main__.py` — CLI entry point (`python3 -m hax7700_widget [--port 9090] [--gate-port 9000] [--db items.db] [--sdk-dir sdk-win-x86]`).
- `tests/test_core.py` — Unit tests for ABI struct layout, EPC formatting, SQLite `sold: true/false` gate decisions, Pad checkout modes, and Gate TCP handshake/alarm flow.
- `docs/` — Complete hardware study, `USR-TCP232-E2` live snapshot, `HAX7700_desc.pdf`, PCB/connector photos, DLL analysis, and SDK headers (`hax_7k_adapt.h`, `hax_7k_sdk.h`, `7k_gate_demo.cpp`).

```bash
# Run unit tests
python3 -m unittest discover -s tests -v

# Launch widget on Linux
./start.sh

# Launch widget on Windows (prefers 32-bit Python for card_7k.dll)
start-windows.bat
```
