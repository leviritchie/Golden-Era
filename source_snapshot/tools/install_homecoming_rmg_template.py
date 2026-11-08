#!/usr/bin/env python3
"""Install the Homecoming POC .rmg.json into Golden Era map_templates/.

Does not overwrite Core or scenario .map files. Sets OfflineLauncherConfig
MapTemplate to "Homecoming POC" when --set-launcher is passed.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

DEFAULT_GAME_ROOT = Path(
    r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
)
TEMPLATE_REL = Path("scenarios") / "homecoming_roe_castle" / "Homecoming_POC.rmg.json"
TEMPLATE_NAME = "Homecoming POC"
TEMPLATES_REL = Path("HeroesOldenEra_Data") / "StreamingAssets" / "map_templates"


def fail(message: str) -> None:
    raise SystemExit(f"install_homecoming_rmg_template failed: {message}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--game-root", type=Path, default=DEFAULT_GAME_ROOT)
    parser.add_argument("--set-launcher", action="store_true")
    args = parser.parse_args()

    src = (args.repo_root / TEMPLATE_REL).resolve()
    if not src.is_file():
        fail(f"missing template: {src}")

    # Validate JSON parses and name matches filename stem convention used by Plugin.
    data = json.loads(src.read_text(encoding="utf-8-sig"))
    if data.get("name") != TEMPLATE_NAME:
        fail(f"template name must be {TEMPLATE_NAME!r}, got {data.get('name')!r}")

    dest_dir = args.game_root / TEMPLATES_REL
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{TEMPLATE_NAME}.rmg.json"
    shutil.copy2(src, dest)
    print(f"installed {dest}")

    if args.set_launcher:
        for rel in (
            Path("BepInEx") / "plugins" / "OfflineUnlockMod" / "OfflineLauncherConfig.json",
            Path("BepInEx") / "config" / "OfflineUnlockMod" / "OfflineLauncherConfig.json",
        ):
            cfg_path = args.game_root / rel
            if not cfg_path.is_file():
                continue
            cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
            cfg["MapTemplate"] = TEMPLATE_NAME
            cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
            print(f"set MapTemplate={TEMPLATE_NAME!r} in {cfg_path}")
            break
        else:
            fail("OfflineLauncherConfig.json not found under game root")

    print(
        "next: enable capture flag, start RMG match (ai_start_match / New Game), "
        "then inspect artifacts/rmg_capture/"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
