# Exe Collect Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Update the PyInstaller exe build to bundle `tb_gateway_collect` (KV8000 + SCADA connectors) with their JAR, native DLL, and configs so the Windows executable supports collect connectors out of the box.

**Architecture:** Add hidden imports for dynamically loaded collect modules, bundle non-Python data files (JAR, DLL, configs), and copy collect configs to the user-editable dist/config/ at build time. Java (JRE 17+) is assumed pre-installed on target machines.

**Tech Stack:** PyInstaller, JPype1, existing `tb_gateway_windows/build/` infrastructure.

**Key Reference Files:**
- PyInstaller spec: `tb_gateway_windows/build/windows.spec`
- Build script: `tb_gateway_windows/build/build.py`
- Collect package: `tb_gateway_collect/`
- Extension shims: `thingsboard_gateway/extensions/kv8000/`, `thingsboard_gateway/extensions/scada/`

---

## Task 1: Update PyInstaller spec — hidden imports and data files

**Files:**
- Modify: `tb_gateway_windows/build/windows.spec:9-11` (add COLLECT_PKG path)
- Modify: `tb_gateway_windows/build/windows.spec:15-55` (add hidden imports)
- Modify: `tb_gateway_windows/build/windows.spec:61-66` (add datas)

**Step 1: Write a test that verifies the spec includes collect imports**

```python
# tests/unit/windows/test_build_collect.py

import ast
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
        assert "tb_gateway_collect/exlib" in text or 'tb_gateway_collect/exlib' in text
        assert "tb_gateway_collect/config" in text or 'tb_gateway_collect/config' in text
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/windows/test_build_collect.py -v`
Expected: FAIL — assertions fail (spec doesn't have collect entries yet)

**Step 3: Update the spec file**

Add `COLLECT_PKG` path constant (after line 11):
```python
COLLECT_PKG = PROJECT_ROOT / "tb_gateway_collect"
```

Add collect hidden imports (after the `"PIL",` line, before `]`):
```python
    # Collect connectors (dynamically loaded via extension shims)
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
    # JPype (SCADA/FC7 JVM bridge)
    "jpype",
    "jpype._core",
    "jpype._jclass",
```

Add collect data files (after the extensions datas line, before `],`):
```python
        # Bundle collect connector data files (JAR, DLL, configs)
        (str(COLLECT_PKG / "exlib"), "tb_gateway_collect/exlib"),
        (str(COLLECT_PKG / "config"), "tb_gateway_collect/config"),
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/windows/test_build_collect.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add tb_gateway_windows/build/windows.spec tests/unit/windows/test_build_collect.py
git commit -m "feat(exe): add collect connector imports and data files to PyInstaller spec"
```

---

## Task 2: Update build script — copy collect configs to dist

**Files:**
- Modify: `tb_gateway_windows/build/build.py:14-16` (add collect config path)
- Modify: `tb_gateway_windows/build/build.py:37-41` (add collect config copy)

**Step 1: Add test for build script collect config copy logic**

```python
# tests/unit/windows/test_build_collect.py (append to existing file)

class TestBuildScriptCollectIntegration:
    def test_build_script_copies_collect_configs(self):
        build_py = Path(__file__).parent.parent.parent.parent / "tb_gateway_windows" / "build" / "build.py"
        text = build_py.read_text()
        assert "tb_gateway_collect" in text
        assert "collect" in text.lower()
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/windows/test_build_collect.py::TestBuildScriptCollectIntegration -v`
Expected: FAIL

**Step 3: Update build.py**

Add collect config source path (after line 14, `config_src = ...`):
```python
    collect_config_src = project_root / "tb_gateway_collect" / "config"
```

Add collect config copy (after the existing config copy block, after line 41):
```python
    # Copy collect connector configs (user-editable)
    if collect_config_src.exists():
        for f in collect_config_src.glob("*.json"):
            shutil.copy2(str(f), str(config_dst))
        print(f"Copied collect configs to: {config_dst}")
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/windows/test_build_collect.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add tb_gateway_windows/build/build.py tests/unit/windows/test_build_collect.py
git commit -m "feat(exe): copy collect connector configs to dist on build"
```

---

## Task 3: Run full test suite and verify build

**Step 1: Run all tests**

Run: `python -m pytest tests/unit/ -v`
Expected: All tests PASS (86 existing + 5 new = 91)

**Step 2: Run exe build**

Run: `python tb_gateway_windows/build/build.py`
Expected: Build completes. Verify dist/ contains:
- `dist/tb-gateway.exe`
- `dist/config/kv8000.json`
- `dist/config/scada.json`
- `dist/config/tb_gateway_connectors.json`

**Step 3: Commit (if any fixes needed)**

```bash
git commit -m "fix(exe): <description of fix>"
```

---

## Summary

| Task | Component | Tests | Status |
|------|-----------|-------|--------|
| 1 | PyInstaller spec — hidden imports + datas | 4 | - |
| 2 | Build script — collect config copy | 1 | - |
| 3 | Full test suite + build verification | - | - |
| **Total** | | **5 new tests** | |
