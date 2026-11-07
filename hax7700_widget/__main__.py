"""CLI entry point for the standalone HAX7700 Python counter widget."""

from __future__ import annotations

import argparse
from pathlib import Path

from .api import TransactionOutbox, load_settings
from .core import ScanSession, TcpDeactivatorListener
from .gui import run_gtk_widget, run_tk_widget


def main() -> int:
    app_dir = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Standalone HAX7700 Deactivator tag/EPC counter widget")
    parser.add_argument("--port", type=int, default=9090, help="Inbound TCP port for HAX7700 (default: 9090)")
    parser.add_argument(
        "--sdk-dir",
        default=str(app_dir / "sdk-win-x86"),
        help="Directory containing 32-bit Windows card_7k.dll + common.dll",
    )
    parser.add_argument(
        "--capture-dir",
        default=str(app_dir / "captures"),
        help="Directory for raw TCP packet logs",
    )
    parser.add_argument(
        "--settings",
        default=str(app_dir / "settings.json"),
        help="Server settings file (copy settings.example.json to start)",
    )
    parser.add_argument(
        "--pending-dir",
        default=str(app_dir / "pending"),
        help="Directory for sales waiting to be sent to the server",
    )
    args = parser.parse_args()

    session = ScanSession()
    listener = TcpDeactivatorListener(session=session, capture_dir=args.capture_dir)
    settings, settings_error = load_settings(args.settings)
    outbox = TransactionOutbox(args.pending_dir, settings, settings_error)
    sdk_dir = Path(args.sdk_dir)

    try:
        return run_gtk_widget(session, listener, outbox, sdk_dir=sdk_dir, port=args.port)
    except Exception:
        return run_tk_widget(session, listener, outbox, sdk_dir=sdk_dir, port=args.port)


if __name__ == "__main__":
    raise SystemExit(main())
