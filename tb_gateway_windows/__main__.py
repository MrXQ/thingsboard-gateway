"""Entry point for the Windows ThingsBoard Gateway wrapper.

Usage:
    tb-gateway.exe                          (uses ./config/ next to exe)
    tb-gateway.exe --config-dir C:\\myconf  (custom config directory)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys


def get_base_dir() -> str:
    """Get the directory containing the exe (frozen) or project root (dev)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def setup_logging(base_dir: str):
    """Configure basic logging to console + file."""
    logs_dir = os.path.join(base_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(
                os.path.join(logs_dir, "windows_wrapper.log"),
                encoding="utf-8",
            ),
        ],
    )


def main():
    parser = argparse.ArgumentParser(description="ThingsBoard IoT Gateway")
    parser.add_argument(
        "--config-dir",
        default=None,
        help="Path to config directory (default: ./config/ next to exe)",
    )
    args = parser.parse_args()

    base_dir = get_base_dir()
    setup_logging(base_dir)
    log = logging.getLogger("windows_wrapper")

    # Resolve config directory
    config_dir = args.config_dir or os.path.join(base_dir, "config")
    config_dir = os.path.abspath(config_dir)

    if not config_dir.endswith(os.sep):
        config_dir += os.sep

    config_file = config_dir + "tb_gateway.json"

    if not os.path.isfile(config_file):
        log.error("Config file not found: %s", config_file)
        log.error("Please place your configuration in: %s", config_dir)
        sys.exit(1)

    # Set env var so the gateway resolves config paths correctly
    os.environ["TB_GW_CONFIG_DIR"] = config_dir

    # Create logs dir next to config if it doesn't exist
    os.makedirs(os.path.join(base_dir, "logs"), exist_ok=True)

    # Import after env setup
    from tb_gateway_windows.gateway_runner import GatewayRunner
    from tb_gateway_windows.tray import TrayApp

    log.info("Starting ThingsBoard IoT Gateway (Windows)")
    log.info("Config directory: %s", config_dir)
    log.info("Base directory: %s", base_dir)

    # Read version
    try:
        from thingsboard_gateway.version import VERSION
    except ImportError:
        VERSION = "unknown"

    # Start gateway in background thread
    runner = GatewayRunner(config_file)
    runner.start()

    # Run tray on main thread (blocks until exit)
    tray = TrayApp(runner, version=f"v{VERSION}")
    try:
        tray.run()
    except KeyboardInterrupt:
        pass
    finally:
        runner.stop()
        log.info("Gateway shutdown complete.")


if __name__ == "__main__":
    main()
