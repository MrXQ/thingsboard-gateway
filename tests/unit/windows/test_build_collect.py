from pathlib import Path


def _read_spec_as_text():
    spec = Path(__file__).parent.parent.parent.parent / "tb_gateway_windows" / "build" / "windows.spec"
    return spec.read_text()


class TestSpecCollectIntegration:
    def test_spec_has_collect_hidden_imports(self):
        text = _read_spec_as_text()
        assert "tb_gateway_collect.connectors.kv8000.kv8000_connector" in text
        assert "tb_gateway_collect.connectors.scada.scada_connector" in text
        assert "tb_gateway_collect.common.plc_data_types" in text

    def test_spec_has_jpype_hidden_import(self):
        text = _read_spec_as_text()
        assert '"jpype"' in text or "'jpype'" in text

    def test_spec_has_collect_extension_shims(self):
        text = _read_spec_as_text()
        assert "thingsboard_gateway.extensions.kv8000" in text
        assert "thingsboard_gateway.extensions.scada" in text

    def test_spec_has_collect_datas(self):
        text = _read_spec_as_text()
        assert "tb_gateway_collect/exlib" in text
        assert "tb_gateway_collect/config" in text


class TestBuildScriptCollectIntegration:
    def test_build_script_references_collect_configs(self):
        build_py = Path(__file__).parent.parent.parent.parent / "tb_gateway_windows" / "build" / "build.py"
        text = build_py.read_text()
        assert "tb_gateway_collect" in text
