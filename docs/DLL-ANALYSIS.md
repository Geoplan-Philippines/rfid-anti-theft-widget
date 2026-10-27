# card_7k.dll inspection

Updated 26 October 2026 after the native library was supplied separately.

**Later update:** common.dll and the runtime/config ZIP have now been supplied. The exact required HAX export matches; Microsoft MFC support has also been staged from the official redistributable. See [SDK-DEPENDENCIES.md](SDK-DEPENDENCIES.md) for the current dependency status. The original missing-file findings below describe the earlier inspection phase.

**Execution update:** a private Wine 11/x86 loader check successfully loads Microsoft MFC, then terminates during common.dll initialization, before card_7k.dll APIs can be called. Native Windows remains untested. See [SDK-LINUX-LOAD-TEST.md](SDK-LINUX-LOAD-TEST.md). The byte-only scope below applies to the original static inspection.

**The supplied DLL fills the main runtime-file gap. It is a native Windows x86 library, reports version 2.0.1.0 and company HAX, and exports all 13 names declared in the SDK header.** Its visible imports also require a matching vendor `common.dll`, which was not in the ZIP or among the supplied runtime files. The exact connection ABI and device behavior remain unresolved.

This analysis reads file bytes only. The DLL was not loaded or executed. No device or remote endpoint was contacted.

## File identity

- Input: `/home/kaizen/Downloads/card_7k.dll`.
- Preserved copy: `original-runtime/card_7k.dll`.
- Exact size: **10,937,168 bytes**, approximately 10.43 MiB.
- SHA-256: `05205fe38bd368609804a516174b9e35a99d7bf0df4f8c83ea77893f16dc6abf`.
- Format: **PE32 DLL, Intel i386**, machine `0x014c`.
- CLR directory: absent. This is a native library, not a managed .NET assembly.
- File and product versions: **2.0.1.0**, matching the string resources and fixed version structure.
- Company: **HAX**. Product name and file description: **hax_soft**.
- Copyright metadata: `Copyright 2016 HAX`.
- COFF timestamp: **2026-07-22 07:55:51 UTC**. This is mutable file metadata, not a verified release date.
- Linker metadata: **14.51**. This does not identify the exact runtime package independently.
- Preferred image base: `0x10000000`. Size of the mapped image: `0x0105a000` bytes.
- A certificate table exists. Its signature, digest, timestamp and trust chain were not verified; no authenticity conclusion is based on its presence.

The metadata further supports the HAX identification. Metadata and matching names do not establish firmware compatibility, provenance, or a matching function signature.

## Export comparison

There are **23 named exports**. **13 of 13 expected header names are present; none are missing.**

The original SDK functions are:

```text
close
close_tcp_server
enable_alarm
get_config
open
open_tcp_server
read_data
read_epc_id
set_config
start_auto_read
stop_auto_read
write_data
write_epc_id
```

Ten additional names are present:

```text
Device_Dispose
Device_GetStatus
Device_GetVersion
Device_Init
Device_KillCode
Device_RegisterCallback
Device_SetConfig
Device_StartScan
Device_StopScan
_QueryPluginInterface@8
```

No declarations for these ten functions were supplied. Their names alone do not reveal arguments, return types, structures, ownership, or semantics. In particular, `Device_KillCode` does **not** establish a Gen2 tag-kill function, and the plugin name does not establish an externally supported plugin ABI. Do not call these by guessing their declarations.

The machine-readable inventory includes each export's ordinal and RVA. These are details of this file build, not a stable API contract.

## Dependencies visible in the static import table

**Vendor dependency: `common.dll`.** The visible imported C++ symbol is:

```text
?clear@CCurrentDeviceMgr@cdm@hax_soft@@QAEXXZ
```

This is a specific HAX-namespaced symbol, so an unrelated file also named `common.dll` is not a substitute. Obtain the matching x86 vendor library from the same SDK/runtime distribution. It may have further dependencies of its own.

**Microsoft C++ runtime imports:** `MSVCP140.dll` and `VCRUNTIME140.dll`.

**Universal CRT API-set imports:**

```text
api-ms-win-crt-heap-l1-1-0.dll
api-ms-win-crt-runtime-l1-1-0.dll
api-ms-win-crt-string-l1-1-0.dll
api-ms-win-crt-stdio-l1-1-0.dll
api-ms-win-crt-filesystem-l1-1-0.dll
api-ms-win-crt-math-l1-1-0.dll
api-ms-win-crt-convert-l1-1-0.dll
api-ms-win-crt-locale-l1-1-0.dll
```

**Windows system imports:** `KERNEL32.dll` and `USER32.dll`.

For a Windows x86 application, use the supported **x86 Microsoft Visual C++ v14 Redistributable** appropriate to the application and vendor requirements. Microsoft's current guidance requires a redistributable at least as recent as the build tools used, with architecture matching the application. Do not collect individual CRT DLLs from download sites. The redistributable does not supply the vendor's `common.dll`. [Microsoft runtime deployment guidance](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist/).

This is a visible static dependency list, not a complete runtime trace. The image's loader may reconstruct imports or dynamically load additional libraries during initialization. No successful Windows loader test has been performed.

## Why the binary does not settle the ABI conflict yet

The SDK header uses string connection IDs, while the C++ demo uses numeric device identifiers and a different second argument to `open`. Both declare export names such as `open` and `read_epc_id`; the export table confirms the names but carries no C function type declarations. It cannot tell us which variant is authoritative.

There is a further concrete limit in this file: all 23 exported function RVAs point into `.text`, but that section has **zero raw bytes on disk**. The original `.rdata` and `.data` sections also have zero raw size. Most file content is in a large executable `.SM~` section, and the PE entry point is in that section. This is consistent with a packed or protected image that materializes code during initialization; the precise mechanism and product are unconfirmed.

Consequently, ordinary file-offset disassembly cannot inspect the exported implementations in this file. This observation does not establish a malicious file or a faulty SDK; it explains why the static inspection cannot recover the signatures or proprietary protocol. The DLL has not been unpacked, modified or run. [Microsoft PE format reference](https://learn.microsoft.com/en-us/windows/win32/debug/pe-format).

## What is still required

1. **Matching x86 `common.dll`** and the complete dependency package for this build.
2. **The authoritative header and buildable examples for card_7k.dll 2.0.1.0**, resolving `connID` versus numeric `dev` and confirming calling conventions.
3. Declarations and support status for the **ten additional exports**, if they are intended for external use.
4. Device hardware/firmware compatibility and serial/TCP setup instructions.
5. The previously identified EPC length, tag-selection, memory-bank, alarm, region/power/clock and callback-lifecycle definitions.
6. A Windows x86 load check followed by an inventory-only hardware test. The supplied C++ example still performs writes and alarms, and its conflicting casts still need resolution.

The original source defects remain: C# delegates are not rooted correctly, EPC formatting drops zero padding, successful startup never reaches normal cleanup, and the C++ demo ignores intermediate errors before subsequent writes. Supplying a runtime does not repair those examples.

## Evidence and reproducibility

- `dll-inspection.json`: PE metadata, version resources, imports, exports, section layout and source comparison.
- `dll-objdump-pe.txt` and `dll-objdump-sections.txt`: independent GNU objdump output.
- `inspect_pe.py`: standard-library, read-only PE32 parser used for this inspection. It neither imports nor loads the DLL.
- `original-runtime/card_7k.dll`: preserved input copy, verified by SHA-256.

Reproduce the parsing with:

```sh
python3 inspect_pe.py /home/kaizen/Downloads/card_7k.dll dll-inspection.json
```

The report's enriched comparison fields can also be reconstructed by comparing parsed export names with `api-inventory.json`. All findings describe this exact file hash; a different runtime build needs a fresh comparison.
