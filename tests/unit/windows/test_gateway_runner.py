import unittest
from unittest.mock import patch, MagicMock
from threading import Event


class FakeGatewayService:
    """Lightweight stand-in for TBGatewayService.

    Real TBGatewayService.__init__ blocks forever; this returns immediately.
    """
    def __init__(self, config_path):
        self.config_path = config_path
        self.stopped = False
        self.stop_event = Event()
        self.tb_client = None
        self._event_storage = None


class TestGatewayRunner(unittest.TestCase):
    def test_runner_starts_gateway_in_thread(self):
        from tb_gateway_windows.gateway_runner import GatewayRunner

        with patch('tb_gateway_windows.gateway_runner.TBGatewayService', FakeGatewayService):
            runner = GatewayRunner("fake/config/tb_gateway.json")
            runner.start()
            runner._thread.join(timeout=2)

            self.assertIsNotNone(runner.gateway)
            self.assertIsInstance(runner.gateway, FakeGatewayService)
            self.assertEqual(runner.gateway.config_path, "fake/config/tb_gateway.json")

    def test_runner_gateway_is_none_before_start(self):
        from tb_gateway_windows.gateway_runner import GatewayRunner
        runner = GatewayRunner("fake/config/tb_gateway.json")
        self.assertIsNone(runner.gateway)

    def test_runner_stop_cleans_up_and_resets(self):
        from tb_gateway_windows.gateway_runner import GatewayRunner

        with patch('tb_gateway_windows.gateway_runner.TBGatewayService', FakeGatewayService):
            runner = GatewayRunner("fake/config/tb_gateway.json")
            runner.start()
            runner._thread.join(timeout=2)

            # Attach a mock tb_client to verify disconnect is called
            mock_tb_client = MagicMock()
            runner._gateway.tb_client = mock_tb_client

            runner.stop()

            # MQTT client must be disconnected to prevent client ID collision
            mock_tb_client.disconnect.assert_called_once()
            mock_tb_client.stop.assert_called_once()

            # Gateway ref must be cleared so tray shows correct state
            self.assertIsNone(runner.gateway)
            self.assertIsNone(runner.error)

    def test_runner_stop_disconnects_storage(self):
        from tb_gateway_windows.gateway_runner import GatewayRunner

        with patch('tb_gateway_windows.gateway_runner.TBGatewayService', FakeGatewayService):
            runner = GatewayRunner("fake/config/tb_gateway.json")
            runner.start()
            runner._thread.join(timeout=2)

            mock_storage = MagicMock()
            runner._gateway._event_storage = mock_storage

            runner.stop()

            mock_storage.stop.assert_called_once()

    def test_runner_stop_safe_when_not_started(self):
        from tb_gateway_windows.gateway_runner import GatewayRunner

        runner = GatewayRunner("fake/config/tb_gateway.json")
        # Should not raise
        runner.stop()
        self.assertIsNone(runner.gateway)

    def test_runner_exposes_gateway_before_init_completes(self):
        """Verify the gateway ref is set before __init__ returns."""
        from tb_gateway_windows.gateway_runner import GatewayRunner

        init_called = Event()
        gateway_ref_during_init = [None]

        class SlowGatewayService:
            def __init__(self_, config_path):
                # At this point, runner._gateway should already be set
                gateway_ref_during_init[0] = runner._gateway
                init_called.set()
                self_.stopped = False
                self_.stop_event = Event()

        with patch('tb_gateway_windows.gateway_runner.TBGatewayService', SlowGatewayService):
            runner = GatewayRunner("fake/config/tb_gateway.json")
            runner.start()
            init_called.wait(timeout=2)

            # The gateway reference was available DURING __init__
            self.assertIsNotNone(gateway_ref_during_init[0])
            self.assertIs(gateway_ref_during_init[0], runner.gateway)


if __name__ == '__main__':
    unittest.main()
