# tests/unit/collect/test_state_tracker.py
import json
import os
import tempfile
import threading
from tb_gateway_collect.connectors.log_collector.state_tracker import StateTracker


class TestStateTracker:

    def test_get_cursor_returns_none_for_unknown_file(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            tracker = StateTracker(path)
            assert tracker.get_cursor("unknown.txt") is None
        finally:
            os.unlink(path)

    def test_save_and_get_cursor(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            tracker = StateTracker(path)
            tracker.save_cursor("logs/data.txt", {"byte_offset": 1234})
            assert tracker.get_cursor("logs/data.txt") == {"byte_offset": 1234}
        finally:
            os.unlink(path)

    def test_persistence_across_instances(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            tracker1 = StateTracker(path)
            tracker1.save_cursor("file_a.txt", {"byte_offset": 500})
            tracker1.flush_if_dirty()

            tracker2 = StateTracker(path)
            assert tracker2.get_cursor("file_a.txt") == {"byte_offset": 500}
        finally:
            os.unlink(path)

    def test_update_existing_cursor(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            tracker = StateTracker(path)
            tracker.save_cursor("file.txt", {"byte_offset": 100})
            tracker.save_cursor("file.txt", {"byte_offset": 200})
            assert tracker.get_cursor("file.txt") == {"byte_offset": 200}
        finally:
            os.unlink(path)

    def test_multiple_files(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            tracker = StateTracker(path)
            tracker.save_cursor("a.txt", {"byte_offset": 10})
            tracker.save_cursor("b.txt", {"byte_offset": 20})
            assert tracker.get_cursor("a.txt") == {"byte_offset": 10}
            assert tracker.get_cursor("b.txt") == {"byte_offset": 20}
        finally:
            os.unlink(path)

    def test_missing_state_file_creates_new(self):
        path = os.path.join(tempfile.gettempdir(), "nonexistent_state.json")
        if os.path.exists(path):
            os.unlink(path)
        try:
            tracker = StateTracker(path)
            assert tracker.get_cursor("any.txt") is None
            tracker.save_cursor("any.txt", {"byte_offset": 0})
            tracker.flush_if_dirty()
            assert os.path.exists(path)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_corrupted_state_file_resets(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            f.write("not valid json {{{")
            path = f.name
        try:
            tracker = StateTracker(path)
            assert tracker.get_cursor("any.txt") is None
        finally:
            os.unlink(path)

    def test_is_empty_true_when_no_entries(self):
        path = os.path.join(tempfile.gettempdir(), "empty_state.json")
        if os.path.exists(path):
            os.unlink(path)
        try:
            tracker = StateTracker(path)
            assert tracker.is_empty() is True
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_is_empty_false_after_save(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            tracker = StateTracker(path)
            tracker.save_cursor("file.txt", {"byte_offset": 100})
            assert tracker.is_empty() is False
        finally:
            os.unlink(path)


class TestStateTrackerDeferredFlush:

    def test_deferred_flush_does_not_write_immediately(self):
        """save_cursor should NOT flush to disk immediately."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            tracker = StateTracker(path)
            tracker.save_cursor("file.txt", {"byte_offset": 100})
            # File should still be empty or unchanged (not flushed yet)
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            # Empty file or empty JSON — save_cursor did not flush
            assert content.strip() in ("", "{}")
        finally:
            os.unlink(path)

    def test_flush_if_dirty_writes_to_disk(self):
        """flush_if_dirty should persist deferred state."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            tracker = StateTracker(path)
            tracker.save_cursor("file.txt", {"byte_offset": 500})
            tracker.flush_if_dirty()
            # Reload from disk
            tracker2 = StateTracker(path)
            assert tracker2.get_cursor("file.txt") == {"byte_offset": 500}
        finally:
            os.unlink(path)

    def test_flush_if_dirty_noop_when_clean(self):
        """flush_if_dirty does nothing when no saves have occurred."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            tracker = StateTracker(path)
            tracker.flush_if_dirty()  # should not raise or create file content
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            assert content.strip() in ("", "{}")
        finally:
            os.unlink(path)

    def test_atomic_write_no_zero_byte_file(self):
        """After flush, state file should contain valid JSON (never 0 bytes)."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            tracker = StateTracker(path)
            for i in range(50):
                tracker.save_cursor(f"file_{i}.txt", {"byte_offset": i * 100})
            tracker.flush_if_dirty()
            size = os.path.getsize(path)
            assert size > 0, "State file should not be 0 bytes"
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            assert len(data) == 50
            # .tmp file should not remain
            assert not os.path.exists(path + ".tmp")
        finally:
            os.unlink(path)

    def test_concurrent_save_cursor(self):
        """Multiple threads saving cursors should not corrupt state."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            tracker = StateTracker(path)
            errors = []

            def save_many(thread_id):
                try:
                    for i in range(20):
                        tracker.save_cursor(f"t{thread_id}_f{i}.txt", {"byte_offset": i})
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=save_many, args=(t,)) for t in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert not errors, f"Errors during concurrent saves: {errors}"
            tracker.flush_if_dirty()

            # All 100 entries should be present
            tracker2 = StateTracker(path)
            for t in range(5):
                for i in range(20):
                    assert tracker2.get_cursor(f"t{t}_f{i}.txt") == {"byte_offset": i}
        finally:
            os.unlink(path)
