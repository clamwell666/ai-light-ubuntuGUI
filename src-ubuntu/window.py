from __future__ import annotations

import os
from typing import Callable, Dict, Optional

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk

import actions
import config as config_mod
from model import STATUS_NAMES, Status, Tool, composite_key

CSS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui.css")


def load_css() -> None:
    provider = Gtk.CssProvider()
    try:
        provider.load_from_path(CSS_PATH)
    except GLib.Error:
        return
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )


class LightWindow(Gtk.Window):
    def __init__(self, aggregator, on_settings: Callable[[], None],
                 on_quit: Callable[[], None]) -> None:
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.aggregator = aggregator
        self._on_settings = on_settings
        self._on_quit = on_quit
        self._rows: Dict[str, Gtk.Widget] = {}

        self.set_title("AI Light")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_default_size(64, 28)
        self.set_app_paintable(True)
        self.get_style_context().add_class("transparent")
        self._enable_transparency()

        cfg = config_mod.load_app_config()
        self.set_opacity(cfg.window_opacity)
        self._always_on_top = cfg.always_on_top
        self.set_keep_above(self._always_on_top)
        # Restore saved window position (if non-default).
        if cfg.window_x != 100 or cfg.window_y != 100:
            self.move(cfg.window_x, cfg.window_y)

        self.lights_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.lights_container.set_name("lights-container")
        self.add(self.lights_container)

        self.app_handle = self._create_app_handle()
        self.lights_container.add(self.app_handle)

        self.connect("button-press-event", self._on_window_button_press)
        self.connect("configure-event", self._on_configure_event)
        self.connect("destroy", lambda *_: self._on_quit())

        self.show_all()
        self._refresh()

    def _enable_transparency(self) -> None:
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual is not None:
            self.set_visual(visual)

    def set_window_opacity(self, opacity: float) -> None:
        self.set_opacity(opacity)
        cfg = config_mod.load_app_config()
        cfg.window_opacity = opacity
        config_mod.save_app_config(cfg)

    def toggle_always_on_top(self, enabled: bool) -> None:
        self._always_on_top = enabled
        self.set_keep_above(enabled)
        cfg = config_mod.load_app_config()
        cfg.always_on_top = enabled
        config_mod.save_app_config(cfg)

    def is_always_on_top(self) -> bool:
        return self._always_on_top

    def get_window_opacity(self) -> float:
        return self.get_opacity()

    def _on_configure_event(self, _widget, event) -> None:
        """Save window position so it is restored on next launch."""
        cfg = config_mod.load_app_config()
        cfg.window_x = event.x
        cfg.window_y = event.y
        config_mod.save_app_config(cfg)

    # --- rendering ----------------------------------------------------------
    def schedule_refresh(self) -> None:
        GLib.idle_add(self._refresh)

    def _refresh(self) -> bool:
        lights = self.aggregator.get_lights()
        visible_keys = {light.key for light in lights}

        # Keep app handle always visible — it serves as the primary drag
        # target and right-click entry point.  Hiding it when sessions are
        # active made the window impossible to drag (row left-click returns
        # True, preventing propagation to the window drag handler).
        self.app_handle.set_visible(True)

        for light in lights:
            row = self._rows.get(light.key)
            if row is None:
                row = self._create_project_row(light)
                self._rows[light.key] = row
                self.lights_container.add(row)
                row.show_all()
            self._update_project_row(row, light)

        for key, row in list(self._rows.items()):
            if key not in visible_keys:
                self.lights_container.remove(row)
                self._rows.pop(key, None)

        self._resize_to_content()
        return False

    def _resize_to_content(self) -> None:
        # Unmaximize first — if the WM put the window in a shaded/maximized
        # state (e.g. from a double-click), resize alone won't expand it.
        self.unmaximize()
        self.lights_container.show_all()
        min_rect, nat_rect = self.lights_container.get_preferred_size()
        width = max(64, nat_rect.width + 8)
        height = max(28, nat_rect.height + 8)
        self.resize(width, height)
        # Re-apply keep_above after resize — some WMs (Mutter, KWin) reset
        # _NET_WM_STATE_ABOVE on configure events triggered by resize.
        self.set_keep_above(self._always_on_top)

    # --- widgets ------------------------------------------------------------
    def _create_app_handle(self) -> Gtk.Widget:
        box = Gtk.EventBox()
        label = Gtk.Label(label="AI")
        label.set_name("app-handle")
        label.get_style_context().add_class("app-handle")
        box.add(label)
        box.connect("button-press-event", self._on_handle_button_press)
        return box

    def _create_project_row(self, light) -> Gtk.Widget:
        event_box = Gtk.EventBox()
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.get_style_context().add_class("project-row")
        row.project_key = light.key

        label = Gtk.Label(label=light.project_label or "unknown")
        label.set_name("row-label")
        label.get_style_context().add_class("row-label")
        row.pack_start(label, expand=True, fill=True, padding=0)

        badge = Gtk.Label(label=light.tool.badge)
        badge.get_style_context().add_class("tool-badge")
        row.pack_start(badge, expand=False, fill=False, padding=0)

        housing = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        housing.get_style_context().add_class("lamp-housing")
        for color in ("red", "yellow", "green"):
            lamp = Gtk.Box()
            lamp.get_style_context().add_class("lamp")
            lamp.get_style_context().add_class(color)
            setattr(row, f"_lamp_{color}", lamp)
            housing.pack_start(lamp, expand=False, fill=False, padding=0)
        row.pack_start(housing, expand=False, fill=False, padding=0)

        event_box.add(row)
        event_box.connect("button-press-event", self._on_row_button_press, light.key, row)
        return event_box

    def _update_project_row(self, event_box, light) -> None:
        row = event_box.get_child()
        row.project_key = light.key
        status = light.status
        actionable = status in (Status.Done, Status.Error)
        if actionable:
            row.get_style_context().add_class("actionable")
        else:
            row.get_style_context().remove_class("actionable")

        label = next(child for child in row.get_children()
                     if isinstance(child, Gtk.Label) and child.get_name() == "row-label")
        label.set_text(light.project_label or "unknown")

        for child in row.get_children():
            if isinstance(child, Gtk.Label) and child.get_style_context().has_class("tool-badge"):
                child.set_text(light.tool.badge)
                break

        getattr(row, "_lamp_red").get_style_context().toggle_class("on", status == Status.Error)
        getattr(row, "_lamp_yellow").get_style_context().toggle_class("on", status == Status.Working)
        getattr(row, "_lamp_green").get_style_context().toggle_class("on", status == Status.Done)

        tooltip = light.project_label or light.project_id
        tooltip += f" ({light.tool.label})"
        tooltip += "\n" + STATUS_NAMES.get(status, "Idle")
        if light.last_tool_call:
            tooltip += "\n" + light.last_tool_call
        event_box.set_tooltip_text(tooltip)

    # --- interaction --------------------------------------------------------
    def _on_window_button_press(self, _widget, event) -> bool:
        # Ignore double-click — WMs interpret it as maximize/shade toggle,
        # which shrinks the window and prevents _resize_to_content from
        # expanding it back.
        if event.type == Gdk.EventType._2BUTTON_PRESS:
            return True
        if event.button == 1:
            self.begin_move_drag(1, int(event.x_root), int(event.y_root), int(event.time))
            return True
        if event.button == 3:
            self._show_main_menu(int(event.x_root), int(event.y_root))
            return True
        return False

    def _on_handle_button_press(self, _widget, event) -> bool:
        if event.type == Gdk.EventType._2BUTTON_PRESS:
            return True
        if event.button == 3:
            self._show_main_menu(int(event.x_root), int(event.y_root))
            return True
        if event.button == 1:
            self.begin_move_drag(1, int(event.x_root), int(event.y_root), int(event.time))
            return True
        return False

    def _on_row_button_press(self, _widget, event, key: str, _row) -> bool:
        if event.button == 1:
            light_status = self._light_status(key)
            if light_status in (Status.Done, Status.Error):
                self.aggregator.confirm_light(key)
            return True
        if event.button == 3:
            self._show_row_menu(key, int(event.x_root), int(event.y_root))
            return True
        return False

    def _light_status(self, key: str) -> Optional[Status]:
        for light in self.aggregator.get_lights():
            if light.key == key:
                return light.status
        return None

    # --- menus --------------------------------------------------------------
    def _make_always_on_top_item(self) -> Gtk.CheckMenuItem:
        item = Gtk.CheckMenuItem(label="Always on top")
        item.set_active(self._always_on_top)
        item.connect("activate", lambda _w: self.toggle_always_on_top(item.get_active()))
        return item

    def _show_main_menu(self, x: int, y: int) -> None:
        menu = Gtk.Menu()
        menu.attach_to_widget(self, None)
        for label, callback in [
            ("Settings", self._on_settings),
            ("Diagnostics", lambda: self._show_diagnostics()),
            ("Quit", self._on_quit),
        ]:
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _w, cb=callback: cb())
            menu.append(item)
        menu.append(self._make_always_on_top_item())
        menu.show_all()
        menu.popup(None, None, None, None, 0, Gtk.get_current_event_time())

    def _show_row_menu(self, key: str, x: int, y: int) -> None:
        menu = Gtk.Menu()
        menu.attach_to_widget(self, None)
        items = [
            ("Open", lambda: actions.open_path(key.split("|")[0])),
            ("Copy Path", lambda: actions.copy_to_clipboard(key.split("|")[0])),
            ("Diagnostics", lambda: self._show_diagnostics()),
            ("Settings", self._on_settings),
            ("Remove", lambda: self.aggregator.remove_light(key)),
        ]
        for label, callback in items:
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _w, cb=callback: cb())
            menu.append(item)
        menu.append(self._make_always_on_top_item())
        menu.show_all()
        menu.popup(None, None, None, None, 3, Gtk.get_current_event_time())

    def _show_diagnostics(self) -> None:
        text = actions.build_diagnostics_text(self.aggregator)
        actions.copy_to_clipboard(text)
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="AI Light Diagnostics",
        )
        dialog.format_secondary_text(text)
        dialog.run()
        dialog.destroy()


def _install_toggle_class() -> None:
    if hasattr(Gtk.StyleContext, "toggle_class"):
        return

    def toggle_class(self, css_class, active):
        if active:
            self.add_class(css_class)
        else:
            self.remove_class(css_class)

    Gtk.StyleContext.toggle_class = toggle_class


_install_toggle_class()
