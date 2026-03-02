"""Manages TBGatewayService lifecycle in a background thread."""

from __future__ import annotations

import logging
import os
from threading import Thread
from typing import Optional

from thingsboard_gateway.gateway.tb_gateway_service import TBGatewayService

log = logging.getLogger("windows_wrapper")


class GatewayRunner:
    """Runs TBGatewayService in a daemon thread.

    The gateway's __init__() blocks forever (it has an internal event loop),
    so we run it in a background thread and expose the instance for monitoring.
    """

    def __init__(self, config_path: str):
        self._config_path = config_path
        self._gateway: Optional[TBGatewayService] = None
        self._thread: Optional[Thread] = None
        self._error: Optional[Exception] = None

    @property
    def gateway(self) -> Optional[TBGatewayService]:
        """The live gateway instance, or None if not yet initialized."""
        return self._gateway

    @property
    def error(self) -> Optional[Exception]:
        """Startup error if the gateway failed to initialize."""
        return self._error

    def start(self):
        """Start the gateway in a background daemon thread."""
        self._thread = Thread(
            target=self._run,
            name="TBGatewayService",
            daemon=True,
        )
        self._thread.start()

    def _run(self):
        """Thread target — instantiates TBGatewayService (blocks until stopped)."""
        try:
            log.info("Starting TBGatewayService with config: %s",
                     self._config_path)
            # Split __new__ and __init__ so the tray can poll the instance
            # while __init__ is still running (it blocks forever in an
            # internal event loop).
            gateway = object.__new__(TBGatewayService)
            self._gateway = gateway
            TBGatewayService.__init__(gateway, self._config_path)
        except Exception as e:
            log.error("Gateway failed to start: %s", e, exc_info=True)
            self._error = e

    def stop(self):
        """Signal the gateway to shut down and clean up resources.

        Must fully disconnect the MQTT client before returning, otherwise
        a subsequent start() will create a second client with the same ID
        and the broker will bounce both connections indefinitely.
        """
        if self._gateway is not None:
            log.info("Stopping gateway...")
            self._gateway.stopped = True
            self._gateway.stop_event.set()

            # TBGatewayService.__stop_gateway() is private (name-mangled),
            # so we call the accessible cleanup methods directly.
            try:
                if hasattr(self._gateway, '_event_storage') and self._gateway._event_storage is not None:
                    self._gateway._event_storage.stop()
                if hasattr(self._gateway, 'tb_client') and self._gateway.tb_client is not None:
                    self._gateway.tb_client.disconnect()
                    self._gateway.tb_client.stop()
            except Exception as e:
                log.warning("Error during gateway cleanup: %s", e)

        if self._thread is not None:
            self._thread.join(timeout=10)
        self._gateway = None
        self._error = None

    @property
    def is_alive(self) -> bool:
        """Whether the gateway thread is still running."""
        return self._thread is not None and self._thread.is_alive()
