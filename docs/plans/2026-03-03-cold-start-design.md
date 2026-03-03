# Log Collector Cold Start Design (Forward-Only)

**Goal:** On first-ever startup (cold start), mark all existing log files as "already read" so only new data is uploaded. On warm restart (after crash/shutdown), resume from last cursor and catch up on missed data.

**Design doc:** `docs/plans/2026-03-03-cold-start-design.md`

---

## Problem

When the log collector starts with no state file, `_scan_directory` discovers all existing log files (potentially hundreds, organized in monthly/daily subfolders). Each file gets `cursor=None` from the state tracker, so parsers read from byte 0 — uploading all historical data to ThingsBoard in one burst.

## Solution: Snapshot-on-start (cold start only)

Add a `_snapshot_existing_files()` method to `LogCollectorConnector` that runs once in `open()`, **only on true cold start** (state tracker has zero entries). It walks all watched directories and saves `cursor = {"byte_offset": file_size}` for every matching file, marking them as "already read at current size."

### StateTracker Change

Add an `is_empty()` method to `StateTracker`:

```python
def is_empty(self) -> bool:
    return len(self._state) == 0
```

### Connector Change

New method `_snapshot_existing_files()` and insertion into `open()`:

```python
def open(self):
    self.__stopped = False
    self._setup_watches()
    self._snapshot_existing_files()   # NEW — cold start guard
    self.__watcher.start()
    self.start()
    self.__log.info("Log Collector started with %d sources", len(self.__sources))

def _snapshot_existing_files(self):
    """On cold start, mark all existing files as already-read."""
    if not self.__state_tracker.is_empty():
        return  # warm restart — let new files be read normally

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

## Behavior Matrix

| Scenario | State File | Snapshot? | Behavior |
|----------|-----------|-----------|----------|
| **Cold start** (first-ever) | Empty/missing | Yes | All existing files marked as read. Only new content uploaded. |
| **Warm restart** (after crash) | Has entries | No | Last-read file resumes from cursor. New files during downtime read fully. |
| **Network disconnect + reconnect** | Has entries | No | Same as warm restart — new files read fully, existing files resume. |

### Warm Restart Trace (file-by-file)

1. **File with cursor at byte 5000, now 8000 bytes:** Parser reads bytes 5000-8000. Picks up missed content.
2. **File fully read (cursor = file size), unchanged:** Parser reads 0 new bytes. No duplicates.
3. **New file created during downtime (no cursor):** Parser reads from byte 0. Full file uploaded. No data loss.
4. **After catch-up:** Normal watchdog + polling detects new changes. Back to steady state.

## What This Does NOT Change

- No new config options
- No changes to parsers — they remain cursor-based
- No changes to the watcher or polling loop
- No changes to `_process_file` — it still calls `get_cursor` / `save_cursor` as before
- `StateTracker` gets only a one-line `is_empty()` method

## Testing

| Test | Description |
|------|-------------|
| `test_cold_start_snapshots_existing_files` | Empty state → existing files get cursor at file size, not processed |
| `test_cold_start_new_file_after_snapshot_is_processed` | After snapshot, a new file (appended or created) is read from byte 0 |
| `test_warm_restart_does_not_snapshot` | State has entries → snapshot is a no-op, new files read fully |
| `test_state_tracker_is_empty` | `is_empty()` returns True when empty, False when entries exist |
