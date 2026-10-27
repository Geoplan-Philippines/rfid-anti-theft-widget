# Hardware Study & Resource Inventory: HAX7700 Deactivator & HAX9370AMRFID Gate (RFID7000 V3.4)

**Study Date:** 27 October 2026  
**Manufacturer:** Dongguan HAX Electronic Co., Ltd. (`haxeas.com` · Cloud portal `eas-data.net` · FCC Grantee Code `2AZGZ`)  
**Resource Archive:** [`hardware-resources-2026-10-27/`](hardware-resources-2026-10-27/README.md)

---

## 1. Model & Board Naming Reconciliation (Why Jenny Said "RFID7700 Deactivator")

Across HAX's official product catalog (`haxeas.com`), supplier spec sheets (`HAX7700_desc.pdf`), and HAX's remote-management platform (`eas-data.net`), HAX consistently uses **two parallel model namespaces**:

1. **`HAXxxxx` — Finished Enclosure / Product SKU** (sold in the catalog and printed on spec sheets)
2. **`RFIDxxxx` (or 4-digit board code `7000` / `7700` / `9300`) — Internal Controller PCB / Board Type** (used by firmware, `CardMonitor.exe`, and `eas-data.net`)

| Role | Finished Product SKU (`HAX*`) | Internal Controller Board (`RFID*` / `eas-data.net` code) | Evidence Source |
| :--- | :--- | :--- | :--- |
| **Desktop Pad (Reader / Activator / Deactivator)** | **HAX7700** (*"HAX7700 RFID Reader and Deactivator"* / *"HAX7700 RFID Label Activator & Deactivator"*) | **RFID7700 board** (`boardType = "7700"` -> `"7700 RFID Deactivator"`) | [`HAX7700_desc.pdf`](hardware-resources-2026-10-27/HAX7700_desc.pdf) Spec #2 (`Matching Board: RFID7700 board`), [`detail-175.json`](hardware-resources-2026-10-27/web/detail-175.json), [`eas-public-boardTypes-BOh6laRV.js`](web-sources/eas-public-boardTypes-BOh6laRV.js) |
| **Exit Security Gate (AM + UHF RFID All-in-One)** | **HAX9370AMRFID** (*"HAX9370AMRFID Acoustic-Magnetic RFID All-in-One Device"*) | **RFID7000 V3.4** (`boardType = "7000"` -> `"7000 RFID System"`) + AM 58 kHz subsystem (`9300` family) | User hardware inspection (`RFID7000 V3.4`), [`product-detail-9370amrfid.html`](hardware-resources-2026-10-27/web/product-detail-9370amrfid.html), [`crop_HAX9370AMRFID_4.jpg`](hardware-resources-2026-10-27/web/img/crop_HAX9370AMRFID_4.jpg) |
| **Standalone UHF Reader Kit** | **HAX7000** (*"HAX7000 RFID System"*) | **RFID7000** (`boardType = "7000"` -> `"7000 RFID System"`) | [`detail-174.json`](hardware-resources-2026-10-27/web/detail-174.json), [`HAX-RFID_HAX7000.JPG`](hardware-resources-2026-10-27/web/img/HAX-RFID_HAX7000.JPG) |

**Conclusion:** Jenny's message calling the unit the *"RFID7700 Deactivator"* refers to the **internal board name (`RFID7700 board`)** and `eas-data.net` board type (`7700: "7700 RFID Deactivator"`), whereas the complete desktop glass-pad product is the **HAX7700**. They are the exact same physical unit.

---

## 2. HAX7700 Deactivator (`RFID7700 board`) — Hardware Analysis

Source: [`/home/kaizen/Downloads/HAX7700_desc.pdf`](hardware-resources-2026-10-27/HAX7700_desc.pdf) (preserved in `hardware-resources-2026-10-27/HAX7700_desc.pdf`, SHA-256 `6cee02e93988412ade73d46fe2b97fbd486aad7e9ec05fa15a7b6254609e4fe7`) and extracted high-resolution panel photographs [`hax7700-001.jpg`](hardware-resources-2026-10-27/pdf-extracted/hax7700-001.jpg) and [`hax7700-002.jpg`](hardware-resources-2026-10-27/pdf-extracted/hax7700-002.jpg).

### 2.1 Official Specifications (`HAX7700_desc.pdf`)
- **Product Name:** HAX7700 RFID Reader and Deactivator (`HAX7700 RFID Label Activator & Deactivator`, Portal ID `175`)
- **Center Frequency:** UHF `860 ~ 960 MHz`
- **Matching Internal Board:** `RFID7700 board`
- **Detection / Processing Range:** `< 60 cm` (desktop / POS counter pad)
- **Material & Color:** Glass pad top with black metal frame
- **Dimensions & Weight:** `400 × 400 × 40 mm`, `1.5 kg` (packing: `1 pcs/ctn`, `34.4 × 26.9 × 8.5 cm`, `1 kg`)
- **Tuning / Host Feature:** `RS232 cable tuning`

### 2.2 Side-Panel Connectors & Controls (Verified from `hax7700-001.jpg` & `hax7700-002.jpg`)

From left to right along the side panel of the `HAX7700`:

1. **`RS232 Tuning` Port (3-Pin Green Pluggable Phoenix / Euroblock Terminal):**
   - Although the older catalog render ([`hax7700-000.jpg`](hardware-resources-2026-10-27/pdf-extracted/hax7700-000.jpg)) showed a DB9 male socket in the D-sub chassis cutout, the actual production unit in [`hax7700-001.jpg`](hardware-resources-2026-10-27/pdf-extracted/hax7700-001.jpg) and [`hax7700-002.jpg`](hardware-resources-2026-10-27/pdf-extracted/hax7700-002.jpg) exposes a **3-pin green pluggable terminal block header** directly on the `RFID7700` PCB through the D-sub cutout.
   - In [`hax7700-002.jpg`](hardware-resources-2026-10-27/pdf-extracted/hax7700-002.jpg), the mating 3-pin green terminal plug is wired to a black RS232 cable using **three conductors (Red, Yellow, Black)** corresponding to `TX`, `RX`, and `GND` (exact pin order must be verified by continuity to DB9 pins 2, 3, and 5).
   - Visible on the PCB immediately flanking the 3-pin green connector (`hax7700-001.jpg`):
     - Left: a white 4-pin header and a **coin-cell battery holder** (RTC backup battery, matching the 7-byte `clock[7]` parameter in `hax_7k_config_st`).
     - Right: a **16-pin SOIC IC** (standard MAX232/SP3232 RS232 level-shifter package).
2. **`Volume` Trimmer:**
   - Blue PCB-mounted rotary potentiometer accessible through a square cutout, numbered `1` to `8`, adjusting the onboard buzzer volume.
3. **`Power` Input:**
   - Standard DC barrel jack next to the Volume trimmer.
4. **Main Power Switch:**
   - Red illuminated rocker switch (`O` / `-`).
5. **Mode Push-Button & Bi-Color Indicator (`Red light: Decode` / `Green light: Activate`):**
   - Stainless-steel push-button with an integrated LED ring and factory label:
     - **`Red light: Decode`** — Deactivates / decodes UHF tags placed on the pad so they pass silently through the HAX RFID gate in standalone mode.
     - **`Green light: Activate`** — Re-activates / encodes UHF tags placed on the pad so they trigger the HAX RFID gate alarm.

### 2.3 Architectural Implication for Checkout vs. Standalone Gate Mode

The `Red light: Decode / Green light: Activate` button on the HAX7700 reveals how HAX's hardware ecosystem works out of the box when no PC/database is attached:
- In **standalone hardware mode**, the `HAX9370AMRFID` gate (`RFID7000 V3.4` board) checks a specific tag state/storage pattern (likely linked to the 8-byte tag storage area exposed via `read_data` / `write_data` in `hax_7k_adapt.h`, or an EPC/PC prefix rule), and the `HAX7700` pad toggles that state between **Activated (unsold)** and **Decoded/Deactivated (sold)** at the cash desk.
- In your **database-controlled mode** ([`GATE-CHECKOUT-DESIGN.md`](GATE-CHECKOUT-DESIGN.md)), the application tracks each item's exact EPC as `UNSOLD` or `SOLD` in SQLite (`rfid7000-control`) and ignores unknown EPCs. Knowing whether the `HAX7700` can also stream or return the scanned EPC over its `RS232 Tuning` cable (or whether `card_7k.dll` drives both `7000` and `7700` boards) allows the `HAX7700` pad to serve as the desktop checkout reader as well.

---

## 3. HAX9370AMRFID Gate (`RFID7000 V3.4` Board) — Hardware Analysis

Source: [`product-detail-9370amrfid.html`](hardware-resources-2026-10-27/web/product-detail-9370amrfid.html), [`detail-93.json`](hardware-resources-2026-10-27/web/detail-93.json), and factory open-base photographs [`HAX9370AMRFID_2.jpg`](hardware-resources-2026-10-27/web/img/HAX9370AMRFID_2.jpg), [`HAX9370AMRFID_3.jpg`](hardware-resources-2026-10-27/web/img/HAX9370AMRFID_3.jpg), [`HAX9370AMRFID_4.jpg`](hardware-resources-2026-10-27/web/img/HAX9370AMRFID_4.jpg) (cropped close-ups in `web/img/crop_HAX9370AMRFID_*.jpg`).

### 3.1 Official Specifications (`HAX9370AMRFID`, Portal ID `93`)
- **Product Name:** HAX9370AMRFID Acoustic-Magnetic RFID All-in-One Device (`HAX9370AMRFID 声磁RFID一体机 超宽检测系统`)
- **Dual Technology:** AM `58 kHz` + UHF RFID `860 ~ 960 MHz` (also listed as `865.6 ~ 928 MHz` on `HAX9370RFID`)
- **AM Detection Range:** `1.8 ~ 2.2 m` (DR soft label), up to `2.6 m` (AM monster hard tag)
- **UHF RFID Detection Range:** `1.5 ~ 3.0 m` (UHF RFID tag)
- **Frame Material:** Clear acrylic pedestal with integrated AM loop coils and UHF RFID antennas
- **Power Supply:** `100–240V AC, 50/60Hz`
- **Remote Tuning / Upgrade:** Wi-Fi / Ethernet (`eas-data.net`) + local RS232 tuning

### 3.2 Internal Dual-Subsystem Base Architecture (Verified from Open-Base Photos)

Inspection of [`crop_HAX9370AMRFID_2.jpg`](hardware-resources-2026-10-27/web/img/crop_HAX9370AMRFID_2.jpg) and [`crop_HAX9370AMRFID_4.jpg`](hardware-resources-2026-10-27/web/img/crop_HAX9370AMRFID_4.jpg) shows that the pedestal base houses **two distinct electronic subsystems mounted on opposite sides of the vertical metal baseplate**:

1. **Front Side of Baseplate — AM 58 kHz Controller PCB (`9300` / `9000` family):**
   - Features two heavy copper toroidal TX/RX inductors, high-voltage film capacitors, green Phoenix screw terminals wired to the acrylic loop coils (`red/black/white/grey` leads), red status LED, and a round black piezo alarm siren mounted to the right side of the plate.
   - Note: The AM 58 kHz subsystem triggers on physical 58 kHz acoustic-magnetic DR labels/hard tags independently of UHF EPC records.
2. **Rear / Top Edge of Baseplate — UHF `RFID7000 V3.4` Controller Module (`7000` family):**
   - Visible along the top-rear of the metal mounting plate in [`crop_HAX9370AMRFID_2.jpg`](hardware-resources-2026-10-27/web/img/crop_HAX9370AMRFID_2.jpg) and [`crop_HAX9370AMRFID_4.jpg`](hardware-resources-2026-10-27/web/img/crop_HAX9370AMRFID_4.jpg), with **gold SMA coaxial jacks** feeding thin coaxial pigtails into the UHF antenna elements inside the acrylic pedestal.
   - Matches `hax_7k_config_st` in [`hax_7k_adapt.h`](decoded-utf8/7000-sdk/hax_7k_adapt.h), which defines up to 4 antenna ports (`MAX_ANTENNA_COUNT = 4`), per-antenna enable/readPower/writePower (`antenna_st`), `work_freq` region code (`1` US, `6` China, `8` EU, `10` China, `255` full band), 7-byte `clock`, 12-byte `serial_num`, and 20-byte `version`.

---

## 4. Findings from HAX's `eas-data.net` Portal Frontend Bundles (`7000` & `7700`)

33 public frontend JavaScript modules from `https://eas-data.net/sys/assets/js/` were archived in [`hardware-resources-2026-10-27/eas-data-portal-js/`](hardware-resources-2026-10-27/eas-data-portal-js/) and formatted into readable `.pretty.txt` files. Key technical findings:

1. **Complete HAX Board-Type Registry ([`eas-public-boardTypes-BOh6laRV.js`](web-sources/eas-public-boardTypes-BOh6laRV.js)):**
   ```text
   2002: "2002 People Counter"
   3200: "3200 RF Dual Economic"
   4200: "4200 RF Dual Advanced"
   4300: "4300 Metal Detector TX"
   4400: "4400 Metal Detector RX"
   4500: "4500 Magnetic Sensor"
   5003: "5003 RF Mono"
   6600: "6600 RF Deactivator"
   6700: "6700 AM Deactivator"
   7000: "7000 RFID System"          <-- HAX9370AMRFID gate's RFID7000 V3.4 board
   7700: "7700 RFID Deactivator"     <-- HAX7700 pad's RFID7700 board
   8000: "8000 AM System"
   9000: "9000 AM Economic"
   9300: "9300 AM Advanced"          <-- HAX9370 AM 58kHz subsystem
   ```
2. **Why `7000` and `7700` Use Desktop `CardMonitor.exe` Instead of the Web Waveform UI ([`modify-Ce1Tv239.js`](hardware-resources-2026-10-27/eas-data-portal-js/modify-Ce1Tv239.js.pretty.txt), [`index-DdGSGO1n.js`](hardware-resources-2026-10-27/eas-data-portal-js/index-DdGSGO1n.js)):**
   - In `modify-Ce1Tv239.js` line 13:
     `const na = ["3200", "4300", "7000", "7700", "8000"];`
   - In `easBoardListOnline` (`index-DdGSGO1n.js` lines 549–619), the portal checks whether it is running inside the embedded Windows `CardMonitor.exe` host (`typeof window.external.CloseWindow == "function"`).
   - For board types in `na` (`3200`, `4300`, `7000`, `7700`, `8000`), clicking **Connect** inside `CardMonitor.exe` calls `window.external.CloseWindow(JSON.stringify({ uid, type, server_ip }))` so that `CardMonitor.exe`'s native C++/MFC UI handles the connection directly rather than the web oscilloscope dialog (`connectDialog.vue`, which only plots analog waveforms for `4200`, `4400`, `4500`, `5003`, `9000`, `9300`).
3. **Parameter-Command Table Architecture ([`index-B9Z8IEe2.js`](hardware-resources-2026-10-27/eas-data-portal-js/index-B9Z8IEe2.js.pretty.txt), [`edit.vue_vue_type_script_setup_true_lang-e0fcwXHr.js`](hardware-resources-2026-10-27/eas-data-portal-js/edit.vue_vue_type_script_setup_true_lang-e0fcwXHr.js.pretty.txt)):**
   - HAX boards use a 1-byte hex command opcode (`commandHex`, e.g., `0xDF`, `0xBD`, `0xFD`, `0x4D`) with fixed `sendDataLength`, `revDataLength`, and `operationType` (`1 = Read`, `2 = Write`, `3 = Other`).
   - In `common.dll` ([`common-dll-inspection.json`](common-dll-inspection.json)), `hax_soft::common::CComMgr` implements this exact framing over serial or TCP:
     - `CComMgr::ProtocolConfig(unsigned char, unsigned char)`
     - `CComMgr::SetKey(bool, int, unsigned char)` and `CCodingMgr::coding(unsigned char *, int)`
     - `CCRC::calc_crc(unsigned char *, unsigned int)`, `CCRC::high()`, `CCRC::low()`
     - `CComMgr::Send(unsigned int cmd, unsigned char const *data, int len, unsigned short ...)`

4. **`CardMonitor` Installer Plugin Matrix (`hax_monitor_2.4.51.cab` from `hax_monitor.exe`):**
   - `card_7k.dll` (`10,937,168` bytes, `2026-07-22`) is the plugin for board `7000` (`RFID7000`) and exports all 13 C SDK functions (`open_tcp_server`, `start_auto_read`, `read_epc_id`, etc.), 9 `Device_*` functions, and `_QueryPluginInterface@8`.
   - `card_7k7.dll` (`10,630,480` bytes, `2026-07-22`) is the dedicated `CardMonitor` plugin for board `7700` (`RFID7700`) and exports **only** `_QueryPluginInterface@8` (it does not export the 13 standalone C SDK functions).
   - `card_9k3.dll` (`10,984,272` bytes, `2026-07-22`) is the `CardMonitor` plugin for board `9300` (the 58 kHz AM board inside `HAX9370AMRFID`).
5. **Physical `HAX7700` Internal Ethernet Converter (`USR-TCP232-E2` Observed in `hax7700-widget`):**
   - On the bench unit tested with [`/mnt/ExternalSSD/Active-Projects/geoplan/hax7700-widget`](/mnt/ExternalSSD/Active-Projects/geoplan/hax7700-widget/README.md), the Ethernet port on the `HAX7700` connects to an internal PUSR **`USR-TCP232-E2`** dual UART-to-Ethernet module at `169.254.68.93` (MAC `38:F4:06:10:5D:43`):
     - **Port 1 (`port0.json`, UART0):** `115200 8N1`, `workmodea=2` (TCP Client), factory-configured to dial `eas-data.net:8810` (retargeted to `169.254.68.94:9090` for local PC listening).
     - **Port 2 (`port1.json`, UART1):** `115200 8N1`, `workmodea=4` (TCP Server) listening on port `26`, plus WebSocket port `6432` and log port `6433`.
   - Passive connections to both Port 1 (inbound TCP from `169.254.68.93` to PC `:9090`) and Port 2 (`169.254.68.93:26` and `ws://169.254.68.93:6432/`) received **0 payload bytes** even while the `HAX7700` beeped on a tag, confirming that the `RFID7700` board does not stream unsolicited EPC frames without a host poll/inventory command.

---

## 5. Summary of All Collected Local Resources

All resources for the **HAX7700 (`RFID7700 board`)** and **HAX9370AMRFID (`RFID7000 V3.4` board)** are stored locally on this workstation:

1. **Deactivator Spec Sheet & Extracted Connector Photos:**
   - [`hardware-resources-2026-10-27/HAX7700_desc.pdf`](hardware-resources-2026-10-27/HAX7700_desc.pdf) — Official 1-page HAX7700 spec sheet (`Matching Board: RFID7700 board`, `RS232 cable tuning`, `Red light: Decode / Green light: Activate`).
   - [`hardware-resources-2026-10-27/pdf-extracted/hax7700-001.jpg`](hardware-resources-2026-10-27/pdf-extracted/hax7700-001.jpg) — Unplugged side-panel close-up (`1590×441`) showing 3-pin green Phoenix RS232 header, 4-pin internal header, coin-cell holder, 16-pin RS232 transceiver IC, Volume trimmer, DC jack, power switch, and mode button.
   - [`hardware-resources-2026-10-27/pdf-extracted/hax7700-002.jpg`](hardware-resources-2026-10-27/pdf-extracted/hax7700-002.jpg) — Labeled side-panel close-up (`1570×559`) showing the 3-wire (`Red/Yellow/Black`) `RS232 Tuning` plug connected.
2. **Gate & Deactivator Catalog Pages, API JSON, and Factory Base Photos:**
   - [`hardware-resources-2026-10-27/web/product-detail-9370amrfid.html`](hardware-resources-2026-10-27/web/product-detail-9370amrfid.html) & [`detail-93.json`](hardware-resources-2026-10-27/web/detail-93.json) — Official HAX9370AMRFID specifications and product metadata.
   - [`hardware-resources-2026-10-27/web/detail-175.json`](hardware-resources-2026-10-27/web/detail-175.json) (`HAX7700`) & [`detail-174.json`](hardware-resources-2026-10-27/web/detail-174.json) (`HAX7000`).
   - [`hardware-resources-2026-10-27/web/img/HAX9370AMRFID_1.jpg`](hardware-resources-2026-10-27/web/img/HAX9370AMRFID_1.jpg) through [`HAX9370AMRFID_4.jpg`](hardware-resources-2026-10-27/web/img/HAX9370AMRFID_4.jpg) and base close-ups [`crop_HAX9370AMRFID_2.jpg`](hardware-resources-2026-10-27/web/img/crop_HAX9370AMRFID_2.jpg) to [`crop_HAX9370AMRFID_4.jpg`](hardware-resources-2026-10-27/web/img/crop_HAX9370AMRFID_4.jpg).
3. **`eas-data.net` Cloud Portal Frontend Modules:**
   - [`hardware-resources-2026-10-27/eas-data-portal-js/`](hardware-resources-2026-10-27/eas-data-portal-js/) — 33 JS bundles + readable `.pretty.txt` extracts documenting board types, command hex structures, online relay WebSocket format, and firmware upgrade flow.
4. **SDK Source, Native x86 Binaries, and Staged Runtime (`7000-SDK-Research-2026-10-26/`):**
   - [`decoded-utf8/7000-sdk/`](decoded-utf8/7000-sdk/) — `hax_7k_adapt.h`, `7k_api_demo.cpp`, `7k_api_demo.cs`, `config.ini`.
   - [`original-runtime/`](original-runtime/) & [`sdk-staging/`](sdk-staging/) — `card_7k.dll` (v2.0.1.0), `common.dll` (v2.0.6.2), `adapt_for_imports.dll` (v1.1.1001.0), 9 board INI files (`3200.ini`, `4200.ini`, `4400.ini`, `4500.ini`, `5003.ini`, `6700.ini`, `9000.ini`, `9300.ini`, `config.ini`), and x86 VC++/MFC runtime libraries.
5. **Deactivator Overlay Widget Project (`hax7700-widget` on External SSD):**
   - [`/mnt/ExternalSSD/Active-Projects/geoplan/hax7700-widget/`](/mnt/ExternalSSD/Active-Projects/geoplan/hax7700-widget/README.md) — C# / .NET 10 + Avalonia desktop scan-count overlay widget (`Hax7700Widget`), 32-bit Windows `card_7k.dll` listener (`Card7kListener.cs`, `Hax7700Widget.Listen`), SDK-free `USR-TCP232-E2` Ethernet probe (`Hax7700Widget.Probe`), hardware notes (`docs/hardware-research.md`, `docs/supplier-questions.md`), and staged x86 DLLs (`.tools/sdk-win-x86/`).
6. **Gate & Checkout Control Application (`rfid7000-control/`):**
   - [`/home/kaizen/Desktop/rfid7000-control/`](/home/kaizen/Desktop/rfid7000-control/README.md) — Working Linux/Windows SQLite inventory, checkout, gate-decision service, and RS232 capture tool.

---

## 6. Key Technical Questions to Send to Jenny / HAX Engineer

Because both the **HAX7700 (`RFID7700 board`)** and **HAX9370AMRFID (`RFID7000 V3.4` board)** use a 3-pin RS232 tuning interface and proprietary binary framing (and the packed Windows `common.dll` crashes under Linux Wine during initialization), we need the following specifics from Jenny's engineering team to complete direct Linux RS232 integration:

1. **RS232 Pinout & Serial Framing for Both Boards (`RFID7000 V3.4` and `RFID7700`):**
   - Pin assignment (`TX`, `RX`, `GND`) on the 3-pin green terminal block (`Red / Yellow / Black` wires in `HAX7700_desc.pdf`) and on the `RFID7000 V3.4` board inside the `HAX9370AMRFID` gate.
   - Confirmed baud rate (e.g., `115200`), data bits, parity, and stop bits.
2. **RS232 Command Protocol Manual (or Unpacked/Linux SDK) for `RFID7000 V3.4` & `RFID7700`:**
   - Frame header, length, command byte (`commandHex`), payload, CRC (`CCRC`), and any XOR/key encoding (`CCodingMgr`) for:
     - Reading EPC inventory (`read_epc_id`)
     - Disabling autonomous gate alarming while keeping EPC reading active
     - Triggering a host-controlled gate alarm pulse (`enable_alarm`)
3. **Interaction Between `HAX7700` (`Red light: Decode` / `Green light: Activate`) and `RFID7000 V3.4`:**
   - What exact tag memory bank / offset / 8-byte `hax_7k_data` value does the `HAX7700` write when switching a tag between **Activate (Green)** and **Decode/Deactivate (Red)**?
   - Can the `HAX7700` report scanned EPCs to the checkout PC over its `RS232 Tuning` cable while in Decode mode?
   - On the `HAX9370AMRFID` gate, can the UHF `RFID7000 V3.4` board's autonomous alarm be disabled independently of the 58 kHz AM board, or how are the AM and RFID alarm relays/buzzers linked in the base?
