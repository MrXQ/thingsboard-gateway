# Watchfiles Migration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace watchdog with watchfiles for ~1s file detection latency on network shares, matching the original Java collect project.

**Architecture:** Single data path through watchfiles (`force_polling=True`, 500ms poll, 500ms debounce). Poll loop becomes health-check only. LogFileWatcher auto-restarts on crash with 3s backoff.

**Tech Stack:** Python 3, watchfiles (Rust-powered), threading.Event for stop/restart

**Design doc:** `docs/plans/2026-03-04-watchfiles-migration-design.md`

---

### Task 1: Update Dependencies

**Files:**
- Modify: `requirements-sae.txt`

**Step 1: Replace watchdog with watchfiles**

In `requirements-sae.txt`, replace:
```
watchdog>=4.0
```
With:
```
watchfiles>=1.0
```

**Step 2: Install new dependency**

Run: `pip install watchfiles>=1.0`

**Step 3: Commit**

```bash
git add requirements-sae.txt
git commit -m "deps: replace watchdog with watchfiles for network share support"
```

---

### Task 2: Rewrite LogFileWatcher with watchfiles

**Files:**
- Rewrite: `tb_gateway_collect/connectors/log_collector/log_file_watcher.py`
- Rewrite: `tests/unit/collect/test_log_file_watcher.py`

**Step 1: Write new tests**

Replace `tests/unit/collect/test_log_file_watcher.py` entirely:

```python
# tests/unit/collect/test_log_file_watcher.py
import os
import tempfile
import time
from unittest.mock import MagicMock, patch

from tb_gateway_collect.connectors.log_collector.log_file_watcher import LogFileWatcher


class TestLogFileWatcher:

    def test_create_watcher(self):
        callback = MagicMock()
        watcher = LogFileWatcher(callback)
        assert watcher is not None

    def test_add_watch_dir(self):
        callback = MagicMock()
        watcher = LogFileWatcher(callback)
        d = tempfile.mkdtemp()
        try:
            watcher.add_watch(d, "*.txt")
            assert len(watcher.watched_dirs) == 1
            assert d in watcher.watched_dirs
        finally:
            os.rmdir(d)

    def test_start_stop(self):
        callback = MagicMock()
        watcher = LogFileWatcher(callback, poll_delay_ms=100, debounce_ms=100)
        d = tempfile.mkdtemp()
        try:
            watcher.add_watch(d, "*.txt")
            watcher.start()
            time.sleep(0.5)
            assert watcher.is_running()
            watcher.stop()
            assert not watcher.is_running()
        finally:
            if os.path.exists(d):
                os.rmdir(d)

    def test_detects_new_file(self):
        callback = MagicMock()
        watcher = LogFileWatcher(callback, poll_delay_ms=100, debounce_ms=100)
        d = tempfile.mkdtemp()
        try:
            watcher.add_watch(d, "*.txt")
            watcher.start()
            time.sleep(0.5)

            path = os.path.join(d, "test.txt")
            with open(path, "w") as f:
                f.write("data\n")

            time.sleep(2)
            watcher.stop()

            assert callback.call_count >= 1
            # Verify the path ends with our filename
            paths_called = [call[0][0] for call in callback.call_args_list]
            assert any(p.endswith("test.txt") for p in paths_called)
        finally:
            if os.path.exists(os.path.join(d, "test.txt")):
                os.unlink(os.path.join(d, "test.txt"))
            if os.path.exists(d):
                os.rmdir(d)

    def test_detects_modified_file(self):
        callback = MagicMock()
        d = tempfile.mkdtemp()
        path = os.path.join(d, "existing.txt")
        with open(path, "w") as f:
            f.write("initial\n")

        watcher = LogFileWatcher(callback, poll_delay_ms=100, debounce_ms=100)
        try:
            watcher.add_watch(d, "*.txt")
            watcher.start()
            time.sleep(0.5)

            # Modify the file
            with open(path, "a") as f:
                f.write("appended\n")

            time.sleep(2)
            watcher.stop()

            assert callback.call_count >= 1
        finally:
            if os.path.exists(path):
                os.unlink(path)
            if os.path.exists(d):
                os.rmdir(d)

    def test_ignores_non_matching_files(self):
        callback = MagicMock()
        watcher = LogFileWatcher(callback, poll_delay_ms=100, debounce_ms=100)
        d = tempfile.mkdtemp()
        try:
            watcher.add_watch(d, "*.txt")
            watcher.start()
            time.sleep(0.5)

            path = os.path.join(d, "test.jpg")
            with open(path, "w") as f:
                f.write("data\n")

            time.sleep(2)
            watcher.stop()

            assert callback.call_count == 0
        finally:
            if os.path.exists(os.path.join(d, "test.jpg")):
                os.unlink(os.path.join(d, "test.jpg"))
            if os.path.exists(d):
                os.rmdir(d)

    def test_stop_without_start(self):
        """stop() should not raise if watcher was never started."""
        callback = MagicMock()
        watcher = LogFileWatcher(callback)
        watcher.stop()  # should not raise


class TestLogFileWatcherResilience:

    def test_auto_restart_after_error(self):
        """Watcher thread should stay alive and retry after watch() raises."""
        callback = MagicMock()
        watcher = LogFileWatcher(callback, poll_delay_ms=100, debounce_ms=100)
        d = tempfile.mkdtemp()
        watcher.add_watch(d, "*.txt")

        error_count = {"n": 0}

        def always_fail(*args, **kwargs):
            error_count["n"] += 1
            raise OSError("simulated network error")

        try:
            with patch(
                'tb_gateway_collect.connectors.log_collector.log_file_watcher.watch',
                side_effect=always_fail,
            ):
                watcher.start()
                time.sleep(5)  # allow multiple restart attempts (3s backoff)
                assert watcher.is_running(), "Thread should stay alive despite errors"
                assert error_count["n"] >= 2, "Should have retried at least once"
                watcher.stop()

            assert not watcher.is_running()
        finally:
            if os.path.exists(d):
                os.rmdir(d)

    def test_stop_interrupts_backoff(self):
        """stop() should interrupt the 3s restart backoff immediately."""
        callback = MagicMock()
        watcher = LogFileWatcher(callback, poll_delay_ms=100, debounce_ms=100)
        d = tempfile.mkdtemp()
        watcher.add_watch(d, "*.txt")

        def always_fail(*args, **kwargs):
            raise OSError("simulated error")

        try:
            with patch(
                'tb_gateway_collect.connectors.log_collector.log_file_watcher.watch',
                side_effect=always_fail,
            ):
                watcher.start()
                time.sleep(0.5)  # let it hit the error and enter backoff
                start = time.monotonic()
                watcher.stop()
                elapsed = time.monotonic() - start
                # stop() should return quickly, not wait for 3s backoff
                assert elapsed < 2, f"stop() took {elapsed:.1f}s, should be < 2s"
        finally:
            if os.path.exists(d):
                os.rmdir(d)
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/collect/test_log_file_watcher.py -v`
Expected: FAIL — `LogFileWatcher` still uses watchdog, doesn't accept `poll_delay_ms`/`debounce_ms`

**Step 3: Implement new LogFileWatcher**

Replace `tb_gateway_collect/connectors/log_collector/log_file_watcher.py` entirely:

```python
# tb_gateway_collect/connectors/log_collector/log_file_watcher.py
import fnmatch
import logging
import os
from threading import Thread, Event
from typing import Callable

from watchfiles import watch, Change

log = logging.getLogger(__name__)

_RESTART_BACKOFF_S = 3


class LogFileWatcher:
    """Watches directories for file changes using watchfiles (Rust-powered polling).

    Uses force_polling=True for reliable detection on both local and network paths.
    Auto-restarts with backoff on failure.

    Args:
        callback: Called with file_path (str) when a matching file is created/modified.
        poll_delay_ms: Delay between stat polls in milliseconds (default 500).
        debounce_ms: Group rapid changes within this window in milliseconds (default 500).
    """

    def __init__(self, callback: Callable[[str], None],
                 poll_delay_ms: int = 500, debounce_ms: int = 500):
        self._callback = callback
        self._poll_delay_ms = poll_delay_ms
        self._debounce_ms = debounce_ms
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._watches: list[dict] = []

    @property
    def watched_dirs(self) -> list[str]:
        return [w["dir"] for w in self._watches]

    def add_watch(self, directory: str, pattern: str = "*.*", recursive: bool = True):
        self._watches.append({"dir": directory, "pattern": pattern, "recursive": recursive})

    def remove_watch(self, directory: str):
        self._watches = [w for w in self._watches if w["dir"] != directory]

    def start(self):
        if not self._watches:
            return
        self._stop_event.clear()
        self._thread = Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        dirs = [w["dir"] for w in self._watches]
        while not self._stop_event.is_set():
            try:
                for changes in watch(
                    *dirs,
                    force_polling=True,
                    poll_delay_ms=self._poll_delay_ms,
                    debounce=self._debounce_ms,
                    stop_event=self._stop_event,
                    recursive=True,
                ):
                    for change_type, path in changes:
                        if change_type in (Change.added, Change.modified):
                            if self._matches_any_watch(path):
                                try:
                                    self._callback(path)
                                except Exception as e:
                                    log.error("Callback error for %s: %s", path, e)
            except Exception as e:
                if self._stop_event.is_set():
                    return
                log.warning("File watcher error, restarting in %ds: %s",
                            _RESTART_BACKOFF_S, e)
                self._stop_event.wait(timeout=_RESTART_BACKOFF_S)

    def _matches_any_watch(self, path: str) -> bool:
        fname = os.path.basename(path)
        for w in self._watches:
            if fnmatch.fnmatch(fname, w["pattern"]):
                try:
                    if os.path.commonpath([w["dir"], path]) == os.path.normpath(w["dir"]):
                        return True
                except ValueError:
                    continue
        return False

    def stop(self):
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/collect/test_log_file_watcher.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add tb_gateway_collect/connectors/log_collector/log_file_watcher.py tests/unit/collect/test_log_file_watcher.py
git commit -m "feat(log-watcher): migrate from watchdog to watchfiles with auto-restart"
```

---

### Task 3: Simplify LogCollectorConnector — Health-Check Only Poll Loop

Wire new LogFileWatcher API into the connector. Remove file-processing from poll loop. Remove obsolete tests.

**Files:**
- Modify: `tb_gateway_collect/connectors/log_collector/log_collector_connector.py`
- Modify: `tests/unit/collect/test_log_collector_connector.py`

**Step 1: Update tests**

In `tests/unit/collect/test_log_collector_connector.py`:

1. Update `_make_config` to add watcher config for fast test execution:

Replace:
```python
def _make_config(sources=None, state_dir=None):
    if state_dir is None:
        state_dir = tempfile.mkdtemp()
    return {
        "name": "Log Collector",
        "id": "test-log-collector-001",
        "pollIntervalMs": 500,
        "stateFile": os.path.join(state_dir, "state.json"),
        "logLevel": "DEBUG",
        "sources": sources or [],
    }
```

With:
```python
def _make_config(sources=None, state_dir=None):
    if state_dir is None:
        state_dir = tempfile.mkdtemp()
    return {
        "name": "Log Collector",
        "id": "test-log-collector-001",
        "pollIntervalMs": 500,
        "watcherPollDelayMs": 200,
        "watcherDebounceMs": 200,
        "stateFile": os.path.join(state_dir, "state.json"),
        "logLevel": "DEBUG",
        "sources": sources or [],
    }
```

2. Update `TestLogCollectorFlushIntegration.test_state_flushed_after_poll_cycle` — the poll loop no longer flushes (no file processing), so change assertion:

Replace the test with:
```python
    def test_state_flushed_after_file_event(self):
        """State tracker should be flushed after watchfiles processes a file."""
        d = tempfile.mkdtemp()
        state_dir = tempfile.mkdtemp()
        path = os.path.join(d, "data.txt")
        # File created BEFORE open — will be snapshotted
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

        tracker = connector._LogCollectorConnector__state_tracker
        with patch.object(tracker, 'flush_if_dirty', wraps=tracker.flush_if_dirty) as mock_flush:
            connector.open()
            time.sleep(2)
            connector.close()
            # flush_if_dirty called from: snapshot (1) + close (1) = at least 2
            assert mock_flush.call_count >= 2
```

3. **Delete** the entire `TestLogCollectorPollSkip` class — poll loop no longer processes files.

4. **Delete** the entire `TestLogCollectorNetworkDetection` class — no more PollingObserver detection.

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/collect/test_log_collector_connector.py -v`
Expected: FAIL — connector still uses old LogFileWatcher API (`polling_interval` param)

**Step 3: Implement connector changes**

In `log_collector_connector.py`:

1. **Replace the watcher creation in `__init__`:**

Replace:
```python
        polling_interval = self._detect_polling_interval(config)
        self.__watcher = LogFileWatcher(self._on_file_event, polling_interval=polling_interval)
```

With:
```python
        poll_delay_ms = config.get("watcherPollDelayMs", 500)
        debounce_ms = config.get("watcherDebounceMs", 500)
        self.__watcher = LogFileWatcher(self._on_file_event,
                                        poll_delay_ms=poll_delay_ms,
                                        debounce_ms=debounce_ms)
```

2. **Change default pollIntervalMs from 60000 to 30000** (health check only, doesn't affect data latency):

Replace:
```python
        self.__poll_interval = config.get("pollIntervalMs", 60000) / 1000.0
```

With:
```python
        self.__poll_interval = config.get("pollIntervalMs", 30000) / 1000.0
```

3. **Update `_on_file_event` docstring:**

Replace:
```python
    def _on_file_event(self, file_path: str):
        """Called by watchdog when a file is created or modified."""
```

With:
```python
    def _on_file_event(self, file_path: str):
        """Called by watchfiles when a file is created or modified."""
```

4. **Delete `_detect_polling_interval` method** (lines 125-140).

5. **Replace `run()` and `_poll_all_sources()` with health-check only:**

Replace:
```python
    # --- Thread run loop (fallback polling) ---

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

    def _poll_all_sources(self):
        """Fallback polling: scan directories for new/changed files."""
        for src in self.__sources:
            device_name = src["deviceName"]
            status = self.__source_statuses.get(device_name)

            for watch_dir in src.get("watchDirs", []):
                is_accessible = os.path.isdir(watch_dir)

                if status:
                    was_connected = status.connected
                    status.connected = is_accessible
                    status.last_check = datetime.now()

                    if is_accessible and not was_connected:
                        self.__log.info("Source %s reconnected: %s", device_name, watch_dir)
                        status.error = None
                    elif not is_accessible and was_connected:
                        status.error = f"Directory not accessible: {watch_dir}"
                        self.__log.warning("Source %s disconnected: %s", device_name, watch_dir)

                if is_accessible:
                    self._scan_directory(watch_dir, src)

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

With:
```python
    # --- Thread run loop (health check) ---

    def run(self):
        while not self.__stopped:
            start = monotonic()
            self._check_source_health()

            elapsed = monotonic() - start
            remaining = self.__poll_interval - elapsed
            if remaining > 0 and not self.__stopped:
                sleep(remaining)

    def _check_source_health(self):
        """Monitor directory accessibility and update source connection status."""
        for src in self.__sources:
            device_name = src["deviceName"]
            status = self.__source_statuses.get(device_name)

            for watch_dir in src.get("watchDirs", []):
                is_accessible = os.path.isdir(watch_dir)

                if status:
                    was_connected = status.connected
                    status.connected = is_accessible
                    status.last_check = datetime.now()

                    if is_accessible and not was_connected:
                        self.__log.info("Source %s reconnected: %s", device_name, watch_dir)
                        status.error = None
                    elif not is_accessible and was_connected:
                        status.error = f"Directory not accessible: {watch_dir}"
                        self.__log.warning("Source %s disconnected: %s", device_name, watch_dir)

        any_connected = any(s.connected for s in self.__source_statuses.values())
        self.__connected = any_connected
```

6. **Remove unused imports** — `fnmatch` may no longer be needed if `_file_belongs_to_source` still uses it (it does). Keep `fnmatch`. Remove any leftover unused imports after all changes.

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/collect/test_log_collector_connector.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add tb_gateway_collect/connectors/log_collector/log_collector_connector.py tests/unit/collect/test_log_collector_connector.py
git commit -m "refactor(log-connector): health-check only poll loop, wire watchfiles watcher"
```

---

### Task 4: Run Full Test Suite

**Step 1: Run all collect tests**

Run: `python -m pytest tests/unit/collect/ -v`
Expected: ALL PASS

**Step 2: Run all SAE tests**

Run: `python -m pytest tests/unit/collect/ tests/unit/windows/ -v`
Expected: ALL PASS

**Step 3: Final commit if any fixups needed**

If all tests pass, no commit needed. If fixes were required:
```bash
git commit -m "fix: address test failures from watchfiles migration"
```
