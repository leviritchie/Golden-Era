# HoMM3 Fortress Release Audit

Created May 13, 2026 after Fortress map/session loading was unblocked.

## Summary

Current Fortress is a loadable release scaffold, not a release-quality implementation of `docs/homm3_faction_plans/fortress.md`.

The faction was promoted with enough data to register, generate sessions, resolve heroes, and instantiate units, but several release rows still preserve Nature/Human/Dungeon donor behavior. Treat this faction as mechanically incomplete until the gaps below are closed against the faction doc.

## Confirmed Load-Bearing Fixes

- `DB/heroes_specializations/specializations_homm3_fortress.json` is required. Generated Fortress heroes reference `homm3_fortress_hero_N_specialization`; missing rows abort map/session load in `Hex.Session.Logic.Hero`.
- Fortress city rows must retain Nature donor city UI/icon/localization/build-tree tokens until real Fortress build-tree assets exist. Broad `Nature` -> `Homm3Fortress` remapping creates missing runtime keys.
- Fortress law text belongs in `Lang/english/texts/factionLaws.json`; typo member `fractionLaws.json` is ignored by release.

## Major Spec Drift

- Faction config still uses some Nature presentation/scaffold fields: `icon=fraction_nature`, `biome=Autumn`, and Nature city/building tokens. Fortress law-panel icon routing now uses Fortress faction art; the faction doc target is still Swamp/Fortress identity.
- City data is mostly Nature scaffold. Mage Guild is capped to level 3 and recruitment payloads use Fortress `h3_*` units, but building identities, magic roll chances, city economy, special buildings, and build-tree art/text are not Fortress-quality.
- Laws are cloned Nature laws with generic Fortress text. They are structurally valid, but not a designed Fortress law set.
- Hero specializations are cloned Nature specialization mechanics with Fortress ids/text. This prevents load failure but does not implement Beastmaster/Witch or HoMM3 Fortress hero specialty design.
- Unit logic has a first native-mechanics pass, but it is still not a final balance/design pass:
  - Serpent Fly / Dragon Fly now get focus Dispel / Weakening Dispel using the native `dispel` mechanic and `magic_shorten_shadow_effect_1` debuff.
  - Basilisk rows now get focus Petrifying Gaze using the native `medusa_stone` effect.
  - Mighty Gorgon rows now get focus Death Stare using the native `kill_stacks` mechanic.
  - Wyvern Monarch / Acid Wyvern now get focus poison effects using native Fatal Decay / poison-over-time style buffs.
  - Hydra rows now use native Dungeon Hydra all-adjacent attack patterns while retaining no-retaliation. Ruinous Hydra also has a native `heal_percent` regeneration passive and focus double strike.
  - `tools/release_port/apply_release_core_overlay.py` strips known donor ability/passive UI and donor mechanics before adding these source-backed Fortress mechanics. Do not re-add Griffin, Qilin/Wisp, Minos, Angel, or raw Dungeon Hydra ability strings as placeholders.
- ToA alternate upgrades are not a faithful mechanics pass. Several alternate rows reuse closest donor/upgrade mechanics and should be treated as asset/data placeholders.

## Technical Display And Asset Gaps

- Fortress unit bundles, unit static portraits, portrait animation manifests, faction icon/card art, city map-object frame, and direct dwelling map-object frames are present in the Steam plugin payload.
- Fortress town-screen support is partially staged, but the current layer map is not release-quality. Local VCMI has authoritative Fortress town placement data in `vcmi/Mods/third-upgrades/content/config/town-screen/fortress/factions.json`; do not preserve the stale "missing base placement data" assumption. `positions.json` and `building_layer_map.json` must be keyed to those named Fortress structures, not generic/all-zero rows or third-upgrade-only visibility scaffolding.
- Fortress build-tree icons are not wired. `Homm3StrongholdBuildingIconSpriteCache` recognizes only `homm3_stronghold_building_` and `homm3_tower_building_` keys; it has no `homm3_fortress_building_` prefix or Fortress icon map. The city data also intentionally keeps `Nature_Build_*` icon/name keys, so a full Fortress build tree cannot display from current data.
- Fortress direct city/dwelling map-object art exists in `homm3_runtime_assets/map_object_refs/homm3_fortress_*`, but runtime hook coverage is incomplete. `Homm3StrongholdTownMapBillboard` / `Homm3StrongholdDwellingMapBillboard` do not contain Fortress branches, and `Plugin.cs` only has a broad `homm3_fortress` predicate in generic HoMM3 logic. Direct and generated map objects can therefore show donor map art or miss replacement depending on the runtime path.
- Fortress hero portraits have resolver aliases, including 17/18 -> 15/16 fallback aliases in `Homm3ImportPortraitSpriteCache`, but the Steam payload audit did not confirm real `homm3_hero_portraits/homm3_fortress_hero_*.png` files. Some hero surfaces may therefore show donor/missing portraits even though unit portraits are present.
- Fortress faction UI is partially wired through `ReleaseCustomGameUiProbe` and `Homm3StrongholdFactionBannerSpriteCache`, but Core still advertises Nature icon keys. Surfaces that bypass the custom runtime replacement can still show Nature/Dungeon donor faction art.
- Fortress law and specialization icons remain donor Nature keys. Text rows exist after the load fix, but visual icon identity is still donor.

## Donor Collision Notes

- Fortress shares donors with Stronghold and Tower. Custom -> donor aliasing is acceptable only when the source custom SID is explicit.
- Donor -> custom reverse lookup must require faction/context or fail closed. Ambiguous donors include `minos`, `hydra`, `esquire`, `crossbowman`, `griffin`, and `angel`.
- Do not add fallback reverse mappings to make Fortress UI appear correct; that can misroute Stronghold/Tower/Human/Dungeon surfaces.

## Minimum Next Pass

1. Decide whether Fortress remains visible in Steam release while mechanically scaffolded.
2. Normalize faction identity fields that are safe without new runtime assets.
3. Live-test Dragon Fly Dispel/Weakness, Basilisk Petrifying Gaze, Mighty Gorgon Death Stare, Wyvern poison, Hydra all-adjacent targeting, Ruinous Hydra regeneration, and Ruinous Hydra double strike. The rows are data-backed now, but combat behavior still needs in-game confirmation.
4. Build a proper Fortress hero specialization table instead of cloned Nature mechanics.
5. Design Fortress laws from the faction doc instead of Nature donor laws.
6. Wire Fortress town-screen, map-object billboard, dwelling billboard, faction UI, hero portrait, law icon, specialization icon, and build-tree icon paths explicitly.
7. Keep `tools/validate_custom_faction_manifests.py` in the gate. It now fails stale Fortress town-layer placement when local VCMI base rows exist but source/deployed `positions.json` or `building_layer_map.json` are generic, all-zero, unknown to VCMI, or third-upgrade-only.
8. Add static validation that fails when Fortress hero specialization rows are missing, when non-arena skill tables leak donor faction skill ids, when known donor mechanic tokens remain in Fortress unit logic outside explicitly allowed presentation fields, and when Fortress data references custom asset keys with no matching resolver/payload.
