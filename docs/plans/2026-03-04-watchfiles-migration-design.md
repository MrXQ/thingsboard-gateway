# Log Collector File Watcher Migration — Design Doc

> **Goal:** Eliminate ~60s data latency on network shares by migrating from watchdog to watchfiles with polling-based detection, matching the original Java collect project's ~1s latency.

## Problem

The log collector has two independent file detection paths:
1. **Watchdog** (event-based): Uses `ReadDirectoryChangesW` on Windows, which is unreliable on SMB/CIFS network shares. Events silently fail to fire.
2. **Poll loop** (fallback): Walks directories every `pollIntervalMs` (60s default). This is the only working path on network shares, causing ~60s latency for 6s-frequency ICS data.

The original Java collect project uses Apache Commons IO `FileAlterationMonitor` at **1-second polling** with 500ms debounce — a pure stat-based approach that works identically on local and network paths. We need to match this approach.

## Solution

Replace watchdog with **watchfiles** (Rust-powered, `force_polling=True`). Single data path through watchfiles with auto-restart on failure. Poll loop becomes health-check only.

## Architecture

```
Before:
  watchdog Observer ──(broken on SMB)──→ _on_file_event → process
  poll loop (60s) ──────────────────────→ _scan_directory → process

After:
  watchfiles watch() ──(500ms poll)───→ _on_file_event → process  (THE data path)
  LogFileWatcher auto-restarts on crash (3s backoff)
  poll loop (30s) ─────────────────────→ health check only (no file processing)
```

## Component Changes

### 1. LogFileWatcher (`log_file_watcher.py`) — Full Rewrite

Replace watchdog Observer/PollingObserver with `watchfiles.watch()`.

**Key parameters:**
- `force_polling=True` — pure stat-based polling, works on local and network paths
- `poll_delay_ms=500` — check for changes every 500ms (configurable)
- `debounce=500` — group rapid changes within 500ms window (configurable)
- `stop_event` — clean shutdown via `threading.Event`
- `recursive=True` — watch subdirectories

**Auto-restart on failure:**
```python
def _run(self):
    while not self._stop_event.is_set():
        try:
            for changes in watch(*dirs, force_polling=True, ...):
                for change_type, path in changes:
                    if change_type in (Change.added, Change.modified):
                        if self._matches_pattern(path):
                            self._callback(path)
        except Exception as e:
            if self._stop_event.is_set():
                return
            log.warning("File watcher error, restarting in 3s: %s", e)
            self._stop_event.wait(timeout=3)  # backoff, interruptible by stop
```

**Interface stays the same:** `add_watch(dir, pattern)`, `start()`, `stop()`, `is_running()`, `watched_dirs`

### 2. LogCollectorConnector (`log_collector_connector.py`) — Simplify

- **Remove:** `_detect_polling_interval()` — no longer needed (watchfiles handles all paths)
- **Remove:** `polling_interval` param from LogFileWatcher creation
- **Remove:** `_scan_directory()` and `_process_file` calls from poll loop
- **Add:** Config keys `watcherPollDelayMs` (default 500) and `watcherDebounceMs` (default 500)
- **Simplify `run()`:** Health-check only — monitor directory accessibility, update source connection status

```python
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

### 3. Dependencies

- **Remove:** `watchdog>=4.0` from `requirements-sae.txt`
- **Add:** `watchfiles>=1.0` to `requirements-sae.txt`

### 4. Tests

- **test_log_file_watcher.py:** Rewrite for watchfiles-based watcher. Remove PollingObserver tests. Add auto-restart test.
- **test_log_collector_connector.py:** Remove `TestLogCollectorNetworkDetection` (no longer relevant). Update existing tests if needed.

## Config

```json
{
  "pollIntervalMs": 30000,
  "watcherPollDelayMs": 500,
  "watcherDebounceMs": 500,
  "stateFile": "log_collector_state.json",
  "sources": [...]
}
```

| Key | Default | Purpose |
|-----|---------|---------|
| `pollIntervalMs` | 30000 | Health check interval (no longer affects data latency) |
| `watcherPollDelayMs` | 500 | watchfiles stat polling delay in ms |
| `watcherDebounceMs` | 500 | watchfiles debounce window in ms |

## Latency Analysis

| Component | Time |
|-----------|------|
| File write → watchfiles detects (poll_delay) | ~500ms |
| Debounce window | ~500ms |
| Parse + send to gateway queue | ~10-50ms |
| Gateway internal pipeline to MQTT | ~100-500ms |
| **Total** | **~1-1.5s** |

Matches the Java collect project's performance (1s poll + 500ms debounce ≈ 1.5s).

## Resilience

- **Watcher crash:** Auto-restart with 3s backoff. Uses `stop_event.wait(timeout=3)` so shutdown is still instant.
- **Network share offline:** watchfiles stat calls fail gracefully. Health check loop detects and logs disconnection. When share comes back, watchfiles resumes detecting changes.
- **No dual data path:** watchfiles is THE file processing path. No fallback poll processing — simpler, no duplicate processing risk.

## Migration Notes

- The `watcherPollingIntervalSec` config key from Task 4 is superseded by `watcherPollDelayMs`. Remove support for the old key.
- The `_file_unchanged()` mtime/size skip from Task 3 is no longer used in `_scan_directory` (removed from poll loop), but remains in the codebase for potential future use.
- Task 4's PollingObserver auto-detection is removed entirely — watchfiles always polls.
