import logging
from threading import Thread
from time import sleep, monotonic

from thingsboard_gateway.connectors.connector import Connector
from thingsboard_gateway.gateway.constants import CONNECTOR_PARAMETER
from thingsboard_gateway.tb_utility.tb_logger import init_logger

from tb_gateway_collect.common.plc_data_types import PlcParam, KVTypeFormat
from tb_gateway_collect.connectors.kv8000.kv8000_protocol import KV8000Client
from tb_gateway_collect.common.change_filter import ChangeFilter
from tb_gateway_collect.connectors.kv8000.kv8000_uplink_converter import KV8000UplinkConverter

log = logging.getLogger(__name__)


class KV8000Connector(Connector, Thread):

    def __init__(self, gateway, config, connector_type):
        super().__init__()
        self.__gateway = gateway
        self.__config = config
        self.__connector_type = connector_type
        self.__name = config.get("name", "KV8000 Connector")
        self.__id = config.get("id")
        self.__poll_interval = config.get("pollIntervalMs", 3000) / 1000.0
        self.__connected = False
        self.__stopped = False
        self.daemon = True
        self.__converter = KV8000UplinkConverter()
        self.__change_filter = ChangeFilter(
            enabled=config.get("uploadOnChangeOnly", True)
        )
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
            })

    # --- Connector interface ---

    def open(self):
        self.__stopped = False
        self.start()
        self.__log.info("KV8000 Connector started")

    def close(self):
        self.__stopped = True
        self.__connected = False
        self.__log.info("KV8000 Connector stopped")

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
                self._poll_device(dev["config"], dev.get("params"))

            if not self.__stopped:
                self.__connected = True

            elapsed = monotonic() - start
            remaining = self.__poll_interval - elapsed
            if remaining > 0 and not self.__stopped:
                sleep(remaining)

    def _poll_device(self, dev_config, params=None):
        if isinstance(dev_config, dict) and params is None:
            for dev in self.__devices:
                if dev["config"] is dev_config:
                    params = dev["params"]
                    break
            if params is None:
                params = [PlcParam.from_dict(p) for p in dev_config.get("parameters", [])]

        host = dev_config["address"]
        port = dev_config["port"]
        device_name = dev_config["deviceName"]
        device_type = dev_config.get("deviceType", "plc")

        try:
            client = KV8000Client(host, port)
        except Exception as e:
            self.__log.warning("Failed to connect to %s:%d - %s", host, port, e)
            return

        telemetry_data = {}
        try:
            for param in params:
                try:
                    value = client.read_param(param)
                    telemetry_data[param.name] = value
                except Exception as e:
                    self.__log.warning("Failed to read param %s from %s - %s",
                                       param.name, device_name, e)
        finally:
            client.close()

        if telemetry_data:
            config = {"deviceName": device_name, "deviceType": device_type}
            converted = self.__converter.convert(config, telemetry_data)
            filtered = self.__change_filter.filter(converted)

            if filtered is not None:
                self.__gateway.add_device(device_name, {CONNECTOR_PARAMETER: self},
                                          device_type=device_type)
                self.__gateway.send_to_storage(self.get_name(), self.get_id(), filtered)

    def _handle_plc_write(self, device_name, params):
        address = params.get("address")
        data_type_str = params.get("dataType")
        value = params.get("value")

        for dev in self.__devices:
            if dev["config"]["deviceName"] == device_name:
                host = dev["config"]["address"]
                port = dev["config"]["port"]
                try:
                    type_format = KVTypeFormat.from_string(data_type_str)
                    client = KV8000Client(host, port)
                    try:
                        result = client.write(address, type_format, int(value))
                        self.__log.info("PLC write to %s/%s = %s -> %s",
                                         device_name, address, value, result)
                    finally:
                        client.close()
                except Exception as e:
                    self.__log.error("PLC write failed for %s/%s: %s",
                                     device_name, address, e)
                break
