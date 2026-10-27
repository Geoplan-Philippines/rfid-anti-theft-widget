# SDK-free HAX7700 investigation

The SDK is not a prerequisite for a C# integration. We need actual tag-read messages and the correct reporting behavior. The floating counter does not yet decode HAX7700 messages. The probe added here provides a repeatable way to inspect the Ethernet converter and capture real data for a decoder.

The hardware and vendor application were unavailable when this probe was implemented. Its transport and inspection behavior were tested against local mock servers. It has not yet been run against the reader.

## Capture both existing interfaces

With the reader connected and powered, run on Linux:

```bash
./artifacts/linux-x64/Hax7700Probe capture --host 169.254.68.93 --seconds 60 --output captures
```

On Windows, open a terminal in the extracted preview folder:

```powershell
.\Hax7700Probe.exe capture --host 169.254.68.93 --seconds 60 --output captures
```

Present one known tag several times, remove it, and present a second tag. The probe receives TCP port 26 and WebSocket port 6432 concurrently, using the settings observed on this particular unit. It sends no RFID inventory, tag-write, activation, or deactivation commands. WebSocket handshaking uses the standard network protocol; it does not send serial application messages.

The output JSONL file records timestamps, transport identity, complete received bytes in hex, and WebSocket fragment boundaries. TCP read boundaries are not packet/frame boundaries. A final record reports payload-byte totals, not tag counts. Files have private permissions on Linux and a 16 MiB size limit. Captures can contain actual tag identifiers; they do not contain the web-login password.

Capture exit codes:

- `0`: some payload data was captured. This does not establish that it contains EPC reads.
- `2`: a connection was established, but no payload arrived.
- `3`: no capture connection was established.
- `4`: the capture file reached its size limit and recording stopped.

Ports can be changed using `--tcp-port` and `--websocket-port`. Set either to `0` to disable that transport. Use `--help` for all options. These port defaults are from the observed bench configuration, not a claim about HAX factory settings.

The Linux USB Ethernet profile uses `169.254.68.94/24` and is saved with automatic connection enabled for the tested adapter. A Windows PC needs its own compatible Ethernet configuration. The device's observed address is `169.254.68.93`; reconnecting or resetting equipment can change its configuration.

## Inspect the converter channels

```bash
./artifacts/linux-x64/Hax7700Probe inspect --host 169.254.68.93 --username admin
```

On Windows:

```powershell
.\Hax7700Probe.exe inspect --host 169.254.68.93 --username admin
```

The command first checks reachability. If the endpoint requires authentication, it prompts for the device password locally with hidden input. The password is never accepted as a command argument, printed, or written to disk. `--password-stdin` supports a secure pipe for automated tests; avoid putting real passwords in shell command history.

The inspector reads known converter JSON endpoints and prints only selected non-credential fields. It identifies each channel's network role, remote destination, local port, serial parameters and available Ethernet counters. It selects the web status view for each channel using the same endpoint as the manufacturer's interface, then restores the previous view. It does not save UART/network settings, reboot the module, or send commands to the RFID board.

The status counters describe converter Ethernet traffic, not the number of scanned items. Unsupported counters/views are reported explicitly. The source of these fields and mode mappings is the manufacturer's [published web-interface package](https://www.pusr.com/support/downloads/Customized-Webpage-USR-TCP232-E2-ED2-Customized-Webpage.html).

## Findings to verify when the reader returns

The probe also supports an inbound TCP listener for a converter channel configured to connect to the PC:

```bash
./artifacts/linux-x64/Hax7700Probe listen --host 169.254.68.93 --bind 169.254.68.94 --listen-port 8811 --seconds 60 --output captures
```

Here `--host` is the expected device IP and `--bind` is the PC's Ethernet IP. Connections from other device addresses are rejected. This command prepares the PC's receiver; it does not redirect the converter away from its existing destination. Any future converter routing test needs a configuration backup and restoration after the test. The listener sends no serial application data. Its default bind address is loopback, so a network-facing address must be supplied explicitly.

The published converter interface maps `workmodea=2` to TCP client and `workmodea=4` to TCP server. Combined with the configuration read from the unit, the first channel connects outward to `eas-data.net:8810`; the second is configured as a server on port 26. An outbound destination is not an inbound data port on the reader. The physical UART assignment to the RFID7700 board is still unverified.

`eas-data.net` is HAX’s remote-tuning dashboard, not a documented item-count feed. Leave UART0 pointed at that host. The capture command below listens on the local interfaces only and does not change converter settings.

The published WebSocket page forwards incoming serial bytes directly. Its direction selector must be verified against the installed firmware before assigning captured data to a physical UART.

If captures contain data, compare repeated reads of one known EPC and a different EPC, identify framing and checksums, and implement/test `ITagDecoder` against those captured messages. If both interfaces remain empty, check the physical serial-channel wiring and the reader's required inventory/reporting command with the supplier or a working vendor application. A beep/light alone cannot supply a unique tag identifier.

## Build and verify

```bash
dotnet build Hax7700Widget.slnx -c Release
python3 checks/probe_smoke.py
bash scripts/publish.sh win-x64
bash scripts/publish.sh linux-x64
```

The probe smoke check requires Python with the `websockets` package in the development environment. The published probe executables themselves require neither Python nor a separate .NET installation. Checks cover authenticated inspection, mode/counter extraction, credential redaction, view restoration, fragmented TCP data, binary/text WebSocket data, device-initiated TCP data, private capture files, and distinct empty/disconnected results. They use loopback mock devices and send no traffic to the HAX hardware.
