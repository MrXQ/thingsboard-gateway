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
- Keep `requirements.txt` untouched for clean upstream pulls; use separate requirements files for feature-specific deps (e.g. `requirements-windows-exe.txt`)
- The `部署指南.md` (deployment guide) at repo root IS merged to dev (it's operational docs, not design docs)

## Project Structure

- `thingsboard_gateway/` — upstream ThingsBoard IoT Gateway (DO NOT MODIFY)
- `tb_gateway_windows/` — Windows native exe wrapper package
- `tests/unit/windows/` — tests for the Windows wrapper
- `docs/plans/` — design and implementation plans (feature branches only)

## Testing

```bash
python -m pytest tests/unit/windows/ -v
```

## Building Windows Exe

```bash
pip install -r requirements.txt
pip install -r requirements-windows-exe.txt
pip install -e .
python tb_gateway_windows/build/build.py
# Output: dist/tb-gateway.exe
```
