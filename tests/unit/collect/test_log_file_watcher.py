# tests/unit/collect/test_log_file_watcher.py
import os
import tempfile
import time
from unittest.mock import MagicMock

from tb_gateway_collect.connectors.log_collector.log_file_watcher import LogFileWatcher


class TestLogFileWatcher:

    def test_create_watcher(self):
        callback = MagicMock()
        watcher = LogFileWatcher(callback)
        assert watcher is not None

    def test_add_watch_dir(self):
        callback = MagicMock()
        watcher = LogFileWatcher(callback)
        d = tempfile.mkdtemp()
        try:
            watcher.add_watch(d, "*.txt")
            assert len(watcher.watched_dirs) == 1
        finally:
            watcher.stop()
            os.rmdir(d)

    def test_start_stop(self):
        callback = MagicMock()
        watcher = LogFileWatcher(callback)
        d = tempfile.mkdtemp()
        try:
            watcher.add_watch(d, "*.txt")
            watcher.start()
            assert watcher.is_running()
            watcher.stop()
            assert not watcher.is_running()
        finally:
            if os.path.exists(d):
                os.rmdir(d)

    def test_detects_new_file(self):
        callback = MagicMock()
        watcher = LogFileWatcher(callback)
        d = tempfile.mkdtemp()
        try:
            watcher.add_watch(d, "*.txt")
            watcher.start()
            time.sleep(0.5)

            path = os.path.join(d, "test.txt")
            with open(path, "w") as f:
                f.write("data\n")

            # Give watchdog time to detect
            time.sleep(2)
            watcher.stop()

            assert callback.call_count >= 1
            args = callback.call_args[0]
            assert args[0].endswith("test.txt")
        finally:
            if os.path.exists(os.path.join(d, "test.txt")):
                os.unlink(os.path.join(d, "test.txt"))
            if os.path.exists(d):
                os.rmdir(d)

    def test_ignores_non_matching_files(self):
        callback = MagicMock()
        watcher = LogFileWatcher(callback)
        d = tempfile.mkdtemp()
        try:
            watcher.add_watch(d, "*.txt")
            watcher.start()
            time.sleep(0.5)

            path = os.path.join(d, "test.jpg")
            with open(path, "w") as f:
                f.write("data\n")

            time.sleep(2)
            watcher.stop()

            assert callback.call_count == 0
        finally:
            if os.path.exists(os.path.join(d, "test.jpg")):
                os.unlink(os.path.join(d, "test.jpg"))
            if os.path.exists(d):
                os.rmdir(d)


class TestLogFileWatcherPolling:

    def test_polling_observer_when_interval_set(self):
        from watchdog.observers.polling import PollingObserver as WatchdogPollingObserver
        callback = MagicMock()
        watcher = LogFileWatcher(callback, polling_interval=5)
        assert isinstance(watcher._observer, WatchdogPollingObserver)

    def test_native_observer_when_no_polling(self):
        from watchdog.observers.polling import PollingObserver as WatchdogPollingObserver
        callback = MagicMock()
        watcher = LogFileWatcher(callback, polling_interval=0)
        assert not isinstance(watcher._observer, WatchdogPollingObserver)

    def test_default_is_native_observer(self):
        from watchdog.observers.polling import PollingObserver as WatchdogPollingObserver
        callback = MagicMock()
        watcher = LogFileWatcher(callback)
        assert not isinstance(watcher._observer, WatchdogPollingObserver)
