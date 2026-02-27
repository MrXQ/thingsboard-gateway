"""Build helper for creating the Windows executable."""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    project_root = Path(__file__).parent.parent.parent
    spec_file = Path(__file__).parent / "windows.spec"
    dist_dir = project_root / "dist"
    config_src = project_root / "thingsboard_gateway" / "config"
    collect_config_src = project_root / "tb_gateway_collect" / "config"
    config_dst = dist_dir / "config"
    extensions_dst = dist_dir / "extensions"

    print("=" * 60)
    print("Building ThingsBoard IoT Gateway Windows Executable")
    print("=" * 60)

    # Run PyInstaller
    cmd = [
        sys.executable, "-m", "PyInstaller",
        str(spec_file),
        "--distpath", str(dist_dir),
        "--workpath", str(project_root / "build"),
        "--clean",
        "-y",
    ]
    print(f"\nRunning: {' '.join(cmd)}\n")
    result = subprocess.run(cmd, cwd=str(project_root))
    if result.returncode != 0:
        print("PyInstaller failed!")
        sys.exit(1)

    # Copy config files next to exe (user-editable copies)
    if config_dst.exists():
        shutil.rmtree(config_dst)
    shutil.copytree(str(config_src), str(config_dst))
    print(f"\nCopied config to: {config_dst}")

    # Copy collect connector configs (user-editable)
    if collect_config_src.exists():
        for f in collect_config_src.glob("*.json"):
            shutil.copy2(str(f), str(config_dst))
        print(f"Copied collect configs to: {config_dst}")

    # Create extensions directory
    extensions_dst.mkdir(exist_ok=True)
    print(f"Created extensions dir: {extensions_dst}")

    # Create logs directory
    (dist_dir / "logs").mkdir(exist_ok=True)
    print(f"Created logs dir: {dist_dir / 'logs'}")

    print("\n" + "=" * 60)
    print("Build complete!")
    print(f"Executable: {dist_dir / 'tb-gateway.exe'}")
    print(f"Config:     {config_dst}")
    print(f"\nTo run: {dist_dir / 'tb-gateway.exe'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
