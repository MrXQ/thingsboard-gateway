# ThingsBoard IoT Gateway — Project Guide for Claude

## Branching Strategy

### Branch Naming

- `release/3.8.2-sae-main` — stable base, tracks upstream ThingsBoard
- `release/3.8.2-sae-main-dev` — integration branch, merges all feature branches
- `release/3.8.2-sae-main-<feature>` — feature branches (e.g. `-exe`, `-modbus-fix`)

### Feature Branch Workflow

1. Create feature branch from the base branch
2. Keep design docs and implementation plans in `docs/plans/` on the **feature branch only**
3. When merging to dev, **exclude `docs/`** so each feature branch retains its own design docs while dev stays code-only

### Merge Without docs/

```bash
git checkout release/3.8.2-sae-main-dev
git merge --no-commit --no-ff release/3.8.2-sae-main-<feature>

# If docs/ files appear in staged changes:
git reset HEAD -- docs/
git checkout -- docs/
# If docs/ is new (doesn't exist on dev), use rm instead:
# git rm --cached -r docs/plans/<feature-specific-files>

git commit -m "merge: <description> from release/3.8.2-sae-main-<feature>"
```

### Key Rules

- **Never modify files under `thingsboard_gateway/`** — all custom code lives in separate packages (e.g. `tb_gateway_windows/`)
- Keep `requirements.txt` untouched for clean upstream pulls; add all SAE custom deps to `requirements-sae.txt`
- The `部署指南.md` (deployment guide) at repo root IS merged to dev (it's operational docs, not design docs)

## Project Structure

- `thingsboard_gateway/` — upstream ThingsBoard IoT Gateway (DO NOT MODIFY)
- `tb_gateway_collect/` — KV8000 PLC data collection connector package
- `tb_gateway_windows/` — Windows native exe wrapper package
- `tests/unit/windows/` — tests for the Windows wrapper
- `docs/plans/` — design and implementation plans (feature branches only)

## Active Branches

| Branch | Purpose |
|--------|---------|
| `release/3.8.2-sae-main` | Stable base, tracks upstream |
| `release/3.8.2-sae-main-dev` | Integration branch (code only, no docs/) |
| `release/3.8.2-sae-main-exe` | Windows exe wrapper (`tb_gateway_windows/`) |
| `release/3.8.2-sae-main-collect-integrate` | Integrates collect connector into exe build |

## Testing

```bash
python -m pytest tests/unit/windows/ -v
```

## Building Windows Exe

```bash
pip install -r requirements.txt
pip install -r requirements-sae.txt
pip install -e .
python tb_gateway_windows/build/build.py
# Output: dist/tb-gateway.exe
```

## Collect Connector (KV8000)

- Package: `tb_gateway_collect/` — Keyence KV8000 PLC connector (ASCII protocol over TCP)
- Extension shim: `thingsboard_gateway/extensions/kv8000/` re-exports `KV8000Connector` so `TBModuleLoader` can discover it
- Config: `tb_gateway_collect/config/kv8000.json` (copied to `dist/config/` on build)
- Custom connector types not in `DEFAULT_CONNECTORS` require `"class": "KV8000Connector"` in the connector entry of `tb_gateway.json`
