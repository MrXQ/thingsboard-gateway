# Change Filter Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a shared `ChangeFilter` component so KV8000 and SCADA connectors only upload telemetry when values change.

**Architecture:** A `ChangeFilter` class in `tb_gateway_collect/common/` tracks last-sent values per device in memory. Each connector constructs a `ChangeFilter` in `__init__` and calls `filter()` after conversion — if result is `None`, skip `send_to_storage`. Config flag `uploadOnChangeOnly` (default `true`) controls behavior.

**Tech Stack:** Python, ThingsBoard Gateway `ConvertedData` / `TelemetryEntry` / `DatapointKey` entities.

**Design doc:** `docs/plans/2026-03-03-change-filter-design.md`

---

## Task 1: ChangeFilter Component

**Files:**
- Create: `tb_gateway_collect/common/change_filter.py`
- Test: `tests/unit/collect/test_change_filter.py`

**Step 1: Write the failing test**

```python
# tests/unit/collect/test_change_filter.py
from thingsboard_gateway.gateway.entities.converted_data import ConvertedData
from thingsboard_gateway.gateway.entities.datapoint_key import DatapointKey
from thingsboard_gateway.gateway.entities.telemetry_entry import TelemetryEntry

from tb_gateway_collect.common.change_filter import ChangeFilter


def _make_converted(device_name, values, ts=1000):
    """Helper: build a ConvertedData with one TelemetryEntry."""
    cd = ConvertedData(device_name, "default")
    tv = {DatapointKey(k): v for k, v in values.items()}
    cd.add_to_telemetry(TelemetryEntry(tv, ts))
    return cd


class TestChangeFilterColdStart:

    def test_first_call_passes_all_values(self):
        cf = ChangeFilter()
        cd = _make_converted("DEV-A", {"temp": 25.0, "speed": 100})
        result = cf.filter(cd)
        assert result is not None
        assert len(result.telemetry) == 1
        assert len(result.telemetry[0].values) == 2

    def test_first_call_per_device_passes_all(self):
        cf = ChangeFilter()
        cd_a = _make_converted("DEV-A", {"temp": 25.0})
        cd_b = _make_converted("DEV-B", {"temp": 30.0})
        result_a = cf.filter(cd_a)
        result_b = cf.filter(cd_b)
        assert result_a is not None
        assert result_b is not None


class TestChangeFilterSuppression:

    def test_unchanged_values_return_none(self):
        cf = ChangeFilter()
        cd = _make_converted("DEV-A", {"temp": 25.0, "speed": 100})
        cf.filter(cd)
        result = cf.filter(_make_converted("DEV-A", {"temp": 25.0, "speed": 100}, ts=2000))
        assert result is None

    def test_one_key_changed_returns_only_changed(self):
        cf = ChangeFilter()
        cf.filter(_make_converted("DEV-A", {"temp": 25.0, "speed": 100}))
        result = cf.filter(_make_converted("DEV-A", {"temp": 26.0, "speed": 100}, ts=2000))
        assert result is not None
        assert len(result.telemetry) == 1
        keys = {k.key for k in result.telemetry[0].values.keys()}
        assert keys == {"temp"}

    def test_all_keys_changed_returns_all(self):
        cf = ChangeFilter()
        cf.filter(_make_converted("DEV-A", {"temp": 25.0, "speed": 100}))
        result = cf.filter(_make_converted("DEV-A", {"temp": 26.0, "speed": 200}, ts=2000))
        assert result is not None
        keys = {k.key for k in result.telemetry[0].values.keys()}
        assert keys == {"temp", "speed"}

    def test_devices_tracked_independently(self):
        cf = ChangeFilter()
        cf.filter(_make_converted("DEV-A", {"temp": 25.0}))
        cf.filter(_make_converted("DEV-B", {"temp": 25.0}))
        # DEV-A unchanged, DEV-B unchanged
        assert cf.filter(_make_converted("DEV-A", {"temp": 25.0}, ts=2000)) is None
        assert cf.filter(_make_converted("DEV-B", {"temp": 25.0}, ts=2000)) is None
        # DEV-A changed
        result = cf.filter(_make_converted("DEV-A", {"temp": 30.0}, ts=3000))
        assert result is not None
        assert result.device_name == "DEV-A"


class TestChangeFilterDisabled:

    def test_disabled_passes_everything(self):
        cf = ChangeFilter(enabled=False)
        cd = _make_converted("DEV-A", {"temp": 25.0})
        cf.filter(cd)
        result = cf.filter(_make_converted("DEV-A", {"temp": 25.0}, ts=2000))
        assert result is not None


class TestChangeFilterAttributes:

    def test_attributes_always_pass_through(self):
        cf = ChangeFilter()
        cd = ConvertedData("DEV-A", "default")
        cd.add_to_attributes({"firmware": "1.0"})
        tv = {DatapointKey("temp"): 25.0}
        cd.add_to_telemetry(TelemetryEntry(tv, 1000))
        cf.filter(cd)

        # Second call: telemetry unchanged, but has attributes
        cd2 = ConvertedData("DEV-A", "default")
        cd2.add_to_attributes({"firmware": "1.0"})
        tv2 = {DatapointKey("temp"): 25.0}
        cd2.add_to_telemetry(TelemetryEntry(tv2, 2000))
        result = cf.filter(cd2)
        # Telemetry unchanged → None (attributes alone don't force upload)
        assert result is None
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/collect/test_change_filter.py -v`
Expected: FAIL (import error)

**Step 3: Implement**

```python
# tb_gateway_collect/common/change_filter.py
from typing import Any, Optional

from thingsboard_gateway.gateway.entities.converted_data import ConvertedData
from thingsboard_gateway.gateway.entities.datapoint_key import DatapointKey
from thingsboard_gateway.gateway.entities.telemetry_entry import TelemetryEntry


class ChangeFilter:
    """Filters ConvertedData to only include telemetry values that changed since last call."""

    def __init__(self, enabled: bool = True):
        self._enabled = enabled
        # {device_name: {datapoint_key_str: last_value}}
        self._last_values: dict[str, dict[str, Any]] = {}

    def filter(self, converted: ConvertedData) -> Optional[ConvertedData]:
        if not self._enabled:
            return converted

        device_cache = self._last_values.setdefault(converted.device_name, {})
        changed_entries: list[TelemetryEntry] = []

        for entry in converted.telemetry:
            changed_values = {}
            for dp_key, value in entry.values.items():
                key_str = dp_key.key
                if key_str not in device_cache or device_cache[key_str] != value:
                    changed_values[dp_key] = value
                    device_cache[key_str] = value

            if changed_values:
                changed_entries.append(TelemetryEntry(changed_values, entry.ts))

        if not changed_entries:
            return None

        result = ConvertedData(converted.device_name, converted.device_type)
        for entry in changed_entries:
            result.add_to_telemetry(entry)
        return result
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/collect/test_change_filter.py -v`
Expected: PASS (all 8 tests)

**Step 5: Commit**

```bash
git add tb_gateway_collect/common/change_filter.py \
        tests/unit/collect/test_change_filter.py
git commit -m "feat(change-filter): add ChangeFilter for upload-on-change-only telemetry"
```

---

## Task 2: Integrate into KV8000 Connector

**Files:**
- Modify: `tb_gateway_collect/connectors/kv8000/kv8000_connector.py`
- Test: existing `tests/unit/collect/test_kv8000_connector.py` must still pass

**Step 1: Add import and construct ChangeFilter in `__init__`**

At the top of `kv8000_connector.py`, add import:
```python
from tb_gateway_collect.common.change_filter import ChangeFilter
```

In `__init__`, after line 29 (`self.__converter = KV8000UplinkConverter()`), add:
```python
        self.__change_filter = ChangeFilter(
            enabled=config.get("uploadOnChangeOnly", True)
        )
```

**Step 2: Wrap send_to_storage in `_poll_device`**

Replace lines 160-164:
```python
            converted = self.__converter.convert(config, telemetry_data)

            self.__gateway.add_device(device_name, {CONNECTOR_PARAMETER: self},
                                      device_type=device_type)
            self.__gateway.send_to_storage(self.get_name(), self.get_id(), converted)
```

With:
```python
            converted = self.__converter.convert(config, telemetry_data)
            filtered = self.__change_filter.filter(converted)

            if filtered is not None:
                self.__gateway.add_device(device_name, {CONNECTOR_PARAMETER: self},
                                          device_type=device_type)
                self.__gateway.send_to_storage(self.get_name(), self.get_id(), filtered)
```

**Step 3: Run tests to verify no regressions**

Run: `python -m pytest tests/unit/collect/test_kv8000_connector.py -v`
Expected: PASS (all existing tests pass — first poll is cold start, sends everything)

**Step 4: Commit**

```bash
git add tb_gateway_collect/connectors/kv8000/kv8000_connector.py
git commit -m "feat(kv8000): integrate ChangeFilter for upload-on-change-only"
```

---

## Task 3: Integrate into SCADA Connector

**Files:**
- Modify: `tb_gateway_collect/connectors/scada/scada_connector.py`
- Test: existing `tests/unit/collect/test_scada_connector.py` must still pass

**Step 1: Add import and construct ChangeFilter in `__init__`**

At the top of `scada_connector.py`, add import:
```python
from tb_gateway_collect.common.change_filter import ChangeFilter
```

In `__init__`, after line 30 (`self.__converter = ScadaUplinkConverter()`), add:
```python
        self.__change_filter = ChangeFilter(
            enabled=config.get("uploadOnChangeOnly", True)
        )
```

**Step 2: Wrap send_to_storage in `_poll_device`**

Replace lines 185-190:
```python
            converted = self.__converter.convert(config, raw_data, params)

            if converted.telemetry:
                self.__gateway.add_device(device_name, {CONNECTOR_PARAMETER: self},
                                          device_type=device_type)
                self.__gateway.send_to_storage(self.get_name(), self.get_id(), converted)
```

With:
```python
            converted = self.__converter.convert(config, raw_data, params)
            filtered = self.__change_filter.filter(converted)

            if filtered is not None:
                self.__gateway.add_device(device_name, {CONNECTOR_PARAMETER: self},
                                          device_type=device_type)
                self.__gateway.send_to_storage(self.get_name(), self.get_id(), filtered)
```

Note: `ChangeFilter.filter()` returns `None` when nothing changed, which replaces the old `if converted.telemetry:` check. When the filter is disabled, it returns the original `ConvertedData` which has the same truthiness.

**Step 3: Run tests to verify no regressions**

Run: `python -m pytest tests/unit/collect/test_scada_connector.py -v`
Expected: PASS (all existing tests pass)

**Step 4: Commit**

```bash
git add tb_gateway_collect/connectors/scada/scada_connector.py
git commit -m "feat(scada): integrate ChangeFilter for upload-on-change-only"
```

---

## Task 4: Update Config and Build, Full Verification

**Files:**
- Modify: `tb_gateway_collect/config/kv8000.json` (add `uploadOnChangeOnly` field)
- Modify: `tb_gateway_collect/config/scada.json` (add `uploadOnChangeOnly` field)
- Modify: `tb_gateway_windows/build/windows.spec` (add `change_filter` hidden import)

**Step 1: Add `uploadOnChangeOnly` to config files**

Add `"uploadOnChangeOnly": true` to both `kv8000.json` and `scada.json` at the top level (next to `pollIntervalMs`).

**Step 2: Add hidden import to windows.spec**

In the `HIDDEN_IMPORTS` list, add:
```python
'tb_gateway_collect.common.change_filter',
```

**Step 3: Run all collect + windows tests**

Run: `python -m pytest tests/unit/collect/ tests/unit/windows/ -v`
Expected: All tests pass (no regressions)

**Step 4: Commit**

```bash
git add tb_gateway_collect/config/kv8000.json \
        tb_gateway_collect/config/scada.json \
        tb_gateway_windows/build/windows.spec
git commit -m "feat(change-filter): add config defaults and build integration"
```

---

## Summary

| Task | Component | Changes |
|------|-----------|---------|
| 1 | ChangeFilter | New class + 8 unit tests |
| 2 | KV8000 integration | Import + 2 init lines + 3 poll lines |
| 3 | SCADA integration | Import + 2 init lines + 3 poll lines |
| 4 | Config + build | 2 JSON fields + 1 hidden import |
