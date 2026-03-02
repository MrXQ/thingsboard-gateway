# Tray Status Stuck at "Starting" — Bug Fix Design

## Problem

The system tray icon permanently shows "Starting..." (yellow) even after the gateway successfully connects to ThingsBoard and connectors begin sending telemetry.

## Root Cause

`GatewayRunner._run()` assigns `self._gateway = TBGatewayService(config_path)`. But `TBGatewayService.__init__()` never returns — it blocks forever in an internal event loop (`while not self.stopped: self.stop_event.wait(1)`). The assignment only completes on shutdown, so `_runner.gateway` is always `None` during normal operation.

The tray polls `GatewayState.from_gateway(self._runner.gateway)` every 5 seconds. Since `gateway` is `None`, `from_gateway` returns `None`, and the tray stays at "Starting" indefinitely.

## Fix

In `tb_gateway_windows/gateway_runner.py`, split `__new__` and `__init__` to expose the gateway instance before the blocking `__init__` begins:

```python
def _run(self):
    try:
        gateway = TBGatewayService.__new__(TBGatewayService)
        self._gateway = gateway
        gateway.__init__(self._config_path)
    except Exception as e:
        log.error("Gateway failed to start: %s", e, exc_info=True)
        self._error = e
```

### Why This Works

1. `__new__` creates the bare object instantly (no attributes)
2. `self._gateway = gateway` exposes it to the tray immediately
3. `__init__` runs progressively, setting attributes, then blocks
4. During early init, tray polls see `AttributeError` on `gateway.tb_client` → caught by `from_gateway`'s `except Exception: return None` → "Starting" (correct)
5. After init reaches line 190 (`self.tb_client = TBClient(...)`), polls succeed → "Connected"

### Constraints

- Cannot modify `thingsboard_gateway/` (upstream package)
- Fix is entirely in `tb_gateway_windows/gateway_runner.py` (2-line change)
