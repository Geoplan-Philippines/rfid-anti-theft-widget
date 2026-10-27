# HAX7700 / RFID7700 questions for Jenny

Draft for the operator to include in their next supplier message; not sent.

We are building a small PC overlay that counts unique items read by the HAX7700. The available one-page datasheet lists an RFID7700 board, 860–960 MHz, detection under 60 cm, and “RS232 cable tuning”. We do not have a HAX7700 manual, SDK, or tag-message protocol.

Please confirm:

1. Can the HAX7700/RFID7700 expose individual EPC/tag-read events to a PC, and over which physical/data interface? Please distinguish tag-data output from tuning access.
2. The Ethernet cable plugs directly into the HAX7700 reader/deactivator. Its endpoint at 169.254.68.93 reports module name TCP232-E2, two UART channels, and accepts TCP connections on port 26. Which UART connects to the RFID7700 board, and which network interface carries its tag data? Is this separate from the documented C215 module at 10.10.100.254?
3. If TCP tag-data output is supported, what are the client/server role, device address, data port, and commands needed to enable reporting? If serial tag-data output is supported, what are the wiring, baud rate, parity, data bits, and stop bits?
4. Please provide the communication protocol, a sample tag-read packet and its EPC field/checksum, or an SDK/sample application if one exists. We need to distinguish real tag reads from status and tuning messages.
5. Is Cardmonitor the correct application/version for this HAX7700? If it requires a tuning account or module login, please supply the relevant access details through the usual private channel and identify which component each login belongs to.

The Ethernet module's UART0 settings list remote destination eas-data.net:8810; UART1 lists local server port 26. Please confirm the purpose of each channel and whether port 26 can carry HAX7700 tag-read events without changing the existing socket configuration.

The physical unit reacts when a tag is presented, but the widget and a separate TCP receiver see zero payload bytes on port 26. The converter's WebSocket interface at port 6432 also accepts a connection but supplied zero payload bytes during a receive-only test. Please confirm the physical wiring/channel for RFID7700 and whether an inventory, subscription, or reporting command is required before tags are sent to the PC. We have not sent unknown reader commands or changed converter settings for these receive-only tests.

The C215 setup login and Cardmonitor tuning account have not been established as HAX7700 credentials. The HAX9370AMRFID gate's “7000” board is separate from the reader's RFID7700 board.
