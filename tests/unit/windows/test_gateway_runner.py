import unittest
from unittest.mock import patch, MagicMock
from threading import Event


class TestGatewayRunner(unittest.TestCase):
    def test_runner_starts_gateway_in_thread(self):
        from tb_gateway_windows.gateway_runner import GatewayRunner

        # Mock TBGatewayService so it doesn't actually start
        with patch('tb_gateway_windows.gateway_runner.TBGatewayService') as MockGW:
            mock_instance = MagicMock()
            mock_instance.stopped = False
            mock_instance.stop_event = Event()
            MockGW.return_value = mock_instance

            runner = GatewayRunner("fake/config/tb_gateway.json")
            runner.start()
            runner._thread.join(timeout=2)

            MockGW.assert_called_once_with("fake/config/tb_gateway.json")
            self.assertEqual(runner.gateway, mock_instance)

    def test_runner_gateway_is_none_before_start(self):
        from tb_gateway_windows.gateway_runner import GatewayRunner
        runner = GatewayRunner("fake/config/tb_gateway.json")
        self.assertIsNone(runner.gateway)

    def test_runner_stop_sets_stopped(self):
        from tb_gateway_windows.gateway_runner import GatewayRunner

        with patch('tb_gateway_windows.gateway_runner.TBGatewayService') as MockGW:
            mock_instance = MagicMock()
            mock_instance.stopped = False
            mock_stop_event = MagicMock()
            mock_instance.stop_event = mock_stop_event
            MockGW.return_value = mock_instance

            runner = GatewayRunner("fake/config/tb_gateway.json")
            runner.start()
            runner._thread.join(timeout=2)
            runner.stop()

            self.assertTrue(mock_instance.stopped)
            mock_stop_event.set.assert_called()


if __name__ == '__main__':
    unittest.main()
