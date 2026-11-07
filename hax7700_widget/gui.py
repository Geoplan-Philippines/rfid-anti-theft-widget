"""Desktop UI for HAX7700 Pad Counter + Items Table (sold: true/false) + HAX7000 RFID Gate Controller (GTK3 on Linux, Tkinter on Windows)."""

from __future__ import annotations

import ctypes
import math
import os
from pathlib import Path
import platform
import time

from .core import ItemDatabase, RfidGateController, ScanSession, TcpDeactivatorListener


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
    sdk_dir: Path,
    port: int = 9090,
    item_db: ItemDatabase | None = None,
    gate: RfidGateController | None = None,
    gate_port: int = 9000,
) -> int:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib, Gtk

    if item_db is None:
        item_db = session.item_db or ItemDatabase()
        session.item_db = item_db
    if gate is None:
        gate = RfidGateController(item_db=item_db, sdk_dir=sdk_dir)

    css = b"""
    window {
      background-color: #f8fafc;
      color: #0f172a;
    }
    .card {
      background-color: #ffffff;
      border: 1px solid #e2e8f0;
      border-radius: 8px;
      padding: 12px;
    }
    .header-box {
      border-bottom: 1px solid #e2e8f0;
      padding-bottom: 10px;
    }
    .title {
      color: #0f172a;
      font-size: 16px;
      font-weight: 800;
    }
    .section-title {
      color: #0f172a;
      font-size: 13px;
      font-weight: 800;
    }
    .status-text {
      color: #475569;
      font-size: 12px;
      font-weight: 600;
    }
    .count-label {
      color: #0f172a;
      font-size: 42px;
      font-weight: 800;
    }
    .unit-label {
      color: #64748b;
      font-size: 12px;
      font-weight: 600;
    }
    .primary-btn {
      background-image: none;
      background-color: #0f172a;
      color: #ffffff;
      font-weight: 700;
      border-radius: 6px;
      padding: 6px 12px;
    }
    .success-btn {
      background-image: none;
      background-color: #16a34a;
      color: #ffffff;
      font-weight: 700;
      border-radius: 6px;
      padding: 6px 12px;
    }
    .danger-btn {
      background-image: none;
      background-color: #dc2626;
      color: #ffffff;
      font-weight: 700;
      border-radius: 6px;
      padding: 6px 12px;
    }
    .banner-idle {
      background-color: #f1f5f9;
      color: #334155;
      font-weight: 700;
      border-radius: 6px;
      padding: 8px 12px;
    }
    .banner-pass {
      background-color: #dcfce7;
      color: #166534;
      font-weight: 800;
      border-radius: 6px;
      padding: 8px 12px;
    }
    .banner-alarm {
      background-color: #fee2e2;
      color: #991b1b;
      font-weight: 800;
      border-radius: 6px;
      padding: 8px 12px;
    }
    """
    provider = Gtk.CssProvider()
    provider.load_from_data(css)
    screen = Gtk.Window().get_screen()
    Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    listener.set_scanning(False)

    win = Gtk.Window(title="HAX7700 Pad & HAX7000 RFID Gate Controller")
    win.set_default_size(920, 680)
    win.set_border_width(14)

    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    win.add(root)

    # --- Header ---
    header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    header.get_style_context().add_class("header-box")
    title = Gtk.Label(label="RFID Checkout & Gate Alarm Controller", xalign=0)
    title.get_style_context().add_class("title")

    status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    pad_dot = Gtk.DrawingArea()
    pad_dot.set_size_request(16, 16)
    pad_status_lbl = Gtk.Label(label=f"Pad (:{port}): Connecting...", xalign=1)
    pad_status_lbl.get_style_context().add_class("status-text")

    gate_dot = Gtk.DrawingArea()
    gate_dot.set_size_request(16, 16)
    gate_status_lbl = Gtk.Label(label=f"Gate (:{gate_port}): Listening...", xalign=1)
    gate_status_lbl.get_style_context().add_class("status-text")

    status_box.pack_start(pad_dot, False, False, 0)
    status_box.pack_start(pad_status_lbl, False, False, 0)
    status_box.pack_start(gate_dot, False, False, 0)
    status_box.pack_start(gate_status_lbl, False, False, 0)

    header.pack_start(title, True, True, 0)
    header.pack_end(status_box, False, False, 0)
    root.pack_start(header, False, False, 0)

    # --- Top Row: Pad Counter + Mode Selector ---
    top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    top_row.get_style_context().add_class("card")

    counter_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    count_lbl = Gtk.Label(label="0", xalign=0.5)
    count_lbl.get_style_context().add_class("count-label")
    unit_lbl = Gtk.Label(label="Unique Pad Tags Scanned", xalign=0.5)
    unit_lbl.get_style_context().add_class("unit-label")
    counter_col.pack_start(count_lbl, False, False, 0)
    counter_col.pack_start(unit_lbl, False, False, 0)
    top_row.pack_start(counter_col, False, False, 16)

    controls_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    scan_btn = Gtk.Button(label="Start Scanning")
    scan_btn.get_style_context().add_class("primary-btn")
    demo_btn = Gtk.Button(label="+ Scan Demo Item")
    btn_row.pack_start(scan_btn, False, False, 0)
    btn_row.pack_start(demo_btn, False, False, 0)

    mode_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    mode_lbl = Gtk.Label(label="When Pad Scans Tag:", xalign=0)
    mode_lbl.get_style_context().add_class("section-title")
    rb_register = Gtk.RadioButton.new_with_label_from_widget(None, "Register Item (sold = False -> Alarm)")
    rb_checkout = Gtk.RadioButton.new_with_label_from_widget(rb_register, "Customer Checkout (sold = True -> No Alarm)")
    mode_row.pack_start(mode_lbl, False, False, 0)
    mode_row.pack_start(rb_register, False, False, 0)
    mode_row.pack_start(rb_checkout, False, False, 0)

    controls_col.pack_start(btn_row, False, False, 0)
    controls_col.pack_start(mode_row, False, False, 0)
    top_row.pack_start(controls_col, True, True, 8)
    root.pack_start(top_row, False, False, 0)

    # --- Middle: Items Table (sold: True / False) ---
    items_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    items_card.get_style_context().add_class("card")

    items_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    items_title = Gtk.Label(label="Items Table (Double-click row or click Toggle Sold)", xalign=0)
    items_title.get_style_context().add_class("section-title")
    counts_summary_lbl = Gtk.Label(label="Total: 0 | Sold (True): 0 | Unsold (False): 0", xalign=1)
    counts_summary_lbl.get_style_context().add_class("status-text")
    items_hdr.pack_start(items_title, True, True, 0)
    items_hdr.pack_end(counts_summary_lbl, False, False, 0)
    items_card.pack_start(items_hdr, False, False, 0)

    # ListStore: epc, name, sold_str, gate_action, updated_at
    items_store = Gtk.ListStore(str, str, str, str, str)
    items_tree = Gtk.TreeView(model=items_store)
    items_tree.set_headers_visible(True)
    for idx, (col_title, width) in enumerate(
        [
            ("EPC", 230),
            ("Item Name", 140),
            ("Sold", 80),
            ("Gate Decision", 180),
            ("Updated At (UTC)", 200),
        ]
    ):
        renderer = Gtk.CellRendererText()
        col = Gtk.TreeViewColumn(col_title, renderer, text=idx)
        col.set_min_width(width)
        col.set_resizable(True)
        items_tree.append_column(col)

    items_scroll = Gtk.ScrolledWindow()
    items_scroll.set_min_content_height(190)
    items_scroll.add(items_tree)
    items_card.pack_start(items_scroll, True, True, 0)

    # Manual add + Table action buttons
    add_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    epc_entry = Gtk.Entry()
    epc_entry.set_placeholder_text("EPC hex (e.g. E2000017221101441890ABCD)")
    epc_entry.set_width_chars(28)
    name_entry = Gtk.Entry()
    name_entry.set_placeholder_text("Item name (optional)")
    name_entry.set_width_chars(16)
    add_unsold_btn = Gtk.Button(label="Add Item (sold=False)")
    use_gate_epc_btn = Gtk.Button(label="Add Last Gate EPC")
    add_row.pack_start(epc_entry, True, True, 0)
    add_row.pack_start(name_entry, False, False, 0)
    add_row.pack_start(add_unsold_btn, False, False, 0)
    add_row.pack_start(use_gate_epc_btn, False, False, 0)
    items_card.pack_start(add_row, False, False, 0)

    action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    toggle_sold_btn = Gtk.Button(label="Toggle Sold (True / False)")
    toggle_sold_btn.get_style_context().add_class("primary-btn")
    mark_sold_btn = Gtk.Button(label="Mark Sold (True - No Alarm)")
    mark_sold_btn.get_style_context().add_class("success-btn")
    mark_unsold_btn = Gtk.Button(label="Mark Unsold (False - Will Alarm)")
    mark_unsold_btn.get_style_context().add_class("danger-btn")
    sim_gate_btn = Gtk.Button(label="Test Gate Pass (Selected)")
    delete_btn = Gtk.Button(label="Delete Selected")
    clear_btn = Gtk.Button(label="Clear All")

    action_row.pack_start(toggle_sold_btn, False, False, 0)
    action_row.pack_start(mark_sold_btn, False, False, 0)
    action_row.pack_start(mark_unsold_btn, False, False, 0)
    action_row.pack_start(sim_gate_btn, False, False, 0)
    action_row.pack_end(clear_btn, False, False, 0)
    action_row.pack_end(delete_btn, False, False, 0)
    items_card.pack_start(action_row, False, False, 0)

    root.pack_start(items_card, True, True, 0)

    # --- Bottom: Gate Monitor & Event Log ---
    gate_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    gate_card.get_style_context().add_class("card")

    gate_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    gate_title = Gtk.Label(label=f"RFID Gate Monitor (Port {gate_port} — ServerControl + Alarm)", xalign=0)
    gate_title.get_style_context().add_class("section-title")
    gate_stats_lbl = Gtk.Label(label="Alarms: 0 | Passed (Sold): 0 | Ignored: 0", xalign=1)
    gate_stats_lbl.get_style_context().add_class("status-text")
    gate_hdr.pack_start(gate_title, True, True, 0)
    gate_hdr.pack_end(gate_stats_lbl, False, False, 0)
    gate_card.pack_start(gate_hdr, False, False, 0)

    gate_banner = Gtk.Label(label="Waiting for RFID Gate events...", xalign=0)
    gate_banner.get_style_context().add_class("banner-idle")
    gate_card.pack_start(gate_banner, False, False, 0)

    events_store = Gtk.ListStore(str, str, str, str)
    events_tree = Gtk.TreeView(model=events_store)
    for idx, (col_title, width) in enumerate(
        [
            ("Time (UTC)", 180),
            ("Gate Decision", 120),
            ("EPC(s)", 240),
            ("Details", 300),
        ]
    ):
        renderer = Gtk.CellRendererText()
        col = Gtk.TreeViewColumn(col_title, renderer, text=idx)
        col.set_min_width(width)
        events_tree.append_column(col)

    events_scroll = Gtk.ScrolledWindow()
    events_scroll.set_min_content_height(120)
    events_scroll.add(events_tree)
    gate_card.pack_start(events_scroll, True, True, 0)
    root.pack_start(gate_card, False, False, 0)

    # --- Helpers & State Sync ---
    last_items_snapshot: list[tuple] = []
    last_events_snapshot: list[tuple] = []

    def get_selected_epc() -> str | None:
        selection = items_tree.get_selection()
        model, tree_iter = selection.get_selected()
        if tree_iter is not None:
            return model[tree_iter][0]
        return None

    def refresh_items_table(force: bool = False) -> None:
        nonlocal last_items_snapshot
        rows = item_db.list_items()
        snap = [(r["epc"], r["name"], "TRUE" if r["sold"] else "FALSE", r["gate_action"], r["updated_at"]) for r in rows]
        c = item_db.counts()
        counts_summary_lbl.set_text(
            f"Total: {c['total']} | Sold (True): {c['sold']} | Unsold (False): {c['unsold']}"
        )
        if not force and snap == last_items_snapshot:
            return
        selected_epc = get_selected_epc()
        last_items_snapshot = snap
        items_store.clear()
        restore_iter = None
        for tup in snap:
            it = items_store.append(list(tup))
            if selected_epc and tup[0] == selected_epc:
                restore_iter = it
        if restore_iter is not None:
            items_tree.get_selection().select_iter(restore_iter)

    def on_draw_pad_dot(_area, cr) -> bool:
        st = listener.state()
        pulse = 0.5 + 0.5 * math.sin(time.monotonic() * 4.0)
        cx, cy = 8.0, 8.0
        halo_r = 4.5 + 3.0 * pulse
        if st.peer:
            cr.set_source_rgba(0.13, 0.77, 0.37, 0.25)
            cr.arc(cx, cy, halo_r, 0, 2 * math.pi)
            cr.fill()
            cr.set_source_rgba(0.09, 0.64, 0.29, 0.9)
        else:
            cr.set_source_rgba(0.96, 0.62, 0.04, 0.25)
            cr.arc(cx, cy, halo_r, 0, 2 * math.pi)
            cr.fill()
            cr.set_source_rgba(0.96, 0.62, 0.04, 0.85)
        cr.arc(cx, cy, 4.0, 0, 2 * math.pi)
        cr.fill()
        return False

    def on_draw_gate_dot(_area, cr) -> bool:
        gst = gate.state()
        pulse = 0.5 + 0.5 * math.sin(time.monotonic() * 4.0)
        cx, cy = 8.0, 8.0
        halo_r = 4.5 + 3.0 * pulse
        if gst.peer:
            cr.set_source_rgba(0.13, 0.77, 0.37, 0.25)
            cr.arc(cx, cy, halo_r, 0, 2 * math.pi)
            cr.fill()
            cr.set_source_rgba(0.09, 0.64, 0.29, 0.9)
        else:
            cr.set_source_rgba(0.96, 0.62, 0.04, 0.25)
            cr.arc(cx, cy, halo_r, 0, 2 * math.pi)
            cr.fill()
            cr.set_source_rgba(0.96, 0.62, 0.04, 0.85)
        cr.arc(cx, cy, 4.0, 0, 2 * math.pi)
        cr.fill()
        return False

    pad_dot.connect("draw", on_draw_pad_dot)
    gate_dot.connect("draw", on_draw_gate_dot)

    def refresh_ui() -> bool:
        nonlocal last_events_snapshot
        snap = session.snapshot()
        st = listener.state()
        gst = gate.state()

        count_lbl.set_text(str(snap["unique_count"]))
        pad_status_lbl.set_text(f"Pad (:{port}): {'Connected' if st.peer else 'Connecting...'}")
        gate_status_lbl.set_text(
            f"Gate (:{gate_port}): {'Connected' if gst.peer else 'Listening...'}"
        )

        btn_ctx = scan_btn.get_style_context()
        if st.scanning:
            scan_btn.set_label("Stop Pad Scan")
            btn_ctx.remove_class("primary-btn")
            btn_ctx.add_class("danger-btn")
        else:
            scan_btn.set_label("Start Scanning")
            btn_ctx.remove_class("danger-btn")
            btn_ctx.add_class("primary-btn")

        gate_stats_lbl.set_text(
            f"Alarms: {gst.alarm_count} | Passed (Sold): {gst.pass_count} | Ignored: {gst.ignore_count}"
        )
        banner_ctx = gate_banner.get_style_context()
        banner_ctx.remove_class("banner-idle")
        banner_ctx.remove_class("banner-pass")
        banner_ctx.remove_class("banner-alarm")
        if gst.last_action == "ALARM":
            banner_ctx.add_class("banner-alarm")
        elif gst.last_action == "PASS":
            banner_ctx.add_class("banner-pass")
        else:
            banner_ctx.add_class("banner-idle")
        gate_banner.set_text(gst.last_summary)

        ev_list = gate.recent_events()
        ev_snap = [(e.at, e.action, ", ".join(e.epcs), e.summary) for e in ev_list[:30]]
        if ev_snap != last_events_snapshot:
            last_events_snapshot = ev_snap
            events_store.clear()
            for row in ev_snap:
                events_store.append(list(row))

        refresh_items_table()
        pad_dot.queue_draw()
        gate_dot.queue_draw()
        return True

    def on_toggle_scan(_btn: Gtk.Button) -> None:
        if listener.is_scanning():
            listener.set_scanning(False)
        else:
            session.reset()
            listener.set_scanning(True)
        refresh_ui()

    def on_demo_scan(_btn: Gtk.Button) -> None:
        session.observe(None, source="demo")
        refresh_items_table(force=True)
        refresh_ui()

    def on_mode_toggled(_rb: Gtk.RadioButton) -> None:
        if rb_checkout.get_active():
            session.set_pad_mode("checkout_sold")
        else:
            session.set_pad_mode("register_unsold")

    def on_add_unsold(_btn: Gtk.Button) -> None:
        raw_epc = epc_entry.get_text().strip()
        raw_name = name_entry.get_text().strip() or None
        if not raw_epc:
            return
        try:
            item_db.upsert_item(raw_epc, sold=False, name=raw_name)
            epc_entry.set_text("")
            name_entry.set_text("")
            refresh_items_table(force=True)
        except ValueError:
            pass

    def on_use_gate_epc(_btn: Gtk.Button) -> None:
        last_epc = gate.state().last_epc
        if last_epc:
            item_db.upsert_item(last_epc, sold=False)
            refresh_items_table(force=True)

    def on_toggle_selected(_btn=None) -> None:
        epc = get_selected_epc()
        if epc:
            item_db.toggle_sold(epc)
            refresh_items_table(force=True)

    def on_row_activated(_tree, path, _col) -> None:
        epc = items_store[path][0]
        item_db.toggle_sold(epc)
        refresh_items_table(force=True)

    def on_mark_sold(_btn: Gtk.Button) -> None:
        epc = get_selected_epc()
        if epc:
            item_db.set_sold(epc, True)
            refresh_items_table(force=True)

    def on_mark_unsold(_btn: Gtk.Button) -> None:
        epc = get_selected_epc()
        if epc:
            item_db.set_sold(epc, False)
            refresh_items_table(force=True)

    def on_sim_gate(_btn: Gtk.Button) -> None:
        epc = get_selected_epc() or epc_entry.get_text().strip()
        if epc:
            gate.simulate_gate_read([epc])
            refresh_ui()

    def on_delete_selected(_btn: Gtk.Button) -> None:
        epc = get_selected_epc()
        if epc:
            item_db.delete_item(epc)
            refresh_items_table(force=True)

    def on_clear_all(_btn: Gtk.Button) -> None:
        item_db.clear_items()
        refresh_items_table(force=True)

    def on_destroy(_win: Gtk.Window) -> None:
        listener.stop()
        gate.stop()
        Gtk.main_quit()

    scan_btn.connect("clicked", on_toggle_scan)
    demo_btn.connect("clicked", on_demo_scan)
    rb_register.connect("toggled", on_mode_toggled)
    rb_checkout.connect("toggled", on_mode_toggled)
    add_unsold_btn.connect("clicked", on_add_unsold)
    use_gate_epc_btn.connect("clicked", on_use_gate_epc)
    toggle_sold_btn.connect("clicked", on_toggle_selected)
    items_tree.connect("row-activated", on_row_activated)
    mark_sold_btn.connect("clicked", on_mark_sold)
    mark_unsold_btn.connect("clicked", on_mark_unsold)
    sim_gate_btn.connect("clicked", on_sim_gate)
    delete_btn.connect("clicked", on_delete_selected)
    clear_btn.connect("clicked", on_clear_all)
    win.connect("destroy", on_destroy)

    _auto_start_listener(listener, sdk_dir, port=port)
    gate.start(host="0.0.0.0", port=gate_port)
    win.show_all()
    refresh_items_table(force=True)
    refresh_ui()
    GLib.timeout_add(50, refresh_ui)
    Gtk.main()
    return 0


def run_tk_widget(
    session: ScanSession,
    listener: TcpDeactivatorListener,
    sdk_dir: Path,
    port: int = 9090,
    item_db: ItemDatabase | None = None,
    gate: RfidGateController | None = None,
    gate_port: int = 9000,
) -> int:
    if item_db is None:
        item_db = session.item_db or ItemDatabase()
        session.item_db = item_db
    if gate is None:
        gate = RfidGateController(item_db=item_db, sdk_dir=sdk_dir)

    # Start in idle state so Pad tags are only counted after clicking "Start Scanning"
    listener.set_scanning(False)
    # Start native Windows SDK (card_7k.dll / mfc140.dll) before initializing Tcl/Tk
    _auto_start_listener(listener, sdk_dir, port=port)
    gate.start(host="0.0.0.0", port=gate_port)

    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("HAX7700 Pad & HAX7000 RFID Gate Controller")
    root.geometry("940x690")
    root.configure(bg="#f8fafc", padx=16, pady=12)

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure("Treeview", font=("Segoe UI", 10), rowheight=26)
    style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))

    # --- Header: Title on left, Pad + Gate breathing indicators on right ---
    header = tk.Frame(root, bg="#f8fafc")
    header.pack(fill="x", pady=(0, 8))
    tk.Label(
        header,
        text="RFID Checkout & Gate Alarm Controller",
        font=("Segoe UI", 14, "bold"),
        fg="#0f172a",
        bg="#f8fafc",
    ).pack(side="left")

    status_frame = tk.Frame(header, bg="#f8fafc")
    status_frame.pack(side="right")

    pad_dot_canvas = tk.Canvas(status_frame, width=18, height=18, bg="#f8fafc", highlightthickness=0, bd=0)
    pad_dot_canvas.pack(side="left", padx=(0, 4))
    pad_halo_id = pad_dot_canvas.create_oval(1, 1, 17, 17, fill="#fef3c7", outline="")
    pad_core_id = pad_dot_canvas.create_oval(5, 5, 13, 13, fill="#f59e0b", outline="")

    pad_status_var = tk.StringVar(value=f"Pad (:{port}): Connecting...")
    pad_status_lbl = tk.Label(
        status_frame,
        textvariable=pad_status_var,
        font=("Segoe UI", 9, "bold"),
        fg="#d97706",
        bg="#f8fafc",
    )
    pad_status_lbl.pack(side="left", padx=(0, 14))

    gate_dot_canvas = tk.Canvas(status_frame, width=18, height=18, bg="#f8fafc", highlightthickness=0, bd=0)
    gate_dot_canvas.pack(side="left", padx=(0, 4))
    gate_halo_id = gate_dot_canvas.create_oval(1, 1, 17, 17, fill="#fef3c7", outline="")
    gate_core_id = gate_dot_canvas.create_oval(5, 5, 13, 13, fill="#f59e0b", outline="")

    gate_status_var = tk.StringVar(value=f"Gate (:{gate_port}): Listening...")
    gate_status_lbl = tk.Label(
        status_frame,
        textvariable=gate_status_var,
        font=("Segoe UI", 9, "bold"),
        fg="#d97706",
        bg="#f8fafc",
    )
    gate_status_lbl.pack(side="left")

    # --- Top Card: Pad Counter & Pad Scan Mode ---
    top_card = tk.Frame(root, bg="#ffffff", highlightbackground="#e2e8f0", highlightthickness=1, padx=14, pady=10)
    top_card.pack(fill="x", pady=(0, 10))

    counter_frame = tk.Frame(top_card, bg="#ffffff")
    counter_frame.pack(side="left", padx=(4, 24))
    count_var = tk.StringVar(value="0")
    tk.Label(
        counter_frame,
        textvariable=count_var,
        font=("Segoe UI", 34, "bold"),
        fg="#0f172a",
        bg="#ffffff",
    ).pack()
    tk.Label(
        counter_frame,
        text="Unique Pad Tags",
        font=("Segoe UI", 9, "bold"),
        fg="#64748b",
        bg="#ffffff",
    ).pack()

    pad_controls = tk.Frame(top_card, bg="#ffffff")
    pad_controls.pack(side="left", fill="both", expand=True)

    pad_btn_row = tk.Frame(pad_controls, bg="#ffffff")
    pad_btn_row.pack(fill="x", pady=(0, 8))

    def on_toggle_scan() -> None:
        if listener.is_scanning():
            listener.set_scanning(False)
        else:
            session.reset()
            listener.set_scanning(True)
        update_ui()

    def on_demo_scan() -> None:
        session.observe(None, source="demo")
        refresh_items_table(force=True)
        update_ui()

    scan_btn = tk.Button(
        pad_btn_row,
        text="Start Scanning",
        font=("Segoe UI", 10, "bold"),
        bg="#0f172a",
        fg="#ffffff",
        activebackground="#1e293b",
        activeforeground="#ffffff",
        relief="flat",
        bd=0,
        padx=14,
        pady=6,
        cursor="hand2",
        command=on_toggle_scan,
    )
    scan_btn.pack(side="left", padx=(0, 8))

    tk.Button(
        pad_btn_row,
        text="+ Scan Demo Item",
        font=("Segoe UI", 10, "bold"),
        bg="#e2e8f0",
        fg="#0f172a",
        relief="flat",
        bd=0,
        padx=12,
        pady=6,
        cursor="hand2",
        command=on_demo_scan,
    ).pack(side="left")

    mode_var = tk.StringVar(value=session.get_pad_mode())

    def on_mode_change() -> None:
        session.set_pad_mode(mode_var.get())

    mode_row = tk.Frame(pad_controls, bg="#ffffff")
    mode_row.pack(fill="x")
    tk.Label(
        mode_row,
        text="Pad Scan Mode:",
        font=("Segoe UI", 10, "bold"),
        fg="#0f172a",
        bg="#ffffff",
    ).pack(side="left", padx=(0, 10))
    tk.Radiobutton(
        mode_row,
        text="Register Item (sold = False -> Will Alarm)",
        variable=mode_var,
        value="register_unsold",
        font=("Segoe UI", 9, "bold"),
        bg="#ffffff",
        fg="#b91c1c",
        selectcolor="#ffffff",
        command=on_mode_change,
    ).pack(side="left", padx=(0, 14))
    tk.Radiobutton(
        mode_row,
        text="Customer Checkout (sold = True -> No Alarm)",
        variable=mode_var,
        value="checkout_sold",
        font=("Segoe UI", 9, "bold"),
        bg="#ffffff",
        fg="#15803d",
        selectcolor="#ffffff",
        command=on_mode_change,
    ).pack(side="left")

    # --- Middle Card: Items Table (sold: True / False) ---
    items_card = tk.Frame(root, bg="#ffffff", highlightbackground="#e2e8f0", highlightthickness=1, padx=14, pady=10)
    items_card.pack(fill="both", expand=True, pady=(0, 10))

    items_hdr = tk.Frame(items_card, bg="#ffffff")
    items_hdr.pack(fill="x", pady=(0, 6))
    tk.Label(
        items_hdr,
        text="Items Table — Double-click any item to toggle Sold (True / False)",
        font=("Segoe UI", 11, "bold"),
        fg="#0f172a",
        bg="#ffffff",
    ).pack(side="left")
    counts_var = tk.StringVar(value="Total: 0 | Sold (True): 0 | Unsold (False): 0")
    tk.Label(
        items_hdr,
        textvariable=counts_var,
        font=("Segoe UI", 9, "bold"),
        fg="#475569",
        bg="#ffffff",
    ).pack(side="right")

    tree_frame = tk.Frame(items_card, bg="#ffffff")
    tree_frame.pack(fill="both", expand=True, pady=(0, 8))

    cols = ("epc", "name", "sold", "gate_action", "updated_at")
    items_tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=7, selectmode="browse")
    items_tree.heading("epc", text="EPC (Hex)")
    items_tree.heading("name", text="Item Name")
    items_tree.heading("sold", text="Sold")
    items_tree.heading("gate_action", text="Gate Alarm Behavior")
    items_tree.heading("updated_at", text="Updated At (UTC)")

    items_tree.column("epc", width=230, anchor="w")
    items_tree.column("name", width=140, anchor="w")
    items_tree.column("sold", width=90, anchor="center")
    items_tree.column("gate_action", width=180, anchor="center")
    items_tree.column("updated_at", width=200, anchor="w")

    items_tree.tag_configure("sold_true", background="#f0fdf4", foreground="#166534")
    items_tree.tag_configure("sold_false", background="#fef2f2", foreground="#991b1b")

    tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=items_tree.yview)
    items_tree.configure(yscrollcommand=tree_scroll.set)
    items_tree.pack(side="left", fill="both", expand=True)
    tree_scroll.pack(side="right", fill="y")

    # Add EPC manually + Action Buttons
    add_row = tk.Frame(items_card, bg="#ffffff")
    add_row.pack(fill="x", pady=(0, 6))
    tk.Label(add_row, text="EPC:", font=("Segoe UI", 9, "bold"), bg="#ffffff").pack(side="left", padx=(0, 4))
    epc_entry = tk.Entry(add_row, width=28, font=("Consolas", 10))
    epc_entry.pack(side="left", padx=(0, 8))
    tk.Label(add_row, text="Name:", font=("Segoe UI", 9, "bold"), bg="#ffffff").pack(side="left", padx=(0, 4))
    name_entry = tk.Entry(add_row, width=16, font=("Segoe UI", 10))
    name_entry.pack(side="left", padx=(0, 8))

    last_items_snapshot: list[tuple] = []
    last_events_snapshot: list[tuple] = []

    def get_selected_epc() -> str | None:
        sel = items_tree.selection()
        if not sel:
            return None
        vals = items_tree.item(sel[0], "values")
        return str(vals[0]) if vals else None

    def refresh_items_table(force: bool = False) -> None:
        nonlocal last_items_snapshot
        rows = item_db.list_items()
        snap = [
            (r["epc"], r["name"], "TRUE" if r["sold"] else "FALSE", r["gate_action"], r["updated_at"])
            for r in rows
        ]
        c = item_db.counts()
        counts_var.set(f"Total: {c['total']} | Sold (True): {c['sold']} | Unsold (False): {c['unsold']}")
        if not force and snap == last_items_snapshot:
            return
        selected_epc = get_selected_epc()
        last_items_snapshot = snap
        items_tree.delete(*items_tree.get_children())
        for tup in snap:
            tag = "sold_true" if tup[2] == "TRUE" else "sold_false"
            iid = items_tree.insert("", "end", values=tup, tags=(tag,))
            if selected_epc and tup[0] == selected_epc:
                items_tree.selection_set(iid)

    def on_add_unsold() -> None:
        raw_epc = epc_entry.get().strip()
        raw_name = name_entry.get().strip() or None
        if not raw_epc:
            return
        try:
            item_db.upsert_item(raw_epc, sold=False, name=raw_name)
            epc_entry.delete(0, "end")
            name_entry.delete(0, "end")
            refresh_items_table(force=True)
        except ValueError:
            pass

    def on_add_last_gate_epc() -> None:
        last_epc = gate.state().last_epc
        if last_epc:
            item_db.upsert_item(last_epc, sold=False)
            refresh_items_table(force=True)

    tk.Button(
        add_row,
        text="Add Item (sold=False)",
        font=("Segoe UI", 9, "bold"),
        bg="#e2e8f0",
        fg="#0f172a",
        relief="flat",
        padx=10,
        pady=4,
        cursor="hand2",
        command=on_add_unsold,
    ).pack(side="left", padx=(0, 6))

    tk.Button(
        add_row,
        text="Add Last Gate EPC",
        font=("Segoe UI", 9, "bold"),
        bg="#e2e8f0",
        fg="#0f172a",
        relief="flat",
        padx=10,
        pady=4,
        cursor="hand2",
        command=on_add_last_gate_epc,
    ).pack(side="left")

    action_row = tk.Frame(items_card, bg="#ffffff")
    action_row.pack(fill="x")

    def on_toggle_sold(_event=None) -> None:
        epc = get_selected_epc()
        if epc:
            item_db.toggle_sold(epc)
            refresh_items_table(force=True)

    def on_mark_sold() -> None:
        epc = get_selected_epc()
        if epc:
            item_db.set_sold(epc, True)
            refresh_items_table(force=True)

    def on_mark_unsold() -> None:
        epc = get_selected_epc()
        if epc:
            item_db.set_sold(epc, False)
            refresh_items_table(force=True)

    def on_sim_gate() -> None:
        epc = get_selected_epc() or epc_entry.get().strip()
        if epc:
            gate.simulate_gate_read([epc])
            update_ui()

    def on_delete_selected() -> None:
        epc = get_selected_epc()
        if epc:
            item_db.delete_item(epc)
            refresh_items_table(force=True)

    def on_clear_all() -> None:
        item_db.clear_items()
        refresh_items_table(force=True)

    items_tree.bind("<Double-1>", on_toggle_sold)

    tk.Button(
        action_row,
        text="Toggle Sold (True / False)",
        font=("Segoe UI", 9, "bold"),
        bg="#0f172a",
        fg="#ffffff",
        relief="flat",
        padx=12,
        pady=5,
        cursor="hand2",
        command=on_toggle_sold,
    ).pack(side="left", padx=(0, 6))

    tk.Button(
        action_row,
        text="Mark Sold (True -> No Alarm)",
        font=("Segoe UI", 9, "bold"),
        bg="#16a34a",
        fg="#ffffff",
        relief="flat",
        padx=12,
        pady=5,
        cursor="hand2",
        command=on_mark_sold,
    ).pack(side="left", padx=(0, 6))

    tk.Button(
        action_row,
        text="Mark Unsold (False -> Alarm)",
        font=("Segoe UI", 9, "bold"),
        bg="#dc2626",
        fg="#ffffff",
        relief="flat",
        padx=12,
        pady=5,
        cursor="hand2",
        command=on_mark_unsold,
    ).pack(side="left", padx=(0, 6))

    tk.Button(
        action_row,
        text="Test Gate Pass (Selected Item)",
        font=("Segoe UI", 9, "bold"),
        bg="#2563eb",
        fg="#ffffff",
        relief="flat",
        padx=12,
        pady=5,
        cursor="hand2",
        command=on_sim_gate,
    ).pack(side="left", padx=(0, 6))

    tk.Button(
        action_row,
        text="Clear All",
        font=("Segoe UI", 9, "bold"),
        bg="#f1f5f9",
        fg="#475569",
        relief="flat",
        padx=10,
        pady=5,
        cursor="hand2",
        command=on_clear_all,
    ).pack(side="right")

    tk.Button(
        action_row,
        text="Delete",
        font=("Segoe UI", 9, "bold"),
        bg="#f1f5f9",
        fg="#b91c1c",
        relief="flat",
        padx=10,
        pady=5,
        cursor="hand2",
        command=on_delete_selected,
    ).pack(side="right", padx=(0, 6))

    # --- Bottom Card: RFID Gate Monitor & Live Log ---
    gate_card = tk.Frame(root, bg="#ffffff", highlightbackground="#e2e8f0", highlightthickness=1, padx=14, pady=10)
    gate_card.pack(fill="x")

    gate_hdr = tk.Frame(gate_card, bg="#ffffff")
    gate_hdr.pack(fill="x", pady=(0, 6))
    tk.Label(
        gate_hdr,
        text=f"RFID Gate Monitor (Port {gate_port} — SDK 2.1.2.0 ServerControl & DeviceAlarm)",
        font=("Segoe UI", 11, "bold"),
        fg="#0f172a",
        bg="#ffffff",
    ).pack(side="left")
    gate_stats_var = tk.StringVar(value="Alarms: 0 | Passed (Sold): 0 | Ignored: 0")
    tk.Label(
        gate_hdr,
        textvariable=gate_stats_var,
        font=("Segoe UI", 9, "bold"),
        fg="#475569",
        bg="#ffffff",
    ).pack(side="right")

    gate_banner_var = tk.StringVar(value="Waiting for RFID Gate connection...")
    gate_banner = tk.Label(
        gate_card,
        textvariable=gate_banner_var,
        font=("Segoe UI", 10, "bold"),
        bg="#f1f5f9",
        fg="#334155",
        anchor="w",
        padx=10,
        pady=6,
    )
    gate_banner.pack(fill="x", pady=(0, 6))

    ev_cols = ("at", "action", "epcs", "summary")
    events_tree = ttk.Treeview(gate_card, columns=ev_cols, show="headings", height=4)
    events_tree.heading("at", text="Time (UTC)")
    events_tree.heading("action", text="Decision")
    events_tree.heading("epcs", text="EPC(s)")
    events_tree.heading("summary", text="Details")
    events_tree.column("at", width=180, anchor="w")
    events_tree.column("action", width=100, anchor="center")
    events_tree.column("epcs", width=230, anchor="w")
    events_tree.column("summary", width=360, anchor="w")
    events_tree.tag_configure("ALARM", background="#fee2e2", foreground="#991b1b")
    events_tree.tag_configure("PASS", background="#dcfce7", foreground="#166534")
    events_tree.pack(fill="x")

    def update_ui() -> None:
        nonlocal last_events_snapshot
        snap = session.snapshot()
        st = listener.state()
        gst = gate.state()
        count_var.set(str(snap["unique_count"]))

        pulse = 0.5 + 0.5 * math.sin(time.monotonic() * 4.2)
        halo_r = 4.5 + 3.5 * pulse
        pad_dot_canvas.coords(pad_halo_id, 9.0 - halo_r, 9.0 - halo_r, 9.0 + halo_r, 9.0 + halo_r)
        gate_dot_canvas.coords(gate_halo_id, 9.0 - halo_r, 9.0 - halo_r, 9.0 + halo_r, 9.0 + halo_r)

        if st.peer:
            pad_status_var.set(f"Pad (:{port}): Connected")
            pad_status_lbl.configure(fg="#16a34a")
            pad_dot_canvas.itemconfig(pad_halo_id, fill=_lerp_hex("#f8fafc", "#bbf7d0", 0.35 + 0.65 * pulse))
            pad_dot_canvas.itemconfig(pad_core_id, fill=_lerp_hex("#22c55e", "#15803d", pulse))
        else:
            pad_status_var.set(f"Pad (:{port}): Connecting...")
            pad_status_lbl.configure(fg="#d97706")
            pad_dot_canvas.itemconfig(pad_halo_id, fill=_lerp_hex("#f8fafc", "#fde68a", 0.35 + 0.65 * pulse))
            pad_dot_canvas.itemconfig(pad_core_id, fill=_lerp_hex("#fcd34d", "#d97706", pulse))

        if gst.peer:
            gate_status_var.set(f"Gate (:{gate_port}): Connected")
            gate_status_lbl.configure(fg="#16a34a")
            gate_dot_canvas.itemconfig(gate_halo_id, fill=_lerp_hex("#f8fafc", "#bbf7d0", 0.35 + 0.65 * pulse))
            gate_dot_canvas.itemconfig(gate_core_id, fill=_lerp_hex("#22c55e", "#15803d", pulse))
        else:
            gate_status_var.set(f"Gate (:{gate_port}): Listening...")
            gate_status_lbl.configure(fg="#d97706")
            gate_dot_canvas.itemconfig(gate_halo_id, fill=_lerp_hex("#f8fafc", "#fde68a", 0.35 + 0.65 * pulse))
            gate_dot_canvas.itemconfig(gate_core_id, fill=_lerp_hex("#fcd34d", "#d97706", pulse))

        if st.scanning:
            scan_btn.configure(
                text="Stop Pad Scan",
                bg="#dc2626",
                fg="#ffffff",
                activebackground="#b91c1c",
                activeforeground="#ffffff",
            )
        else:
            scan_btn.configure(
                text="Start Scanning",
                bg="#0f172a",
                fg="#ffffff",
                activebackground="#1e293b",
                activeforeground="#ffffff",
            )

        gate_stats_var.set(
            f"Alarms: {gst.alarm_count} | Passed (Sold): {gst.pass_count} | Ignored: {gst.ignore_count}"
        )
        gate_banner_var.set(gst.last_summary)
        if gst.last_action == "ALARM":
            gate_banner.configure(bg="#fee2e2", fg="#991b1b")
        elif gst.last_action == "PASS":
            gate_banner.configure(bg="#dcfce7", fg="#166534")
        else:
            gate_banner.configure(bg="#f1f5f9", fg="#334155")

        ev_list = gate.recent_events()
        ev_snap = [(e.at, e.action, ", ".join(e.epcs), e.summary) for e in ev_list[:30]]
        if ev_snap != last_events_snapshot:
            last_events_snapshot = ev_snap
            events_tree.delete(*events_tree.get_children())
            for row in ev_snap:
                tags = (row[1],) if row[1] in ("ALARM", "PASS") else ()
                events_tree.insert("", "end", values=row, tags=tags)

        refresh_items_table()

    def tick() -> None:
        update_ui()
        root.after(50, tick)

    def on_close() -> None:
        listener.stop()
        gate.stop()
        root.destroy()
        os._exit(0)

    root.protocol("WM_DELETE_WINDOW", on_close)
    refresh_items_table(force=True)
    tick()
    root.mainloop()
    return 0
