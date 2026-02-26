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
