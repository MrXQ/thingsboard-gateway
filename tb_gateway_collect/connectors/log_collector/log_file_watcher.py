# tb_gateway_collect/connectors/log_collector/log_file_watcher.py
import fnmatch
import logging
import os
from typing import Callable

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent

log = logging.getLogger(__name__)


class _FileHandler(FileSystemEventHandler):
    """Routes file create/modify events to the callback if they match the pattern."""

    def __init__(self, callback: Callable[[str], None], pattern: str):
        self._callback = callback
        self._pattern = pattern

    def on_created(self, event):
        if not event.is_directory and self._matches(event.src_path):
            self._callback(event.src_path)

    def on_modified(self, event):
        if not event.is_directory and self._matches(event.src_path):
            self._callback(event.src_path)

    def _matches(self, path: str) -> bool:
        return fnmatch.fnmatch(os.path.basename(path), self._pattern)


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
