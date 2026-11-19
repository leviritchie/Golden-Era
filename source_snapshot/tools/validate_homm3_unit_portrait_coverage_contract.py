#!/usr/bin/env python3
"""Validate that every imported unit has a portrait every portrait surface will serve.

Owner report 2026-11-16: Elemental Fusion portraits did not show in battle. The portrait PNGs shipped; the turn-order
and selected-unit hooks (Homm3ImportReleaseBattleUiHook) and the native sprite-resolver gate
(Homm3CustomUiIconHook.IsCustomKey) asked Homm3CustomFactionRegistry.IsCustomUnitSid, which lists only units with a
manifest donor line. Fusion units and the custom neutrals exist only as generated Core rows, so they kept the native
placeholder. The shared gate is Homm3ImportPortraitSpriteCache.IsImportedUnitPortraitSid: manifest roster, or an
`h3_` sid with a shipped homm3_portraits/<sid>.png.

Checks (source/static plus file existence; about 0.2 s, no texture decode):
- every gameUnitSid in homm3_import.json and every fusion sid in fusion_units.json starts with `h3_` and has
  homm3_portraits/<sid>.png (so the shared gate accepts it);
- every fusion sid has an import row;
- the battle UI hook and the native sprite-resolver gate route through the shared gate, and the tooltip and
  army-strip gates still accept `h3_` sids;
- with --installed-plugin-dir, the same PNGs exist in the deployed plugin folder.

This does not prove what the game draws; only a battle does.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

PREFIX = "h3_"


def fail(message: str) -> None:
    print(f"homm3-unit-portrait-coverage-contract: {message}", file=sys.stderr)
    raise SystemExit(1)


def method_body(source: str, signature: str, path: pathlib.Path) -> str:
    start = source.find(signature)
    if start < 0:
        fail(f"{path.name}: missing '{signature}'")
    brace = source.find("{", start)
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[brace : index + 1]
    fail(f"{path.name}: unterminated body for '{signature}'")
    return ""


def require(body: str, needle: str, context: str) -> None:
    if needle not in body:
        fail(f"{context} must contain `{needle}`")


def unit_sids(plugin_dir: pathlib.Path, repo_root: pathlib.Path) -> tuple[list[str], list[str]]:
    table = json.loads((plugin_dir / "homm3_import.json").read_text(encoding="utf-8"))
    imported: set[str] = set()
    for entry in table.get("entries") or []:
        for sid in entry.get("gameUnitSids") or []:
            if isinstance(sid, str) and sid.strip():
                imported.add(sid.strip())
    if not imported:
        fail("homm3_import.json lists no gameUnitSids")
    fusion_data = json.loads(
        (repo_root / "custom_factions" / "conflux_fusion" / "fusion_units.json").read_text(encoding="utf-8")
    )
    fusion = sorted(set(fusion_data.get("units") or {}) | set(fusion_data.get("stage2") or {}))
    if not fusion:
        fail("fusion_units.json lists no fusion units")
    missing_rows = [sid for sid in fusion if sid not in imported]
    if missing_rows:
        fail(f"{len(missing_rows)} fusion unit(s) have no homm3_import.json row, e.g. {missing_rows[:5]}")
    return sorted(imported), fusion


def check_portraits(sids: list[str], portrait_dir: pathlib.Path, label: str) -> None:
    if not portrait_dir.is_dir():
        fail(f"{label}: portrait folder missing: {portrait_dir}")
    have = {path.stem for path in portrait_dir.glob("*.png")}
    wrong_prefix = [sid for sid in sids if not sid.startswith(PREFIX)]
    if wrong_prefix:
        fail(f"{len(wrong_prefix)} imported unit sid(s) do not start with '{PREFIX}', e.g. {wrong_prefix[:5]}")
    missing = [sid for sid in sids if sid not in have]
    if missing:
        fail(f"{label}: {len(missing)} unit(s) have no homm3_portraits/<sid>.png, e.g. {missing[:8]}")


def check_source(plugin_dir: pathlib.Path) -> None:
    cache_path = plugin_dir / "Homm3ImportPortraitSpriteCache.cs"
    cache = cache_path.read_text(encoding="utf-8")
    gate = method_body(cache, "internal static bool IsImportedUnitPortraitSid(string sid)", cache_path)
    require(gate, "Homm3CustomFactionRegistry.IsCustomUnitSid(key)", "shared portrait gate")
    require(gate, f'key.StartsWith("{PREFIX}", StringComparison.Ordinal)', "shared portrait gate")
    require(gate, '"homm3_portraits"', "shared portrait gate")

    battle_path = plugin_dir / "Homm3ImportReleaseBattleUiHook.cs"
    battle = battle_path.read_text(encoding="utf-8")
    battle_gate = method_body(battle, "private static bool IsCustomUnitSid(string sid)", battle_path)
    require(battle_gate, "Homm3ImportPortraitSpriteCache.IsImportedUnitPortraitSid(sid)", "battle UI portrait gate")
    if re.search(r"Homm3CustomFactionRegistry\.IsCustomUnitSid\(", battle):
        fail("Homm3ImportReleaseBattleUiHook.cs must not gate portraits on the manifest registry directly")

    icon_path = plugin_dir / "Homm3CustomUiIconHook.cs"
    icon = icon_path.read_text(encoding="utf-8")
    custom_key = method_body(icon, "private static bool IsCustomKey(string key)", icon_path)
    require(custom_key, "Homm3ImportPortraitSpriteCache.IsImportedUnitPortraitSid(sid)", "native sprite-resolver gate")
    resolve = method_body(icon, "internal static bool TryResolveSprite(string key, out Sprite sprite)", icon_path)
    require(resolve, "IsHomm3UnitSid(sid) && Homm3ImportPortraitSpriteCache.TryGetOrCreateSprite(sid, out sprite)", "custom sprite resolver")

    tooltip_path = plugin_dir / "Homm3ImportTooltipPortraitHook.cs"
    tooltip = method_body(
        tooltip_path.read_text(encoding="utf-8"), "private static string NormalizeCustomUnitSid(string sid)", tooltip_path
    )
    require(tooltip, f'StartsWith("{PREFIX}", StringComparison.Ordinal)', "tooltip portrait gate")

    strip_path = plugin_dir / "Homm3ImportArmyStripPortraitHook.cs"
    strip = method_body(strip_path.read_text(encoding="utf-8"), "private static bool IsStrongholdSid(string sid)", strip_path)
    require(strip, f'StartsWith("{PREFIX}", StringComparison.Ordinal)', "army-strip portrait gate")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--plugin-dir", required=True, type=pathlib.Path, help="OfflineUnlockMod source folder")
    parser.add_argument("--repo-root", type=pathlib.Path, default=None)
    parser.add_argument("--installed-plugin-dir", type=pathlib.Path, default=None,
                        help="Deployed BepInEx/plugins/OfflineUnlockMod folder to check as well")
    args = parser.parse_args()
    plugin_dir = args.plugin_dir.resolve()
    repo_root = (args.repo_root or plugin_dir.parent.parent).resolve()

    imported, fusion = unit_sids(plugin_dir, repo_root)
    check_portraits(imported, plugin_dir / "homm3_portraits", "source")
    if args.installed_plugin_dir is not None:
        check_portraits(imported, args.installed_plugin_dir / "homm3_portraits", "installed")
    check_source(plugin_dir)
    print(
        "homm3-unit-portrait-coverage-contract: OK "
        f"({len(imported)} imported unit sid(s), {len(fusion)} fusion; portraits present"
        f"{' in source and installed' if args.installed_plugin_dir is not None else ' in source'}; "
        "battle UI and native resolver use the shared gate)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
