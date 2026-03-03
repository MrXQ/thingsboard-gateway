# Change Filter Design — Upload on Change Only

**Date:** 2026-03-03
**Branch:** release/3.8.2-sae-main-collect-integrate
**Status:** Approved

## Problem

KV8000 and SCADA connectors upload all telemetry every poll cycle (default 3s). With 600+ parameters per device and 2 devices per connector, this produces ~1200 telemetry points every 3 seconds — most of which are unchanged between polls. This creates unnecessary I/O and storage pressure on ThingsBoard.

## Decision

Add a shared `ChangeFilter` component that wraps the uplink converter output. It compares each telemetry value against the last-sent value and only passes through changed keys. This keeps connector code minimal and the filter reusable.

## Design

### ChangeFilter Component

**Location:** `tb_gateway_collect/common/change_filter.py`

```python
class ChangeFilter:
    def __init__(self, enabled: bool = True)
    def filter(self, converted: ConvertedData) -> ConvertedData | None
```

**Internal state:** `dict[str, dict[str, Any]]` — keyed by `device_name`, then by `DatapointKey.key` to last value. Purely in-memory, resets on restart.

**Behavior:**
- `enabled=False`: passes through unchanged (no-op)
- Compares each telemetry key's value with exact equality (`==`)
- If all keys in a TelemetryEntry are unchanged: drops that entry
- If some keys changed: returns ConvertedData with only changed keys
- If nothing changed: returns `None` (caller skips `send_to_storage`)
- Attributes always pass through unfiltered
- First call per device always passes everything through (cold start)

### Configuration

Each connector's JSON config gets:

```json
{
  "uploadOnChangeOnly": true
}
```

- Default: `true` (enabled)
- Set to `false` to revert to uploading everything every cycle

### Integration

Both KV8000 and SCADA connectors get the same change:

**In `__init__`:**
```python
self.__change_filter = ChangeFilter(
    enabled=config.get("uploadOnChangeOnly", True)
)
```

**In `_poll_device`, after conversion:**
```python
converted = self.__converter.convert(...)
filtered = self.__change_filter.filter(converted)
if filtered is not None:
    self.__gateway.send_to_storage(self.get_name(), self.get_id(), filtered)
```

~3 lines changed per connector, plus 2 lines in `__init__`.

### Not Affected

- **Log collector:** already has per-parser change detection (XJSBB, HCCM Slider). No changes needed.
- **Numeric tolerance / deadband:** not needed. PLC values are stable; exact equality is sufficient.
- **Persistent state:** not needed. In-memory state resets on restart; first poll after restart sends everything.

## Testing

**ChangeFilter unit tests** (`tests/unit/collect/test_change_filter.py`):

1. First call passes all values through (cold start)
2. Second call with same values returns `None`
3. Second call with one changed key returns only that key
4. Mixed: some keys change, some don't — only changed keys in result
5. Different devices tracked independently
6. `enabled=False` passes everything through
7. Attributes always pass through unfiltered

**Existing connector tests** remain valid — first poll (cold start) sends everything, which is what tests assert.

## Alternatives Considered

| Approach | Pros | Cons |
|----------|------|------|
| **A. Converter wrapper (chosen)** | Reusable, testable, minimal connector changes | Converter still processes unchanged values (negligible cost) |
| B. In each connector's poll method | Avoids converter work entirely | Duplicated logic, harder to test |
| C. In protocol/bridge layer | Earliest filtering | Mixes transport with business logic, least reusable |
