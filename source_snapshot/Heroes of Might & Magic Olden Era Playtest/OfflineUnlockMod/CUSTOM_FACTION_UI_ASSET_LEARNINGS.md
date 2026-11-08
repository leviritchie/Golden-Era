# Custom Faction UI Asset Learnings

## Context

`homm3_stronghold`, `homm3_fortress`, and `dungeon_raw` are data-level custom factions layered on top of vanilla Dungeon assets. Their session data can be valid while UI code still assumes that every faction id is present in Unity-authored serialized assets.

The most important failure case was `homm3_stronghold` on the Blitz quick game path. The map could load, the start city and hero could be assigned, and recruitment data could exist, but the in-game session still behaved as broken.

## Symptoms

- Map loaded with no fog of war and the cursor remained in an hourglass state.
- The selected hero existed, but the bottom army panel did not bind correctly.
- Opening the town could show a city screen with incorrect initial building state.
- City buttons could become nonresponsive, and leaving the city could corrupt the visible garrison/hero portrait.
- Logs were misleading: after some data fixes, the original "start hero killed" signature disappeared even though the UI/session was still broken.

## Data Fixes That Were Necessary But Not Sufficient

These fixes reduced real data errors but did not solve the final UI breakage by themselves:

- Clone Stronghold `barracks_homm3_stronghold_1..7` rows in `DB/objects_logic/hires/barracks.json`.
- Register Stronghold barracks map objects in `DB/map/objects/4_interactables.json`.
- Clone map object sounds for Stronghold barracks when available.
- Clone M2/M10 building banlist and construction preset rows for `homm3_stronghold_city`.
- Clone Dungeon squad trees into `DB/squads/squads_homm3_stronghold/**`.
- Patch `DB/biomes_info.json` Dirt ownership during testing so RMG can produce Stronghold-owned towns and barracks.
- Add localization aliases for bare city and barracks ids to remove `LocKit` noise.

These changes are still useful because they prevent map generation, city, and recruitment tables from failing before the UI layer is reached.

## Misleading Signals

`Hero by id -1 not found` is not enough to prove the custom faction is broken. The same line appears in vanilla Dungeon control runs around start-day or city interaction paths. Treat it as a clue only when it is paired with a failing UI transition or a `BhHUDSession.ira` exception.

The more important signal was this stack:

```text
Hex.Session.Hud.BhHUDSession.ira<T>()
cmc.sni<T>(string, T)
ke.hqy()
duk.zav()
czk.uvl()
```

During city interaction the equivalent failure surfaced as:

```text
Hex.Session.Hud.BhHUDSession.ira<T>()
cmc.sni<T>(string, T)
dwa.Open(ezx _city)
czg.uvu(ezx)
```

Those stacks pointed at UI screen binding, not at start hero ownership.

## Root Cause

`BhHUDSession` uses `Hex.GameHub.UICommon.SoFractions.pqu(string)` to resolve serialized `FractionLobbyAsset` entries for faction UI. Vanilla faction ids like `dungeon` are present in that Unity asset. Runtime-added custom ids like `homm3_stronghold`, `homm3_fortress`, and `dungeon_raw` are not.

The JSON fraction config can reuse Dungeon icon ids (`fraction_dungeon`, `Scroll_Faction_Dungeon`), but that does not populate `SoFractions.fractions` or its runtime dictionary. The session can therefore be valid while the HUD crashes trying to bind faction UI assets for the custom faction sid.

## Fix

Patch `SoFractions.pqu(string)` at runtime and alias custom faction ids that intentionally reuse Dungeon UI assets back to `dungeon` for this UI lookup only.

This preserves the real session faction id, city id, hero id, squads, laws, and recruitment data. It only changes the Unity serialized lobby/HUD asset lookup that cannot be patched through `Core.zip` JSON.

The durable patch lives in `Plugin.cs` as `SoFractionsCustomFactionAliasPatch`:

- `homm3_stronghold` -> `dungeon`
- `homm3_fortress` -> `dungeon`
- `dungeon_raw` -> `dungeon`

As of May 4, 2026, the Stronghold alias path returns a cloned `FractionLobbyAsset` instead of the shared Dungeon asset. The clone keeps Dungeon UI backgrounds but replaces `icon` and `bigIcon` with `homm3_runtime_assets/faction_icons/homm3_stronghold/Stronghold_H6_banner.png`, loaded by `Homm3StrongholdFactionBannerSpriteCache`. Do not fix the top-right HUD faction emblem by changing only `DB/fractions/7_homm3_stronghold.json`: this surface binds through serialized `SoFractions` sprites, so JSON icon keys alone are not enough.

As of May 6, 2026, the release Custom Game faction hover panel also needs an explicit `BhFractionAdditionalInfo.Show/Init` postfix for `homm3_stronghold`. The big oval faction art in that hover panel binds through the private `icon` `Image` on `BhFractionAdditionalInfo`, not just the `FractionLobbyAsset` list entry. Use `Homm3StrongholdFactionBannerSpriteCache.TryGetOrCreateCardSprite()` there and point the card at `homm3_runtime_assets/town_scene_refs/homm3_stronghold/Stronghold-in-background.png`. Do not reuse `mockups/homm3_stronghold_background_mock_1920x1080.png` for the lobby card: it contains a large black lower area intended for town-scene composition, not the cropped faction-hover screenshot.

The hover panel instance is reused between factions. If the Stronghold postfix sets `Image.overrideSprite`, the non-Stronghold path must clear that override when it still points at `homm3_stronghold_faction_card_sprite`; otherwise the Stronghold card sticks on every later faction hover even though native code has rebound `Image.sprite`.

## Runtime Sprites Must Survive UnloadUnusedAssets (2026-10-02)

User report: custom-faction icons in the top-right HUD stopped loading; vanilla ones still showed. `BhHUDSession.factionPic` and `BhSideTimers` both bind through the `SoFractions` clone above. Its `icon`/`bigIcon` are banner sprites decoded from PNG at the main menu (`Homm3RuntimeManifestPreloader` -> `Homm3StrongholdFactionBannerSpriteCache`). The clone is a runtime `FractionLobbyAsset` that only a managed GC handle roots. Unity's `UnloadUnusedAssets` does not count that root, and it runs at `[GameLoading] Start loading` and at session end (Player.log `Unloading N unused Assets`). So the sprite was freed while the cached clone kept the dead reference. The same Player.log shows these passes on 2026-10-02 (game 1 and game 2 in one process).

Fix (source/static + build proven; runtime unproven until the check-queue row passes):
- Both prewarmed caches (`Homm3StrongholdFactionBannerSpriteCache`, `Homm3StrongholdCityIconSpriteCache`) set `HideFlags.DontUnloadUnusedAsset` on the texture and the sprite.
- The clone cache will not return a clone whose `icon`/`bigIcon` was freed. It logs `SoFractions: cached UI asset clone ... freed icon sprite` and rebuilds the clone.
- `Homm3NativeSpriteCatalogRegistrar` overwrites a catalog entry whose sprite was freed. Before, `Add` threw on the existing key and the native resolver kept returning the dead sprite.

Gate: `tools/validate_runtime_ui_sprite_persistence_contract.py` (csproj `ValidateRuntimeUiSpritePersistenceContract`, full tier).

## Validation Signals

A good Stronghold run after the fix showed:

- `SoFractions: aliasing UI asset lookup 'homm3_stronghold' -> 'dungeon'.`
- No `BhHUDSession.ira` NullReferenceException on startup HUD binding.
- Opening `homm3_stronghold_city` completed with `time spent for City`.
- Recruiting HoMM3 Stronghold units logged successful `hire h3_* ... done:True`.
- Returning from city logged `mode world` / `SPAM modes -> czk`.

The remaining `Hero by id -1 not found` line also appears in vanilla controls, so do not use it as the sole pass/fail criterion.

## Probe Safety Lesson

The broad `SessionStateProbe` shape graph scan was useful while bisecting, but it is not safe to leave enabled during normal play. It can reflect into Unity/IL2CPP value types whose property getters touch native memory. One observed hard crash was:

```text
System.AccessViolationException
UnityEngine.Rendering.LocalKeyword.get_isDynamic()
OfflineUnlockMod.SessionStateProbe.InspectShapeMembersAndQueue(...)
OfflineUnlockMod.LoaderLlaProbePatch.Prefix()
```

Keep diagnostics targeted to known session data objects and avoid recursive reflection across arbitrary Unity objects. If a probe must inspect Unity-facing objects, prefer explicit fields/methods that are known safe rather than enumerating every property.

## Future Guidance

When adding another custom faction that reuses a vanilla visual identity, first decide which vanilla `SoFractions` asset it should alias to. If a faction needs unique UI art later, the robust fix is to provide a real serialized `FractionLobbyAsset` entry in Unity assets rather than relying only on JSON fraction icons.

For future diagnostics, compare these separately:

- Data/session validity: hero side id, city owner side, visitor hero id, barracks registrations, squad tree, building presets.
- UI binding validity: `SoFractions.pqu`, `BhHUDSession.ira`, `cmc.sni`, and city screen open paths.
