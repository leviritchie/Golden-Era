# HoMM3 Fortress Release Collision Risk Plan

Created May 13, 2026 while adding Fortress to the Steam release path after Tower exposed donor-collision bugs.

## Current Contract

Fortress is generated in `tools/release_port/apply_release_core_overlay.py` from `docs/homm3_faction_plans/fortress.md`, not from the old `generate_homm3_fortress_city.py` debug clone. The old generator explicitly made a Dungeon-perfect test faction and should not be promoted as release content.

Release Fortress currently uses Nature city/hero/law scaffolding, mixed unit donors, and a unique `skill_faction_homm3_fortress` Swamp Tactics row. Unit view rows keep native-safe donor `mesh` / `mapMesh` fields while preserving custom `h3_*` ids.

## Breakage Risks

- Do not infer a custom unit from a donor SID alone. Stronghold and Fortress both use some Dungeon donors, and Tower/Fortress share some Human donors. Reverse lookup from `minos`, `hydra`, `angel`, etc. is ambiguous unless explicit custom faction context is still available.
- Donor aliases must be one-way and local to the native call that needs them. Prefix/postfix state should restore original custom SIDs; global donor-to-custom fallback mappings can misroute HUD, previews, tooltips, and battle UI.
- Do not rewrite shared donor `ObjectConfig.id` fields when direct custom map-object rows also exist. That can poison the live config array and crash map load with duplicate keys.
- Fortress direct map objects include `homm3_fortress_city` plus `barracks_homm3_fortress_1..7`, all using Nature donor prefab paths. Do not add Fortress to `DB/data.json` without the direct city object row, or random map/session load can select the faction and fail to materialize its starting town.
- Fortress city logic currently keeps `sceneName=cityNature` until a real Fortress town scene exists. Do not token-remap that to a nonexistent `cityHomm3Fortress` scene; release-safe custom towns must use a native donor scene plus runtime art hooks.
- Keep Nature donor city UI/icon/localization/build-tree tokens until Fortress has real build-tree art and localization rows. A broad `nature`/`Nature` token remap generates missing `Homm3Fortress_Build_*`, `siege_walls_*_homm3_fortress`, and related keys; that is a data regression, not a visual polish issue.
- Nature donor city and dwelling rows contain Nature unit hire payloads under `unitsHire.units[].sids`, `unitsData.units[].sids`, and `cityUnitsIncrementFromBarrack` bonus parameters. Do not add cosmetic/top-level `units` fields and assume recruitment is fixed; rewrite the native payload fields to Fortress SIDs.
- Fortress must ship `DB/squads/squads_homm3_fortress/**`, cloned from Nature squad budgets with Nature unit SIDs rewritten to Fortress `h3_*` SIDs. Missing the squad tree can leave random map/session loading stuck after `loadingScene/worldLight` without a useful managed exception.
- Any generated donor-dwelling aliasing must be scoped by current map/town context, not by "a custom town was seen" booleans.
- Fortress currently has data-backed Swamp Tactics. Petrify, death stare, poison, dispel/weakness, and full hydra all-adjacent/no-retaliation behavior remain static-trace/implementation work; do not claim those as working in player-facing text until implemented.

## Validation Gates

- `DB/data.json` includes `homm3_fortress` in both `fractions` and `availableFractions`.
- `DB/fractions/11_homm3_fortress.json`, `DB/objects_logic/cities/homm3_fortress_city.json`, `DB/fractions_laws/fractions_laws_table_homm3_fortress.json`, and `DB/heroes/homm3_fortress/*.json` exist.
- `DB/heroes_specializations/specializations_homm3_fortress.json` exists and contains every `homm3_fortress_hero_N_specialization` referenced by the generated Fortress hero configs. Missing this table aborts map/session load in `Hex.Session.Logic.Hero`.
- All 21 Fortress unit logic/view rows exist under `DB/units/units_logics/homm3_fortress/` and `DB/units/units_views/homm3_fortress/`.
- `DB/squads/squads_homm3_fortress/**` exists and contains remapped Fortress unit SIDs, not Nature units.
- `skill_faction_homm3_fortress` exists and does not reuse donor subskill ids.
- `homm3_fortress_city` exists in direct map objects, and `barracks_homm3_fortress_1..7` exist in both direct map objects and hire logic.
- Fortress city rows retain donor Nature build UI/icon/localization tokens except for explicit Fortress identity and recruitment payload fields.
- Fortress law localization must merge into `Lang/english/texts/factionLaws.json`. Do not create `fractionLaws.json`; that typo leaves the live law table pointing at missing text tokens.
- Fortress `Build_Tier_1..7` `unitsHire` rows and `barracks_homm3_fortress_1..7` `unitsData` rows reference only Fortress `h3_*` unit SIDs, not Nature donor units.
- Quick Play and lobby faction selectors inject/repair `homm3_fortress` separately from Dungeon, Stronghold, and Tower.
