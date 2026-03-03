from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional


@dataclass
class LogRecord:
    """A single parsed log entry to send as ThingsBoard telemetry."""
    device_name: str
    timestamp: datetime
    values: dict[str, Any]
    system_type: str


class LogParser(ABC):
    """Abstract base for log file parsers.

    Each parser handles a specific log format (AB Dim, IVS, ICS, etc.).
    The cursor is opaque — each parser defines its own format.
    """

    @abstractmethod
    def parse(
        self,
        file_path: str,
        device_name: str,
        cursor: Optional[dict],
    ) -> tuple[list[LogRecord], dict]:
        """Parse file from cursor position.

        Args:
            file_path: Absolute path to the log file.
            device_name: ThingsBoard device name for the records.
            cursor: Previous cursor state, or None for first read.

        Returns:
            Tuple of (new_records, updated_cursor).
        """
        ...

    @abstractmethod
    def matches_file(self, file_path: str) -> bool:
        """Check if this parser handles the given file."""
        ...
