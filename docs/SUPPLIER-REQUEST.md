# HAX7000 SDK completion request

Updated after receiving card_7k.dll, common.dll, adapt_for_imports.dll and the runtime/config ZIP. Draft only; no message has been sent.

Suggested recipient: HAX technical support via the supplier who provided the device, or the current official contact listed at [haxeas.com/contact.html](https://www.haxeas.com/contact.html): `joyce@haxeas.com`, WhatsApp/mobile `+86 13823535409` (verified 26 October 2026).

Subject: HAX7000 / card_7k.dll 2.0.1.0 — matching common.dll, API contract and communication manual

Hello,

We received the HAX7000 source examples and card_7k.dll separately. Static inspection confirms a native Windows x86 DLL reporting HAX version 2.0.1.0. All 13 header export names are present. The newly supplied common.dll 2.0.6.2 now matches the visible import from card_7k.dll, including `?clear@CCurrentDeviceMgr@cdm@hax_soft@@QAEXXZ`. The supplied DLL SHA-256 is `05205fe38bd368609804a516174b9e35a99d7bf0df4f8c83ea77893f16dc6abf`.

Our intended application keeps one database record per item EPC. Checkout marks an EPC sold. At the gate we want alarms for registered unsold EPCs only; sold EPCs and EPCs outside our database must be ignored. We are told automatic alarms can be disabled while reading continues. Please confirm how software can then trigger a timed alarm and reset it without restoring autonomous alarming. A mixed group containing a registered unsold item must still alarm even if sold items are present.

Our development and current deployment computer runs Linux only, with Windows compatibility also desired. We selected RS232. Please prioritize a Linux SDK or documented RS232 protocol, and supply the connector pinout, cable wiring, electrical levels, baud rate, data bits, parity, stop bits and flow control requirements. If only the Windows runtime is supported, please state any supported compatibility route and its limits.

Please provide:

1. Confirmation that the supplied x86 common.dll 2.0.6.2 and dependency bundle match card_7k.dll 2.0.1.0, required Microsoft runtime version, buildable C#/C++ projects, supported firmware/hardware matrix, and redistribution terms. Please confirm x86, x64, and Linux support.
2. The authoritative declarations for that exact DLL. Our header declares `open(const char *connID, unsigned int socket, int time_out)`, while the C++ demo casts it as `open(unsigned int dev, hax_dev_type type, int time_out)`. Most direct functions also disagree on string versus numeric device identifiers.
3. The serial and TCP communication manual, including physical pinout/electrical standard, baud/parity/stop settings, network mode, host listener configuration, handshake, framing/checksum, keepalive, reconnect, command responses, and detailed errors.
4. Confirmation of Cdecl, one-byte structure packing, callback thread/concurrency/reentrancy rules, connection-ID lifetime, auto-read behavior across multiple readers, and whether stop/close waits for in-flight callbacks.
5. EPC semantics: units of `len`, PC/CRC byte order, supported EPC lengths, handling beyond 32 tags, and the rules used to select a tag for EPC writing.
6. The bank, address, password, and target-selection behavior for the eight-byte `read_data`/`write_data` API. Please explain any relation to sale state or activation/deactivation.
7. Exact `enable_alarm` semantics, duration, disable/reset/status operations, and how alarm events are reported.
8. Region-code/channel tables (including codes 6 and 10), the appropriate approved configuration for the deployment country, RF power units/ranges, antenna indexing, and clock-byte encoding.
9. Whether `config.ini` is consumed by `card_7k.dll`, CardMonitor, or both; whether `eas-data.net:8820` is required or optional for local integration.
10. Any extended API for per-tag antenna, RSSI, timestamps, direction, reader buffering, GPIO, or POS/sale-state integration.

Please also provide declarations and external support status for the ten additional exports: `Device_Dispose`, `Device_GetStatus`, `Device_GetVersion`, `Device_Init`, `Device_KillCode`, `Device_RegisterCallback`, `Device_SetConfig`, `Device_StartScan`, `Device_StopScan`, and `_QueryPluginInterface@8`.

We can provide the device serial number, board revision, firmware, and exact intended application as they are identified. We would like to begin with a minimal inventory-only example before exercising configuration writes, tag writes, or alarms.

Thank you.
