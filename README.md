# HAX7700 Standalone Python Tag/EPC Counter Widget

A minimal, self-contained Python desktop widget that counts unique tags/EPCs scanned on the **HAX7700 Deactivator (`RFID7700` board)**.

- **Zero external Python package dependencies** (uses Python standard library + native `GTK3` on Linux or `Tkinter` on Windows).
- **Unique EPC deduplication:** Each physical tag EPC increments the session counter once (`1`, `2`, `3`…); repeat reads of the same EPC are ignored. Clicking **Start Scanning** resets the count and starts a fresh scan session; clicking **Stop** pauses counting.
- **Breathing connection indicator:** Displays an amber breathing indicator (`Connecting...`) while waiting for the HAX7700 and switches to green (`Connected`) once the pad connects on TCP port `9090`.
- **High-speed HAX7700 scanner support (`~245 ms` per scan):**
  - **Windows x86 Native HAX SDK (`sdk-win-x86/card_7k.dll` + `common.dll`):** When run with 32-bit Python on Windows (`start-windows.bat`), automatically tunes `common.dll`'s `config.ini` network wait times (`net_send_data_wait_time=5`, `net_time_out=120`, `time_out=80`), opens the TCP listener on `0.0.0.0:9090`, and runs a dedicated fast-polling worker (`read_epc_id`) every `~245 ms`.
  - **Linux / Windows Direct TCP Listener (`0.0.0.0:9090`):** Accepts the inbound TCP connection from the HAX7700's internal `USR-TCP232-E2` (`169.254.68.93`).

---

## Windows Setup & Network Configuration

### 1. Prerequisites
1. **32-bit (x86) Python 3.x for Windows** (with Tkinter and the `py` launcher installed), because `card_7k.dll` and `common.dll` are 32-bit (`PE32` x86) native libraries:
   - Default path used by `start-windows.bat`: `%LOCALAPPDATA%\Programs\Python\Python312-32\pythonw.exe` (or `py -3-32`).
2. **Vendor 32-bit SDK DLLs in `sdk-win-x86/`:**
   - Place `card_7k.dll` and `common.dll` in `sdk-win-x86/` (alongside the 32-bit VC++/MFC runtime DLLs `mfc140.dll`, `msvcp140.dll`, `vcruntime140.dll`).

### 2. Network & Firewall Configuration (`setup-network-windows.bat`)
The HAX7700's internal Ethernet module (`USR-TCP232-E2`) has factory static IP **`169.254.68.93/16`** and operates in **TCP Client** mode, automatically connecting out to **`169.254.68.94:9090`** (your PC).

To configure the Ethernet adapter and Windows Defender Firewall automatically:
1. Plug the HAX7700 Ethernet cable into your PC's Ethernet / USB-Ethernet adapter (default adapter name: `"Ethernet 2"`).
2. Double-click **`setup-network-windows.bat`** and approve the Administrator prompt (or run `setup-network-windows.bat "Your Adapter Name"` from Command Prompt if your adapter is not named `Ethernet 2`).

What `setup-network-windows.bat` configures:
- **Static IPv4 address:** Assigns `169.254.68.94` (subnet mask `255.255.255.0`) to the Ethernet interface connected to the HAX7700:
  ```bat
  netsh interface ipv4 set address name="Ethernet 2" static 169.254.68.94 255.255.255.0
  netsh interface ipv4 add address "Ethernet 2" 169.254.68.94 255.255.255.0
  ```
- **Windows Defender Firewall rules:** Ensures `python.exe` and `pythonw.exe` are allowed on `Public` (unidentified link-local) networks and opens inbound TCP port `9090`:
  ```bat
  netsh advfirewall firewall set rule name="python.exe" new action=allow
  netsh advfirewall firewall set rule name="pythonw.exe" new action=allow
  netsh advfirewall firewall add rule name="HAX7700 TCP 9090" dir=in action=allow protocol=TCP localport=9090 profile=any
  ```
- **Connectivity test:** Pings `169.254.68.93` to verify physical link reachability.

### 3. Run the Widget on Windows
Double-click **`start-windows.bat`** (which launches the widget window directly via 32-bit `pythonw.exe` without keeping a console window open), or run from a terminal:
```bat
py -3-32 -m hax7700_widget
```

---

## Linux Setup & Network Configuration

Configure your Ethernet interface with `169.254.68.94/16` and launch `./start.sh`:
```bash
sudo ip addr add 169.254.68.94/16 dev <eth-interface>
./start.sh
```

## Run Unit Tests

```bash
# Windows (32-bit Python)
py -3-32 -m unittest discover -s tests -v

# Linux
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
