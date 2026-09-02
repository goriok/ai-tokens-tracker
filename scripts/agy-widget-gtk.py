#!/usr/bin/env python3
"""AGY Token Widget - native GTK3 always-on-top panel."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, Gdk
from datetime import datetime, timezone
from collections import defaultdict

from adapters.sqlite_usage_store import SqliteUsageStore


def tok(n):
    if n >= 1e6: return f"{n/1e6:.1f}M"
    if n >= 1e3: return f"{n/1e3:.1f}K"
    return str(n)


class AgyWidget(Gtk.Window):
    def __init__(self):
        super().__init__(title="AGY-TOKENS")
        self.set_default_size(220, 190)
        self.set_size_request(220, 190)
        self.set_resizable(False)
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)

        # Dark theme
        css = b"""
        window { background: #1a1b26; }
        .title { color: #7aa2f7; font-size: 11px; font-weight: bold; }
        .section { color: #565f89; font-size: 9px; }
        .label { color: #565f89; font-size: 10px; }
        .value { color: #c0caf5; font-size: 10px; font-weight: bold; }
        .top { color: #7aa2f7; font-size: 10px; }
        .dim { color: #444b6a; font-size: 8px; }
        .sep { color: #33364a; }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_margin_start(10)
        box.set_margin_end(10)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        self.add(box)

        # Title
        title = Gtk.Label(label="⚡ AGY tokens")
        title.get_style_context().add_class("title")
        title.set_xalign(0)
        box.add(title)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.get_style_context().add_class("sep")
        box.add(sep)

        # Weekly quota section
        sec = Gtk.Label(label="QUOTA SEMANAL")
        sec.get_style_context().add_class("section")
        sec.set_xalign(0)
        box.add(sec)

        self.quota_rows = {}

        sep2 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep2.get_style_context().add_class("sep")
        box.add(sep2)

        # Task calls section (tracked -p calls only)
        sec2 = Gtk.Label(label="TAREFAS RASTREADAS (HOJE)")
        sec2.get_style_context().add_class("section")
        sec2.set_xalign(0)
        box.add(sec2)

        self.calls_label = self._row(box, "calls")
        self.tokens_label = self._row(box, "tokens")
        self.top_label = self._row(box, "top model")

        self.quota_box = box  # insert quota rows dynamically before this point

        self.ts_label = Gtk.Label(label="")
        self.ts_label.get_style_context().add_class("dim")
        self.ts_label.set_xalign(1)
        box.add(self.ts_label)

        # Drag to move
        self.connect("button-press-event", self.on_click)
        self._drag = False
        self._dx = 0
        self._dy = 0

        # Right-click to close
        self.connect("destroy", Gtk.main_quit)

        self.refresh()
        GLib.timeout_add(15000, self.refresh)

        # Position top-right of primary monitor (1920x1080)
        self.move(1700, 40)

    def _row(self, parent, label):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        l = Gtk.Label(label=f"  {label}:")
        l.get_style_context().add_class("label")
        l.set_xalign(0)
        l.set_hexpand(True)
        v = Gtk.Label(label="—")
        v.get_style_context().add_class("value")
        v.set_xalign(1)
        box.add(l)
        box.add(v)
        parent.add(box)
        box.show_all()
        return v

    def refresh(self):
        store = SqliteUsageStore()
        try:
            snapshots = store.list_snapshots()
            calls = store.list_task_calls()
        finally:
            store.close()

        # latest snapshot per model group
        latest = {}
        for s in snapshots:
            latest[s.model_group] = s  # snapshots are ordered by timestamp, last wins
        for group, snap in latest.items():
            if group not in self.quota_rows:
                self.quota_rows[group] = self._row(self.quota_box, group[:14])
            self.quota_rows[group].set_text(f"{snap.remaining_fraction*100:.0f}%")

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today = [c for c in calls if c.timestamp[:10] == today_str]

        tc = len(today)
        tt = sum(c.total_tokens for c in today)

        by_m = defaultdict(int)
        for c in today: by_m[c.model] += 1
        top = max(by_m, key=by_m.get) if by_m else "—"

        self.calls_label.set_text(str(tc))
        self.tokens_label.set_text(tok(tt))
        self.top_label.set_text(top[:20])

        self.ts_label.set_text(datetime.now().strftime("%H:%M:%S"))
        return True

    def on_click(self, widget, event):
        if event.button == 3:  # Right-click = close
            self.destroy()
            return True
        # Drag
        self._drag = True
        self._dx = int(event.x_root - self.get_position()[0])
        self._dy = int(event.y_root - self.get_position()[1])
        self.connect("motion-notify-event", self.on_drag)
        self.connect("button-release-event", self.on_release)
        return True

    def on_drag(self, widget, event):
        if self._drag:
            self.move(int(event.x_root - self._dx), int(event.y_root - self._dy))
        return True

    def on_release(self, widget, event):
        self._drag = False
        self.disconnect_by_func(self.on_drag)
        self.disconnect_by_func(self.on_release)
        return True


if __name__ == "__main__":
    win = AgyWidget()
    win.show_all()
    Gtk.main()
