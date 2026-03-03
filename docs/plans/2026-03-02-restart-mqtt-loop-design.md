# Restart MQTT Reconnect Loop — Bug Fix Design

## Problem

After clicking "Restart Gateway" in the tray, the gateway enters an infinite connect/disconnect loop (~5 second cycle). The tray flickers between Connected and Disconnected. Telemetry delivery is intermittent.

## Root Cause

`GatewayRunner.stop()` sets `gateway.stopped = True` to exit the `__init__` event loop, but never calls `__stop_gateway()` (private/name-mangled). The MQTT client is never disconnected.

When `start()` creates a new gateway with the same access token (same MQTT client ID), the broker sees two active clients with the same ID and disconnects one. The disconnected client auto-reconnects, kicking the other. This cycle repeats indefinitely.

## Fix

In `GatewayRunner.stop()`, explicitly disconnect the MQTT client and stop the event storage before joining the thread:

```python
try:
    if hasattr(gw, '_event_storage') and gw._event_storage is not None:
        gw._event_storage.stop()
    if hasattr(gw, 'tb_client') and gw.tb_client is not None:
        gw.tb_client.disconnect()
        gw.tb_client.stop()
except Exception as e:
    log.warning("Error during gateway cleanup: %s", e)
```

After join, reset `_gateway = None` and `_error = None` so the tray shows correct state during restart transition.

## Files Changed

- `tb_gateway_windows/gateway_runner.py` — enhanced `stop()` with MQTT cleanup
- `tests/unit/windows/test_gateway_runner.py` — added tests for disconnect, storage stop, and safe stop when not started
