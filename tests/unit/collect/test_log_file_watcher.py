# tests/unit/collect/test_log_file_watcher.py
import os
import tempfile
import time
from unittest.mock import MagicMock, patch

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
            assert d in watcher.watched_dirs
        finally:
            os.rmdir(d)

    def test_start_stop(self):
        callback = MagicMock()
        watcher = LogFileWatcher(callback, poll_delay_ms=100, debounce_ms=100)
        d = tempfile.mkdtemp()
        try:
            watcher.add_watch(d, "*.txt")
            watcher.start()
            time.sleep(0.5)
            assert watcher.is_running()
            watcher.stop()
            assert not watcher.is_running()
        finally:
            if os.path.exists(d):
                os.rmdir(d)

    def test_detects_new_file(self):
        callback = MagicMock()
        watcher = LogFileWatcher(callback, poll_delay_ms=100, debounce_ms=100)
        d = tempfile.mkdtemp()
        try:
            watcher.add_watch(d, "*.txt")
            watcher.start()
            time.sleep(0.5)

            path = os.path.join(d, "test.txt")
            with open(path, "w") as f:
                f.write("data\n")

            time.sleep(2)
            watcher.stop()

            assert callback.call_count >= 1
            # Verify the path ends with our filename
            paths_called = [call[0][0] for call in callback.call_args_list]
            assert any(p.endswith("test.txt") for p in paths_called)
        finally:
            if os.path.exists(os.path.join(d, "test.txt")):
                os.unlink(os.path.join(d, "test.txt"))
            if os.path.exists(d):
                os.rmdir(d)

    def test_detects_modified_file(self):
        callback = MagicMock()
        d = tempfile.mkdtemp()
        path = os.path.join(d, "existing.txt")
        with open(path, "w") as f:
            f.write("initial\n")

        watcher = LogFileWatcher(callback, poll_delay_ms=100, debounce_ms=100)
        try:
            watcher.add_watch(d, "*.txt")
            watcher.start()
            time.sleep(1)  # allow watchfiles to establish baseline snapshot

            # Modify the file
            with open(path, "a") as f:
                f.write("appended\n")

            time.sleep(2)
            watcher.stop()

            assert callback.call_count >= 1
        finally:
            if os.path.exists(path):
                os.unlink(path)
            if os.path.exists(d):
                os.rmdir(d)

    def test_ignores_non_matching_files(self):
        callback = MagicMock()
        watcher = LogFileWatcher(callback, poll_delay_ms=100, debounce_ms=100)
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

    def test_stop_without_start(self):
        """stop() should not raise if watcher was never started."""
        callback = MagicMock()
        watcher = LogFileWatcher(callback)
        watcher.stop()  # should not raise


class TestLogFileWatcherResilience:

    def test_auto_restart_after_error(self):
        """Watcher thread should stay alive and retry after watch() raises."""
        callback = MagicMock()
        watcher = LogFileWatcher(callback, poll_delay_ms=100, debounce_ms=100)
        d = tempfile.mkdtemp()
        watcher.add_watch(d, "*.txt")

        error_count = {"n": 0}

        def always_fail(*args, **kwargs):
            error_count["n"] += 1
            raise OSError("simulated network error")

        try:
            with patch(
                'tb_gateway_collect.connectors.log_collector.log_file_watcher.watch',
                side_effect=always_fail,
            ):
                watcher.start()
                time.sleep(5)  # allow multiple restart attempts (3s backoff)
                assert watcher.is_running(), "Thread should stay alive despite errors"
                assert error_count["n"] >= 2, "Should have retried at least once"
                watcher.stop()

            assert not watcher.is_running()
        finally:
            if os.path.exists(d):
                os.rmdir(d)

    def test_stop_interrupts_backoff(self):
        """stop() should interrupt the 3s restart backoff immediately."""
        callback = MagicMock()
        watcher = LogFileWatcher(callback, poll_delay_ms=100, debounce_ms=100)
        d = tempfile.mkdtemp()
        watcher.add_watch(d, "*.txt")

        def always_fail(*args, **kwargs):
            raise OSError("simulated error")

        try:
            with patch(
                'tb_gateway_collect.connectors.log_collector.log_file_watcher.watch',
                side_effect=always_fail,
            ):
                watcher.start()
                time.sleep(0.5)  # let it hit the error and enter backoff
                start = time.monotonic()
                watcher.stop()
                elapsed = time.monotonic() - start
                # stop() should return quickly, not wait for 3s backoff
                assert elapsed < 2, f"stop() took {elapsed:.1f}s, should be < 2s"
        finally:
            if os.path.exists(d):
                os.rmdir(d)
