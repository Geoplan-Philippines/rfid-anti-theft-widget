"""Standalone desktop counter widget UI (GTK3 on Linux, Tkinter on Windows)."""

from __future__ import annotations

import ctypes
import math
import os
from pathlib import Path
import platform
import time

from .api import TransactionOutbox, pending_line, status_line
from .core import ScanSession, TcpDeactivatorListener

# Text colors for the tones returned by api.status_line() / api.pending_line()
_TONE_COLORS = {
    "muted": "#71717a",
    "busy": "#2563eb",
    "ok": "#16a34a",
    "warn": "#d97706",
    "error": "#dc2626",
}


def _toggle_scan(session: ScanSession, listener: TcpDeactivatorListener, outbox: TransactionOutbox) -> None:
    """Start Scanning begins a new sale; Stop ends it and hands it to the outbox to send (GTK and Tk)."""
    if listener.is_scanning():
        listener.set_scanning(False)
        outbox.submit(session.finish())
    else:
        session.reset()
        listener.set_scanning(True)


def _auto_start_listener(listener: TcpDeactivatorListener, sdk_dir: Path, port: int = 9090) -> None:
    if platform.system() == "Windows" and ctypes.sizeof(ctypes.c_void_p) == 4 and (sdk_dir / "card_7k.dll").is_file():
        try:
            listener.start_windows_sdk(sdk_dir=sdk_dir, host="0.0.0.0", port=port, poll_ms=50)
            return
        except Exception:
            pass
    listener.start_tcp(mode="listen", host="0.0.0.0", port=port, peer_filter="169.254.68.93")


def _lerp_hex(c1: str, c2: str, t: float) -> str:
    """Linearly interpolate between two #RRGGBB hex colors (t in 0.0..1.0)."""
    t = max(0.0, min(1.0, t))
    r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def run_gtk_widget(
    session: ScanSession,
    listener: TcpDeactivatorListener,
    outbox: TransactionOutbox,
    sdk_dir: Path,
    port: int = 9090,
) -> int:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib, Gtk

    css = b"""
    window {
      background-color: #ffffff;
      color: #18181b;
    }
    .header-box {
      border-bottom: 1px solid #e4e4e7;
      padding-bottom: 10px;
    }
    .title {
      color: #18181b;
      font-size: 15px;
      font-weight: 800;
    }
    .status-text {
      color: #52525b;
      font-size: 12px;
      font-weight: 600;
    }
    .count-label {
      color: #18181b;
      font-size: 56px;
      font-weight: 800;
    }
    .unit-label {
      color: #71717a;
      font-size: 12px;
      font-weight: 600;
    }
    .primary-btn {
      background-image: none;
      background-color: #18181b;
      color: #fafafa;
      font-weight: 700;
      border-radius: 6px;
      padding: 10px 14px;
    }
    .danger-btn {
      background-image: none;
      background-color: #dc2626;
      color: #ffffff;
      font-weight: 700;
      border-radius: 6px;
      padding: 10px 14px;
    }
    .primary-btn:disabled {
      background-color: #e4e4e7;
    }
    .primary-btn:disabled label {
      color: #a1a1aa;
    }
    .sync-text {
      font-size: 12px;
      font-weight: 700;
    }
    .pending-text {
      font-size: 12px;
      font-weight: 600;
    }
    """ + "".join(f".tone-{tone} {{ color: {color}; }}\n" for tone, color in _TONE_COLORS.items()).encode()
    provider = Gtk.CssProvider()
    provider.load_from_data(css)
    screen = Gtk.Window().get_screen()
    Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    listener.set_scanning(False)

    win = Gtk.Window(title="HAX7700")
    win.set_default_size(290, 280)
    win.set_resizable(False)
    win.set_keep_above(True)
    win.set_border_width(16)

    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    win.add(root)

    header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    header.get_style_context().add_class("header-box")
    title = Gtk.Label(label="Tag Counter", xalign=0)
    title.get_style_context().add_class("title")

    status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    dot_area = Gtk.DrawingArea()
    dot_area.set_size_request(18, 18)
    status_lbl = Gtk.Label(label="Connecting...", xalign=1)
    status_lbl.get_style_context().add_class("status-text")
    status_box.pack_start(dot_area, False, False, 0)
    status_box.pack_start(status_lbl, False, False, 0)

    header.pack_start(title, True, True, 0)
    header.pack_end(status_box, False, False, 0)
    root.pack_start(header, False, False, 0)

    counter_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    count_lbl = Gtk.Label(label="0", xalign=0.5)
    count_lbl.get_style_context().add_class("count-label")
    unit_lbl = Gtk.Label(label="Tags scanned", xalign=0.5)
    unit_lbl.get_style_context().add_class("unit-label")
    counter_box.pack_start(count_lbl, True, True, 2)
    counter_box.pack_start(unit_lbl, False, False, 0)
    root.pack_start(counter_box, True, True, 0)

    scan_btn = Gtk.Button(label="Start Scanning")
    scan_btn.get_style_context().add_class("primary-btn")
    # Stays disabled until settings.json is complete; the status line says what is missing
    scan_btn.set_sensitive(outbox.ready)
    root.pack_end(scan_btn, False, False, 0)

    # Sync status line and the number of sales still waiting to be sent, just above the button
    footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    sync_lbl = Gtk.Label(label="", xalign=0)
    sync_lbl.set_line_wrap(True)
    sync_lbl.set_max_width_chars(36)
    sync_lbl.get_style_context().add_class("sync-text")
    pending_lbl = Gtk.Label(label="", xalign=0)
    pending_lbl.get_style_context().add_class("pending-text")
    footer.pack_start(sync_lbl, False, False, 0)
    footer.pack_start(pending_lbl, False, False, 0)
    root.pack_end(footer, False, False, 0)

    def show_line(label: Gtk.Label, text: str, tone: str) -> None:
        if label.get_text() != text:
            label.set_text(text)
        ctx = label.get_style_context()
        if not ctx.has_class(f"tone-{tone}"):
            for name in _TONE_COLORS:
                ctx.remove_class(f"tone-{name}")
            ctx.add_class(f"tone-{tone}")

    def on_draw_dot(_area, cr) -> bool:
        st = listener.state()
        pulse = 0.5 + 0.5 * math.sin(time.monotonic() * 4.0)
        cx, cy = 9.0, 9.0
        halo_r = 5.0 + 3.5 * pulse
        if st.peer:
            cr.set_source_rgba(0.13, 0.77, 0.37, 0.18 + 0.20 * pulse)
            cr.arc(cx, cy, halo_r, 0, 2 * math.pi)
            cr.fill()
            cr.set_source_rgba(0.09, 0.64, 0.29, 0.75 + 0.25 * pulse)
        else:
            cr.set_source_rgba(0.96, 0.62, 0.04, 0.18 + 0.22 * pulse)
            cr.arc(cx, cy, halo_r, 0, 2 * math.pi)
            cr.fill()
            cr.set_source_rgba(0.96, 0.62, 0.04, 0.55 + 0.45 * pulse)
        cr.arc(cx, cy, 4.5, 0, 2 * math.pi)
        cr.fill()
        return False

    dot_area.connect("draw", on_draw_dot)

    def refresh_ui() -> bool:
        snap = session.snapshot()
        st = listener.state()
        count_lbl.set_text(str(snap["unique_count"]))
        status_lbl.set_text("Connected" if st.peer else "Connecting...")
        sync = outbox.state()
        show_line(sync_lbl, *status_line(sync))
        show_line(pending_lbl, *pending_line(sync))
        btn_ctx = scan_btn.get_style_context()
        if st.scanning:
            scan_btn.set_label("Stop")
            btn_ctx.remove_class("primary-btn")
            btn_ctx.add_class("danger-btn")
        else:
            scan_btn.set_label("Start Scanning")
            btn_ctx.remove_class("danger-btn")
            btn_ctx.add_class("primary-btn")
        dot_area.queue_draw()
        return True

    def on_toggle_scan(_btn: Gtk.Button) -> None:
        _toggle_scan(session, listener, outbox)
        refresh_ui()

    def on_destroy(_win: Gtk.Window) -> None:
        listener.stop()
        outbox.stop()
        Gtk.main_quit()

    scan_btn.connect("clicked", on_toggle_scan)
    win.connect("destroy", on_destroy)

    _auto_start_listener(listener, sdk_dir, port=port)
    outbox.start()
    win.show_all()
    refresh_ui()
    GLib.timeout_add(30, refresh_ui)
    Gtk.main()
    return 0


def run_tk_widget(
    session: ScanSession,
    listener: TcpDeactivatorListener,
    outbox: TransactionOutbox,
    sdk_dir: Path,
    port: int = 9090,
) -> int:
    # Start in idle state so tags are only counted after clicking "Start Scanning"
    listener.set_scanning(False)
    # Start native Windows SDK (card_7k.dll / mfc140.dll) before initializing Tcl/Tk
    _auto_start_listener(listener, sdk_dir, port=port)
    outbox.start()

    import tkinter as tk

    root = tk.Tk()
    root.title("HAX7700")
    root.geometry("290x280")
    root.resizable(False, False)
    root.attributes("-topmost", True)
    root.configure(bg="#ffffff", padx=18, pady=14)

    # Header: Title on left, breathing circle + status on right
    header = tk.Frame(root, bg="#ffffff")
    header.pack(fill="x", pady=(0, 8))
    tk.Label(
        header,
        text="Tag Counter",
        font=("Segoe UI", 12, "bold"),
        fg="#18181b",
        bg="#ffffff",
    ).pack(side="left")

    status_frame = tk.Frame(header, bg="#ffffff")
    status_frame.pack(side="right")

    dot_canvas = tk.Canvas(
        status_frame,
        width=18,
        height=18,
        bg="#ffffff",
        highlightthickness=0,
        bd=0,
    )
    dot_canvas.pack(side="left", padx=(0, 5))
    halo_id = dot_canvas.create_oval(1, 1, 17, 17, fill="#fef3c7", outline="")
    core_id = dot_canvas.create_oval(5, 5, 13, 13, fill="#f59e0b", outline="")

    status_var = tk.StringVar(value="Connecting...")
    status_lbl = tk.Label(
        status_frame,
        textvariable=status_var,
        font=("Segoe UI", 9, "bold"),
        fg="#71717a",
        bg="#ffffff",
    )
    status_lbl.pack(side="left")

    tk.Frame(root, bg="#f4f4f5", height=1).pack(fill="x", pady=(0, 8))

    # Center Big Counter (packed last so it only takes the space the footer and button leave)
    center = tk.Frame(root, bg="#ffffff")
    count_var = tk.StringVar(value="0")
    tk.Label(
        center,
        textvariable=count_var,
        font=("Segoe UI", 46, "bold"),
        fg="#18181b",
        bg="#ffffff",
    ).pack(expand=True)

    # Start Scanning / Stop Button
    def on_toggle_scan() -> None:
        _toggle_scan(session, listener, outbox)
        update_ui()

    scan_btn = tk.Button(
        root,
        text="Start Scanning",
        font=("Segoe UI", 11, "bold"),
        bg="#18181b",
        fg="#fafafa",
        activebackground="#27272a",
        activeforeground="#fafafa",
        relief="flat",
        bd=0,
        pady=8,
        cursor="hand2",
        command=on_toggle_scan,
    )
    scan_btn.pack(side="bottom", fill="x", pady=(8, 0))
    if not outbox.ready:
        # Stays disabled until settings.json is complete; the status line says what is missing
        scan_btn.configure(state="disabled", bg="#e4e4e7", disabledforeground="#a1a1aa", cursor="arrow")

    # Sync status line and the number of sales still waiting to be sent
    footer = tk.Frame(root, bg="#ffffff")
    footer.pack(side="bottom", fill="x")
    sync_var = tk.StringVar(value="")
    sync_lbl = tk.Label(
        footer,
        textvariable=sync_var,
        font=("Segoe UI", 9, "bold"),
        fg=_TONE_COLORS["muted"],
        bg="#ffffff",
        anchor="w",
        justify="left",
        wraplength=254,
    )
    sync_lbl.pack(fill="x")
    pending_var = tk.StringVar(value="")
    pending_lbl = tk.Label(
        footer,
        textvariable=pending_var,
        font=("Segoe UI", 9),
        fg=_TONE_COLORS["muted"],
        bg="#ffffff",
        anchor="w",
    )
    pending_lbl.pack(fill="x")

    center.pack(expand=True, fill="both")

    def update_ui() -> None:
        snap = session.snapshot()
        st = listener.state()
        count_var.set(str(snap["unique_count"]))

        sync = outbox.state()
        text, tone = status_line(sync)
        sync_var.set(text)
        sync_lbl.configure(fg=_TONE_COLORS[tone])
        text, tone = pending_line(sync)
        pending_var.set(text)
        pending_lbl.configure(fg=_TONE_COLORS[tone])

        # Smooth breathing animation (sine wave 0.0 .. 1.0)
        pulse = 0.5 + 0.5 * math.sin(time.monotonic() * 4.2)
        halo_r = 4.5 + 3.5 * pulse
        dot_canvas.coords(halo_id, 9.0 - halo_r, 9.0 - halo_r, 9.0 + halo_r, 9.0 + halo_r)

        if st.peer:
            status_var.set("Connected")
            status_lbl.configure(fg="#16a34a")
            dot_canvas.itemconfig(
                halo_id,
                fill=_lerp_hex("#ffffff", "#bbf7d0", 0.35 + 0.65 * pulse),
            )
            dot_canvas.itemconfig(
                core_id,
                fill=_lerp_hex("#22c55e", "#15803d", pulse),
            )
        else:
            status_var.set("Connecting...")
            status_lbl.configure(fg="#d97706")
            dot_canvas.itemconfig(
                halo_id,
                fill=_lerp_hex("#ffffff", "#fde68a", 0.35 + 0.65 * pulse),
            )
            dot_canvas.itemconfig(
                core_id,
                fill=_lerp_hex("#fcd34d", "#d97706", pulse),
            )

        if not outbox.ready:
            return
        if st.scanning:
            scan_btn.configure(
                text="Stop",
                bg="#dc2626",
                fg="#ffffff",
                activebackground="#b91c1c",
                activeforeground="#ffffff",
            )
        else:
            scan_btn.configure(
                text="Start Scanning",
                bg="#18181b",
                fg="#fafafa",
                activebackground="#27272a",
                activeforeground="#fafafa",
            )

    def tick() -> None:
        update_ui()
        root.after(30, tick)

    def on_close() -> None:
        listener.stop()
        outbox.stop()
        root.destroy()
        os._exit(0)

    root.protocol("WM_DELETE_WINDOW", on_close)
    tick()
    root.mainloop()
    return 0
