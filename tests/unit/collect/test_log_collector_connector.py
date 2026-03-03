# tests/unit/collect/test_log_collector_connector.py
import json
import os
import tempfile
import time
from unittest.mock import MagicMock, patch

from tb_gateway_collect.connectors.log_collector.log_collector_connector import LogCollectorConnector


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


class TestLogCollectorConnectorLifecycle:

    def test_constructor(self):
        gateway = MagicMock()
        config = _make_config()
        connector = LogCollectorConnector(gateway, config, "log_collector")
        assert connector.get_name() == "Log Collector"
        assert connector.get_id() == "test-log-collector-001"
        assert connector.is_stopped() is False
        assert connector.is_connected() is False

    def test_open_and_close(self):
        gateway = MagicMock()
        config = _make_config()
        connector = LogCollectorConnector(gateway, config, "log_collector")
        connector.open()
        time.sleep(0.5)
        assert connector.is_stopped() is False
        connector.close()
        time.sleep(0.5)
        assert connector.is_stopped() is True

    def test_get_type_and_config(self):
        gateway = MagicMock()
        config = _make_config()
        connector = LogCollectorConnector(gateway, config, "log_collector")
        assert connector.get_type() == "log_collector"
        assert connector.get_config() is config


class TestLogCollectorConnectorSources:

    def test_source_health_connected(self):
        d = tempfile.mkdtemp()
        gateway = MagicMock()
        config = _make_config(sources=[{
            "systemType": "ab",
            "deviceName": "AB-YB101",
            "deviceType": "log_source",
            "watchDirs": [d],
            "filePattern": "*.txt",
        }])
        connector = LogCollectorConnector(gateway, config, "log_collector")
        connector.open()
        time.sleep(1)
        assert connector.is_connected() is True
        connector.close()
        os.rmdir(d)

    def test_source_health_disconnected(self):
        gateway = MagicMock()
        config = _make_config(sources=[{
            "systemType": "ab",
            "deviceName": "AB-YB101",
            "deviceType": "log_source",
            "watchDirs": ["/nonexistent/path/that/does/not/exist"],
            "filePattern": "*.txt",
        }])
        connector = LogCollectorConnector(gateway, config, "log_collector")
        connector.open()
        time.sleep(1)
        assert connector.is_connected() is False
        connector.close()

    def test_file_event_triggers_parse_and_send(self):
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
        connector.open()
        time.sleep(1)

        # Write a valid XJSBB log file
        path = os.path.join(d, "test.txt")
        with open(path, "w", newline="") as f:
            f.write("2026-03-03 10:30:45:123   Temp:25.5\r\n")

        time.sleep(3)
        connector.close()

        assert gateway.send_to_storage.call_count >= 1
        os.unlink(path)
        os.rmdir(d)


class TestLogCollectorColdStart:

    def test_cold_start_snapshots_existing_files(self):
        """Cold start (empty state): existing files are NOT processed."""
        d = tempfile.mkdtemp()
        path = os.path.join(d, "existing.txt")
        with open(path, "w", newline="") as f:
            f.write("2026-03-03 10:30:45:123   Temp:25.5\r\n")

        gateway = MagicMock()
        config = _make_config(sources=[{
            "systemType": "xjsbb",
            "deviceName": "XJSBB-YB101",
            "deviceType": "log_source",
            "watchDirs": [d],
            "filePattern": "*.txt",
        }])
        connector = LogCollectorConnector(gateway, config, "log_collector")
        connector.open()
        time.sleep(2)
        connector.close()

        assert gateway.send_to_storage.call_count == 0

    def test_cold_start_new_file_after_snapshot_is_processed(self):
        """Cold start: files created AFTER open() are processed normally."""
        d = tempfile.mkdtemp()
        # Pre-existing file (will be snapshotted)
        existing = os.path.join(d, "old.txt")
        with open(existing, "w", newline="") as f:
            f.write("2026-03-03 10:00:00:000   Old:1.0\r\n")

        gateway = MagicMock()
        config = _make_config(sources=[{
            "systemType": "xjsbb",
            "deviceName": "XJSBB-YB101",
            "deviceType": "log_source",
            "watchDirs": [d],
            "filePattern": "*.txt",
        }])
        connector = LogCollectorConnector(gateway, config, "log_collector")
        connector.open()
        time.sleep(1)

        # Write new file after snapshot
        new_path = os.path.join(d, "new.txt")
        with open(new_path, "w", newline="") as f:
            f.write("2026-03-03 11:00:00:000   New:2.0\r\n")

        time.sleep(3)
        connector.close()

        assert gateway.send_to_storage.call_count >= 1

    def test_warm_restart_does_not_snapshot(self):
        """Warm restart (state has entries): new files ARE processed from byte 0."""
        d = tempfile.mkdtemp()
        state_dir = tempfile.mkdtemp()
        state_path = os.path.join(state_dir, "state.json")

        # Pre-populate state file with one entry (makes it non-empty)
        with open(state_path, "w") as f:
            json.dump({"some_old_file.txt": {"byte_offset": 100}}, f)

        # Create a file that should be processed (warm restart, no snapshot)
        # Use unique variable name to avoid parser change-detection filtering
        path = os.path.join(d, "data.txt")
        with open(path, "w", newline="") as f:
            f.write("2026-03-03 10:30:45:123   WarmTemp:99.9\r\n")

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

        assert gateway.send_to_storage.call_count >= 1
