# tests/unit/collect/test_state_tracker.py
import json
import os
import tempfile
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
