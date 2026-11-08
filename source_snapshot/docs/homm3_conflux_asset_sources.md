# HoMM3 Conflux Asset Sources

This document records the Conflux source declarations added with the initial manifest slice. It is not evidence that the runtime payload has been generated.

## Current Status

- `custom_factions/homm3_conflux.json` is release-enabled through the generic Core overlay and runtime manifest path.
- Older `validation.releasePromotionBlocked=true` notes were stale; do not remove Conflux from release selection to route around a runtime issue.
- Do not satisfy Conflux validation by copying Nature donor art or placeholder PNGs. Missing or incorrect Conflux assets should stay visible as validation debt and be fixed in the owned generation/deployment path.

## Known Source Archives

- Base HoMM3 source root: `HoMM 3 Complete/Data/`
- Town building/layer DEFs: `H3ab_spr.lod`
- Base creature and adventure-map DEFs: `H3sprite.lod`
- Static town backdrop candidate: `H3bitmap.lod`
- Tears of Ashan alternate upgrade candidates: `vcmi/Mods/tears-of-ashan/content.zip`

## Creature DEF Declarations

| SID | Battle source | Map source | Notes |
| --- | --- | --- | --- |
| `h3_pixie` | `Cpixie.def` | `AVGpixie.def` | Base Pixie; do not grant Sprite no-retaliation to this row. |
| `h3_pixie_upg` | `CSprite.def` | `AVWpixie.def` | Sprite no-retaliation needs real behavior support. |
| `h3_air_elemental` | `CAELEM.def` | `AVGair0.def` | Elemental immunity/vulnerability behavior is not data-complete. |
| `h3_air_elemental_upg` | `Cstorm.def` | `AVWstorm.def` | Storm Elemental is a shooter with normal melee penalty. |
| `h3_water_elemental` | `CWELEM.def` | `avgelem0.def` | Verify map DEF identity before bundle build. |
| `h3_water_elemental_upg` | `Cicee.def` | `AVWicee.def` | Ice Elemental is a shooter with normal melee penalty. |
| `h3_fire_elemental` | `CFELEM.def` | `AVGfire0.def` | Fire immunity is spell-specific and must not block fire-based creature attacks. |
| `h3_fire_elemental_upg` | `Cnrg.def` | `AVWnrg.def` | Energy Elemental is flying and casts Protection from Fire. |
| `h3_earth_elemental` | `CEELEM.def` | `avgelem0.def` | Verify base Earth map DEF identity before bundle build. |
| `h3_earth_elemental_upg` | `Cmagel.def` | `AVWmagel.def` | Magma/Lava source identity must be verified by visual inspection. |
| `h3_psychic_elemental` | `Cpsyel.def` | `AVWpsye.def` | All-adjacent enemy targeting cannot be replaced by a cone fallback. |
| `h3_psychic_elemental_upg` | `Cmagel.def` | `AVWmagel.def` | Magic Elemental source identity is still ambiguous with Magma naming; verify before extracting. |
| `h3_firebird` | `Cfbird.DEF` | `AVWfbird.def` | Firebird has breath attack and partial HotA fire reduction, not full immunity. |
| `h3_firebird_upg` | `Cphx.def` | `AVWphx.def` | Phoenix rebirth formula must be statically traced before enabling behavior. |

## Town And Map Objects

- Conflux town layer DEFs found in `H3ab_spr.lod` include `TBELhall.def`, `TBELcstl.def`, `TBELdw_0.def` through `TBELdw_6.def`, `TBELup_0.def` through `TBELup_6.def`, `TBELHrd1.def`, `TBELHrd2.def`, `TBELSpec.def`, `TBELHoly.def`, `TBELmag2.def` through `TBELmag5.def`, and related economy/navigation structures.
- External elemental dwelling art appears to include `HallElem.def`; confirm whether this is the HoMM3 Elemental Conflux object before using it for all direct dwelling rows.
- The exact Conflux town adventure-map city DEF was not confirmed in this slice. Do not alias `homm3_conflux_city` to a donor city object as a visual fallback.

## Blocking Checks Before Release Promotion

- Generate real `homm3_import.json` rows for all 21 Conflux unit SIDs.
- Build and deploy `homm3_bundles/custom_units_conflux_*` bundles from the verified lab sources.
- Generate static portraits, portrait animations, and `homm3_lab/<labSid>/extracted_battle` sidecars.
- Decode and verify the true Conflux town backdrop by eye before using it as the faction card or town scene.
- Generate direct `homm3_conflux_city` and `barracks_homm3_conflux_1..7` map-object art payloads.
- Implement or explicitly block elemental immunities, vulnerabilities, morale/resurrection immunity, all-adjacent attacks, breath attack, caster charges, Magic University, Aurora Borealis, and Phoenix rebirth.
