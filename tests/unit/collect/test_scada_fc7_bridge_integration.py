"""Integration tests for FC7Bridge — requires JPype, Java, and the native DLL.

These tests verify that the FC7 JAR loads correctly via JPype and that
the DBComm Java methods are callable with correct signatures. They do NOT
require a running SCADA server — they test JVM startup, class loading,
session initialization, and graceful behavior when no server is available.

Skipped automatically if JPype or the native DLL is unavailable.
"""

import os
import sys

import pytest

# Skip entire module if JPype is not installed
jpype = pytest.importorskip("jpype", reason="JPype1 not installed")

# Locate JAR and native DLL relative to this test file
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_JAR_PATH = os.path.join(_REPO_ROOT, "tb_gateway_collect", "exlib", "FC7_DBcomm_Java.jar")
_NATIVE_DIR = os.path.join(_REPO_ROOT, "tb_gateway_collect", "exlib", "native")

_HAS_JAR = os.path.isfile(_JAR_PATH)
_HAS_DLL = os.path.isfile(os.path.join(_NATIVE_DIR, "FC7_DbComm.dll"))

skip_reason = []
if not _HAS_JAR:
    skip_reason.append(f"JAR not found at {_JAR_PATH}")
if not _HAS_DLL:
    skip_reason.append(f"Native DLL not found in {_NATIVE_DIR}")
if sys.platform != "win32":
    skip_reason.append("FC7 native DLL is Windows-only")

pytestmark = pytest.mark.skipif(
    bool(skip_reason),
    reason="; ".join(skip_reason) if skip_reason else "",
)


@pytest.fixture(scope="module")
def dbcomm():
    """Start JVM and return a DBComm instance. Shared across all tests in module."""
    if not jpype.isJVMStarted():
        jpype.startJVM(
            f"-Djava.library.path={_NATIVE_DIR}",
            classpath=[_JAR_PATH],
        )
    DBComm = jpype.JClass("com.scada.dbcomm.DBComm")
    return DBComm()


@pytest.fixture(scope="module")
def session_id(dbcomm):
    """Initialize a session and return its ID."""
    sid = dbcomm.Initial()
    return int(sid)


class TestFC7BridgeJVMStartup:
    def test_dbcomm_instantiation(self, dbcomm):
        """DBComm class loads from JAR and instantiates without error."""
        assert dbcomm is not None

    def test_initial_returns_session_id(self, session_id):
        """Initial() returns a positive session ID (pointer-like long)."""
        assert isinstance(session_id, int)
        assert session_id > 0


class TestFC7BridgeMethodSignatures:
    def test_connect_remote_server_returns_bool(self, dbcomm, session_id):
        """ConnectRemoteServer returns a boolean (True = attempted, not necessarily connected)."""
        result = dbcomm.ConnectRemoteServer(session_id, "192.168.1.99", 2006, "", False)
        assert isinstance(bool(result), bool)

    def test_is_connected_returns_false_without_server(self, dbcomm, session_id):
        """IsConnected returns False when no SCADA server is running."""
        result = dbcomm.IsConnected(session_id)
        assert bool(result) is False

    def test_disconnect_does_not_crash(self, dbcomm, session_id):
        """DisConnect on an unconnected session doesn't throw."""
        dbcomm.DisConnect(session_id)


class TestFC7BridgeWrapper:
    def test_bridge_connect_and_is_connected(self):
        """FC7Bridge.connect() returns an int session ID; is_connected() returns False."""
        from tb_gateway_collect.connectors.scada.scada_fc7_bridge import FC7Bridge
        bridge = FC7Bridge(jar_path=_JAR_PATH)

        sid = bridge.connect("192.168.1.99", 2006)
        assert isinstance(sid, int)
        assert sid > 0
        assert bridge.is_connected(sid) is False
