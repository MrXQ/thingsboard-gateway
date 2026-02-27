# Exe Build Update for Collect Integration — Design

**Date:** 2026-02-27
**Status:** Approved
**Branch:** release/3.8.2-sae-main-exe

## Goal

Update the PyInstaller exe build to bundle the `tb_gateway_collect` package (KV8000 and SCADA connectors) so the Windows executable can run collect connectors out of the box.

## Constraints

- Java (JRE 17+) is assumed pre-installed on target machines. JPype finds the JVM via `getDefaultJVMPath()` (registry/JAVA_HOME). No JVM bundled in exe.
- KV8000 connector works without Java (pure Python TCP). SCADA/FC7 connector requires Java at runtime.
- Exe size grows ~1.2MB (FC7 JAR + native DLL).

## Changes

### 1. `windows.spec` — Hidden imports

PyInstaller can't detect dynamically loaded modules. Add:

- `tb_gateway_collect.*` submodules (connectors, common, protocol)
- `thingsboard_gateway.extensions.kv8000` and `.scada` (shims)
- `jpype`, `jpype._core`, `jpype._jclass` (SCADA dependency)

### 2. `windows.spec` — Data files

Bundle non-Python files into the exe:

- `tb_gateway_collect/exlib/` → JAR + native DLL (1.2MB)
- `tb_gateway_collect/config/` → example connector configs

### 3. `build.py` — Copy collect configs

After copying gateway configs, also copy collect connector configs (`kv8000.json`, `scada.json`, `tb_gateway_connectors.json`) into the `dist/config/` directory so they're user-editable alongside the gateway config.

### 4. No other changes

- Extension shims already bundled (spec bundles entire `extensions/` dir)
- `FC7Bridge._find_native_dir()` resolves DLL path relative to JAR at runtime
- JPype uses system Java — no bundling needed

## Testing

- Run existing 86 tests (69 collect + 17 windows) to verify no regressions
- Build exe and verify it starts without import errors
