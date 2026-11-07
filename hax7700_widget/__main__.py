"""CLI entry point for the HAX7700 Pad + HAX7000 RFID Gate Controller widget."""

from __future__ import annotations

import argparse
from pathlib import Path

from .core import ItemDatabase, RfidGateController, ScanSession, TcpDeactivatorListener
from .gui import run_gtk_widget, run_tk_widget


def main() -> int:
    root_dir = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(
        description="HAX7700 Pad Counter + SQLite Items Table (sold: true/false) + HAX7000 RFID Gate Controller"
    )
    parser.add_argument("--port", type=int, default=9090, help="Inbound TCP port for HAX7700 Pad (default: 9090)")
    parser.add_argument(
        "--gate-port",
        type=int,
        default=9000,
        help="Inbound TCP port for HAX7000 RFID Gate ServerControl/Alarm (default: 9000)",
    )
    parser.add_argument(
        "--serial",
        default=None,
        help="RS232 serial port (e.g. /dev/ttyUSB0 on Linux or COM3 on Windows; auto-detected if omitted)",
    )
    parser.add_argument(
        "--db",
        default=str(root_dir / "items.db"),
        help="SQLite database file for items table (default: items.db)",
    )
    parser.add_argument(
        "--sdk-dir",
        default=str(root_dir / "sdk-win-x86"),
        help="Directory containing 32-bit Windows card_7k.dll + common.dll (v2.1.2.0)",
    )
    parser.add_argument(
        "--capture-dir",
        default=str(root_dir / "captures"),
        help="Directory for raw TCP/RS232 packet logs",
    )
    args = parser.parse_args()

    sdk_dir = Path(args.sdk_dir)
    item_db = ItemDatabase(db_path=args.db)
    session = ScanSession(item_db=item_db)
    listener = TcpDeactivatorListener(session=session, capture_dir=args.capture_dir)
    gate = RfidGateController(
        item_db=item_db,
        sdk_dir=sdk_dir,
        capture_dir=args.capture_dir,
        session=session,
    )

    try:
        return run_gtk_widget(
            session,
            listener,
            sdk_dir=sdk_dir,
            port=args.port,
            item_db=item_db,
            gate=gate,
            gate_port=args.gate_port,
            serial_port=args.serial,
        )
    except Exception:
        return run_tk_widget(
            session,
            listener,
            sdk_dir=sdk_dir,
            port=args.port,
            item_db=item_db,
            gate=gate,
            gate_port=args.gate_port,
            serial_port=args.serial,
        )


if __name__ == "__main__":
    raise SystemExit(main())
