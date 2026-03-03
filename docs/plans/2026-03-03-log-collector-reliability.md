# Log Collector Reliability Fix — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the log collector's 60s-polling-on-startup behavior and state file corruption (0KB↔92KB oscillation) caused by non-atomic writes, missing thread safety, and watchdog failing on network shares.

**Architecture:** Three independent fixes layered bottom-up: (1) make StateTracker thread-safe with atomic deferred writes, (2) add skip-if-processing guard + mtime/size poll optimization in the connector, (3) switch LogFileWatcher to PollingObserver for network paths. Each fix is independently valuable.

**Tech Stack:** Python 3, threading.Lock, os.replace (atomic rename), watchdog PollingObserver

**Design doc:** See root cause analysis in conversation — three root causes: non-atomic state writes, no thread safety, watchdog ReadDirectoryChangesW unreliable on SMB/CIFS.

---

### Task 1: StateTracker — Atomic Write + Lock + Deferred Flush

This is the most critical fix. Eliminates the 0KB↔92KB state file oscillation.

**Files:**
- Modify: `tb_gateway_collect/connectors/log_collector/state_tracker.py`
- Modify: `tests/unit/collect/test_state_tracker.py`

**Step 1: Write new failing tests**

Add these tests to `test_state_tracker.py`:

```python
import threading

def test_deferred_flush_does_not_write_immediately(self):
    """save_cursor should NOT flush to disk immediately."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    try:
        tracker = StateTracker(path)
        tracker.save_cursor("file.txt", {"byte_offset": 100})
        # File should still be empty or unchanged (not flushed yet)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        # Empty file or empty JSON — save_cursor did not flush
        assert content.strip() in ("", "{}")
    finally:
        os.unlink(path)

def test_flush_if_dirty_writes_to_disk(self):
    """flush_if_dirty should persist deferred state."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    try:
        tracker = StateTracker(path)
        tracker.save_cursor("file.txt", {"byte_offset": 500})
        tracker.flush_if_dirty()
        # Reload from disk
        tracker2 = StateTracker(path)
        assert tracker2.get_cursor("file.txt") == {"byte_offset": 500}
    finally:
        os.unlink(path)

def test_flush_if_dirty_noop_when_clean(self):
    """flush_if_dirty does nothing when no saves have occurred."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    try:
        tracker = StateTracker(path)
        tracker.flush_if_dirty()  # should not raise or create file content
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        assert content.strip() in ("", "{}")
    finally:
        os.unlink(path)

def test_atomic_write_no_zero_byte_file(self):
    """After flush, state file should contain valid JSON (never 0 bytes)."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    try:
        tracker = StateTracker(path)
        for i in range(50):
            tracker.save_cursor(f"file_{i}.txt", {"byte_offset": i * 100})
        tracker.flush_if_dirty()
        size = os.path.getsize(path)
        assert size > 0, "State file should not be 0 bytes"
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert len(data) == 50
        # .tmp file should not remain
        assert not os.path.exists(path + ".tmp")
    finally:
        os.unlink(path)

def test_concurrent_save_cursor(self):
    """Multiple threads saving cursors should not corrupt state."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    try:
        tracker = StateTracker(path)
        errors = []

        def save_many(thread_id):
            try:
                for i in range(20):
                    tracker.save_cursor(f"t{thread_id}_f{i}.txt", {"byte_offset": i})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=save_many, args=(t,)) for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors during concurrent saves: {errors}"
        tracker.flush_if_dirty()

        # All 100 entries should be present
        tracker2 = StateTracker(path)
        for t in range(5):
            for i in range(20):
                assert tracker2.get_cursor(f"t{t}_f{i}.txt") == {"byte_offset": i}
    finally:
        os.unlink(path)
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/collect/test_state_tracker.py -v`
Expected: FAIL — `flush_if_dirty` doesn't exist, `save_cursor` still flushes immediately

**Step 3: Implement StateTracker changes**

Replace the full `state_tracker.py` with:

```python
import json
import logging
import os
import threading
from typing import Optional

log = logging.getLogger(__name__)


class StateTracker:
    """Persists per-file cursor state to a JSON file.

    Thread-safe. Writes are deferred — call flush_if_dirty() to persist.
    Uses atomic write (temp file + os.replace) to prevent 0-byte corruption.
    """

    def __init__(self, state_file_path: str):
        self._path = state_file_path
        self._lock = threading.Lock()
        self._dirty = False
        self._state: dict[str, dict] = {}
        self._load()

    def _load(self):
        if not os.path.exists(self._path):
            self._state = {}
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                self._state = json.load(f)
        except (json.JSONDecodeError, ValueError):
            log.warning("Corrupted state file %s, resetting", self._path)
            self._state = {}

    def _flush_locked(self):
        """Write state to disk atomically. Must be called with self._lock held."""
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        tmp_path = self._path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self._state, f, indent=2)
        os.replace(tmp_path, self._path)

    def get_cursor(self, file_path: str) -> Optional[dict]:
        with self._lock:
            return self._state.get(file_path)

    def is_empty(self) -> bool:
        with self._lock:
            return len(self._state) == 0

    def save_cursor(self, file_path: str, cursor: dict):
        """Update cursor in memory. Call flush_if_dirty() to persist."""
        with self._lock:
            self._state[file_path] = cursor
            self._dirty = True

    def flush_if_dirty(self):
        """Persist state to disk if any cursors have been updated since last flush."""
        with self._lock:
            if not self._dirty:
                return
            self._flush_locked()
            self._dirty = False
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/collect/test_state_tracker.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add tb_gateway_collect/connectors/log_collector/state_tracker.py tests/unit/collect/test_state_tracker.py
git commit -m "fix(state-tracker): atomic write, thread lock, deferred flush"
```

---

### Task 2: LogCollectorConnector — Deferred Flush + Skip-If-Processing Guard

Wire up deferred flush and prevent duplicate concurrent processing of the same file.

**Files:**
- Modify: `tb_gateway_collect/connectors/log_collector/log_collector_connector.py`
- Modify: `tests/unit/collect/test_log_collector_connector.py`

**Step 1: Write failing tests**

Add to `test_log_collector_connector.py`:

```python
class TestLogCollectorFlushIntegration:

    def test_state_flushed_after_poll_cycle(self):
        """State tracker should be flushed after each poll cycle, not per-file."""
        d = tempfile.mkdtemp()
        state_dir = tempfile.mkdtemp()
        path = os.path.join(d, "data.txt")
        with open(path, "w", newline="") as f:
            f.write("2026-03-03 10:30:45:123   FlushTest:1.0\r\n")

        gateway = MagicMock()
        config = _make_config(sources=[{
            "systemType": "xjsbb",
            "deviceName": "XJSBB-YB101",
            "deviceType": "log_source",
            "watchDirs": [d],
            "filePattern": "*.txt",
        }], state_dir=state_dir)
        connector = LogCollectorConnector(gateway, config, "log_collector")

        # Spy on flush_if_dirty
        tracker = connector._LogCollectorConnector__state_tracker
        with patch.object(tracker, 'flush_if_dirty', wraps=tracker.flush_if_dirty) as mock_flush:
            connector.open()
            time.sleep(2)
            connector.close()
            # flush_if_dirty should have been called (at least once per poll + once on close)
            assert mock_flush.call_count >= 2

    def test_close_flushes_state(self):
        """close() should flush any pending state to disk."""
        d = tempfile.mkdtemp()
        state_dir = tempfile.mkdtemp()
        state_path = os.path.join(state_dir, "state.json")
        path = os.path.join(d, "data.txt")
        with open(path, "w", newline="") as f:
            f.write("2026-03-03 10:30:45:123   CloseTest:2.0\r\n")

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
        time.sleep(0.5)

        # State should be persisted on disk
        assert os.path.exists(state_path)
        with open(state_path, "r") as f:
            data = json.load(f)
        # The data file's cursor should be saved
        assert any("data.txt" in k for k in data.keys())
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/collect/test_log_collector_connector.py::TestLogCollectorFlushIntegration -v`
Expected: FAIL — `flush_if_dirty` not called in run loop or close

**Step 3: Implement connector changes**

In `log_collector_connector.py`, make the following changes:

1. Add import at top:
```python
from threading import Thread, Lock
```

2. In `__init__`, add after `self.daemon = True`:
```python
self.__process_lock = Lock()
self.__processing: set[str] = set()
```

3. Replace `close()`:
```python
def close(self):
    self.__stopped = True
    self.__connected = False
    try:
        self.__watcher.stop()
    except Exception:
        pass
    self.__state_tracker.flush_if_dirty()
    self.__log.info("Log Collector stopped")
```

4. Replace `_snapshot_existing_files()` — add flush at end:
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

    self.__state_tracker.flush_if_dirty()
    if count > 0:
        self.__log.info("Cold start: marked %d existing files as already-read", count)
```

5. Replace `_on_file_event()` — add flush after processing:
```python
def _on_file_event(self, file_path: str):
    """Called by watchdog when a file is created or modified."""
    for src in self.__sources:
        if self._file_belongs_to_source(file_path, src):
            self._process_file(file_path, src)
            self.__state_tracker.flush_if_dirty()
            return
```

6. Replace `_process_file()` — add skip-if-processing guard:
```python
def _process_file(self, file_path: str, source: dict):
    # Skip if another thread is already processing this file
    with self.__process_lock:
        if file_path in self.__processing:
            return
        self.__processing.add(file_path)

    try:
        self._process_file_inner(file_path, source)
    finally:
        with self.__process_lock:
            self.__processing.discard(file_path)

def _process_file_inner(self, file_path: str, source: dict):
    system_type = source["systemType"]
    device_name = source["deviceName"]
    device_type = source.get("deviceType", "log_source")
    date_filter_days = source.get("dateFilterDays")

    if date_filter_days and not self._file_in_date_range(file_path, date_filter_days):
        return

    try:
        parser = get_parser(system_type)
        cursor = self.__state_tracker.get_cursor(file_path)
        records, new_cursor = parser.parse(file_path, device_name, cursor)
        self.__state_tracker.save_cursor(file_path, new_cursor)

        for record in records:
            converted = self.__converter.convert(record)
            self.__gateway.add_device(device_name, {CONNECTOR_PARAMETER: self},
                                      device_type=device_type)
            self.__gateway.send_to_storage(self.get_name(), self.get_id(), converted)

        if records:
            status = self.__source_statuses.get(device_name)
            if status:
                status.last_data = datetime.now()
            self.__log.debug("Processed %d records from %s for %s",
                             len(records), file_path, device_name)
    except Exception as e:
        self.__log.error("Error processing %s: %s", file_path, e)
```

7. Replace `run()` — add flush after each poll:
```python
def run(self):
    while not self.__stopped:
        start = monotonic()
        self._poll_all_sources()
        self.__state_tracker.flush_if_dirty()

        any_connected = any(s.connected for s in self.__source_statuses.values())
        self.__connected = any_connected

        elapsed = monotonic() - start
        remaining = self.__poll_interval - elapsed
        if remaining > 0 and not self.__stopped:
            sleep(remaining)
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/collect/test_log_collector_connector.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add tb_gateway_collect/connectors/log_collector/log_collector_connector.py tests/unit/collect/test_log_collector_connector.py
git commit -m "fix(log-connector): deferred flush + skip-if-processing guard"
```

---

### Task 3: Poll Skip — mtime/size Check

Avoid processing unchanged files during poll cycles. This reduces unnecessary I/O on network shares.

**Files:**
- Modify: `tb_gateway_collect/connectors/log_collector/log_collector_connector.py`
- Modify: `tests/unit/collect/test_log_collector_connector.py`

**Step 1: Write failing tests**

Add to `test_log_collector_connector.py`:

```python
class TestLogCollectorPollSkip:

    def test_poll_skips_unchanged_file(self):
        """Second poll should not re-process a file that hasn't changed."""
        d = tempfile.mkdtemp()
        state_dir = tempfile.mkdtemp()
        path = os.path.join(d, "data.txt")
        with open(path, "w", newline="") as f:
            f.write("2026-03-03 10:30:45:123   SkipTest:1.0\r\n")

        gateway = MagicMock()
        config = _make_config(sources=[{
            "systemType": "xjsbb",
            "deviceName": "XJSBB-YB101",
            "deviceType": "log_source",
            "watchDirs": [d],
            "filePattern": "*.txt",
        }], state_dir=state_dir)
        # Use very short poll interval to get multiple polls
        config["pollIntervalMs"] = 300
        connector = LogCollectorConnector(gateway, config, "log_collector")
        connector.open()
        time.sleep(2)  # should get ~6 polls
        connector.close()

        # Data should be sent exactly once (first poll), not on subsequent polls
        assert gateway.send_to_storage.call_count == 1

    def test_poll_processes_modified_file(self):
        """File modified between polls should be re-processed."""
        d = tempfile.mkdtemp()
        state_dir = tempfile.mkdtemp()
        path = os.path.join(d, "data.txt")
        with open(path, "w", newline="") as f:
            f.write("2026-03-03 10:30:45:123   ModTest:1.0\r\n")

        gateway = MagicMock()
        config = _make_config(sources=[{
            "systemType": "xjsbb",
            "deviceName": "XJSBB-YB101",
            "deviceType": "log_source",
            "watchDirs": [d],
            "filePattern": "*.txt",
        }], state_dir=state_dir)
        config["pollIntervalMs"] = 500
        connector = LogCollectorConnector(gateway, config, "log_collector")
        connector.open()
        time.sleep(1)

        # Append new data between polls
        with open(path, "a", newline="") as f:
            f.write("2026-03-03 10:31:00:000   ModTest:2.0\r\n")

        time.sleep(2)
        connector.close()

        # Should have sent data at least twice (first poll + after modification)
        assert gateway.send_to_storage.call_count >= 2
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/collect/test_log_collector_connector.py::TestLogCollectorPollSkip -v`
Expected: FAIL — `test_poll_skips_unchanged_file` sees send_to_storage called on every poll

**Step 3: Implement mtime/size skip**

In `log_collector_connector.py`:

1. Replace `_process_file_inner` — store mtime/size after processing:
```python
def _process_file_inner(self, file_path: str, source: dict):
    system_type = source["systemType"]
    device_name = source["deviceName"]
    device_type = source.get("deviceType", "log_source")
    date_filter_days = source.get("dateFilterDays")

    if date_filter_days and not self._file_in_date_range(file_path, date_filter_days):
        return

    try:
        parser = get_parser(system_type)
        cursor = self.__state_tracker.get_cursor(file_path)
        records, new_cursor = parser.parse(file_path, device_name, cursor)

        # Store file stat for poll skip optimization
        try:
            st = os.stat(file_path)
            new_cursor["mtime"] = st.st_mtime
            new_cursor["size"] = st.st_size
        except OSError:
            pass

        self.__state_tracker.save_cursor(file_path, new_cursor)

        for record in records:
            converted = self.__converter.convert(record)
            self.__gateway.add_device(device_name, {CONNECTOR_PARAMETER: self},
                                      device_type=device_type)
            self.__gateway.send_to_storage(self.get_name(), self.get_id(), converted)

        if records:
            status = self.__source_statuses.get(device_name)
            if status:
                status.last_data = datetime.now()
            self.__log.debug("Processed %d records from %s for %s",
                             len(records), file_path, device_name)
    except Exception as e:
        self.__log.error("Error processing %s: %s", file_path, e)
```

2. Replace `_scan_directory` — add mtime/size check:
```python
def _scan_directory(self, directory: str, source: dict):
    """Walk directory and process any matching files that have changed."""
    pattern = source.get("filePattern", "*.txt")
    for root, dirs, files in os.walk(directory):
        for fname in files:
            if fnmatch.fnmatch(fname, pattern):
                file_path = os.path.join(root, fname)
                if self._file_unchanged(file_path):
                    continue
                self._process_file(file_path, source)

def _file_unchanged(self, file_path: str) -> bool:
    """Check if file mtime+size match the stored cursor. Skip if unchanged."""
    cursor = self.__state_tracker.get_cursor(file_path)
    if cursor is None or "mtime" not in cursor:
        return False  # no previous stat — must process
    try:
        st = os.stat(file_path)
        return st.st_mtime == cursor["mtime"] and st.st_size == cursor["size"]
    except OSError:
        return False
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/collect/test_log_collector_connector.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add tb_gateway_collect/connectors/log_collector/log_collector_connector.py tests/unit/collect/test_log_collector_connector.py
git commit -m "fix(log-connector): skip unchanged files in poll via mtime/size"
```

---

### Task 4: LogFileWatcher — PollingObserver for Network Paths

Replace native Observer with PollingObserver for network share paths. This makes watchdog reliably detect file changes on SMB/CIFS mounts.

**Files:**
- Modify: `tb_gateway_collect/connectors/log_collector/log_file_watcher.py`
- Modify: `tb_gateway_collect/connectors/log_collector/log_collector_connector.py`
- Modify: `tests/unit/collect/test_log_file_watcher.py`

**Step 1: Write failing tests**

Add to `test_log_file_watcher.py`:

```python
from watchdog.observers.polling import PollingObserver as WatchdogPollingObserver

class TestLogFileWatcherPolling:

    def test_polling_observer_when_interval_set(self):
        callback = MagicMock()
        watcher = LogFileWatcher(callback, polling_interval=5)
        assert isinstance(watcher._observer, WatchdogPollingObserver)

    def test_native_observer_when_no_polling(self):
        callback = MagicMock()
        watcher = LogFileWatcher(callback, polling_interval=0)
        assert not isinstance(watcher._observer, WatchdogPollingObserver)

    def test_default_is_native_observer(self):
        callback = MagicMock()
        watcher = LogFileWatcher(callback)
        assert not isinstance(watcher._observer, WatchdogPollingObserver)
```

Add to `test_log_collector_connector.py`:

```python
class TestLogCollectorNetworkDetection:

    def test_unc_path_enables_polling_observer(self):
        """UNC watchDirs should auto-enable PollingObserver."""
        gateway = MagicMock()
        config = _make_config(sources=[{
            "systemType": "xjsbb",
            "deviceName": "XJSBB-YB101",
            "deviceType": "log_source",
            "watchDirs": ["\\\\server\\share\\logs"],
            "filePattern": "*.txt",
        }])
        connector = LogCollectorConnector(gateway, config, "log_collector")
        watcher = connector._LogCollectorConnector__watcher
        from watchdog.observers.polling import PollingObserver as WDP
        assert isinstance(watcher._observer, WDP)

    def test_local_path_uses_native_observer(self):
        """Local watchDirs should use native Observer."""
        d = tempfile.mkdtemp()
        gateway = MagicMock()
        config = _make_config(sources=[{
            "systemType": "xjsbb",
            "deviceName": "XJSBB-YB101",
            "deviceType": "log_source",
            "watchDirs": [d],
            "filePattern": "*.txt",
        }])
        connector = LogCollectorConnector(gateway, config, "log_collector")
        watcher = connector._LogCollectorConnector__watcher
        from watchdog.observers.polling import PollingObserver as WDP
        assert not isinstance(watcher._observer, WDP)
        os.rmdir(d)

    def test_config_override_polling_interval(self):
        """watcherPollingIntervalSec config should override auto-detection."""
        d = tempfile.mkdtemp()
        gateway = MagicMock()
        config = _make_config(sources=[{
            "systemType": "xjsbb",
            "deviceName": "XJSBB-YB101",
            "deviceType": "log_source",
            "watchDirs": [d],
            "filePattern": "*.txt",
        }])
        config["watcherPollingIntervalSec"] = 10  # force polling even for local
        connector = LogCollectorConnector(gateway, config, "log_collector")
        watcher = connector._LogCollectorConnector__watcher
        from watchdog.observers.polling import PollingObserver as WDP
        assert isinstance(watcher._observer, WDP)
        os.rmdir(d)
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/collect/test_log_file_watcher.py::TestLogFileWatcherPolling tests/unit/collect/test_log_collector_connector.py::TestLogCollectorNetworkDetection -v`
Expected: FAIL — `LogFileWatcher` doesn't accept `polling_interval`

**Step 3: Implement LogFileWatcher polling support**

In `log_file_watcher.py`, replace the `LogFileWatcher` class:

```python
class LogFileWatcher:
    """Wraps watchdog Observer to watch multiple directories with file patterns.

    Args:
        callback: Called with file_path when a matching file is created/modified.
        polling_interval: If > 0, use PollingObserver with this interval (seconds).
                          Use for network share paths where native events are unreliable.
                          If 0 (default), use native OS Observer.
    """

    def __init__(self, callback: Callable[[str], None], polling_interval: int = 0):
        self._callback = callback
        if polling_interval > 0:
            from watchdog.observers.polling import PollingObserver
            self._observer = PollingObserver(timeout=polling_interval)
        else:
            self._observer = Observer()
        self._watches: list[dict] = []

    @property
    def watched_dirs(self) -> list[str]:
        return [w["dir"] for w in self._watches]

    def add_watch(self, directory: str, pattern: str = "*.*", recursive: bool = True):
        handler = _FileHandler(self._callback, pattern)
        watch = self._observer.schedule(handler, directory, recursive=recursive)
        self._watches.append({"dir": directory, "pattern": pattern, "watch": watch})

    def remove_watch(self, directory: str):
        for w in self._watches:
            if w["dir"] == directory:
                self._observer.unschedule(w["watch"])
                self._watches.remove(w)
                break

    def start(self):
        self._observer.start()

    def stop(self):
        self._observer.stop()
        if self._observer.is_alive():
            self._observer.join(timeout=5)

    def is_running(self) -> bool:
        return self._observer.is_alive()
```

**Step 4: Implement connector auto-detection**

In `log_collector_connector.py`, replace the watcher creation in `__init__`:

Replace:
```python
self.__watcher = LogFileWatcher(self._on_file_event)
```

With:
```python
polling_interval = self._detect_polling_interval(config)
self.__watcher = LogFileWatcher(self._on_file_event, polling_interval=polling_interval)
```

Add method:
```python
def _detect_polling_interval(self, config: dict) -> int:
    """Auto-detect whether to use PollingObserver.

    Returns polling interval in seconds (0 = native observer).
    UNC paths (\\\\server\\share) trigger automatic 5s polling.
    Config key 'watcherPollingIntervalSec' overrides auto-detection.
    """
    explicit = config.get("watcherPollingIntervalSec")
    if explicit is not None:
        return int(explicit)

    for src in self.__sources:
        for wd in src.get("watchDirs", []):
            if wd.startswith("\\\\") or wd.startswith("//"):
                return 5  # default polling interval for network shares
    return 0
```

**Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/unit/collect/test_log_file_watcher.py tests/unit/collect/test_log_collector_connector.py -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add tb_gateway_collect/connectors/log_collector/log_file_watcher.py tb_gateway_collect/connectors/log_collector/log_collector_connector.py tests/unit/collect/test_log_file_watcher.py tests/unit/collect/test_log_collector_connector.py
git commit -m "fix(log-watcher): use PollingObserver for network share paths"
```

---

### Task 5: Run Full Test Suite

**Step 1: Run all collect tests**

Run: `python -m pytest tests/unit/collect/ -v`
Expected: ALL PASS

**Step 2: Run all SAE tests**

Run: `python -m pytest tests/unit/collect/ tests/unit/windows/ -v`
Expected: ALL PASS

**Step 3: Final commit if any fixups needed**

If all tests pass, no commit needed. If fixes were required:
```bash
git commit -m "fix: address test failures from log collector reliability fixes"
```
