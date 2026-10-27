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
cd /home/kaizen/Desktop/hax7700-widget-py
./start.sh
```

## Run on Windows

Double-click `start-windows.bat` (or run `py -3-32 -m hax7700_widget` for 32-bit `card_7k.dll` SDK polling).

## Run Unit Tests

```bash
python3 -m unittest discover -s tests -v
```
