# HAX7700 Standalone Python Tag/EPC Counter Widget

A minimal, self-contained Python desktop widget that counts unique tags/EPCs scanned on the **HAX7700 Deactivator (`RFID7700` board)**.

- **Zero external Python package dependencies** (uses Python standard library + native `GTK3` on Linux or `Tkinter` on Windows).
- **Unique EPC deduplication:** Each physical tag EPC increments the session counter once (`1`, `2`, `3`…); repeat reads of the same EPC are ignored until **New session** is clicked.
- **Built-in HAX7700 scanner support:**
  - **Linux / Windows Direct TCP Listener (`0.0.0.0:9090`):** Automatically accepts the inbound TCP connection from the HAX7700's internal `USR-TCP232-E2` (`169.254.68.93`), or switches to `169.254.68.93:26` with one click.
  - **Windows x86 Native HAX SDK (`sdk-win-x86/card_7k.dll`):** When run with 32-bit Python on Windows (`start-windows.bat`), automatically loads `card_7k.dll` (`open_tcp_server` + `start_auto_read(200)`) to poll the HAX7700 every 200 ms and decode 12-byte EPCs directly into the counter.
  - **Scan / Wedge Input:** Also accepts EPCs directly in the built-in scan box (`Scan or enter EPC hex…`).

## Run on Linux

```bash
./start.sh
```

## Run on Windows

Place the 32-bit HAX runtime DLLs (`card_7k.dll`, `common.dll`, and VC++/MFC x86 runtime DLLs) in `sdk-win-x86/`, then double-click `start-windows.bat` (or run `py -3-32 -m hax7700_widget`).

## Run Unit Tests

```bash
python3 -m unittest discover -s tests -v
```

## Hardware Research & Reference Documentation (`docs/`)

- [`docs/HARDWARE-STUDY-HAX7700-HAX9370AMRFID.md`](docs/HARDWARE-STUDY-HAX7700-HAX9370AMRFID.md) — Complete hardware & protocol study reconciling **HAX7700** (`RFID7700 board` inside) and **HAX9370AMRFID** (`RFID7000 V3.4` + `9300` AM boards inside), `eas-data.net` portal architecture, and live `169.254.68.93` bench test results.
- [`docs/hardware-research.md`](docs/hardware-research.md) — Direct Ethernet (`169.254.68.93` / `USR-TCP232-E2`), TCP Port `9090` / `26`, and WebSocket Port `6432` investigation notes.
- [`docs/DLL-ANALYSIS.md`](docs/DLL-ANALYSIS.md) & [`docs/SDK-LINUX-LOAD-TEST.md`](docs/SDK-LINUX-LOAD-TEST.md) — Binary analysis of `card_7k.dll` (v2.0.1.0) and `common.dll` (v2.0.6.2, VMProtect-packed) and Linux Wine x86 loader test results.
- [`docs/sdk-free-testing.md`](docs/sdk-free-testing.md) — Guide for passive TCP/WebSocket capture and read-only `USR-TCP232-E2` inspection.
- [`docs/supplier-questions.md`](docs/supplier-questions.md) & [`docs/SUPPLIER-REQUEST.md`](docs/SUPPLIER-REQUEST.md) — Specific protocol and SDK questions for Jenny / HAX engineering.
- [`docs/hardware-resources/`](docs/hardware-resources/) — Official [`HAX7700_desc.pdf`](docs/hardware-resources/HAX7700_desc.pdf) datasheet, extracted high-resolution connector/PCB photos (`hax7700-000.jpg`–`hax7700-002.jpg`), product JSON records (`detail-175.json`, `detail-93.json`), and live `USR-TCP232-E2` status snapshot ([`usr-tcp232-e2-live-snapshot.json`](docs/hardware-resources/usr-tcp232-e2-live-snapshot.json)).
- [`docs/sdk-reference/`](docs/sdk-reference/) — UTF-8 decoded vendor SDK header ([`hax_7k_adapt.h`](docs/sdk-reference/hax_7k_adapt.h)) and reference samples ([`7k_api_demo.cs`](docs/sdk-reference/7k_api_demo.cs), [`7k_api_demo.cpp`](docs/sdk-reference/7k_api_demo.cpp)).
