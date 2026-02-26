"""System tray application using pystray."""

from __future__ import annotations

import logging
import os
import sys
from threading import Timer
from typing import Optional

import pystray
from pystray import MenuItem, Menu

from tb_gateway_windows.icons import create_status_icon
from tb_gateway_windows.gateway_monitor import (
    GatewayState,
    STATUS_ICON_MAP,
    detect_transitions,
)

log = logging.getLogger("windows_wrapper")

POLL_INTERVAL_SECONDS = 5


class TrayApp:
    """System tray icon with gateway status monitoring."""

    def __init__(self, gateway_runner, version: str = ""):
        self._runner = gateway_runner
        self._version = version
        self._previous_state: Optional[GatewayState] = None
        self._current_state: Optional[GatewayState] = None
        self._poll_timer: Optional[Timer] = None

        self._icon = pystray.Icon(
            name="tb-gateway",
            icon=create_status_icon("yellow"),
            title="TB Gateway - Starting...",
            menu=self._build_menu(),
        )

    def run(self):
        """Start the tray icon and polling loop. Blocks until exit."""
        self._schedule_poll()
        self._icon.run()

    def stop(self):
        """Stop polling and remove tray icon."""
        if self._poll_timer is not None:
            self._poll_timer.cancel()
        self._icon.stop()

    def _schedule_poll(self):
        """Schedule the next status poll."""
        self._poll_timer = Timer(POLL_INTERVAL_SECONDS, self._poll)
        self._poll_timer.daemon = True
        self._poll_timer.start()

    def _poll(self):
        """Poll gateway status and update tray."""
        try:
            new_state = GatewayState.from_gateway(self._runner.gateway)

            if new_state is not None:
                # Detect transitions and notify
                transitions = detect_transitions(
                    self._previous_state, new_state
                )
                for t in transitions:
                    self._notify(t["message"])

                self._previous_state = self._current_state
                self._current_state = new_state

                # Update icon and tooltip
                color = STATUS_ICON_MAP.get(new_state.status, "grey")
                self._icon.icon = create_status_icon(color)
                self._icon.title = self._build_tooltip(new_state)

                # Rebuild menu with fresh stats
                self._icon.menu = self._build_menu()

            elif self._runner.error is not None:
                self._icon.icon = create_status_icon("red")
                self._icon.title = f"TB Gateway - Error: {self._runner.error}"

            elif not self._runner.is_alive and self._runner.gateway is None:
                # Gateway thread died before initializing
                self._icon.icon = create_status_icon("grey")
                self._icon.title = "TB Gateway - Stopped"

        except Exception as e:
            log.error("Tray poll error: %s", e, exc_info=True)
        finally:
            self._schedule_poll()

    def _build_tooltip(self, state: GatewayState) -> str:
        status = "Connected" if state.tb_connected else "Disconnected"
        return (
            f"TB Gateway - {status} "
            f"({state.device_count} devices, "
            f"{state.active_connectors}/{state.total_connectors} connectors)"
        )

    def _build_menu(self) -> Menu:
        state = self._current_state
        if state is not None:
            status_text = "Connected" if state.tb_connected else "Disconnected"
            devices_text = f"{state.device_count} connected"
            connectors_text = (
                f"{state.active_connectors}/{state.total_connectors} active"
            )
            storage_text = f"{state.storage_events} events queued"
        else:
            status_text = "Starting..."
            devices_text = "-"
            connectors_text = "-"
            storage_text = "-"

        version_label = f"ThingsBoard IoT Gateway {self._version}"

        return Menu(
            MenuItem(version_label, None, enabled=False),
            Menu.SEPARATOR,
            MenuItem(f"Status:       {status_text}", None, enabled=False),
            MenuItem(f"Devices:      {devices_text}", None, enabled=False),
            MenuItem(f"Connectors:   {connectors_text}", None, enabled=False),
            MenuItem(f"Storage:      {storage_text}", None, enabled=False),
            Menu.SEPARATOR,
            MenuItem("Open Config Folder", self._open_config_folder),
            MenuItem("Open Logs Folder", self._open_logs_folder),
            MenuItem("Restart Gateway", self._restart_gateway),
            Menu.SEPARATOR,
            MenuItem("Exit", self._exit),
        )

    def _notify(self, message: str):
        """Show a Windows toast notification."""
        try:
            self._icon.notify(message, title="ThingsBoard Gateway")
        except Exception as e:
            log.warning("Failed to show notification: %s", e)

    def _open_config_folder(self, icon, item):
        config_dir = self._get_base_dir() + os.sep + "config"
        if os.path.isdir(config_dir):
            os.startfile(config_dir)

    def _open_logs_folder(self, icon, item):
        logs_dir = self._get_base_dir() + os.sep + "logs"
        if os.path.isdir(logs_dir):
            os.startfile(logs_dir)

    def _restart_gateway(self, icon, item):
        """Stop and restart the gateway."""
        log.info("Restart requested by user")
        self._runner.stop()
        self._previous_state = None
        self._current_state = None
        self._icon.icon = create_status_icon("yellow")
        self._icon.title = "TB Gateway - Restarting..."
        self._runner.start()

    def _exit(self, icon, item):
        """Shut down gateway and exit."""
        log.info("Exit requested by user")
        self._runner.stop()
        self.stop()

    def _get_base_dir(self) -> str:
        """Get the directory containing the exe (or script)."""
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
