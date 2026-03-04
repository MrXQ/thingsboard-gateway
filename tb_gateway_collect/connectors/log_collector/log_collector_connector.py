# tb_gateway_collect/connectors/log_collector/log_collector_connector.py
import fnmatch
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from threading import Thread, Lock
from time import sleep, monotonic
from typing import Optional

from thingsboard_gateway.connectors.connector import Connector
from thingsboard_gateway.gateway.constants import CONNECTOR_PARAMETER
from thingsboard_gateway.tb_utility.tb_logger import init_logger

from tb_gateway_collect.connectors.log_collector.log_file_watcher import LogFileWatcher
from tb_gateway_collect.connectors.log_collector.log_uplink_converter import LogUplinkConverter
from tb_gateway_collect.connectors.log_collector.parsers import get_parser
from tb_gateway_collect.connectors.log_collector.state_tracker import StateTracker

log = logging.getLogger(__name__)


@dataclass
class SourceStatus:
    system_type: str
    device_name: str
    connected: bool = False
    last_check: Optional[datetime] = None
    last_data: Optional[datetime] = None
    error: Optional[str] = None


class LogCollectorConnector(Connector, Thread):

    def __init__(self, gateway, config, connector_type):
        super().__init__()
        self.__gateway = gateway
        self.__config = config
        self.__connector_type = connector_type
        self.__name = config.get("name", "Log Collector")
        self.__id = config.get("id")
        self.__poll_interval = config.get("pollIntervalMs", 30000) / 1000.0
        self.__connected = False
        self.__stopped = False
        self.daemon = True
        self.__process_lock = Lock()
        self.__processing: set[str] = set()

        self.__converter = LogUplinkConverter(
            device_type=config.get("defaultDeviceType", "log_source")
        )
        self.__state_tracker = StateTracker(config.get("stateFile", "log_collector_state.json"))
        self.__sources = config.get("sources", [])
        self.__source_statuses: dict[str, SourceStatus] = {}

        for src in self.__sources:
            key = src["deviceName"]
            self.__source_statuses[key] = SourceStatus(
                system_type=src["systemType"],
                device_name=src["deviceName"],
            )

        self.__log = self._create_logger(config)
        poll_delay_ms = config.get("watcherPollDelayMs", 500)
        debounce_ms = config.get("watcherDebounceMs", 500)
        self.__watcher = LogFileWatcher(self._on_file_event,
                                        poll_delay_ms=poll_delay_ms,
                                        debounce_ms=debounce_ms,
                                        logger=self.__log)

    def _create_logger(self, config):
        try:
            logger = init_logger(self.__gateway, self.__name,
                                 config.get('logLevel', 'INFO'),
                                 enable_remote_logging=config.get('enableRemoteLogging', False),
                                 is_connector_logger=True)
            # Validate the logger works (catches MagicMock handler issues in tests)
            logger.debug("Logger initialized")
            return logger
        except Exception:
            return log

    # --- Connector interface ---

    def open(self):
        self.__stopped = False
        self._setup_watches()
        self._snapshot_existing_files()
        self.__watcher.start()
        self.start()
        self.__log.info("Log Collector started with %d sources", len(self.__sources))

    def close(self):
        self.__stopped = True
        self.__connected = False
        try:
            self.__watcher.stop()
        except Exception:
            pass
        self.__state_tracker.flush_if_dirty()
        self.__log.info("Log Collector stopped")

    def get_id(self):
        return self.__id

    def get_name(self):
        return self.__name

    def get_type(self):
        return self.__connector_type

    def get_config(self):
        return self.__config

    def is_connected(self):
        return self.__connected

    def is_stopped(self):
        return self.__stopped

    def on_attributes_update(self, content):
        pass

    def server_side_rpc_handler(self, content):
        pass

    # --- Setup ---

    def _setup_watches(self):
        for src in self.__sources:
            pattern = src.get("filePattern", "*.txt")
            for watch_dir in src.get("watchDirs", []):
                if os.path.isdir(watch_dir):
                    try:
                        self.__watcher.add_watch(watch_dir, pattern)
                    except Exception as e:
                        self.__log.warning("Failed to watch %s: %s", watch_dir, e)

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

    # --- File event handler ---

    def _on_file_event(self, file_path: str):
        """Called by watchfiles when a file is created or modified."""
        for src in self.__sources:
            if self._file_belongs_to_source(file_path, src):
                self._process_file(file_path, src)
                self.__state_tracker.flush_if_dirty()
                return

    def _file_belongs_to_source(self, file_path: str, source: dict) -> bool:
        pattern = source.get("filePattern", "*.txt")
        norm_path = os.path.normcase(os.path.normpath(file_path))
        if not fnmatch.fnmatch(os.path.basename(norm_path), pattern):
            return False
        for watch_dir in source.get("watchDirs", []):
            norm_dir = os.path.normcase(os.path.normpath(watch_dir))
            if norm_path.startswith(norm_dir + os.sep) or norm_path == norm_dir:
                return True
        return False

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

    @staticmethod
    def _file_in_date_range(file_path: str, days: int) -> bool:
        """Check if file path contains a date pattern (yyyyMM/dd) within range."""
        from datetime import timedelta
        now = datetime.now()
        start = now - timedelta(days=days)
        current = start
        while current <= now:
            # Match Java pattern: yyyyMM\dd (e.g., "202603\03" or "202603/03")
            pattern = current.strftime("%Y%m") + os.sep + current.strftime("%d")
            pattern_alt = current.strftime("%Y%m") + "/" + current.strftime("%d")
            pattern_back = current.strftime("%Y%m") + "\\" + current.strftime("%d")
            if pattern in file_path or pattern_alt in file_path or pattern_back in file_path:
                return True
            current += timedelta(days=1)
        return False

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
