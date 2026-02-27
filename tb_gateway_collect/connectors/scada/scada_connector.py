import logging
from threading import Thread
from time import sleep, monotonic

from thingsboard_gateway.connectors.connector import Connector
from thingsboard_gateway.gateway.constants import CONNECTOR_PARAMETER
from thingsboard_gateway.tb_utility.tb_logger import init_logger

from tb_gateway_collect.common.plc_data_types import PlcParam
from tb_gateway_collect.connectors.scada.scada_fc7_bridge import FC7Bridge
from tb_gateway_collect.connectors.scada.scada_uplink_converter import ScadaUplinkConverter

log = logging.getLogger(__name__)


class ScadaConnector(Connector, Thread):

    def __init__(self, gateway, config, connector_type):
        super().__init__()
        self.__gateway = gateway
        self.__config = config
        self.__connector_type = connector_type
        self.__name = config.get("name", "SCADA Connector")
        self.__id = config.get("id")
        self.__poll_interval = config.get("pollIntervalMs", 3000) / 1000.0
        self.__connected = False
        self.__stopped = False
        self.daemon = True
        self.__converter = ScadaUplinkConverter()
        self.__bridge = FC7Bridge(jar_path=config.get("jarPath", "FC7_DBcomm_Java.jar"))
        self.__devices = []
        self._parse_devices(config.get("devices", []))

        self.__log = self._create_logger(config)

    def _create_logger(self, config):
        try:
            logger = init_logger(self.__gateway, self.__name,
                                 config.get('logLevel', 'INFO'),
                                 enable_remote_logging=config.get('enableRemoteLogging', False),
                                 is_connector_logger=True)
            # Verify logger works (catches broken handlers from mocked gateways)
            logger.debug("Logger initialized")
            return logger
        except Exception:
            return log

    def _parse_devices(self, devices_config):
        self.__devices = []
        for dev_cfg in devices_config:
            params = [PlcParam.from_dict(p) for p in dev_cfg.get("parameters", [])]
            self.__devices.append({
                "config": dev_cfg,
                "params": params,
                "session_id": None,
            })

    # --- Connector interface ---

    def open(self):
        self.__stopped = False
        self.start()
        self.__log.info("SCADA Connector started")

    def close(self):
        self.__stopped = True
        self.__connected = False
        for dev in self.__devices:
            if dev.get("session_id") is not None:
                try:
                    self.__bridge.disconnect(dev["session_id"])
                except Exception:
                    pass
                dev["session_id"] = None
        self.__log.info("SCADA Connector stopped")

    def get_id(self):
        return self.__id

    def get_name(self):
        return self.__name

    def get_type(self):
        return self.__connector_type

    def get_config(self):
        return self.__config

    def is_connected(self):
        return self.__connected

    def is_stopped(self):
        return self.__stopped

    def on_attributes_update(self, content):
        device_name = content.get("device")
        data = content.get("data", {})

        if "plcParams" in data:
            for dev in self.__devices:
                if dev["config"]["deviceName"] == device_name:
                    dev["params"] = [PlcParam.from_dict(p) for p in data["plcParams"]]
                    self.__log.info("Updated PLC params for %s: %d params",
                                    device_name, len(dev["params"]))
                    break

    def server_side_rpc_handler(self, content):
        device_name = content.get("device")
        rpc_data = content.get("data", {})
        method = rpc_data.get("method")
        params = rpc_data.get("params", {})

        if method == "plc_write":
            self._handle_plc_write(device_name, params)

    # --- Thread run loop ---

    def run(self):
        while not self.__stopped:
            start = monotonic()

            for dev in self.__devices:
                if self.__stopped:
                    break
                self._poll_device(dev["config"], dev)

            if not self.__stopped:
                self.__connected = True

            elapsed = monotonic() - start
            remaining = self.__poll_interval - elapsed
            if remaining > 0 and not self.__stopped:
                sleep(remaining)

    def _poll_device(self, dev_config, dev_state=None):
        if dev_state is None:
            for dev in self.__devices:
                if dev["config"] is dev_config:
                    dev_state = dev
                    break
            if dev_state is None:
                dev_state = {
                    "config": dev_config,
                    "params": [PlcParam.from_dict(p) for p in dev_config.get("parameters", [])],
                    "session_id": None,
                }

        host = dev_config["address"]
        port = dev_config["port"]
        device_name = dev_config["deviceName"]
        device_type = dev_config.get("deviceType", "plc")
        params = dev_state["params"]

        try:
            session_id = dev_state.get("session_id")
            if session_id is None or not self.__bridge.is_connected(session_id):
                session_id = self.__bridge.connect(host, port)
                dev_state["session_id"] = session_id
        except Exception as e:
            self.__log.warning("Failed to connect to SCADA %s:%d - %s", host, port, e)
            return

        try:
            addresses = [p.address for p in params]
            raw_data = self.__bridge.get_data(session_id, addresses)
        except Exception as e:
            self.__log.warning("Failed to read from SCADA %s - %s", device_name, e)
            dev_state["session_id"] = None
            return

        if raw_data:
            config = {"deviceName": device_name, "deviceType": device_type}
            converted = self.__converter.convert(config, raw_data, params)

            if converted.telemetry:
                self.__gateway.add_device(device_name, {CONNECTOR_PARAMETER: self},
                                          device_type=device_type)
                self.__gateway.send_to_storage(self.get_name(), self.get_id(), converted)

    def _handle_plc_write(self, device_name, params):
        address = params.get("address")
        value = params.get("value")

        for dev in self.__devices:
            if dev["config"]["deviceName"] == device_name:
                session_id = dev.get("session_id")
                if session_id is None:
                    self.__log.error("No SCADA session for %s, cannot write", device_name)
                    return
                try:
                    self.__bridge.set_data(session_id, address, int(value))
                    self.__log.info("SCADA write to %s/%s = %s", device_name, address, value)
                except Exception as e:
                    self.__log.error("SCADA write failed for %s/%s: %s", device_name, address, e)
                break
