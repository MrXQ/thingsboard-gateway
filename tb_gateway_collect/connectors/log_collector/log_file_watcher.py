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
                 poll_delay_ms: int = 500, debounce_ms: int = 500,
                 logger=None):
        self._callback = callback
        self._poll_delay_ms = poll_delay_ms
        self._debounce_ms = debounce_ms
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._watches: list[dict] = []
        self._log = logger or log

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
        self._log.info("File watcher started, watching %d dirs: %s", len(dirs), dirs)
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
                                    self._log.error("Callback error for %s: %s", path, e)
            except Exception as e:
                if self._stop_event.is_set():
                    return
                self._log.warning("File watcher error, restarting in %ds: %s",
                                  _RESTART_BACKOFF_S, e)
                self._stop_event.wait(timeout=_RESTART_BACKOFF_S)
        self._log.info("File watcher stopped")

    def _matches_any_watch(self, path: str) -> bool:
        norm_path = os.path.normcase(os.path.normpath(path))
        fname = os.path.basename(norm_path)
        for w in self._watches:
            if fnmatch.fnmatch(fname, w["pattern"]):
                norm_dir = os.path.normcase(os.path.normpath(w["dir"]))
                if norm_path.startswith(norm_dir + os.sep) or norm_path == norm_dir:
                    return True
        return False

    def stop(self):
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
