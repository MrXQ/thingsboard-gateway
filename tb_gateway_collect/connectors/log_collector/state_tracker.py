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
