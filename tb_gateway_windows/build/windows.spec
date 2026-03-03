# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for ThingsBoard IoT Gateway Windows executable."""

import os
import sys
from pathlib import Path

# Project root (two levels up from this spec file)
PROJECT_ROOT = Path(SPECPATH).parent.parent
GATEWAY_PKG = PROJECT_ROOT / "thingsboard_gateway"
WRAPPER_PKG = PROJECT_ROOT / "tb_gateway_windows"
COLLECT_PKG = PROJECT_ROOT / "tb_gateway_collect"

block_cipher = None

# Core connector modules that PyInstaller can't detect (dynamically loaded)
HIDDEN_IMPORTS = [
    # Core connectors
    "thingsboard_gateway.connectors.mqtt.mqtt_connector",
    "thingsboard_gateway.connectors.modbus.modbus_connector",
    "thingsboard_gateway.connectors.opcua.opcua_connector",
    "thingsboard_gateway.connectors.rest.rest_connector",
    "thingsboard_gateway.connectors.socket.socket_connector",
    # Extensions
    "thingsboard_gateway.extensions.mqtt",
    "thingsboard_gateway.extensions.modbus",
    "thingsboard_gateway.extensions.opcua",
    "thingsboard_gateway.extensions.rest",
    "thingsboard_gateway.extensions.socket",
    # Storage backends
    "thingsboard_gateway.storage.memory.memory_event_storage",
    "thingsboard_gateway.storage.file.file_event_storage",
    "thingsboard_gateway.storage.sqlite.sqlite_event_storage",
    # Converters (dynamically loaded by TBModuleLoader)
    "thingsboard_gateway.connectors.mqtt.json_mqtt_uplink_converter",
    "thingsboard_gateway.connectors.mqtt.mqtt_uplink_converter",
    "thingsboard_gateway.connectors.modbus.modbus_converter",
    "thingsboard_gateway.connectors.opcua.opcua_uplink_converter",
    "thingsboard_gateway.connectors.rest.rest_uplink_converter",
    "thingsboard_gateway.connectors.socket.socket_uplink_converter",
    # gRPC
    "thingsboard_gateway.gateway.grpc_service",
    "thingsboard_gateway.gateway.proto",
    # Dependencies that may be missed
    "simplejson",
    "orjson",
    "yaml",
    "mmh3",
    "cachetools",
    "cryptography",
    "grpc",
    "google.protobuf",
    "psutil",
    "pystray",
    "PIL",
    # Collect connectors (dynamically loaded via extension shims)
    "tb_gateway_collect.common.change_filter",
    "tb_gateway_collect.common.plc_data_types",
    "tb_gateway_collect.connectors.kv8000.kv8000_connector",
    "tb_gateway_collect.connectors.kv8000.kv8000_protocol",
    "tb_gateway_collect.connectors.kv8000.kv8000_uplink_converter",
    "tb_gateway_collect.connectors.scada.scada_connector",
    "tb_gateway_collect.connectors.scada.scada_fc7_bridge",
    "tb_gateway_collect.connectors.scada.scada_uplink_converter",
    # Collect extension shims
    "thingsboard_gateway.extensions.kv8000",
    "thingsboard_gateway.extensions.scada",
    "thingsboard_gateway.extensions.log_collector",
    # Log collector modules
    "tb_gateway_collect.connectors.log_collector",
    "tb_gateway_collect.connectors.log_collector.log_collector_connector",
    "tb_gateway_collect.connectors.log_collector.log_file_watcher",
    "tb_gateway_collect.connectors.log_collector.log_uplink_converter",
    "tb_gateway_collect.connectors.log_collector.state_tracker",
    "tb_gateway_collect.connectors.log_collector.parsers",
    "tb_gateway_collect.connectors.log_collector.parsers.ab_dim_parser",
    "tb_gateway_collect.connectors.log_collector.parsers.ivs_parser",
    "tb_gateway_collect.connectors.log_collector.parsers.ics_parser",
    "tb_gateway_collect.connectors.log_collector.parsers.hccm_parser",
    "tb_gateway_collect.connectors.log_collector.parsers.xjsbb_parser",
    # JPype (SCADA/FC7 JVM bridge)
    "jpype",
    "jpype._core",
    "jpype._jclass",
    # Log collector dependencies
    "watchdog",
    "chardet",
]

a = Analysis(
    [str(WRAPPER_PKG / "__main__.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[
        # Bundle default config files
        (str(GATEWAY_PKG / "config"), "thingsboard_gateway/config"),
        # Bundle extensions directory structure
        (str(GATEWAY_PKG / "extensions"), "thingsboard_gateway/extensions"),
        # Bundle collect connector data files (JAR, DLL, configs)
        (str(COLLECT_PKG / "exlib"), "tb_gateway_collect/exlib"),
        (str(COLLECT_PKG / "config"), "tb_gateway_collect/config"),
    ],
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude heavy optional connectors to reduce size
        "thingsboard_gateway.connectors.bacnet",
        "thingsboard_gateway.connectors.ble",
        "thingsboard_gateway.connectors.can",
        "thingsboard_gateway.connectors.knx",
        "thingsboard_gateway.connectors.xmpp",
        "thingsboard_gateway.connectors.snmp",
        "thingsboard_gateway.connectors.odbc",
        "thingsboard_gateway.connectors.ocpp",
        "thingsboard_gateway.connectors.ftp",
        # Exclude their extension counterparts
        "thingsboard_gateway.extensions.bacnet",
        "thingsboard_gateway.extensions.ble",
        "thingsboard_gateway.extensions.can",
        "thingsboard_gateway.extensions.knx",
        "thingsboard_gateway.extensions.xmpp",
        "thingsboard_gateway.extensions.snmp",
        "thingsboard_gateway.extensions.odbc",
        "thingsboard_gateway.extensions.ocpp",
        "thingsboard_gateway.extensions.ftp",
        # Exclude heavy optional deps
        "bacpypes3",
        "bleak",
        "python-can",
        "xknx",
        "slixmpp",
        "puresnmp",
        "pyodbc",
        "ocpp",
        # Exclude test/dev modules
        "debugpy",
        "pytest",
        "unittest",
        "tkinter",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="tb-gateway",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window (--noconsole / --windowed)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon=str(WRAPPER_PKG / "resources" / "tb_gateway.ico"),  # Uncomment when .ico is ready
)
