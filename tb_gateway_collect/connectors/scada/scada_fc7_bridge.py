import logging
import os
from typing import Dict, List, Optional

try:
    import jpype
    import jpype.imports
except ImportError:
    jpype = None

log = logging.getLogger(__name__)


class FC7Bridge:
    """JPype bridge to FC7_DBcomm_Java.jar for SCADA PLC communication."""

    def __init__(self, jar_path: str):
        self._jar_path = jar_path
        self._dbcomm = None
        self._ensure_jvm()

    def _ensure_jvm(self):
        if jpype is None:
            raise ImportError("JPype1 is required for SCADA/FC7 support. Install with: pip install JPype1")
        if not jpype.isJVMStarted():
            native_dir = self._find_native_dir()
            jvm_args = []
            if native_dir:
                jvm_args.append(f"-Djava.library.path={native_dir}")
            jpype.startJVM(*jvm_args, classpath=[self._jar_path])
        DBComm = jpype.JClass("com.scada.dbcomm.DBComm")
        self._dbcomm = DBComm()

    def _find_native_dir(self) -> Optional[str]:
        """Locate the native/ directory next to the JAR file."""
        jar_dir = os.path.dirname(os.path.abspath(self._jar_path))
        native_dir = os.path.join(jar_dir, "native")
        if os.path.isdir(native_dir):
            return native_dir
        return None

    def connect(self, ip: str, port: int) -> int:
        session_id = self._dbcomm.Initial()
        self._dbcomm.ConnectRemoteServer(session_id, ip, port, "", False)
        return int(session_id)

    def is_connected(self, session_id: int) -> bool:
        return bool(self._dbcomm.IsConnected(session_id))

    def get_all_tags(self, session_id: int) -> List[str]:
        tags = self._dbcomm.GetAllTagName(session_id)
        return list(tags)

    def get_data(self, session_id: int, addresses: List[str]) -> Dict[str, str]:
        raw_arr = self._dbcomm.GetData(session_id, addresses)
        result = {}
        for item in raw_arr:
            item_str = str(item)
            if "," in item_str:
                addr, value = item_str.split(",", 1)
                result[addr] = value
        return result

    def set_data(self, session_id: int, address: str, value: int) -> None:
        self._dbcomm.SetData(session_id, address, value)

    def disconnect(self, session_id: int) -> None:
        self._dbcomm.DisConnect(session_id)
