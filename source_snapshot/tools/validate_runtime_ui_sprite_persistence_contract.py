#!/usr/bin/env python3
"""Contract: runtime-created UI sprites that native UI keeps across scene loads survive UnloadUnusedAssets.

    python tools/validate_runtime_ui_sprite_persistence_contract.py

Why: the plugin decodes faction banners/cards and city icons from loose PNGs at the main menu
(Homm3RuntimeManifestPreloader) and hands them to native UI. The HUD faction emblem (BhHUDSession.factionPic)
and the side-timer faction icons bind through a FractionLobbyAsset clone that only a managed GC handle roots
(Plugin.cs SoFractionsCustomFactionAliasPatch). Unity's UnloadUnusedAssets at GameLoading and at session end
(Player.log "Unloading N unused Assets") does not count that root and frees the sprite, so custom-faction icons
went blank while vanilla ones stayed (2026-10-02 report).

Checks (source/static, fails closed, one line per violation):
  - every cache whose PrewarmManifestSprites() the main-menu preloader calls pins each Sprite.Create result and
    its source texture with HideFlags.DontUnloadUnusedAsset before caching it;
  - the SoFractions clone cache refuses to hand back a clone whose icon/bigIcon sprite was freed;
  - the native sprite catalog registrar overwrites an entry whose sprite was freed instead of keeping it
    (Add on the existing key throws and left the resolver returning the dead sprite).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
PRELOADER = PLUGIN / "Homm3RuntimeManifestPreloader.cs"
PLUGIN_CS = PLUGIN / "Plugin.cs"
REGISTRAR = PLUGIN / "Homm3NativeSpriteCatalogRegistrar.cs"

PREWARM_CALL = re.compile(r"\b(\w+)\.PrewarmManifestSprites\s*\(\s*\)")
SPRITE_CREATE = re.compile(r"\b(\w+)\s*=\s*Sprite\.Create\(\s*(\w+)\s*,")
CACHE_STORE = re.compile(r"SpritesByKey\[[^\]]+\]\s*=")


def pinned(var: str, text: str) -> bool:
    return re.search(rf"\b{re.escape(var)}\.hideFlags\s*\|?=\s*[^;]*HideFlags\.DontUnloadUnusedAsset", text) is not None


def check_prewarmed_caches(errors: list[str]) -> int:
    if not PRELOADER.is_file():
        errors.append(f"missing preloader: {PRELOADER}")
        return 0
    classes = sorted(set(PREWARM_CALL.findall(PRELOADER.read_text(encoding="utf-8-sig"))))
    if not classes:
        errors.append(f"{PRELOADER.name}: no PrewarmManifestSprites() calls found (contract scope is empty)")
    sites = 0
    for cls in classes:
        path = PLUGIN / f"{cls}.cs"
        if not path.is_file():
            errors.append(f"{cls}: prewarmed cache source not found at {path.name}")
            continue
        text = path.read_text(encoding="utf-8-sig")
        creates = list(SPRITE_CREATE.finditer(text))
        if not creates:
            errors.append(f"{path.name}: prewarmed cache has no Sprite.Create site to check")
        for m in creates:
            sites += 1
            sprite_var, texture_var = m.group(1), m.group(2)
            store = CACHE_STORE.search(text, m.end())
            if store is None:
                errors.append(f"{path.name}:{text.count(chr(10), 0, m.start()) + 1}: Sprite.Create result is never stored in SpritesByKey")
                continue
            window = text[m.end():store.start()]
            line = text.count("\n", 0, m.start()) + 1
            for role, var in (("sprite", sprite_var), ("texture", texture_var)):
                if not pinned(var, window):
                    errors.append(
                        f"{path.name}:{line}: {role} '{var}' is cached without "
                        f"{var}.hideFlags = HideFlags.DontUnloadUnusedAsset (freed by UnloadUnusedAssets on scene load)")
    return sites


def check_sofractions_clone(errors: list[str]) -> None:
    text = PLUGIN_CS.read_text(encoding="utf-8-sig")
    start = text.find("private static FractionLobbyAsset GetOrCreateCustomFactionClone(")
    if start < 0:
        errors.append("Plugin.cs: GetOrCreateCustomFactionClone not found")
        return
    body = text[start:start + 2500]
    hit = body.find("AssetCloneByFactionAndBase.TryGetValue(")
    ret = body.find("return existing;", hit)
    if hit < 0 or ret < 0:
        errors.append("Plugin.cs: SoFractions clone cache hit path not found")
        return
    guard = body[hit:ret]
    if not re.search(r"existing\.icon\s*&&\s*existing\.bigIcon", guard):
        errors.append("Plugin.cs: SoFractions clone cache returns a cached clone without checking icon/bigIcon are alive")


def check_registrar(errors: list[str]) -> None:
    text = REGISTRAR.read_text(encoding="utf-8-sig")
    start = text.find("internal static bool TryEnsureRegistered(")
    end = text.find("private static bool TryGetSpriteCatalog(", start)
    if start < 0 or end < 0:
        errors.append(f"{REGISTRAR.name}: TryEnsureRegistered not found")
        return
    body = text[start:end]
    replace = re.search(r"if\s*\(\s*hadEntry\s*\)\s*\{[^}]*SetCatalogSprite\(", body)
    add = body.find("AddCatalogSprite(")
    if replace is None or add < 0 or replace.start() > add:
        errors.append(f"{REGISTRAR.name}: a catalog entry whose sprite was freed must be overwritten (SetCatalogSprite) before any Add")
    if "private static bool SetCatalogSprite(" not in text:
        errors.append(f"{REGISTRAR.name}: SetCatalogSprite helper missing")


def main() -> int:
    errors: list[str] = []
    sites = check_prewarmed_caches(errors)
    check_sofractions_clone(errors)
    check_registrar(errors)
    if errors:
        for e in errors:
            print(f"FAIL runtime ui sprite persistence: {e}")
        return 1
    print(f"OK runtime ui sprite persistence: {sites} prewarmed Sprite.Create site(s) pinned; SoFractions clone and native catalog reject freed sprites")
    return 0


if __name__ == "__main__":
    sys.exit(main())
