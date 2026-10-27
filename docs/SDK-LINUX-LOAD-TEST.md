# Linux SDK execution check — 26 October 2026

The current SDK load test **fails before an inventory API can be called**. No EPC was captured or enrolled. This result applies to this Linux/Wine environment and these exact vendor binaries; native Windows remains untested.

## Environment and result

- Linux Mint 22.3, x86_64; USB serial adapter `/dev/ttyUSB0`, FTDI serial `BG04PZ5M`.
- Isolated Wine 11.0 files extracted from official WineHQ Ubuntu noble packages under `runtime-tools/wine-root/`. Nothing was installed into system package directories.
- Private 32-bit prefix `runtime-tools/wine-sdk32-prefix/`; no COM-port symlinks were present during the loader checks.
- Official Python 3.12.10 embedded Windows x86 distribution under `runtime-tools/python-win32/`.
- Required 32-bit Linux runtime/font/X11 libraries were downloaded from the configured Ubuntu repositories and extracted into the same private directory. Only the local Wine ELF interpreter/RPATH was adjusted to use the private Linux loader.
- `wine cmd /c ver` successfully reported Windows 10.0.19045.
- The official Microsoft x86 `mfc140.dll` loaded successfully.
- Loading the supplied `common.dll` terminated the Python process with exit code 1, before the probe could report successful loading. The trace recorded illegal-instruction and repeated execution-access exceptions, followed by stack-overflow exception `c00000fd` during exception handling.
- Loading the optional `adapt_for_imports.dll` also terminated an earlier probe. It is not a visible direct dependency of card_7k.dll, so the final core probe excluded it and still failed at common.dll.

The vendor files have packed/protected layouts. A compatibility failure during their initialization is a plausible explanation, but the trace does not establish the exact cause. It does not prove the DLLs are defective on Windows.

A process-only DEP compatibility experiment returned false with Win32 error 87 and did not change the outcome. No operating-system-wide mitigation or security settings were changed. Further protection bypass or vendor-binary modifications were not attempted.

## Evidence

- `runtime-tools/sdk-load-probe-x11.stdout.log`: MFC successful load, followed by the last stage `loading common.dll`.
- `runtime-tools/sdk-load-probe-x11.stderr.excerpt.log`: bounded exception-trace excerpt. The repetitive full trace was reduced after recording its original size/hash in `sdk-linux-load-result.json`.
- `runtime-tools/sdk-load-probe-compat.stdout.log` and `.stderr.log`: final process compatibility check.
- `sdk-linux-load-result.json`: machine-readable outcome and original log metadata.
- `/home/kaizen/Desktop/rfid7000-control/scripts/windows_sdk_probe.py`: load-only probe, usable with a 32-bit Python process on native Windows. It calls no exported device APIs.

## Hardware and database boundary

Two earlier receive-only serial captures at user-confirmed 115200 baud, with 8N1 framing, received zero bytes. No inventory request, alarm command, tag write or firmware command was sent. A gate's own alarm/light proves local detection, but does not establish transmission of an EPC to this computer.

The local database remains available at `http://127.0.0.1:7000`. The user's instruction is to enroll verified reader EPCs as unsold during the requested test, while preserving existing sold states. No raw bytes, simulated EPCs, or guessed identifiers are enrolled. The normal rule to ignore unknown gate EPCs remains unchanged.

## What enables the next real scan

Either a documented RFID7000 RS232 inventory request/response protocol (including framing and checksum) for a native Linux adapter, or a working vendor-supported SDK/runtime on the current OS. An unprotected compatible DLL build or official Linux SDK may resolve this boundary. A native Windows x86 loader test can also distinguish a Wine-specific failure, but Windows is not currently available on the user's computer.

Alarm control separately requires the semantics for disabling autonomous alarms while continuing to read and for issuing/resetting a host-controlled alarm. Successful EPC decoding alone will not establish these controls.

Sources for the runtime distributions: [WineHQ Ubuntu packages](https://dl.winehq.org/wine-builds/ubuntu/), [official Python 3.12.10 files](https://www.python.org/ftp/python/3.12.10/), [Microsoft x86 runtime downloads](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist/). The process compatibility API is documented in [SetProcessDEPPolicy](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setprocessdeppolicy).
