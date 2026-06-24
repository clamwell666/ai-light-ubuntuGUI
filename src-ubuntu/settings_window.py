"""Settings window — GTK3 port of ``src/settings.html`` + ``src/settings.js``.

Lets the user configure the HTTP bind/port and install/remove Claude Code
integration. Hides on close (not destroyed) so it can be reopened, mirroring
the Tauri settings window behaviour.
"""
from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

import actions
import config as config_mod
import hook_installer


class SettingsWindow(Gtk.Window):
    def __init__(self, aggregator) -> None:
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.aggregator = aggregator
        self.set_title("AI Light Settings")
        self.set_default_size(480, 460)
        self.set_border_width(12)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.add(outer)

        # --- HTTP server section ------------------------------------------------
        server_frame = Gtk.Frame(label="HTTP server")
        server_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        server_box.set_border_width(8)
        server_frame.add(server_box)

        cfg = config_mod.load_app_config()
        grid = Gtk.Grid(column_spacing=8, row_spacing=8)
        grid.attach(Gtk.Label(label="Bind address:"), 0, 0, 1, 1)
        self.bind_entry = Gtk.Entry()
        self.bind_entry.set_text(cfg.http_bind)
        self.bind_entry.set_placeholder_text("127.0.0.1 or 0.0.0.0")
        grid.attach(self.bind_entry, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="Port (blank = auto):"), 0, 1, 1, 1)
        self.port_entry = Gtk.Entry()
        self.port_entry.set_text("" if cfg.http_port is None else str(cfg.http_port))
        grid.attach(self.port_entry, 1, 1, 1, 1)
        server_box.pack_start(grid, expand=False, fill=False, padding=0)

        save_btn = Gtk.Button(label="Save (restart required)")
        save_btn.connect("clicked", self._on_save)
        server_box.pack_start(save_btn, expand=False, fill=False, padding=0)

        runtime = config_mod.load_runtime_config()
        port_text = str(runtime.http_port) if runtime else "(not running)"
        self.runtime_label = Gtk.Label(label=f"Listening on: {cfg.http_bind}:{port_text}")
        self.runtime_label.set_xalign(0)
        server_box.pack_start(self.runtime_label, expand=False, fill=False, padding=0)

        outer.pack_start(server_frame, expand=False, fill=False, padding=0)

        # --- Claude integration section ----------------------------------------
        claude_frame = Gtk.Frame(label="Claude Code integration")
        claude_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        claude_box.set_border_width(8)
        claude_frame.add(claude_box)

        self.hook_status = Gtk.Label(label="")
        self.hook_status.set_xalign(0)
        claude_box.pack_start(self.hook_status, expand=False, fill=False, padding=0)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        install_btn = Gtk.Button(label="Install Claude Integration")
        install_btn.connect("clicked", self._on_install)
        btn_row.pack_start(install_btn, expand=False, fill=False, padding=0)
        remove_btn = Gtk.Button(label="Remove Claude Integration")
        remove_btn.connect("clicked", self._on_remove)
        btn_row.pack_start(remove_btn, expand=False, fill=False, padding=0)
        claude_box.pack_start(btn_row, expand=False, fill=False, padding=0)

        self._refresh_hook_status()
        outer.pack_start(claude_frame, expand=False, fill=False, padding=0)

        # --- Diagnostics --------------------------------------------------------
        diag_btn = Gtk.Button(label="Diagnostics")
        diag_btn.connect("clicked", self._on_diagnostics)
        outer.pack_start(diag_btn, expand=False, fill=False, padding=0)

        # --- opencode note ------------------------------------------------------
        note = Gtk.Label(label="opencode is monitored automatically via its SQLite "
                              "session log — no integration install needed.")
        note.set_line_wrap(True)
        note.set_xalign(0)
        outer.pack_start(note, expand=False, fill=False, padding=0)

        self.connect("delete-event", self._on_delete)

    def show_settings(self) -> None:
        cfg = config_mod.load_app_config()
        self.bind_entry.set_text(cfg.http_bind)
        self.port_entry.set_text("" if cfg.http_port is None else str(cfg.http_port))
        runtime = config_mod.load_runtime_config()
        port_text = str(runtime.http_port) if runtime else "(not running)"
        self.runtime_label.set_text(f"Listening on: {cfg.http_bind}:{port_text}")
        self._refresh_hook_status()
        self.show_all()
        self.present()

    def _on_delete(self, *_args) -> bool:
        self.hide()
        return True  # prevent destruction

    def _on_save(self, *_args) -> None:
        bind = self.bind_entry.get_text().strip()
        port_text = self.port_entry.get_text().strip()
        try:
            import ipaddress
            ipaddress.ip_address(bind)  # validates
        except ValueError:
            self._alert("Bind must be an IP address, e.g. 127.0.0.1 or 0.0.0.0")
            return
        port = None
        if port_text:
            try:
                port = int(port_text)
                if not (1 <= port <= 65535):
                    raise ValueError
            except ValueError:
                self._alert("Port must be blank or between 1 and 65535")
                return
        cfg = config_mod.load_app_config()
        cfg.http_bind = bind
        cfg.http_port = port
        config_mod.save_app_config(cfg)
        self._alert("Saved. Restart AI Light for bind/port changes to take effect.")

    def _on_install(self, *_args) -> None:
        try:
            hook_installer.install_hooks()
        except Exception as error:  # noqa: BLE001 - surface to user
            self._alert(f"Install failed: {error}")
            return
        self._refresh_hook_status()
        self._alert("Claude integration installed. Restart Claude Code (or run /hooks) "
                    "to confirm the AI Light hooks are loaded.")

    def _on_remove(self, *_args) -> None:
        try:
            hook_installer.remove_hooks()
        except Exception as error:  # noqa: BLE001 - surface to user
            self._alert(f"Remove failed: {error}")
            return
        self._refresh_hook_status()
        self._alert("Claude integration removed.")

    def _on_diagnostics(self, *_args) -> None:
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

    def _refresh_hook_status(self) -> None:
        installed = hook_installer.check_hooks_installed()
        hook_path = hook_installer.get_hook_binary_path()
        binary_exists = os.path.exists(hook_path)
        self.hook_status.set_text(
            f"Hooks installed: {installed}\nHook binary: {hook_path} "
            f"({'present' if binary_exists else 'missing'})"
        )

    def _alert(self, message: str) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=message,
        )
        dialog.run()
        dialog.destroy()
