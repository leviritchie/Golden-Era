#!/usr/bin/env python3
"""Validate the Homecoming playable-shell auto-launch diagnostic remains retired."""

from __future__ import annotations

import argparse
from pathlib import Path


def read_text(path: Path) -> str:
    if not path.is_file():
        raise SystemExit(f"missing required file: {path}")
    return path.read_text(encoding="utf-8-sig", errors="replace")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def validate(plugin_dir: Path) -> None:
    plugin_path = plugin_dir / "Plugin.cs"
    plugin = read_text(plugin_path) if plugin_path.is_file() else None
    if plugin is not None:
        require("internal static void MaybeAutoLaunchConfiguredMatch(ScMainMenu menu)" in plugin,
                "configured auto-launch entry point is missing")
        menu_body = plugin.split("internal static void MaybeAutoLaunchConfiguredMatch(ScMainMenu menu)", 1)[1].split("private static void ResetAutoLaunchGateIfMenuReturned", 1)[0]
        for forbidden in [
            "ProbeHomecomingQuickStartStateIfRequested(menu)",
            "MaybeAutoLaunchHomecomingPlayableShell(menu)",
            "StartHomecomingPlayableShellSceneObserver()",
        ]:
            require(forbidden not in menu_body,
                    f"main-menu auto-launch path must not reference retired Homecoming playable-shell diagnostic: {forbidden}")
        for forbidden in [
            "HomecomingPlayableShellLaunchFlag",
            "HomecomingQuickStartStateProbeFlag",
            "homm3_homecoming_playable_shell_launch.flag",
            "homm3_homecoming_quickstart_state_probe.flag",
            "internal static bool MaybeAutoLaunchHomecomingPlayableShell",
            "private static void ProbeHomecomingQuickStartStateIfRequested",
        ]:
            require(forbidden not in plugin,
                    f"retired Homecoming playable-shell launch/probe surface must not exist in Plugin.cs: {forbidden}")
        require("autoLaunchOnMenu" in plugin and "LauncherConfigReader.TryLoad()" in menu_body,
                "normal launcher-config auto-launch path must remain available for non-Homecoming diagnostics")
    for flag_name in [
        "homm3_homecoming_playable_shell_launch.flag",
        "homm3_homecoming_quickstart_state_probe.flag",
    ]:
        require(not (plugin_dir / flag_name).exists(),
                f"retired Homecoming launch/probe flag must not be present in plugin payload: {flag_name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin-dir", default="Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod")
    args = parser.parse_args()
    validate(Path(args.plugin_dir).resolve())
    print("Homecoming playable-shell launch retirement contract OK")


if __name__ == "__main__":
    main()