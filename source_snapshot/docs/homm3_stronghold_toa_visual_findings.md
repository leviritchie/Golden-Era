# HoMM3 Stronghold ToA Visual Asset Findings

Generated: 2026-05-02

## Summary

The `homm3_stronghold` `_upg_alt` visual import now uses dedicated Tears of Ashan visual bundles instead of reusing vanilla HoMM3 upgraded bundles.

The real local Tears of Ashan source is `vcmi/Mods/tears-of-ashan/content.zip`, not the loose `vcmi/Mods/third-upgrades/` tree. `third-upgrades` has very similar Stronghold third-upgrade art, and most files compare byte-identical, but it should not be treated as the authoritative source for ToA names/mechanics.

## Implementation Status

Status as of 2026-05-02: implemented locally and deployed to the active game plugin folder.

- `tools/homm3_import/extract_creature.py` supports `battleZipPath`/`battleZipMember` and `mapZipPath`/`mapZipMember` inventory fields.
- `tools/homm3_import/units_inventory.json` has seven ToA visual rows.
- `tools/homm3_import/presets/toa_*` has authoring presets for the seven ToA visual folders.
- `tools/homm3_import/homm3_units_manifest.json` has seven `custom_units_toa_*` bundle rows.
- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_import.json` maps only the seven `_upg_alt` entries to the new ToA bundles.
- Unity batch build verified these bundle outputs under `tools/homm3_import/build_out/`: `custom_units_toa_goblin_trapper`, `custom_units_toa_boar_rider`, `custom_units_toa_orc_berserker`, `custom_units_toa_ogre_brute`, `custom_units_toa_shahrokh`, `custom_units_toa_blood_eyed_cyclops`, and `custom_units_toa_ghost_behemoth`.
- Those bundles and `.manifest` files were copied to `Heroes of Might & Magic Olden Era Playtest/BepInEx/plugins/OfflineUnlockMod/homm3_bundles/`, and the updated source `homm3_import.json` was copied to the deployed plugin folder.

The bundle outputs and generated `oldenera_factions` lab assets are ignored by git; rebuild them with `tools/homm3_import/build_homm3_units.cmd <toa_sid>` or `tools/homm3_import/build_homm3_stronghold.cmd`.

## Previous Runtime Mapping Problem

`Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_import.json` has 21 Stronghold entries, but the seven `_upg_alt` entries reuse normal upgraded HoMM3 bundles:

| OE SID | Current bundle | ToA target |
|---|---|---|
| `h3_goblin_upg_alt` | `custom_units_h3_hobgoblin` | Goblin Trapper |
| `h3_wolf_rider_upg_alt` | `custom_units_h3_wolf_raider` | Boar Rider |
| `h3_orc_upg_alt` | `custom_units_h3_orc_chieftain` | Orc Berserker |
| `h3_ogre_upg_alt` | `custom_units_h3_ogre_mage` | Ogre Brute |
| `h3_roc_upg_alt` | `custom_units_h3_thunderbird` | Shahrokh |
| `h3_cyclops_upg_alt` | `custom_units_h3_cyclops_king` | Blood-Eyed Cyclops |
| `h3_behemoth_upg_alt` | `custom_units_h3_ancient_behemoth` | Ghost Behemoth |

## ToA Asset Locations

ToA stores its main content inside a zip:

- `vcmi/Mods/tears-of-ashan/content.zip`
- Creature configs: `config/creatures/stronghold/lvl1Alt.json` through `lvl7Alt.json`
- Upgrade wiring: `config/creatures/stronghold/stronghold.json`
- Battle DEFs: `sprites/creatures/stronghold/battle/lvl{N}Alt.def`
- Map DEFs: `sprites/creatures/stronghold/map/lvl{N}Alt.def`
- Icons: `sprites/creatures/stronghold/iconsbig/lvl{N}Alt.png` and `iconssmall/lvl{N}Alt.png`
- Boar icons: `sprites/creatures/neutral/iconsbig/boar.png` and `iconssmall/boar.png`

Tier 2 is the exception: `lvl2Alt.json` maps to `core:boar`, ToA ships Stronghold `map/lvl2Alt.def` and Stronghold `lvl2Alt` icons, but there is no `sprites/creatures/stronghold/battle/lvl2Alt.def` in `content.zip`. A Boar Rider battle visual must come from the VCMI/core neutral Boar source, another mod source, or a custom conversion.

## Extraction Probe

`tools/defextract_py3.py` can read ToA DEF files after they are extracted from `content.zip` to disk.

Probe results:

- `sprites/creatures/stronghold/battle/lvl1Alt.def` extracted cleanly: 98 frames, normal HoMM3 creature groups, 450x400 RGBA frame canvas.
- `sprites/creatures/stronghold/map/lvl1Alt.def` extracted cleanly: 30 movement frames, 64x64 RGBA frame canvas.
- `sprites/creatures/stronghold/battle/lvl6Alt.def` extracted cleanly: 135 frames, including shoot groups 14/15/16 and special groups 17/18/19.
- ToA icons are already PNGs: large 58x64 RGBA, small 32x32 RGBA.

Warning: `defextract_py3.py` requires the output folder to exist before running it directly. The lane-B `extract_creature.py` wrapper creates its temp output folders.

## Comparison Against `third-upgrades`

Byte comparisons show:

- ToA battle `lvl1Alt`, `lvl3Alt`, `lvl4Alt`, `lvl5Alt`, and `lvl7Alt` match `third-upgrades` Stronghold `cr232`, `cr234`, `cr235`, `cr236`, and `CR156`.
- ToA battle `lvl6Alt` differs from `third-upgrades` `cr237` and should be used for Blood-Eyed Cyclops.
- ToA map `lvl1Alt`, `lvl3Alt`, `lvl4Alt`, `lvl5Alt`, `lvl6Alt`, and `lvl7Alt` match the corresponding `third-upgrades` `AVWCR*` map DEFs.

Use `tears-of-ashan/content.zip` as the source of record anyway. Otherwise future agents can accidentally import Third Upgrades' Cyclops Emperor art/config instead of ToA Blood-Eyed Cyclops.

## Pipeline Impact

The lane-B pipeline extensions are now in place for sprite bundles:

- `tools/homm3_import/extract_creature.py` supports zip member extraction.
- Seven new ToA visual bundle SIDs were added rather than overwriting vanilla upgrade folders.
- `homm3_import.json` remaps only `_upg_alt` entries.
- Remaining optional improvement: copy ToA icon PNGs into `homm3_portraits/` or add a parallel portrait/icon cache path if tooltip/army-strip portraits should show ToA icons instead of textures pulled from the battle prefab.

Do not simply change `gameUnitSids` or unit names. The visual replacement is driven by `bundleName`, prefab asset paths, and the runtime resource paths in `homm3_import.json`.
