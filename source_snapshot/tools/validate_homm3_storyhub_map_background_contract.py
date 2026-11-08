#!/usr/bin/env python3
"""Validate baked HoMM3 StoryHub map backgrounds and plugin hook wiring."""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

ROOT_DEFAULT = Path(__file__).resolve().parents[1]
TARGET_SIZE = (1920, 1080)
PLUGIN_REL = Path("Heroes of Might & Magic Olden Era Playtest") / "OfflineUnlockMod"
MAPS_REL = PLUGIN_REL / "homm3_storyhub_maps"
HOOK_REL = PLUGIN_REL / "Homm3StoryHubMapBackgroundHook.cs"
PLUGIN_CS_REL = PLUGIN_REL / "Plugin.cs"
SYMBOLS_REL = PLUGIN_REL / "GameSymbols.cs"
CSPROJ_REL = PLUGIN_REL / "OfflineUnlockMod.csproj"
BAKE_TOOL_REL = Path("tools") / "bake_homm3_storyhub_map_backgrounds.py"
MODULE_REL = Path("experiments") / "campaign_port_poc" / "storyhub_map_background.py"


def load_required_prefixes(root: Path) -> tuple[str, ...]:
    import importlib.util

    module_path = root / MODULE_REL
    spec = importlib.util.spec_from_file_location("storyhub_map_background", module_path)
    require(spec is not None and spec.loader is not None, f"cannot load {MODULE_REL.as_posix()}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    hubs = getattr(module, "DEFAULT_HUBS", None)
    require(isinstance(hubs, dict) and hubs, "DEFAULT_HUBS missing/empty")
    prefixes = tuple(sorted({str(v) for v in hubs.values()}))
    require(
        len(prefixes) == len(hubs),
        "DEFAULT_HUBS must map each hub to a distinct BG prefix "
        f"(hubs={len(hubs)} unique_prefixes={len(prefixes)})",
    )
    return prefixes


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"homm3 storyhub map background contract failed: {message}")


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as f:
        header = f.read(24)
    require(header.startswith(b"\x89PNG\r\n\x1a\n"), f"{path}: not a PNG")
    return struct.unpack(">II", header[16:24])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT_DEFAULT)
    parser.add_argument(
        "--plugin-dir",
        type=Path,
        default=None,
        help="Optional deployed plugin dir to also assert PNG presence after deploy.",
    )
    args = parser.parse_args()
    root: Path = args.repo_root

    for rel in (BAKE_TOOL_REL, MODULE_REL, HOOK_REL, PLUGIN_CS_REL, SYMBOLS_REL, CSPROJ_REL):
        path = root / rel
        require(path.is_file(), f"missing {rel.as_posix()}")

    required_prefixes = load_required_prefixes(root)

    maps_dir = root / MAPS_REL
    require(maps_dir.is_dir(), f"missing maps dir {MAPS_REL.as_posix()}")
    for prefix in required_prefixes:
        png = maps_dir / f"{prefix}_{TARGET_SIZE[0]}x{TARGET_SIZE[1]}.png"
        require(png.is_file(), f"missing baked PNG {png.relative_to(root).as_posix()}")
        size = png_size(png)
        require(size == TARGET_SIZE, f"{png.name} size {size} != {TARGET_SIZE}")
        require(png.stat().st_size > 10_000, f"{png.name} suspiciously small")

    hook = (root / HOOK_REL).read_text(encoding="utf-8")
    require("MapImage" in hook, "hook must target MapImage objects")
    require("MapCanvas" in hook, "hook must scope under MapCanvas")
    require("homm3_storyhub_maps" in hook, "hook must load from homm3_storyhub_maps")
    for prefix in required_prefixes:
        require(
            f'"{prefix}"' in hook or f"'{prefix}'" in hook,
            f"hook must map prefix {prefix}",
        )
    require("E2_BG stand-in" not in hook, "hook must not keep Specter E2_BG stand-in comment")
    require(
        "reuse nearest RoE BG" not in hook,
        "hook must not keep AB/SoD RoE stand-in comment",
    )
    require("Smoke_Tile" not in hook or "Ignore" in hook or "ignore" in hook.lower(), "hook text ok")

    plugin = (root / PLUGIN_CS_REL).read_text(encoding="utf-8")
    require(
        "Homm3StoryHubMapBackgroundHook.TryRegister" in plugin,
        "Plugin.cs must register Homm3StoryHubMapBackgroundHook",
    )

    symbols = (root / SYMBOLS_REL).read_text(encoding="utf-8")
    require(
        "StoryHubMapBackground" in symbols or "BhStoryHubInit" in symbols,
        "GameSymbols.cs must centralize StoryHub map-background symbols",
    )

    csproj = (root / CSPROJ_REL).read_text(encoding="utf-8")
    require(
        "homm3_storyhub_maps" in csproj,
        "OfflineUnlockMod.csproj must deploy homm3_storyhub_maps",
    )
    require(
        "validate_homm3_storyhub_map_background_contract.py" in csproj,
        "OfflineUnlockMod.csproj must wire the storyhub map background validator",
    )

    if args.plugin_dir is not None:
        deployed = Path(args.plugin_dir) / "homm3_storyhub_maps"
        require(deployed.is_dir(), f"deployed maps dir missing: {deployed}")
        for prefix in required_prefixes:
            png = deployed / f"{prefix}_{TARGET_SIZE[0]}x{TARGET_SIZE[1]}.png"
            require(png.is_file(), f"deployed PNG missing: {png}")
            require(png_size(png) == TARGET_SIZE, f"deployed {png.name} wrong size")

    print(
        "homm3 storyhub map background contract OK: "
        + f"{len(required_prefixes)} distinct prefixes "
        + f"@ {TARGET_SIZE[0]}x{TARGET_SIZE[1]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
