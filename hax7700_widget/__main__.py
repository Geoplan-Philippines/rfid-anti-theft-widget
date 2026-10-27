"""CLI entry point for the standalone HAX7700 Python counter widget."""

from __future__ import annotations

import argparse
from pathlib import Path

from .core import ScanSession, TcpDeactivatorListener
from .gui import run_gtk_widget, run_tk_widget


def main() -> int:
    parser = argparse.ArgumentParser(description="Standalone HAX7700 Deactivator tag/EPC counter widget")
    parser.add_argument("--port", type=int, default=9090, help="Inbound TCP port for HAX7700 (default: 9090)")
    parser.add_argument(
        "--sdk-dir",
        default=str(Path(__file__).resolve().parent.parent / "sdk-win-x86"),
        help="Directory containing 32-bit Windows card_7k.dll + common.dll",
    )
    parser.add_argument(
        "--capture-dir",
        default=str(Path(__file__).resolve().parent.parent / "captures"),
        help="Directory for raw TCP packet logs",
    )
    args = parser.parse_args()

    session = ScanSession()
    listener = TcpDeactivatorListener(session=session, capture_dir=args.capture_dir)
    sdk_dir = Path(args.sdk_dir)

    try:
        return run_gtk_widget(session, listener, sdk_dir=sdk_dir, port=args.port)
    except Exception:
        return run_tk_widget(session, listener, sdk_dir=sdk_dir, port=args.port)


if __name__ == "__main__":
    raise SystemExit(main())
