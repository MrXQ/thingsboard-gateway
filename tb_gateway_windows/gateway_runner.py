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
            self._gateway = TBGatewayService(self._config_path)
            # __init__ blocks here until gateway.stopped is True
        except Exception as e:
            log.error("Gateway failed to start: %s", e, exc_info=True)
            self._error = e

    def stop(self):
        """Signal the gateway to shut down."""
        if self._gateway is not None:
            log.info("Stopping gateway...")
            self._gateway.stopped = True
            self._gateway.stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    @property
    def is_alive(self) -> bool:
        """Whether the gateway thread is still running."""
        return self._thread is not None and self._thread.is_alive()
