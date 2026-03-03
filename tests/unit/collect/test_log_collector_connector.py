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


class TestLogCollectorFlushIntegration:

    def test_state_flushed_after_poll_cycle(self):
        """State tracker should be flushed after each poll cycle, not per-file."""
        d = tempfile.mkdtemp()
        state_dir = tempfile.mkdtemp()
        path = os.path.join(d, "data.txt")
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

        # Spy on flush_if_dirty
        tracker = connector._LogCollectorConnector__state_tracker
        with patch.object(tracker, 'flush_if_dirty', wraps=tracker.flush_if_dirty) as mock_flush:
            connector.open()
            time.sleep(2)
            connector.close()
            # flush_if_dirty should have been called (at least once per poll + once on close)
            assert mock_flush.call_count >= 2

    def test_close_flushes_state(self):
        """close() should flush any pending state to disk."""
        d = tempfile.mkdtemp()
        state_dir = tempfile.mkdtemp()
        state_path = os.path.join(state_dir, "state.json")
        path = os.path.join(d, "data.txt")
        with open(path, "w", newline="") as f:
            f.write("2026-03-03 10:30:45:123   CloseTest:2.0\r\n")

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
        time.sleep(0.5)

        # State should be persisted on disk
        assert os.path.exists(state_path)
        with open(state_path, "r") as f:
            data = json.load(f)
        # The data file's cursor should be saved
        assert any("data.txt" in k for k in data.keys())


class TestLogCollectorPollSkip:

    def test_poll_skips_unchanged_file(self):
        """Second poll should not even invoke the parser for unchanged files."""
        from tb_gateway_collect.connectors.log_collector.parsers import get_parser as real_get_parser

        d = tempfile.mkdtemp()
        state_dir = tempfile.mkdtemp()
        state_path = os.path.join(state_dir, "state.json")
        # Warm restart: pre-populate state so snapshot is skipped
        with open(state_path, "w") as f:
            json.dump({"dummy.txt": {"byte_offset": 0}}, f)

        path = os.path.join(d, "data.txt")
        with open(path, "w", newline="") as f:
            f.write("2026-03-03 10:30:45:123   SkipTest:1.0\r\n")

        gateway = MagicMock()
        config = _make_config(sources=[{
            "systemType": "xjsbb",
            "deviceName": "XJSBB-YB101",
            "deviceType": "log_source",
            "watchDirs": [d],
            "filePattern": "*.txt",
        }], state_dir=state_dir)
        # Use very short poll interval to get multiple polls
        config["pollIntervalMs"] = 300
        connector = LogCollectorConnector(gateway, config, "log_collector")

        with patch(
            'tb_gateway_collect.connectors.log_collector.log_collector_connector.get_parser',
            wraps=real_get_parser,
        ) as mock_gp:
            connector.open()
            time.sleep(2)  # should get ~6 polls
            connector.close()

            # With mtime/size skip, parser should only be invoked once (first poll)
            assert mock_gp.call_count == 1

    def test_poll_processes_modified_file(self):
        """File modified between polls should be re-processed."""
        from tb_gateway_collect.connectors.log_collector.parsers import get_parser as real_get_parser

        d = tempfile.mkdtemp()
        state_dir = tempfile.mkdtemp()
        state_path = os.path.join(state_dir, "state.json")
        # Warm restart: pre-populate state so snapshot is skipped
        with open(state_path, "w") as f:
            json.dump({"dummy.txt": {"byte_offset": 0}}, f)

        path = os.path.join(d, "data.txt")
        with open(path, "w", newline="") as f:
            f.write("2026-03-03 10:30:45:123   ModTest:1.0\r\n")

        gateway = MagicMock()
        config = _make_config(sources=[{
            "systemType": "xjsbb",
            "deviceName": "XJSBB-YB101",
            "deviceType": "log_source",
            "watchDirs": [d],
            "filePattern": "*.txt",
        }], state_dir=state_dir)
        config["pollIntervalMs"] = 500
        connector = LogCollectorConnector(gateway, config, "log_collector")

        with patch(
            'tb_gateway_collect.connectors.log_collector.log_collector_connector.get_parser',
            wraps=real_get_parser,
        ) as mock_gp:
            connector.open()
            time.sleep(1)

            # Append new data between polls
            with open(path, "a", newline="") as f:
                f.write("2026-03-03 10:31:00:000   ModTest:2.0\r\n")

            time.sleep(2)
            connector.close()

            # Parser should be invoked at least twice (first poll + after modification)
            assert mock_gp.call_count >= 2


class TestLogCollectorNetworkDetection:

    def test_unc_path_enables_polling_observer(self):
        """UNC watchDirs should auto-enable PollingObserver."""
        gateway = MagicMock()
        config = _make_config(sources=[{
            "systemType": "xjsbb",
            "deviceName": "XJSBB-YB101",
            "deviceType": "log_source",
            "watchDirs": ["\\\\server\\share\\logs"],
            "filePattern": "*.txt",
        }])
        connector = LogCollectorConnector(gateway, config, "log_collector")
        watcher = connector._LogCollectorConnector__watcher
        from watchdog.observers.polling import PollingObserver as WDP
        assert isinstance(watcher._observer, WDP)

    def test_local_path_uses_native_observer(self):
        """Local watchDirs should use native Observer."""
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
        watcher = connector._LogCollectorConnector__watcher
        from watchdog.observers.polling import PollingObserver as WDP
        assert not isinstance(watcher._observer, WDP)
        os.rmdir(d)

    def test_config_override_polling_interval(self):
        """watcherPollingIntervalSec config should override auto-detection."""
        d = tempfile.mkdtemp()
        gateway = MagicMock()
        config = _make_config(sources=[{
            "systemType": "xjsbb",
            "deviceName": "XJSBB-YB101",
            "deviceType": "log_source",
            "watchDirs": [d],
            "filePattern": "*.txt",
        }])
        config["watcherPollingIntervalSec"] = 10  # force polling even for local
        connector = LogCollectorConnector(gateway, config, "log_collector")
        watcher = connector._LogCollectorConnector__watcher
        from watchdog.observers.polling import PollingObserver as WDP
        assert isinstance(watcher._observer, WDP)
        os.rmdir(d)
