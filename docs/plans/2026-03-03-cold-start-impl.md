# Cold Start Forward-Only Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** On first-ever startup (cold start), mark all existing log files as "already read" so only new data is uploaded. On warm restart, resume from cursors and catch up on missed data.

**Architecture:** Add `is_empty()` to `StateTracker`, then add `_snapshot_existing_files()` to `LogCollectorConnector` that runs once in `open()` only when the state tracker is empty (cold start). It walks all watched directories and saves `cursor = {"byte_offset": file_size}` for every matching file.

**Tech Stack:** Python, StateTracker, LogCollectorConnector, fnmatch, os.walk.

**Design doc:** `docs/plans/2026-03-03-cold-start-design.md`

---

## Task 1: StateTracker.is_empty()

**Files:**
- Modify: `tb_gateway_collect/connectors/log_collector/state_tracker.py`
- Test: `tests/unit/collect/test_state_tracker.py`

**Step 1: Write the failing test**

Append to the end of `tests/unit/collect/test_state_tracker.py`:

```python
    def test_is_empty_true_when_no_entries(self):
        path = os.path.join(tempfile.gettempdir(), "empty_state.json")
        if os.path.exists(path):
            os.unlink(path)
        try:
            tracker = StateTracker(path)
            assert tracker.is_empty() is True
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_is_empty_false_after_save(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            tracker = StateTracker(path)
            tracker.save_cursor("file.txt", {"byte_offset": 100})
            assert tracker.is_empty() is False
        finally:
            os.unlink(path)
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/collect/test_state_tracker.py::TestStateTracker::test_is_empty_true_when_no_entries -v`
Expected: FAIL (AttributeError: 'StateTracker' has no attribute 'is_empty')

**Step 3: Implement**

Add to `tb_gateway_collect/connectors/log_collector/state_tracker.py`, after the `get_cursor` method (after line 34):

```python
    def is_empty(self) -> bool:
        return len(self._state) == 0
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/collect/test_state_tracker.py -v`
Expected: PASS (all 9 tests — 7 existing + 2 new)

**Step 5: Commit**

```bash
git add tb_gateway_collect/connectors/log_collector/state_tracker.py \
        tests/unit/collect/test_state_tracker.py
git commit -m "feat(state-tracker): add is_empty() for cold start detection"
```

---

## Task 2: Connector cold start snapshot

**Files:**
- Modify: `tb_gateway_collect/connectors/log_collector/log_collector_connector.py`
- Test: `tests/unit/collect/test_log_collector_connector.py`

**Step 1: Write the failing tests**

Append to the end of `tests/unit/collect/test_log_collector_connector.py`:

```python
class TestLogCollectorColdStart:

    def test_cold_start_snapshots_existing_files(self):
        """Cold start (empty state): existing files are NOT processed."""
        d = tempfile.mkdtemp()
        path = os.path.join(d, "existing.txt")
        with open(path, "w", newline="") as f:
            f.write("2026-03-03 10:30:45:123   Temp:25.5\r\n")

        gateway = MagicMock()
        config = _make_config(sources=[{
            "systemType": "xjsbb",
            "deviceName": "XJSBB-YB101",
            "deviceType": "log_source",
            "watchDirs": [d],
            "filePattern": "*.txt",
        }])
        connector = LogCollectorConnector(gateway, config, "log_collector")
        connector.open()
        time.sleep(2)
        connector.close()

        assert gateway.send_to_storage.call_count == 0

    def test_cold_start_new_file_after_snapshot_is_processed(self):
        """Cold start: files created AFTER open() are processed normally."""
        d = tempfile.mkdtemp()
        # Pre-existing file (will be snapshotted)
        existing = os.path.join(d, "old.txt")
        with open(existing, "w", newline="") as f:
            f.write("2026-03-03 10:00:00:000   Old:1.0\r\n")

        gateway = MagicMock()
        config = _make_config(sources=[{
            "systemType": "xjsbb",
            "deviceName": "XJSBB-YB101",
            "deviceType": "log_source",
            "watchDirs": [d],
            "filePattern": "*.txt",
        }])
        connector = LogCollectorConnector(gateway, config, "log_collector")
        connector.open()
        time.sleep(1)

        # Write new file after snapshot
        new_path = os.path.join(d, "new.txt")
        with open(new_path, "w", newline="") as f:
            f.write("2026-03-03 11:00:00:000   New:2.0\r\n")

        time.sleep(3)
        connector.close()

        assert gateway.send_to_storage.call_count >= 1

    def test_warm_restart_does_not_snapshot(self):
        """Warm restart (state has entries): new files ARE processed from byte 0."""
        d = tempfile.mkdtemp()
        state_dir = tempfile.mkdtemp()
        state_path = os.path.join(state_dir, "state.json")

        # Pre-populate state file with one entry (makes it non-empty)
        with open(state_path, "w") as f:
            json.dump({"some_old_file.txt": {"byte_offset": 100}}, f)

        # Create a file that should be processed (warm restart, no snapshot)
        path = os.path.join(d, "data.txt")
        with open(path, "w", newline="") as f:
            f.write("2026-03-03 10:30:45:123   Temp:25.5\r\n")

        gateway = MagicMock()
        config = _make_config(sources=[{
            "systemType": "xjsbb",
            "deviceName": "XJSBB-YB101",
            "deviceType": "log_source",
            "watchDirs": [d],
            "filePattern": "*.txt",
        }], state_dir=state_dir)
        connector = LogCollectorConnector(gateway, config, "log_collector")
        connector.open()
        time.sleep(2)
        connector.close()

        assert gateway.send_to_storage.call_count >= 1
```

Also add `import json` to the imports at the top of the test file (after line 3, alongside existing imports).

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/collect/test_log_collector_connector.py::TestLogCollectorColdStart::test_cold_start_snapshots_existing_files -v`
Expected: FAIL (existing file gets processed, send_to_storage called)

**Step 3: Implement**

In `tb_gateway_collect/connectors/log_collector/log_collector_connector.py`:

1. In `open()` (line 78), add `self._snapshot_existing_files()` call between `_setup_watches()` and `self.__watcher.start()`:

```python
    def open(self):
        self.__stopped = False
        self._setup_watches()
        self._snapshot_existing_files()
        self.__watcher.start()
        self.start()
        self.__log.info("Log Collector started with %d sources", len(self.__sources))
```

2. Add `_snapshot_existing_files()` method after `_setup_watches()` (after line 128):

```python
    def _snapshot_existing_files(self):
        """On cold start, mark all existing files as already-read."""
        if not self.__state_tracker.is_empty():
            return

        count = 0
        for src in self.__sources:
            pattern = src.get("filePattern", "*.txt")
            for watch_dir in src.get("watchDirs", []):
                if not os.path.isdir(watch_dir):
                    continue
                for root, dirs, files in os.walk(watch_dir):
                    for fname in files:
                        if fnmatch.fnmatch(fname, pattern):
                            file_path = os.path.join(root, fname)
                            try:
                                size = os.path.getsize(file_path)
                                self.__state_tracker.save_cursor(
                                    file_path, {"byte_offset": size}
                                )
                                count += 1
                            except OSError:
                                pass

        if count > 0:
            self.__log.info("Cold start: marked %d existing files as already-read", count)
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/collect/test_log_collector_connector.py -v`
Expected: PASS (all 6 tests — 3 existing + 3 new)

**Step 5: Run all collect tests for regressions**

Run: `python -m pytest tests/unit/collect/ -v`
Expected: All pass

**Step 6: Commit**

```bash
git add tb_gateway_collect/connectors/log_collector/log_collector_connector.py \
        tests/unit/collect/test_log_collector_connector.py
git commit -m "feat(log-collector): add cold start snapshot for forward-only behavior"
```

---

## Summary

| Task | Component | Changes |
|------|-----------|---------|
| 1 | StateTracker | One `is_empty()` method + 2 tests |
| 2 | LogCollectorConnector | `_snapshot_existing_files()` + call in `open()` + 3 tests |
