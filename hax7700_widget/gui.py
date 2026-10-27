"""Standalone desktop counter widget UI (GTK3 on Linux, Tkinter on Windows)."""

from __future__ import annotations

import ctypes
from pathlib import Path
import platform

from .core import ScanSession, TcpDeactivatorListener, local_ipv4_addresses


def _auto_start_listener(listener: TcpDeactivatorListener, sdk_dir: Path, port: int = 9090) -> None:
    if platform.system() == "Windows" and ctypes.sizeof(ctypes.c_void_p) == 4 and (sdk_dir / "card_7k.dll").is_file():
        try:
            listener.start_windows_sdk(sdk_dir=sdk_dir, host="0.0.0.0", port=port, poll_ms=200)
            return
        except Exception:
            pass
    listener.start_tcp(mode="listen", host="0.0.0.0", port=port, peer_filter="169.254.68.93")


def run_gtk_widget(
    session: ScanSession,
    listener: TcpDeactivatorListener,
    sdk_dir: Path,
    port: int = 9090,
) -> int:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib, Gtk, Pango

    css = b"""
    window {
      background-color: #ffffff;
      color: #18181b;
    }
    .header-box {
      border-bottom: 2px solid #18181b;
      padding-bottom: 8px;
    }
    .eyebrow {
      color: #3f3f46;
      font-size: 11px;
      font-weight: 600;
    }
    .title {
      color: #18181b;
      font-size: 16px;
      font-weight: 800;
    }
    .badge {
      background-color: #f4f4f5;
      color: #18181b;
      padding: 3px 8px;
      border-radius: 3px;
      font-family: monospace;
      font-size: 11px;
      font-weight: 700;
    }
    .badge-online {
      background-color: #18181b;
      color: #fafafa;
    }
    .count-label {
      color: #18181b;
      font-size: 52px;
      font-weight: 800;
    }
    .unit-label {
      color: #18181b;
      font-size: 13px;
      font-weight: 700;
    }
    .sub-label {
      color: #3f3f46;
      font-size: 12px;
    }
    .mono-label {
      color: #3f3f46;
      font-family: monospace;
      font-size: 11px;
    }
    .primary-btn {
      background-image: none;
      background-color: #18181b;
      color: #fafafa;
      font-weight: 700;
      border-radius: 3px;
      padding: 6px 10px;
    }
    .secondary-btn {
      background-image: none;
      background-color: #f4f4f5;
      color: #18181b;
      font-weight: 600;
      border-radius: 3px;
      padding: 6px 10px;
    }
    .footer-box {
      border-top: 1px solid #d4d4d8;
      padding-top: 8px;
    }
    """
    provider = Gtk.CssProvider()
    provider.load_from_data(css)
    screen = Gtk.Window().get_screen()
    Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    win = Gtk.Window(title="HAX7700 Tag Counter")
    win.set_default_size(340, 320)
    win.set_resizable(False)
    win.set_keep_above(True)
    win.set_border_width(14)

    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    win.add(root)

    # Header
    header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    header.get_style_context().add_class("header-box")
    title_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
    eyebrow = Gtk.Label(label="HAX7700 / RFID7700", xalign=0)
    eyebrow.get_style_context().add_class("eyebrow")
    title = Gtk.Label(label="Deactivator Counter", xalign=0)
    title.get_style_context().add_class("title")
    title_col.pack_start(eyebrow, False, False, 0)
    title_col.pack_start(title, False, False, 0)

    badge = Gtk.Label(label="STARTING", xalign=1)
    badge.get_style_context().add_class("badge")
    header.pack_start(title_col, True, True, 0)
    header.pack_end(badge, False, False, 0)
    root.pack_start(header, False, False, 0)

    # Big Counter
    counter_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    count_lbl = Gtk.Label(label="0", xalign=0)
    count_lbl.get_style_context().add_class("count-label")
    unit_lbl = Gtk.Label(label="Unique tags scanned in session", xalign=0)
    unit_lbl.get_style_context().add_class("unit-label")
    repeats_lbl = Gtk.Label(label="0 repeat reads ignored · 0 total reads", xalign=0)
    repeats_lbl.get_style_context().add_class("sub-label")
    last_epc_lbl = Gtk.Label(label="Last EPC: none", xalign=0)
    last_epc_lbl.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
    last_epc_lbl.get_style_context().add_class("mono-label")
    counter_box.pack_start(count_lbl, False, False, 0)
    counter_box.pack_start(unit_lbl, False, False, 0)
    counter_box.pack_start(repeats_lbl, False, False, 0)
    counter_box.pack_start(last_epc_lbl, False, False, 0)
    root.pack_start(counter_box, False, False, 0)

    # Buttons
    btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, homogeneous=True)
    demo_btn = Gtk.Button(label="+ Demo tag")
    demo_btn.get_style_context().add_class("primary-btn")
    reset_btn = Gtk.Button(label="New session")
    reset_btn.get_style_context().add_class("secondary-btn")
    btn_row.pack_start(demo_btn, True, True, 0)
    btn_row.pack_start(reset_btn, True, True, 0)
    root.pack_start(btn_row, False, False, 0)

    # EPC Entry (for built-in keyboard wedge or manual tag scan)
    entry_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    epc_entry = Gtk.Entry()
    epc_entry.set_placeholder_text("Scan or enter EPC hex…")
    count_btn = Gtk.Button(label="Count")
    count_btn.get_style_context().add_class("secondary-btn")
    entry_row.pack_start(epc_entry, True, True, 0)
    entry_row.pack_end(count_btn, False, False, 0)
    root.pack_start(entry_row, False, False, 0)

    # Footer (Hardware connection status + mode switch)
    footer_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    footer_box.get_style_context().add_class("footer-box")
    status_lbl = Gtk.Label(label="Listening on :9090…", xalign=0)
    status_lbl.set_ellipsize(Pango.EllipsizeMode.END)
    status_lbl.get_style_context().add_class("sub-label")
    mode_btn = Gtk.Button(label="Port 26")
    mode_btn.get_style_context().add_class("secondary-btn")
    footer_box.pack_start(status_lbl, True, True, 0)
    footer_box.pack_end(mode_btn, False, False, 0)
    root.pack_end(footer_box, False, False, 0)

    def refresh_ui() -> bool:
        snap = session.snapshot()
        st = listener.state()
        count_lbl.set_text(str(snap["unique_count"]))
        repeats_lbl.set_text(
            f"{snap['repeat_reads']} repeat reads ignored · {snap['total_reads']} total reads"
        )
        last_epc_lbl.set_text(
            f"Last EPC: {snap['last_epc']}" if snap["last_epc"] else "Last EPC: none"
        )
        ctx = badge.get_style_context()
        if st.peer:
            badge.set_text("ONLINE")
            ctx.add_class("badge-online")
            status_lbl.set_text(f"{st.peer} · RX {st.bytes_received} B")
        elif st.running:
            badge.set_text("SDK :9090" if st.sdk_active else f"LISTEN :{port}" if st.mode == "listen" else "PORT 26")
            ctx.remove_class("badge-online")
            status_lbl.set_text(st.status_text)
        else:
            badge.set_text("OFFLINE")
            ctx.remove_class("badge-online")
            status_lbl.set_text(st.last_error or st.status_text)
        return True

    def on_demo(_btn: Gtk.Button) -> None:
        session.observe(None, source="demo")
        refresh_ui()

    def on_reset(_btn: Gtk.Button) -> None:
        session.reset()
        refresh_ui()

    def on_submit_epc(_widget) -> None:
        raw = epc_entry.get_text().strip()
        if not raw:
            return
        try:
            session.observe(raw, source="scanner")
            epc_entry.set_text("")
        except ValueError as err:
            status_lbl.set_text(str(err))
        refresh_ui()

    def on_toggle_mode(_btn: Gtk.Button) -> None:
        st = listener.state()
        if st.mode == "listen":
            listener.start_tcp(mode="client", host="169.254.68.93", port=26)
            mode_btn.set_label("Listen :9090")
        else:
            _auto_start_listener(listener, sdk_dir, port=port)
            mode_btn.set_label("Port 26")
        refresh_ui()

    def on_destroy(_win: Gtk.Window) -> None:
        listener.stop()
        Gtk.main_quit()

    demo_btn.connect("clicked", on_demo)
    reset_btn.connect("clicked", on_reset)
    count_btn.connect("clicked", on_submit_epc)
    epc_entry.connect("activate", on_submit_epc)
    mode_btn.connect("clicked", on_toggle_mode)
    win.connect("destroy", on_destroy)

    _auto_start_listener(listener, sdk_dir, port=port)
    win.show_all()
    refresh_ui()
    GLib.timeout_add(300, refresh_ui)
    Gtk.main()
    return 0


def run_tk_widget(
    session: ScanSession,
    listener: TcpDeactivatorListener,
    sdk_dir: Path,
    port: int = 9090,
) -> int:
    import tkinter as tk

    root = tk.Tk()
    root.title("HAX7700 Tag Counter")
    root.geometry("340x320")
    root.resizable(False, False)
    root.attributes("-topmost", True)
    root.configure(bg="#ffffff", padx=14, pady=12)

    header = tk.Frame(root, bg="#ffffff")
    header.pack(fill="x", pady=(0, 8))
    tk.Label(header, text="HAX7700 / RFID7700", font=("Arial", 9, "bold"), fg="#3f3f46", bg="#ffffff").pack(anchor="w")
    title_row = tk.Frame(header, bg="#ffffff")
    title_row.pack(fill="x")
    tk.Label(title_row, text="Deactivator Counter", font=("Arial", 13, "bold"), fg="#18181b", bg="#ffffff").pack(side="left")
    badge_var = tk.StringVar(value="STARTING")
    tk.Label(title_row, textvariable=badge_var, font=("Courier", 9, "bold"), fg="#18181b", bg="#f4f4f5", padx=6, pady=2).pack(side="right")

    tk.Frame(root, bg="#18181b", height=2).pack(fill="x", pady=(0, 8))

    count_var = tk.StringVar(value="0")
    tk.Label(root, textvariable=count_var, font=("Arial", 42, "bold"), fg="#18181b", bg="#ffffff", anchor="w").pack(fill="x")
    tk.Label(root, text="Unique tags scanned in session", font=("Arial", 10, "bold"), fg="#18181b", bg="#ffffff", anchor="w").pack(fill="x")

    repeats_var = tk.StringVar(value="0 repeat reads ignored · 0 total reads")
    tk.Label(root, textvariable=repeats_var, font=("Arial", 9), fg="#3f3f46", bg="#ffffff", anchor="w").pack(fill="x")

    last_epc_var = tk.StringVar(value="Last EPC: none")
    tk.Label(root, textvariable=last_epc_var, font=("Courier", 9), fg="#3f3f46", bg="#ffffff", anchor="w").pack(fill="x", pady=(0, 8))

    btn_row = tk.Frame(root, bg="#ffffff")
    btn_row.pack(fill="x", pady=(0, 8))
    tk.Button(
        btn_row,
        text="+ Demo tag",
        font=("Arial", 10, "bold"),
        bg="#18181b",
        fg="#fafafa",
        relief="flat",
        command=lambda: session.observe(None, source="demo"),
    ).pack(side="left", expand=True, fill="x", padx=(0, 4))
    tk.Button(
        btn_row,
        text="New session",
        font=("Arial", 10, "bold"),
        bg="#f4f4f5",
        fg="#18181b",
        relief="flat",
        command=session.reset,
    ).pack(side="right", expand=True, fill="x", padx=(4, 0))

    status_var = tk.StringVar(value=f"PC IPv4: {', '.join(local_ipv4_addresses()) or '127.0.0.1'}")
    tk.Label(root, textvariable=status_var, font=("Arial", 9), fg="#3f3f46", bg="#ffffff", anchor="w").pack(side="bottom", fill="x")

    _auto_start_listener(listener, sdk_dir, port=port)

    def tick() -> None:
        snap = session.snapshot()
        st = listener.state()
        count_var.set(str(snap["unique_count"]))
        repeats_var.set(f"{snap['repeat_reads']} repeat reads ignored · {snap['total_reads']} total reads")
        last_epc_var.set(f"Last EPC: {snap['last_epc']}" if snap["last_epc"] else "Last EPC: none")
        badge_var.set("ONLINE" if st.peer else ("SDK" if st.sdk_active else "LISTENING"))
        status_var.set(f"{st.peer} · RX {st.bytes_received} B" if st.peer else st.status_text)
        root.after(300, tick)

    def on_close() -> None:
        listener.stop()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    tick()
    root.mainloop()
    return 0
