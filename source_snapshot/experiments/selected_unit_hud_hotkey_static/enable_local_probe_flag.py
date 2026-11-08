#!/usr/bin/env python3
"""Place the selected-unit hotkey probe flag in the Golden Era plugin folder.

Deploy targets delete this flag; run this after a probe-enabled build/deploy.
Does not commit anything. Safe to re-run.
"""

from __future__ import annotations

import argparse
from pathlib import Path

FLAG_NAME = "homm3_selected_unit_hud_hotkey_probe.flag"
DEFAULT_GAME_ROOT = Path(
    r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--game-root",
        type=Path,
        default=DEFAULT_GAME_ROOT,
        help="Golden Era install root",
    )
    parser.add_argument(
        "--also-selected-hud-diag",
        action="store_true",
        help="Also enable homm3_selected_hud_diag.flag for production hotkey decision logs",
    )
    args = parser.parse_args()

    plugin_dir = args.game_root / "BepInEx" / "plugins" / "OfflineUnlockMod"
    if not plugin_dir.is_dir():
        raise SystemExit(f"plugin dir missing: {plugin_dir}")

    flag_path = plugin_dir / FLAG_NAME
    flag_path.write_text("", encoding="utf-8")
    print(f"wrote {flag_path}")

    if args.also_selected_hud_diag:
        diag = plugin_dir / "homm3_selected_hud_diag.flag"
        diag.write_text("", encoding="utf-8")
        print(f"wrote {diag}")

    dll = plugin_dir / "OfflineUnlockMod.dll"
    if not dll.is_file():
        print(f"warning: {dll} missing — build/deploy with EnableSelectedUnitHudHotkeyProbe=true first")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
