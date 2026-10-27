# Hardware and framework research

Checked 2026-10-24. Public documentation is distinct from the equipment details provided by the operator.

## HAX7700

[HAX's official catalog](https://www.haxeas.com/products.html?cat=rf) lists the **HAX7700 RFID Label Activator & Deactivator**, **HAX7000 RFID System**, and **HAX9370AMRFID AM + RFID Integrated Acrylic Alarm System**. The catalog establishes product identities, but the pages reviewed do not supply a HAX7700 network protocol or SDK.

The operator's summary of the available one-page HAX7700 datasheet lists 860–960 MHz, an RFID7700 board, a detection range under 60 cm, and “RS232 cable tuning”. The operator found no HAX7700 manual or SDK in the supplied files. Cable tuning does not establish how a PC can obtain individual tag IDs. LAN/TCP was the requested integration approach; HAX7700 tag-data output over that interface remains unverified.

The HAX9370AMRFID gate uses the “7000” RFID board. The HAX804 is a magnetic hard-tag detacher. These are separate from the HAX7700/RFID7700 integration.

TCP is compatible with C# through Microsoft's built-in [`TcpClient`](https://learn.microsoft.com/en-us/dotnet/api/system.net.sockets.tcpclient?view=net-10.0) and [`NetworkStream`](https://learn.microsoft.com/en-us/dotnet/api/system.net.sockets.networkstream?view=net-10.0) APIs. Ethernet/TCP does not define the HAX application message format. The device IP, port, client/server role, and HAX protocol implementation remain necessary. This build acts as a TCP client; that role must be checked against the reader configuration.

## Direct Ethernet observations

A directly connected Ethernet endpoint advertised 169.254.68.93 with MAC 38:F4:06:10:5D:43. A temporary Linux Ethernet profile using 169.254.68.94/24 allowed three successful pings. TCP port 80 served an HTTP Basic authentication challenge. The other TCP ports checked did not accept connections; this was not an exhaustive port scan.

These observations establish network reachability only. The endpoint's identity, relationship to the HAX7700/RFID7700 board, and ability to deliver tag data have not been established. Port 80 has not been identified as a scan-data port.

After a successful login through a local password form, the endpoint's configuration reported the module name `TCP232-E2` and two serial ports. PUSR's [TCP232-E2 product documentation](https://www.pusr.com/products/112.html) describes a dual UART-to-Ethernet converter. The configured module name alone does not establish the exact physical board or which serial port is wired to HAX hardware.

Read-only checks found TCP ports 26, 6432, and 6433 accepting connections. The retrieved settings list 6432 as the WebSocket port and 6433 as the WebSocket log port. UART0's configuration lists remote host `eas-data.net`, remote port 8810, and `workmodea=2`. UART1 lists `lports=26` and `workmodea=4`. The numeric work-mode meanings have not been independently decoded for this firmware; port 26's ability to accept a TCP client was tested directly. Both serial configurations report 115200 baud and 8 data bits. No serial/socket settings were changed.

These details establish a usable TCP connection to the Ethernet module, not the HAX tag-message format or physical channel assignment. A passive receive check is required before treating port 26 as a candidate tag-data path. PUSR provides a [TCP232-E2/ED2 manual](https://www.pusr.com/uploads/20230622/USR-TCP232-E2-ED2-User-Manual-V1.0.0-20230622124929.pdf); this is a converter manual, not a HAX7700/RFID7700 protocol manual.

A 45-second passive connection to port 26 received zero bytes. No application commands were sent. This does not establish the absence of tags: the serial channel assignment, reader operating state, and any required inventory/reporting command remain unknown. The authenticated inspection session was closed, and temporary configuration responses containing credential fields were removed.

After the operator replugged the hardware, the USB Ethernet adapter had no IPv4 address because the bench profile was disconnected with automatic connection disabled. The profile `HAX7700 direct link` was then saved with automatic connection enabled, priority 20, and bound to adapter MAC FC:19:28:64:35:80. It uses PC address 169.254.68.94/24 and no default route. Reactivation restored two successful pings and a TCP connection to 169.254.68.93:26 in approximately 15 ms. Automatic reconnection is configured; a subsequent physical replug has not been tested. The widget can retry Connect without restarting.

When the operator reported zero bytes while scanning, the widget had an established TCP connection to port 26. Two fresh pings and a fresh TCP connection also succeeded. A separate 25-second receive-only connection to port 26 received zero payload bytes. The operator confirmed the physical unit reacts with a beep or light, which does not establish that it emits EPC messages on the connected serial channel.

The converter manual documents a WebSocket-to-serial interface on configurable port 6432. A standard WebSocket connection to ws://169.254.68.93:6432/ succeeded; a 30-second receive-only check received zero payload bytes. No application messages or reader commands were sent, and no converter settings were changed during these checks. The selected WebSocket channel, physical wiring to RFID7700, and any command needed to enable tag reporting remain unverified.

The operator subsequently confirmed that the Ethernet cable plugs directly into the HAX7700 reader/deactivator. This identifies the physical unit by the operator's observation; its internal UART-to-RFID7700 wiring and the correct tag-data channel still require confirmation. A hardware beep/light is not sufficient evidence that EPC/tag-read messages are being emitted on either tested network interface.

Further offline investigation used PUSR's [published E2/ED2 web-interface source](https://www.pusr.com/support/downloads/Customized-Webpage-USR-TCP232-E2-ED2-Customized-Webpage.html). Its serial-page options explicitly map mode 2 to TCP client and mode 4 to TCP server. This resolves the earlier numeric-mode ambiguity: the retrieved first-channel settings point outward to eas-data.net:8810, and the second channel listens on port 26. The source also documents the channel status-view endpoint, `/por.cgi?port=N`, followed by runtime counters from `/temp.json`.

An SDK-free probe was implemented using these documented read paths and standard TCP/WebSocket receivers; see [SDK-free testing](sdk-free-testing.md). The hardware and Cardmonitor application were unavailable for this phase, so the new utility is validated against loopback mock devices, not the reader. No HAX command format has been inferred or implemented without sample data.

HAX’s [remote-management page](https://www.haxeas.com/feature-remote.html) identifies eas-data.net as the customer web dashboard for board status, remote tuning, people-flow stats, and firmware updates. On 2026-10-24 that name resolved to 8.212.45.22. The page does not publish an EPC or tag-read API. UART0’s client connection to eas-data.net:8810 therefore matches the existing remote-management path. Do not retarget that socket to this PC in order to count items: that would drop the unit’s current cloud connection and still would not supply a verified tag format. Port 26 remains the local receive-only candidate, and it delivered zero payload bytes while the unit beeped.

The operator separately identified C215 Wi-Fi module setup documentation at 10.10.100.254, with module-specific login credentials. Those credentials are not established as a HAX7700 login. Cardmonitor's cover note requests a tuning account, but the account and applicability to HAX7700 were not supplied. Do not infer a shared login or supported tag-data interface from either document.

Questions for the supplier are recorded in [supplier-questions.md](supplier-questions.md).

## Chainway C72

The [official C72 product page](https://www.chainway.net/Products/Info/30) identifies the C72 as an Android UHF RFID handheld. The [official support page](https://www.chainway.net/Support/Info/10) lists Android Studio and Xamarin SDK downloads.

The C72 belongs to the team's R&D equipment, not HAX. Running software on its Android device and showing an overlay on a Windows PC are separate applications / integrations. An old Xamarin download does not by itself establish support for a current .NET Android binding. No C72 integration is included or assumed here.

## C#/.NET and Windows output from Linux

[Avalonia's Windows guide](https://docs.avaloniaui.net/docs/platform-specific-guides/windows) explicitly supports cross-compiling Windows builds from Linux without a Windows-specific .NET workload. [Window management](https://docs.avaloniaui.net/docs/app-development/window-management) documents topmost windows, manual placement, and platform limitations.

[Microsoft's publishing guide](https://learn.microsoft.com/en-us/dotnet/core/deploying/) describes self-contained deployment, which includes the .NET runtime. The [single-file deployment guide](https://learn.microsoft.com/en-us/dotnet/core/deploying/single-file/) explains that published binaries target a specific OS / architecture.

This implementation therefore uses .NET 10 + Avalonia, targets `win-x64` for the normal Windows package, and uses a self-contained single-file publish with native-library extraction. This is ordinary .NET publishing, not Native AOT, an installer, or a signed release. Final Windows desktop and physical HAX7700 validation must run on the target machine.
