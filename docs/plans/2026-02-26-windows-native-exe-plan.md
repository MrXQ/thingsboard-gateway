# Windows Native Exe Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Package the ThingsBoard IoT Gateway as a standalone Windows `.exe` with a system tray UI that shows gateway status, connector health, and device counts — with zero modifications to the original codebase.

**Architecture:** A separate `tb_gateway_windows/` wrapper package that imports `TBGatewayService` and runs it in a background thread. The main thread runs a `pystray` system tray icon that polls the gateway instance for status every 5 seconds and shows Windows toast notifications on state transitions. PyInstaller bundles everything into a single-file `.exe`.

**Tech Stack:** Python 3.10+, pystray, Pillow, PyInstaller, threading

**Critical implementation detail:** `TBGatewayService.__init__()` blocks forever (it has a `while not self.stopped: self.stop_event.wait(1)` loop at line 289 of `tb_gateway_service.py`). The gateway thread will never return from `__init__` until shutdown. The `managerEnabled` config option must be `False` or omitted (its `serve_forever()` would also block and prevent the while loop from running). We access the gateway instance's properties directly from the tray thread since Python's GIL makes simple attribute reads thread-safe.

---

### Task 1: Project Scaffolding

**Files:**
- Create: `tb_gateway_windows/__init__.py`
- Create: `tb_gateway_windows/resources/` (directory)

**Step 1: Create package directory and init file**

```python
# tb_gateway_windows/__init__.py
"""ThingsBoard IoT Gateway - Windows Native Wrapper"""
__version__ = "1.0.0"
```

**Step 2: Create resources directory**

```bash
mkdir -p tb_gateway_windows/resources
```

**Step 3: Install new dependencies**

```bash
pip install pystray Pillow pyinstaller
```

**Step 4: Commit**

```bash
git add tb_gateway_windows/__init__.py
git commit -m "feat: scaffold tb_gateway_windows wrapper package"
```

---

### Task 2: Icon Generator

**Files:**
- Create: `tb_gateway_windows/icons.py`
- Create: `tests/unit/windows/test_icons.py`

**Step 1: Write the failing test**

```python
# tests/unit/windows/test_icons.py
import unittest
from PIL import Image


class TestIcons(unittest.TestCase):
    def test_create_status_icon_returns_pil_image(self):
        from tb_gateway_windows.icons import create_status_icon
        icon = create_status_icon("green")
        self.assertIsInstance(icon, Image.Image)
        self.assertEqual(icon.size, (64, 64))

    def test_create_status_icon_all_colors(self):
        from tb_gateway_windows.icons import create_status_icon
        for color in ["green", "yellow", "red", "orange", "grey"]:
            icon = create_status_icon(color)
            self.assertIsInstance(icon, Image.Image)

    def test_create_status_icon_has_alpha_channel(self):
        from tb_gateway_windows.icons import create_status_icon
        icon = create_status_icon("green")
        self.assertEqual(icon.mode, "RGBA")


if __name__ == '__main__':
    unittest.main()
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/windows/test_icons.py -v`
Expected: FAIL — module not found

**Step 3: Write minimal implementation**

```python
# tb_gateway_windows/icons.py
"""Generate system tray status icons using Pillow."""

from PIL import Image, ImageDraw

# Status color mapping
STATUS_COLORS = {
    "green": (76, 175, 80),      # Connected
    "yellow": (255, 193, 7),     # Starting
    "red": (244, 67, 54),        # Disconnected
    "orange": (255, 152, 0),     # Connector(s) down
    "grey": (158, 158, 158),     # Stopped
}

ICON_SIZE = 64


def create_status_icon(color_name: str) -> Image.Image:
    """Create a circle icon with the given status color.

    Args:
        color_name: One of 'green', 'yellow', 'red', 'orange', 'grey'

    Returns:
        A 64x64 RGBA PIL Image with a colored circle and dark border.
    """
    rgb = STATUS_COLORS.get(color_name, STATUS_COLORS["grey"])

    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Draw outer border circle (dark)
    margin = 4
    draw.ellipse(
        [margin, margin, ICON_SIZE - margin - 1, ICON_SIZE - margin - 1],
        fill=rgb + (255,),
        outline=(50, 50, 50, 255),
        width=3,
    )

    # Draw inner highlight for 3D effect
    highlight_margin = margin + 8
    highlight_color = tuple(min(c + 60, 255) for c in rgb) + (100,)
    draw.ellipse(
        [highlight_margin, highlight_margin,
         ICON_SIZE // 2 + 4, ICON_SIZE // 2 + 4],
        fill=highlight_color,
    )

    return img
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/windows/test_icons.py -v`
Expected: 3 tests PASS

**Step 5: Commit**

```bash
git add tb_gateway_windows/icons.py tests/unit/windows/test_icons.py
git commit -m "feat: add tray icon generator with status colors"
```

---

### Task 3: Gateway Monitor (State Polling & Transition Detection)

**Files:**
- Create: `tb_gateway_windows/gateway_monitor.py`
- Create: `tests/unit/windows/test_gateway_monitor.py`

This is the most logic-heavy module. It polls a `TBGatewayService` instance and detects state transitions.

**Step 1: Write the failing tests**

```python
# tests/unit/windows/test_gateway_monitor.py
import unittest
from unittest.mock import MagicMock, PropertyMock


class TestGatewayState(unittest.TestCase):
    """Test the GatewayState dataclass."""

    def test_state_from_gateway_connected(self):
        from tb_gateway_windows.gateway_monitor import GatewayState
        gw = self._make_mock_gateway(tb_connected=True, devices=5,
                                      active=3, inactive=0, total=3,
                                      storage=100)
        state = GatewayState.from_gateway(gw)
        self.assertTrue(state.tb_connected)
        self.assertEqual(state.device_count, 5)
        self.assertEqual(state.active_connectors, 3)
        self.assertEqual(state.inactive_connectors, 0)
        self.assertEqual(state.total_connectors, 3)
        self.assertEqual(state.storage_events, 100)
        self.assertEqual(state.status, "connected")

    def test_state_status_disconnected(self):
        from tb_gateway_windows.gateway_monitor import GatewayState
        gw = self._make_mock_gateway(tb_connected=False, devices=0,
                                      active=0, inactive=2, total=2,
                                      storage=0)
        state = GatewayState.from_gateway(gw)
        self.assertEqual(state.status, "disconnected")

    def test_state_status_connector_down(self):
        from tb_gateway_windows.gateway_monitor import GatewayState
        gw = self._make_mock_gateway(tb_connected=True, devices=3,
                                      active=2, inactive=1, total=3,
                                      storage=50)
        state = GatewayState.from_gateway(gw)
        self.assertEqual(state.status, "connector_down")

    def test_state_none_when_gateway_not_ready(self):
        from tb_gateway_windows.gateway_monitor import GatewayState
        state = GatewayState.from_gateway(None)
        self.assertIsNone(state)

    def test_state_none_when_tb_client_not_ready(self):
        from tb_gateway_windows.gateway_monitor import GatewayState
        gw = MagicMock()
        gw.tb_client = None
        state = GatewayState.from_gateway(gw)
        self.assertIsNone(state)

    def _make_mock_gateway(self, tb_connected, devices, active, inactive,
                           total, storage):
        gw = MagicMock()
        gw.tb_client.is_connected.return_value = tb_connected
        type(gw).connected_devices = PropertyMock(return_value=devices)
        type(gw).active_connectors = PropertyMock(return_value=active)
        type(gw).inactive_connectors = PropertyMock(return_value=inactive)
        type(gw).total_connectors = PropertyMock(return_value=total)
        gw._event_storage.len.return_value = storage
        return gw


class TestTransitionDetection(unittest.TestCase):
    """Test that state transitions produce the correct notifications."""

    def test_no_transitions_on_first_poll(self):
        from tb_gateway_windows.gateway_monitor import detect_transitions
        from tb_gateway_windows.gateway_monitor import GatewayState
        transitions = detect_transitions(None, self._make_state(True, 3, 0))
        self.assertEqual(transitions, [])

    def test_detect_tb_disconnect(self):
        from tb_gateway_windows.gateway_monitor import detect_transitions
        old = self._make_state(tb_connected=True, active=2, inactive=0)
        new = self._make_state(tb_connected=False, active=2, inactive=0)
        transitions = detect_transitions(old, new)
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0]["event"], "tb_disconnected")

    def test_detect_tb_reconnect(self):
        from tb_gateway_windows.gateway_monitor import detect_transitions
        old = self._make_state(tb_connected=False, active=0, inactive=2)
        new = self._make_state(tb_connected=True, active=2, inactive=0)
        transitions = detect_transitions(old, new)
        events = [t["event"] for t in transitions]
        self.assertIn("tb_reconnected", events)

    def test_detect_connector_went_down(self):
        from tb_gateway_windows.gateway_monitor import detect_transitions
        old = self._make_state(tb_connected=True, active=3, inactive=0)
        new = self._make_state(tb_connected=True, active=2, inactive=1)
        transitions = detect_transitions(old, new)
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0]["event"], "connector_down")

    def test_detect_connector_recovered(self):
        from tb_gateway_windows.gateway_monitor import detect_transitions
        old = self._make_state(tb_connected=True, active=2, inactive=1)
        new = self._make_state(tb_connected=True, active=3, inactive=0)
        transitions = detect_transitions(old, new)
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0]["event"], "connector_recovered")

    def test_no_transition_when_unchanged(self):
        from tb_gateway_windows.gateway_monitor import detect_transitions
        old = self._make_state(tb_connected=True, active=3, inactive=0)
        new = self._make_state(tb_connected=True, active=3, inactive=0)
        transitions = detect_transitions(old, new)
        self.assertEqual(transitions, [])

    def _make_state(self, tb_connected, active, inactive):
        from tb_gateway_windows.gateway_monitor import GatewayState
        return GatewayState(
            tb_connected=tb_connected,
            device_count=5,
            active_connectors=active,
            inactive_connectors=inactive,
            total_connectors=active + inactive,
            storage_events=0,
        )


if __name__ == '__main__':
    unittest.main()
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/windows/test_gateway_monitor.py -v`
Expected: FAIL — module not found

**Step 3: Write the implementation**

```python
# tb_gateway_windows/gateway_monitor.py
"""Polls TBGatewayService for status and detects state transitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class GatewayState:
    """Snapshot of gateway runtime state."""
    tb_connected: bool
    device_count: int
    active_connectors: int
    inactive_connectors: int
    total_connectors: int
    storage_events: int

    @property
    def status(self) -> str:
        """Derive tray icon status from state.

        Returns one of: 'connected', 'disconnected', 'connector_down'
        """
        if not self.tb_connected:
            return "disconnected"
        if self.inactive_connectors > 0:
            return "connector_down"
        return "connected"

    @classmethod
    def from_gateway(cls, gateway) -> Optional["GatewayState"]:
        """Read current state from a live TBGatewayService instance.

        Returns None if the gateway or its tb_client is not yet initialized.
        """
        if gateway is None:
            return None
        try:
            tb_client = gateway.tb_client
            if tb_client is None:
                return None
            return cls(
                tb_connected=tb_client.is_connected(),
                device_count=gateway.connected_devices,
                active_connectors=gateway.active_connectors,
                inactive_connectors=gateway.inactive_connectors,
                total_connectors=gateway.total_connectors,
                storage_events=gateway._event_storage.len(),
            )
        except Exception:
            return None


# Status-to-icon color mapping
STATUS_ICON_MAP = {
    "connected": "green",
    "disconnected": "red",
    "connector_down": "orange",
    "starting": "yellow",
    "stopped": "grey",
}


def detect_transitions(
    old: Optional[GatewayState], new: Optional[GatewayState]
) -> list[dict]:
    """Compare two states and return a list of transition events.

    Each transition is a dict with 'event' and 'message' keys.
    Returns empty list if this is the first poll (old is None)
    or if nothing changed.
    """
    if old is None or new is None:
        return []

    transitions = []

    # ThingsBoard connection transitions
    if old.tb_connected and not new.tb_connected:
        transitions.append({
            "event": "tb_disconnected",
            "message": "ThingsBoard connection lost",
        })
    elif not old.tb_connected and new.tb_connected:
        transitions.append({
            "event": "tb_reconnected",
            "message": "ThingsBoard reconnected",
        })

    # Connector transitions
    if old.inactive_connectors < new.inactive_connectors:
        count = new.inactive_connectors - old.inactive_connectors
        transitions.append({
            "event": "connector_down",
            "message": f"{count} connector(s) went offline",
        })
    elif old.inactive_connectors > new.inactive_connectors:
        count = old.inactive_connectors - new.inactive_connectors
        transitions.append({
            "event": "connector_recovered",
            "message": f"{count} connector(s) recovered",
        })

    return transitions
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/windows/test_gateway_monitor.py -v`
Expected: 10 tests PASS

**Step 5: Commit**

```bash
git add tb_gateway_windows/gateway_monitor.py tests/unit/windows/test_gateway_monitor.py
git commit -m "feat: add gateway state monitor with transition detection"
```

---

### Task 4: Gateway Runner (Thread Lifecycle Management)

**Files:**
- Create: `tb_gateway_windows/gateway_runner.py`
- Create: `tests/unit/windows/test_gateway_runner.py`

This module runs `TBGatewayService` in a daemon thread and provides access to the instance.

**Step 1: Write the failing tests**

```python
# tests/unit/windows/test_gateway_runner.py
import unittest
from unittest.mock import patch, MagicMock
from threading import Event


class TestGatewayRunner(unittest.TestCase):
    def test_runner_starts_gateway_in_thread(self):
        from tb_gateway_windows.gateway_runner import GatewayRunner

        # Mock TBGatewayService so it doesn't actually start
        with patch('tb_gateway_windows.gateway_runner.TBGatewayService') as MockGW:
            mock_instance = MagicMock()
            mock_instance.stopped = False
            mock_instance.stop_event = Event()
            MockGW.return_value = mock_instance

            runner = GatewayRunner("fake/config/tb_gateway.json")
            runner.start()
            runner._thread.join(timeout=2)

            MockGW.assert_called_once_with("fake/config/tb_gateway.json")
            self.assertEqual(runner.gateway, mock_instance)

    def test_runner_gateway_is_none_before_start(self):
        from tb_gateway_windows.gateway_runner import GatewayRunner
        runner = GatewayRunner("fake/config/tb_gateway.json")
        self.assertIsNone(runner.gateway)

    def test_runner_stop_sets_stopped(self):
        from tb_gateway_windows.gateway_runner import GatewayRunner

        with patch('tb_gateway_windows.gateway_runner.TBGatewayService') as MockGW:
            mock_instance = MagicMock()
            mock_instance.stopped = False
            mock_instance.stop_event = Event()
            MockGW.return_value = mock_instance

            runner = GatewayRunner("fake/config/tb_gateway.json")
            runner.start()
            runner._thread.join(timeout=2)
            runner.stop()

            self.assertTrue(mock_instance.stopped)
            mock_instance.stop_event.set.assert_called()


if __name__ == '__main__':
    unittest.main()
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/windows/test_gateway_runner.py -v`
Expected: FAIL — module not found

**Step 3: Write the implementation**

```python
# tb_gateway_windows/gateway_runner.py
"""Manages TBGatewayService lifecycle in a background thread."""

from __future__ import annotations

import logging
import os
from threading import Thread
from typing import Optional

from thingsboard_gateway.gateway.tb_gateway_service import TBGatewayService

log = logging.getLogger("windows_wrapper")


class GatewayRunner:
    """Runs TBGatewayService in a daemon thread.

    The gateway's __init__() blocks forever (it has an internal event loop),
    so we run it in a background thread and expose the instance for monitoring.
    """

    def __init__(self, config_path: str):
        self._config_path = config_path
        self._gateway: Optional[TBGatewayService] = None
        self._thread: Optional[Thread] = None
        self._error: Optional[Exception] = None

    @property
    def gateway(self) -> Optional[TBGatewayService]:
        """The live gateway instance, or None if not yet initialized."""
        return self._gateway

    @property
    def error(self) -> Optional[Exception]:
        """Startup error if the gateway failed to initialize."""
        return self._error

    def start(self):
        """Start the gateway in a background daemon thread."""
        self._thread = Thread(
            target=self._run,
            name="TBGatewayService",
            daemon=True,
        )
        self._thread.start()

    def _run(self):
        """Thread target — instantiates TBGatewayService (blocks until stopped)."""
        try:
            log.info("Starting TBGatewayService with config: %s",
                     self._config_path)
            self._gateway = TBGatewayService(self._config_path)
            # __init__ blocks here until gateway.stopped is True
        except Exception as e:
            log.error("Gateway failed to start: %s", e, exc_info=True)
            self._error = e

    def stop(self):
        """Signal the gateway to shut down."""
        if self._gateway is not None:
            log.info("Stopping gateway...")
            self._gateway.stopped = True
            self._gateway.stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    @property
    def is_alive(self) -> bool:
        """Whether the gateway thread is still running."""
        return self._thread is not None and self._thread.is_alive()
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/windows/test_gateway_runner.py -v`
Expected: 3 tests PASS

**Step 5: Commit**

```bash
git add tb_gateway_windows/gateway_runner.py tests/unit/windows/test_gateway_runner.py
git commit -m "feat: add gateway runner for background thread management"
```

---

### Task 5: System Tray Application

**Files:**
- Create: `tb_gateway_windows/tray.py`

No unit test for this module — it's a thin UI glue layer that calls `pystray` APIs and wires together the monitor and icons modules (which are tested). Testing would require mocking the entire pystray + OS notification system, which adds complexity without value.

**Step 1: Write the implementation**

```python
# tb_gateway_windows/tray.py
"""System tray application using pystray."""

from __future__ import annotations

import logging
import os
import subprocess
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
```

**Step 2: Commit**

```bash
git add tb_gateway_windows/tray.py
git commit -m "feat: add system tray UI with status monitoring and notifications"
```

---

### Task 6: Main Entry Point

**Files:**
- Create: `tb_gateway_windows/__main__.py`

**Step 1: Write the implementation**

```python
# tb_gateway_windows/__main__.py
"""Entry point for the Windows ThingsBoard Gateway wrapper.

Usage:
    tb-gateway.exe                          (uses ./config/ next to exe)
    tb-gateway.exe --config-dir C:\\myconf  (custom config directory)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys


def get_base_dir() -> str:
    """Get the directory containing the exe (frozen) or project root (dev)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def setup_logging(base_dir: str):
    """Configure basic logging to console + file."""
    logs_dir = os.path.join(base_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(
                os.path.join(logs_dir, "windows_wrapper.log"),
                encoding="utf-8",
            ),
        ],
    )


def main():
    parser = argparse.ArgumentParser(description="ThingsBoard IoT Gateway")
    parser.add_argument(
        "--config-dir",
        default=None,
        help="Path to config directory (default: ./config/ next to exe)",
    )
    args = parser.parse_args()

    base_dir = get_base_dir()
    setup_logging(base_dir)
    log = logging.getLogger("windows_wrapper")

    # Resolve config directory
    config_dir = args.config_dir or os.path.join(base_dir, "config")
    config_dir = os.path.abspath(config_dir)

    if not config_dir.endswith(os.sep):
        config_dir += os.sep

    config_file = config_dir + "tb_gateway.json"

    if not os.path.isfile(config_file):
        log.error("Config file not found: %s", config_file)
        log.error("Please place your configuration in: %s", config_dir)
        sys.exit(1)

    # Set env var so the gateway resolves config paths correctly
    os.environ["TB_GW_CONFIG_DIR"] = config_dir

    # Create logs dir next to config if it doesn't exist
    os.makedirs(os.path.join(base_dir, "logs"), exist_ok=True)

    # Import after env setup
    from tb_gateway_windows.gateway_runner import GatewayRunner
    from tb_gateway_windows.tray import TrayApp

    log.info("Starting ThingsBoard IoT Gateway (Windows)")
    log.info("Config directory: %s", config_dir)
    log.info("Base directory: %s", base_dir)

    # Read version
    try:
        from thingsboard_gateway.version import VERSION
    except ImportError:
        VERSION = "unknown"

    # Start gateway in background thread
    runner = GatewayRunner(config_file)
    runner.start()

    # Run tray on main thread (blocks until exit)
    tray = TrayApp(runner, version=f"v{VERSION}")
    try:
        tray.run()
    except KeyboardInterrupt:
        pass
    finally:
        runner.stop()
        log.info("Gateway shutdown complete.")


if __name__ == "__main__":
    main()
```

**Step 2: Test it works manually (dev mode, not frozen)**

Run: `python -m tb_gateway_windows --config-dir ./thingsboard_gateway/config`
Expected: System tray icon appears (yellow, then transitions). Ctrl+C or tray Exit to quit.

**Step 3: Commit**

```bash
git add tb_gateway_windows/__main__.py
git commit -m "feat: add main entry point with config resolution and tray startup"
```

---

### Task 7: PyInstaller Spec File

**Files:**
- Create: `tb_gateway_windows/build/windows.spec`
- Create: `tb_gateway_windows/build/build.py`

**Step 1: Create the PyInstaller spec**

```python
# tb_gateway_windows/build/windows.spec
# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for ThingsBoard IoT Gateway Windows executable."""

import os
import sys
from pathlib import Path

# Project root (two levels up from this spec file)
PROJECT_ROOT = Path(SPECPATH).parent.parent
GATEWAY_PKG = PROJECT_ROOT / "thingsboard_gateway"
WRAPPER_PKG = PROJECT_ROOT / "tb_gateway_windows"

block_cipher = None

# Core connector modules that PyInstaller can't detect (dynamically loaded)
HIDDEN_IMPORTS = [
    # Core connectors
    "thingsboard_gateway.connectors.mqtt.mqtt_connector",
    "thingsboard_gateway.connectors.modbus.modbus_connector",
    "thingsboard_gateway.connectors.opcua.opcua_connector",
    "thingsboard_gateway.connectors.rest.rest_connector",
    "thingsboard_gateway.connectors.socket.socket_connector",
    # Extensions
    "thingsboard_gateway.extensions.mqtt",
    "thingsboard_gateway.extensions.modbus",
    "thingsboard_gateway.extensions.opcua",
    "thingsboard_gateway.extensions.rest",
    "thingsboard_gateway.extensions.socket",
    # Storage backends
    "thingsboard_gateway.storage.memory.memory_event_storage",
    "thingsboard_gateway.storage.file.file_event_storage",
    "thingsboard_gateway.storage.sqlite.sqlite_event_storage",
    # Converters (dynamically loaded by TBModuleLoader)
    "thingsboard_gateway.connectors.mqtt.json_mqtt_uplink_converter",
    "thingsboard_gateway.connectors.mqtt.mqtt_uplink_converter",
    "thingsboard_gateway.connectors.modbus.modbus_converter",
    "thingsboard_gateway.connectors.opcua.opcua_uplink_converter",
    "thingsboard_gateway.connectors.rest.rest_uplink_converter",
    "thingsboard_gateway.connectors.socket.socket_uplink_converter",
    # gRPC
    "thingsboard_gateway.gateway.grpc_service",
    "thingsboard_gateway.gateway.proto",
    # Dependencies that may be missed
    "simplejson",
    "orjson",
    "yaml",
    "mmh3",
    "cachetools",
    "cryptography",
    "grpc",
    "google.protobuf",
    "psutil",
    "pystray",
    "PIL",
]

a = Analysis(
    [str(WRAPPER_PKG / "__main__.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[
        # Bundle default config files
        (str(GATEWAY_PKG / "config"), "thingsboard_gateway/config"),
        # Bundle extensions directory structure
        (str(GATEWAY_PKG / "extensions"), "thingsboard_gateway/extensions"),
    ],
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude heavy optional connectors to reduce size
        "thingsboard_gateway.connectors.bacnet",
        "thingsboard_gateway.connectors.ble",
        "thingsboard_gateway.connectors.can",
        "thingsboard_gateway.connectors.knx",
        "thingsboard_gateway.connectors.xmpp",
        "thingsboard_gateway.connectors.snmp",
        "thingsboard_gateway.connectors.odbc",
        "thingsboard_gateway.connectors.ocpp",
        "thingsboard_gateway.connectors.ftp",
        # Exclude their extension counterparts
        "thingsboard_gateway.extensions.bacnet",
        "thingsboard_gateway.extensions.ble",
        "thingsboard_gateway.extensions.can",
        "thingsboard_gateway.extensions.knx",
        "thingsboard_gateway.extensions.xmpp",
        "thingsboard_gateway.extensions.snmp",
        "thingsboard_gateway.extensions.odbc",
        "thingsboard_gateway.extensions.ocpp",
        "thingsboard_gateway.extensions.ftp",
        # Exclude heavy optional deps
        "bacpypes3",
        "bleak",
        "python-can",
        "xknx",
        "slixmpp",
        "puresnmp",
        "pyodbc",
        "ocpp",
        # Exclude test/dev modules
        "debugpy",
        "pytest",
        "unittest",
        "tkinter",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="tb-gateway",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window (--noconsole / --windowed)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon=str(WRAPPER_PKG / "resources" / "tb_gateway.ico"),  # Uncomment when .ico is ready
)
```

**Step 2: Create the build helper script**

```python
# tb_gateway_windows/build/build.py
"""Build helper for creating the Windows executable."""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    project_root = Path(__file__).parent.parent.parent
    spec_file = Path(__file__).parent / "windows.spec"
    dist_dir = project_root / "dist"
    config_src = project_root / "thingsboard_gateway" / "config"
    config_dst = dist_dir / "config"
    extensions_dst = dist_dir / "extensions"

    print("=" * 60)
    print("Building ThingsBoard IoT Gateway Windows Executable")
    print("=" * 60)

    # Run PyInstaller
    cmd = [
        sys.executable, "-m", "PyInstaller",
        str(spec_file),
        "--distpath", str(dist_dir),
        "--workpath", str(project_root / "build"),
        "--clean",
        "-y",
    ]
    print(f"\nRunning: {' '.join(cmd)}\n")
    result = subprocess.run(cmd, cwd=str(project_root))
    if result.returncode != 0:
        print("PyInstaller failed!")
        sys.exit(1)

    # Copy config files next to exe (user-editable copies)
    if config_dst.exists():
        shutil.rmtree(config_dst)
    shutil.copytree(str(config_src), str(config_dst))
    print(f"\nCopied config to: {config_dst}")

    # Create extensions directory
    extensions_dst.mkdir(exist_ok=True)
    print(f"Created extensions dir: {extensions_dst}")

    # Create logs directory
    (dist_dir / "logs").mkdir(exist_ok=True)
    print(f"Created logs dir: {dist_dir / 'logs'}")

    print("\n" + "=" * 60)
    print("Build complete!")
    print(f"Executable: {dist_dir / 'tb-gateway.exe'}")
    print(f"Config:     {config_dst}")
    print(f"\nTo run: {dist_dir / 'tb-gateway.exe'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
```

**Step 3: Commit**

```bash
git add tb_gateway_windows/build/windows.spec tb_gateway_windows/build/build.py
git commit -m "feat: add PyInstaller spec and build script for Windows exe"
```

---

### Task 8: Test __init__.py Files and Run Full Test Suite

**Files:**
- Create: `tests/unit/windows/__init__.py`

**Step 1: Create test package init**

```python
# tests/unit/windows/__init__.py
```

**Step 2: Run all new tests**

Run: `python -m pytest tests/unit/windows/ -v`
Expected: All 16 tests pass (3 icon + 10 monitor + 3 runner)

**Step 3: Commit**

```bash
git add tests/unit/windows/__init__.py
git commit -m "test: add windows test package init"
```

---

### Task 9: Build the Executable and Smoke Test

**Step 1: Install all dependencies**

```bash
pip install -r requirements.txt
pip install pystray Pillow pyinstaller
```

**Step 2: Run the build**

```bash
python tb_gateway_windows/build/build.py
```

Expected: Build completes, `dist/tb-gateway.exe` is created alongside `dist/config/`, `dist/logs/`, `dist/extensions/`.

**Step 3: Edit config for your ThingsBoard instance**

Edit `dist/config/tb_gateway.json`:
- Set `thingsboard.host` to your ThingsBoard server
- Set `thingsboard.security.accessToken` to your gateway device token
- Set `managerEnabled` to `false` (or remove it) — we don't need the multiprocessing manager

**Step 4: Smoke test the exe**

Run: `dist/tb-gateway.exe`
Expected:
1. System tray icon appears (yellow while starting)
2. After ~5-10 seconds, icon turns green (if ThingsBoard is reachable) or red (if not)
3. Right-click shows menu with status info
4. "Open Config Folder" opens `dist/config/`
5. "Open Logs Folder" opens `dist/logs/`
6. "Exit" shuts down cleanly

**Step 5: Commit build artifacts gitignore**

Add to `.gitignore`:
```
# PyInstaller
build/
dist/
*.spec.bak
```

```bash
git add .gitignore
git commit -m "chore: add PyInstaller build/dist to gitignore"
```

---

### Task 10: Final Review & Documentation

**Step 1: Run full test suite one more time**

```bash
python -m pytest tests/unit/windows/ -v
```

Expected: All tests pass.

**Step 2: Verify no original files were modified**

```bash
git diff --name-only HEAD~10 -- thingsboard_gateway/
```

Expected: No files listed (zero modifications to original code).

**Step 3: Commit all remaining changes**

Review and commit any uncommitted work.

---

## File Summary

| File | Purpose | Lines (est.) |
|------|---------|-------------|
| `tb_gateway_windows/__init__.py` | Package marker | 3 |
| `tb_gateway_windows/__main__.py` | Entry point, arg parsing, startup orchestration | 80 |
| `tb_gateway_windows/icons.py` | Pillow icon generator | 40 |
| `tb_gateway_windows/gateway_runner.py` | Thread lifecycle for TBGatewayService | 65 |
| `tb_gateway_windows/gateway_monitor.py` | State polling and transition detection | 90 |
| `tb_gateway_windows/tray.py` | pystray system tray UI + notifications | 160 |
| `tb_gateway_windows/build/windows.spec` | PyInstaller build spec | 100 |
| `tb_gateway_windows/build/build.py` | Build helper script | 55 |
| `tests/unit/windows/test_icons.py` | Icon tests | 25 |
| `tests/unit/windows/test_gateway_monitor.py` | Monitor + transition tests | 90 |
| `tests/unit/windows/test_gateway_runner.py` | Runner tests | 45 |
| **Total** | | **~750** |
