import json
import logging
import os
from typing import Optional

log = logging.getLogger(__name__)


class StateTracker:
    """Persists per-file cursor state to a JSON file."""

    def __init__(self, state_file_path: str):
        self._path = state_file_path
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

    def _flush(self):
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._state, f, indent=2)

    def get_cursor(self, file_path: str) -> Optional[dict]:
        return self._state.get(file_path)

    def save_cursor(self, file_path: str, cursor: dict):
        self._state[file_path] = cursor
        self._flush()
