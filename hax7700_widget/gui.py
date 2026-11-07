"""Simple, clean Desktop UI for Real RFID Tags Table (Sold: True/False) + RFID Gate Alarm (GTK3 on Linux, Tkinter on Windows)."""

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
    serial_port: str | None = None,
) -> int:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib, Gtk

    if item_db is None:
        item_db = session.item_db or ItemDatabase()
        session.item_db = item_db
    if gate is None:
        gate = RfidGateController(item_db=item_db, sdk_dir=sdk_dir, session=session)
    else:
        gate.session = session

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
      font-size: 16px;
      font-weight: 800;
    }
    .status-text {
      color: #52525b;
      font-size: 12px;
      font-weight: 600;
    }
    .gate-box-idle {
      background-color: #f4f4f5;
      color: #3f3f46;
      border-radius: 8px;
      padding: 14px;
      font-size: 13px;
      font-weight: 700;
    }
    .gate-box-pass {
      background-color: #dcfce7;
      color: #166534;
      border-radius: 8px;
      padding: 14px;
      font-size: 15px;
      font-weight: 800;
    }
    .gate-box-alarm {
      background-color: #fee2e2;
      color: #991b1b;
      border-radius: 8px;
      padding: 14px;
      font-size: 15px;
      font-weight: 800;
    }
    .primary-btn {
      background-image: none;
      background-color: #18181b;
      color: #ffffff;
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
    .btn-blue {
      background-image: none;
      background-color: #2563eb;
      color: #ffffff;
      font-weight: 700;
      border-radius: 6px;
      padding: 10px 14px;
    }
    .btn-light {
      background-image: none;
      background-color: #f4f4f5;
      color: #18181b;
      font-weight: 700;
      border-radius: 6px;
      padding: 10px 14px;
    }
    """
    provider = Gtk.CssProvider()
    provider.load_from_data(css)
    screen = Gtk.Window().get_screen()
    Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    listener.set_scanning(False)
    gate.set_register_mode(False)

    win = Gtk.Window(title="HAX7700 & RFID Gate")
    win.set_default_size(520, 420)
    win.set_border_width(16)

    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    win.add(root)

    # 1. Header: Title + Connection Status
    header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    header.get_style_context().add_class("header-box")
    title = Gtk.Label(label="RFID Items (0)", xalign=0)
    title.get_style_context().add_class("title")

    status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    dot_area = Gtk.DrawingArea()
    dot_area.set_size_request(16, 16)
    status_lbl = Gtk.Label(label="Connecting...", xalign=1)
    status_lbl.get_style_context().add_class("status-text")
    status_box.pack_start(dot_area, False, False, 0)
    status_box.pack_start(status_lbl, False, False, 0)

    header.pack_start(title, True, True, 0)
    header.pack_end(status_box, False, False, 0)
    root.pack_start(header, False, False, 0)

    # 2. Gate Banner (shows Gate Alarm status from real Gate hardware)
    gate_banner = Gtk.Label(label="Gate Status: Waiting for tag...", xalign=0.5)
    gate_banner.get_style_context().add_class("gate-box-idle")
    root.pack_start(gate_banner, False, False, 0)

    # 3. Clean 3-Column Table for Real Scanned Tags: Item | EPC Tag | Sold
    items_store = Gtk.ListStore(str, str, str, str, str)
    items_tree = Gtk.TreeView(model=items_store)
    items_tree.set_headers_visible(True)

    col_item = Gtk.TreeViewColumn("Item", Gtk.CellRendererText(), text=1, background=3, foreground=4)
    col_item.set_min_width(110)
    items_tree.append_column(col_item)

    col_epc = Gtk.TreeViewColumn("EPC Tag", Gtk.CellRendererText(), text=0, background=3, foreground=4)
    col_epc.set_min_width(250)
    items_tree.append_column(col_epc)

    renderer_sold = Gtk.CellRendererText()
    renderer_sold.set_property("xalign", 0.5)
    col_sold = Gtk.TreeViewColumn("Sold", renderer_sold, text=2, background=3, foreground=4)
    col_sold.set_min_width(100)
    items_tree.append_column(col_sold)

    scroll = Gtk.ScrolledWindow()
    scroll.set_vexpand(True)
    scroll.add(items_tree)
    root.pack_start(scroll, True, True, 0)

    # 4. Bottom Action Bar: Start Scanning | Sold: True / False | Clear
    btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

    scan_btn = Gtk.Button(label="Start Scanning")
    scan_btn.get_style_context().add_class("primary-btn")

    toggle_btn = Gtk.Button(label="Sold: True / False")
    toggle_btn.get_style_context().add_class("btn-blue")

    clear_btn = Gtk.Button(label="Clear")
    clear_btn.get_style_context().add_class("btn-light")

    btn_row.pack_start(scan_btn, True, True, 0)
    btn_row.pack_start(toggle_btn, True, True, 0)
    btn_row.pack_end(clear_btn, False, False, 0)
    root.pack_start(btn_row, False, False, 0)

    last_items_snapshot: list[tuple] = []

    def get_selected_epc() -> str | None:
        selection = items_tree.get_selection()
        model, tree_iter = selection.get_selected()
        if tree_iter is not None:
            return model[tree_iter][0]
        return None

    def refresh_items_table(force: bool = False) -> None:
        nonlocal last_items_snapshot
        rows = item_db.list_items()
        snap = [(r["epc"], r["name"], "True" if r["sold"] else "False") for r in rows]
        title.set_text(f"RFID Items ({len(snap)})")
        if not force and snap == last_items_snapshot:
            return
        selected_epc = get_selected_epc()
        last_items_snapshot = snap
        items_store.clear()
        first_iter = None
        restore_iter = None
        for epc, name, sold_str in snap:
            if sold_str == "True":
                bg, fg = "#dcfce7", "#166534"
            else:
                bg, fg = "#fee2e2", "#991b1b"
            it = items_store.append([epc, name, sold_str, bg, fg])
            if first_iter is None:
                first_iter = it
            if selected_epc and epc == selected_epc:
                restore_iter = it
        target_iter = restore_iter or first_iter
        if target_iter is not None:
            items_tree.get_selection().select_iter(target_iter)

    def on_draw_dot(_area, cr) -> bool:
        st = listener.state()
        gst = gate.state()
        connected = bool(st.peer or gst.peer)
        pulse = 0.5 + 0.5 * math.sin(time.monotonic() * 4.0)
        cx, cy = 8.0, 8.0
        halo_r = 4.5 + 3.0 * pulse
        if connected:
            cr.set_source_rgba(0.13, 0.77, 0.37, 0.22)
            cr.arc(cx, cy, halo_r, 0, 2 * math.pi)
            cr.fill()
            cr.set_source_rgba(0.09, 0.64, 0.29, 0.9)
        else:
            cr.set_source_rgba(0.96, 0.62, 0.04, 0.22)
            cr.arc(cx, cy, halo_r, 0, 2 * math.pi)
            cr.fill()
            cr.set_source_rgba(0.96, 0.62, 0.04, 0.85)
        cr.arc(cx, cy, 4.0, 0, 2 * math.pi)
        cr.fill()
        return False

    dot_area.connect("draw", on_draw_dot)

    def refresh_ui() -> bool:
        st = listener.state()
        gst = gate.state()

        if gst.peer:
            status_lbl.set_text(f"Connected ({gst.peer})")
        elif st.peer:
            status_lbl.set_text(f"Connected ({st.peer})")
        elif gst.serial_port:
            status_lbl.set_text(f"Opening {gst.serial_port}...")
        else:
            status_lbl.set_text("Connecting...")

        btn_ctx = scan_btn.get_style_context()
        if st.scanning:
            scan_btn.set_label("Stop")
            btn_ctx.remove_class("primary-btn")
            btn_ctx.add_class("danger-btn")
        else:
            scan_btn.set_label("Start Scanning")
            btn_ctx.remove_class("danger-btn")
            btn_ctx.add_class("primary-btn")

        ctx = gate_banner.get_style_context()
        ctx.remove_class("gate-box-idle")
        ctx.remove_class("gate-box-pass")
        ctx.remove_class("gate-box-alarm")

        if gst.last_error:
            ctx.add_class("gate-box-alarm")
            gate_banner.set_text(gst.last_error)
        elif gst.last_action == "ALARM":
            ctx.add_class("gate-box-alarm")
            gate_banner.set_text(f"GATE ALARM! — {gst.last_epc} (Sold = False)")
        elif gst.last_action == "PASS":
            ctx.add_class("gate-box-pass")
            gate_banner.set_text(f"NO ALARM — {gst.last_epc} (Sold = True)")
        elif gst.last_action == "REGISTERED":
            ctx.add_class("gate-box-pass")
            gate_banner.set_text(gst.last_summary)
        else:
            ctx.add_class("gate-box-idle")
            gate_banner.set_text("Gate Status: Waiting for tag...")

        refresh_items_table()
        dot_area.queue_draw()
        return True

    def on_toggle_scan(_btn: Gtk.Button) -> None:
        if listener.is_scanning():
            listener.set_scanning(False)
            gate.set_register_mode(False)
        else:
            session.reset()
            listener.set_scanning(True)
            gate.set_register_mode(True)
        refresh_ui()

    def on_toggle_sold(_btn=None) -> None:
        epc = get_selected_epc()
        if epc:
            item_db.toggle_sold(epc)
            refresh_items_table(force=True)
            refresh_ui()

    def on_row_activated(_tree, path, _col) -> None:
        epc = items_store[path][0]
        item_db.toggle_sold(epc)
        refresh_items_table(force=True)
        refresh_ui()

    def on_clear(_btn: Gtk.Button) -> None:
        session.reset()
        item_db.clear_items()
        gate._state.last_action = "IDLE"
        gate._state.last_epc = ""
        refresh_items_table(force=True)
        refresh_ui()

    def on_destroy(_win: Gtk.Window) -> None:
        listener.stop()
        gate.stop()
        Gtk.main_quit()

    scan_btn.connect("clicked", on_toggle_scan)
    toggle_btn.connect("clicked", on_toggle_sold)
    items_tree.connect("row-activated", on_row_activated)
    clear_btn.connect("clicked", on_clear)
    win.connect("destroy", on_destroy)

    _auto_start_listener(listener, sdk_dir, port=port)
    gate.start(host="0.0.0.0", port=gate_port, serial_port=serial_port)
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
    serial_port: str | None = None,
) -> int:
    if item_db is None:
        item_db = session.item_db or ItemDatabase()
        session.item_db = item_db
    if gate is None:
        gate = RfidGateController(item_db=item_db, sdk_dir=sdk_dir, session=session)
    else:
        gate.session = session

    listener.set_scanning(False)
    gate.set_register_mode(False)
    _auto_start_listener(listener, sdk_dir, port=port)
    gate.start(host="0.0.0.0", port=gate_port, serial_port=serial_port)

    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("HAX7700 & RFID Gate")
    root.geometry("540x430")
    root.configure(bg="#ffffff", padx=16, pady=14)

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure("Treeview", font=("Segoe UI", 10), rowheight=30)
    style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))

    # 1. Header
    header = tk.Frame(root, bg="#ffffff")
    header.pack(fill="x", pady=(0, 10))
    title_var = tk.StringVar(value="RFID Items (0)")
    tk.Label(
        header,
        textvariable=title_var,
        font=("Segoe UI", 14, "bold"),
        fg="#18181b",
        bg="#ffffff",
    ).pack(side="left")

    status_frame = tk.Frame(header, bg="#ffffff")
    status_frame.pack(side="right")
    dot_canvas = tk.Canvas(status_frame, width=16, height=16, bg="#ffffff", highlightthickness=0, bd=0)
    dot_canvas.pack(side="left", padx=(0, 5))
    halo_id = dot_canvas.create_oval(1, 1, 15, 15, fill="#fef3c7", outline="")
    core_id = dot_canvas.create_oval(4, 4, 12, 12, fill="#f59e0b", outline="")

    status_var = tk.StringVar(value="Connecting...")
    status_lbl = tk.Label(
        status_frame,
        textvariable=status_var,
        font=("Segoe UI", 9, "bold"),
        fg="#d97706",
        bg="#ffffff",
    )
    status_lbl.pack(side="left")

    # 2. Gate Banner
    gate_var = tk.StringVar(value="Gate Status: Waiting for tag...")
    gate_banner = tk.Label(
        root,
        textvariable=gate_var,
        font=("Segoe UI", 10, "bold"),
        bg="#f4f4f5",
        fg="#3f3f46",
        pady=12,
        padx=10,
    )
    gate_banner.pack(fill="x", pady=(0, 12))

    # 3. Clean 3-Column Table: Item | EPC Tag | Sold
    tree_frame = tk.Frame(root, bg="#ffffff")
    tree_frame.pack(fill="both", expand=True, pady=(0, 12))

    cols = ("name", "epc", "sold")
    items_tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")
    items_tree.heading("name", text="Item")
    items_tree.heading("epc", text="EPC Tag")
    items_tree.heading("sold", text="Sold")

    items_tree.column("name", width=110, anchor="w")
    items_tree.column("epc", width=260, anchor="w")
    items_tree.column("sold", width=100, anchor="center")

    items_tree.tag_configure("sold_true", background="#dcfce7", foreground="#166534")
    items_tree.tag_configure("sold_false", background="#fee2e2", foreground="#991b1b")

    tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=items_tree.yview)
    items_tree.configure(yscrollcommand=tree_scroll.set)
    items_tree.pack(side="left", fill="both", expand=True)
    tree_scroll.pack(side="right", fill="y")

    last_items_snapshot: list[tuple] = []

    def get_selected_epc() -> str | None:
        sel = items_tree.selection()
        if not sel:
            return None
        vals = items_tree.item(sel[0], "values")
        return str(vals[1]) if vals and len(vals) > 1 else None

    def refresh_items_table(force: bool = False) -> None:
        nonlocal last_items_snapshot
        rows = item_db.list_items()
        snap = [(r["name"], r["epc"], "True" if r["sold"] else "False") for r in rows]
        title_var.set(f"RFID Items ({len(snap)})")
        if not force and snap == last_items_snapshot:
            return
        selected_epc = get_selected_epc()
        last_items_snapshot = snap
        items_tree.delete(*items_tree.get_children())
        first_iid = None
        restore_iid = None
        for tup in snap:
            tag = "sold_true" if tup[2] == "True" else "sold_false"
            iid = items_tree.insert("", "end", values=tup, tags=(tag,))
            if first_iid is None:
                first_iid = iid
            if selected_epc and tup[1] == selected_epc:
                restore_iid = iid
        target = restore_iid or first_iid
        if target is not None:
            items_tree.selection_set(target)

    # 4. Bottom Action Bar: Start Scanning | Sold: True / False | Clear
    btn_row = tk.Frame(root, bg="#ffffff")
    btn_row.pack(fill="x")

    def on_toggle_scan() -> None:
        if listener.is_scanning():
            listener.set_scanning(False)
            gate.set_register_mode(False)
        else:
            session.reset()
            listener.set_scanning(True)
            gate.set_register_mode(True)
        update_ui()

    def on_toggle_sold(_event=None) -> None:
        epc = get_selected_epc()
        if epc:
            item_db.toggle_sold(epc)
            refresh_items_table(force=True)
            update_ui()

    def on_clear() -> None:
        session.reset()
        item_db.clear_items()
        gate._state.last_action = "IDLE"
        gate._state.last_epc = ""
        refresh_items_table(force=True)
        update_ui()

    items_tree.bind("<Double-1>", on_toggle_sold)

    scan_btn = tk.Button(
        btn_row,
        text="Start Scanning",
        font=("Segoe UI", 10, "bold"),
        bg="#18181b",
        fg="#ffffff",
        activebackground="#27272a",
        activeforeground="#ffffff",
        relief="flat",
        padx=14,
        pady=8,
        cursor="hand2",
        command=on_toggle_scan,
    )
    scan_btn.pack(side="left", expand=True, fill="x", padx=(0, 8))

    tk.Button(
        btn_row,
        text="Sold: True / False",
        font=("Segoe UI", 10, "bold"),
        bg="#2563eb",
        fg="#ffffff",
        activebackground="#1d4ed8",
        activeforeground="#ffffff",
        relief="flat",
        padx=14,
        pady=8,
        cursor="hand2",
        command=on_toggle_sold,
    ).pack(side="left", expand=True, fill="x", padx=(0, 8))

    tk.Button(
        btn_row,
        text="Clear",
        font=("Segoe UI", 10, "bold"),
        bg="#f4f4f5",
        fg="#52525b",
        relief="flat",
        padx=12,
        pady=8,
        cursor="hand2",
        command=on_clear,
    ).pack(side="right")

    def update_ui() -> None:
        st = listener.state()
        gst = gate.state()
        connected = bool(st.peer or gst.peer)

        pulse = 0.5 + 0.5 * math.sin(time.monotonic() * 4.2)
        halo_r = 4.0 + 3.0 * pulse
        dot_canvas.coords(halo_id, 8.0 - halo_r, 8.0 - halo_r, 8.0 + halo_r, 8.0 + halo_r)

        if gst.peer:
            status_var.set(f"Connected ({gst.peer})")
            status_lbl.configure(fg="#16a34a")
        elif st.peer:
            status_var.set(f"Connected ({st.peer})")
            status_lbl.configure(fg="#16a34a")
        elif gst.serial_port:
            status_var.set(f"Opening {gst.serial_port}...")
            status_lbl.configure(fg="#d97706")
        else:
            status_var.set("Connecting...")
            status_lbl.configure(fg="#d97706")

        if connected:
            dot_canvas.itemconfig(halo_id, fill=_lerp_hex("#ffffff", "#bbf7d0", 0.35 + 0.65 * pulse))
            dot_canvas.itemconfig(core_id, fill=_lerp_hex("#22c55e", "#15803d", pulse))
        else:
            dot_canvas.itemconfig(halo_id, fill=_lerp_hex("#ffffff", "#fde68a", 0.35 + 0.65 * pulse))
            dot_canvas.itemconfig(core_id, fill=_lerp_hex("#fcd34d", "#d97706", pulse))

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
                fg="#ffffff",
                activebackground="#27272a",
                activeforeground="#ffffff",
            )

        if gst.last_error:
            gate_var.set(gst.last_error)
            gate_banner.configure(bg="#fee2e2", fg="#991b1b")
        elif gst.last_action == "ALARM":
            gate_var.set(f"GATE ALARM! — {gst.last_epc} (Sold = False)")
            gate_banner.configure(bg="#fee2e2", fg="#991b1b")
        elif gst.last_action == "PASS":
            gate_var.set(f"NO ALARM — {gst.last_epc} (Sold = True)")
            gate_banner.configure(bg="#dcfce7", fg="#166534")
        elif gst.last_action == "REGISTERED":
            gate_var.set(gst.last_summary)
            gate_banner.configure(bg="#dcfce7", fg="#166534")
        else:
            gate_var.set("Gate Status: Waiting for tag...")
            gate_banner.configure(bg="#f4f4f5", fg="#3f3f46")

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
