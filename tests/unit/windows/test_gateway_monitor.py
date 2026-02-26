import unittest
from unittest.mock import MagicMock, PropertyMock


class TestGatewayState(unittest.TestCase):
    """Test the GatewayState dataclass."""

    def test_state_from_gateway_connected(self):
        from tb_gateway_windows.gateway_monitor import GatewayState
        gw = self._make_mock_gateway(tb_connected=True, devices=5,
                                      active=3, inactive=0, total=3,
                                      storage=100)
        state = GatewayState.from_gateway(gw)
        self.assertTrue(state.tb_connected)
        self.assertEqual(state.device_count, 5)
        self.assertEqual(state.active_connectors, 3)
        self.assertEqual(state.inactive_connectors, 0)
        self.assertEqual(state.total_connectors, 3)
        self.assertEqual(state.storage_events, 100)
        self.assertEqual(state.status, "connected")

    def test_state_status_disconnected(self):
        from tb_gateway_windows.gateway_monitor import GatewayState
        gw = self._make_mock_gateway(tb_connected=False, devices=0,
                                      active=0, inactive=2, total=2,
                                      storage=0)
        state = GatewayState.from_gateway(gw)
        self.assertEqual(state.status, "disconnected")

    def test_state_status_connector_down(self):
        from tb_gateway_windows.gateway_monitor import GatewayState
        gw = self._make_mock_gateway(tb_connected=True, devices=3,
                                      active=2, inactive=1, total=3,
                                      storage=50)
        state = GatewayState.from_gateway(gw)
        self.assertEqual(state.status, "connector_down")

    def test_state_none_when_gateway_not_ready(self):
        from tb_gateway_windows.gateway_monitor import GatewayState
        state = GatewayState.from_gateway(None)
        self.assertIsNone(state)

    def test_state_none_when_tb_client_not_ready(self):
        from tb_gateway_windows.gateway_monitor import GatewayState
        gw = MagicMock()
        gw.tb_client = None
        state = GatewayState.from_gateway(gw)
        self.assertIsNone(state)

    def _make_mock_gateway(self, tb_connected, devices, active, inactive,
                           total, storage):
        gw = MagicMock()
        gw.tb_client.is_connected.return_value = tb_connected
        type(gw).connected_devices = PropertyMock(return_value=devices)
        type(gw).active_connectors = PropertyMock(return_value=active)
        type(gw).inactive_connectors = PropertyMock(return_value=inactive)
        type(gw).total_connectors = PropertyMock(return_value=total)
        gw._event_storage.len.return_value = storage
        return gw


class TestTransitionDetection(unittest.TestCase):
    """Test that state transitions produce the correct notifications."""

    def test_no_transitions_on_first_poll(self):
        from tb_gateway_windows.gateway_monitor import detect_transitions
        transitions = detect_transitions(None, self._make_state(True, 3, 0))
        self.assertEqual(transitions, [])

    def test_detect_tb_disconnect(self):
        from tb_gateway_windows.gateway_monitor import detect_transitions
        old = self._make_state(tb_connected=True, active=2, inactive=0)
        new = self._make_state(tb_connected=False, active=2, inactive=0)
        transitions = detect_transitions(old, new)
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0]["event"], "tb_disconnected")

    def test_detect_tb_reconnect(self):
        from tb_gateway_windows.gateway_monitor import detect_transitions
        old = self._make_state(tb_connected=False, active=0, inactive=2)
        new = self._make_state(tb_connected=True, active=2, inactive=0)
        transitions = detect_transitions(old, new)
        events = [t["event"] for t in transitions]
        self.assertIn("tb_reconnected", events)

    def test_detect_connector_went_down(self):
        from tb_gateway_windows.gateway_monitor import detect_transitions
        old = self._make_state(tb_connected=True, active=3, inactive=0)
        new = self._make_state(tb_connected=True, active=2, inactive=1)
        transitions = detect_transitions(old, new)
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0]["event"], "connector_down")

    def test_detect_connector_recovered(self):
        from tb_gateway_windows.gateway_monitor import detect_transitions
        old = self._make_state(tb_connected=True, active=2, inactive=1)
        new = self._make_state(tb_connected=True, active=3, inactive=0)
        transitions = detect_transitions(old, new)
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0]["event"], "connector_recovered")

    def test_no_transition_when_unchanged(self):
        from tb_gateway_windows.gateway_monitor import detect_transitions
        old = self._make_state(tb_connected=True, active=3, inactive=0)
        new = self._make_state(tb_connected=True, active=3, inactive=0)
        transitions = detect_transitions(old, new)
        self.assertEqual(transitions, [])

    def _make_state(self, tb_connected, active, inactive):
        from tb_gateway_windows.gateway_monitor import GatewayState
        return GatewayState(
            tb_connected=tb_connected,
            device_count=5,
            active_connectors=active,
            inactive_connectors=inactive,
            total_connectors=active + inactive,
            storage_events=0,
        )


if __name__ == '__main__':
    unittest.main()
