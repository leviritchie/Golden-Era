# HoMM3 Faction Porting Specs

Date: 2026-05-05

These docs are source-of-truth specs for future non-Stronghold HoMM3 and HotA faction ports.
Tears of Ashan alternate-upgrade stats and creature abilities are mined separately in
`docs/homm3_tears_of_ashan_creature_specs.md`.

They apply the rules from `docs/homm3_ai_first_pass_design_principles.md`: stable donor scaffolding where needed, OE-native data before hooks, honest player-facing text, complete gameplay-surface cloning, and static tracing for native-heavy mechanics. Each faction doc should preserve exact HoMM3/HotA creature stats and special abilities so implementation can be audited against a concrete target.

## Included Factions

- `castle.md`
- `rampart.md`
- `tower.md`
- `inferno.md`
- `necropolis.md`
- `dungeon.md`
- `fortress.md`
- `conflux.md`
- `cove.md`
- `factory.md` (HotA; active manifest + town/Core/bundles; Split Assembly combat and campaign still open)
- `bulwark.md` (HotA; active manifest + town/Core/bundles; Runes runtime-pending; Bulwark town not Bulwark-specific proven)

Stronghold is excluded because it already has implementation-specific docs and generators.

HotA Factory/Bulwark creature import prep lives in `tools/homm3_import/prepare_hota_factory_bulwark_neutral_bundles.py`. Concept drafts (not runtime manifests): `tools/homm3_import/faction_concepts/`. Neutral pool registry: `tools/homm3_import/faction_concepts/homm3_hota_neutral_pool.json`. Multi-option alt recolor previews: `tools/homm3_import/recolor_galleries/`.

## Unique Faction Skill Recommendations

These are design targets, not implementation claims. Player-facing text must describe only behavior that is actually data-backed.

| Faction | Recommended unique skill | Target behavior | Trace/manual cautions |
| --- | --- | --- | --- |
| Castle | OE native `Righteousness` (`skill_faction_humans`) | Reuse the Humans native faction skill: friendly deaths/kills stack temporary hero attribute bonuses. | Verify Castle heroes/classes can reference the native Humans skill without cloning stale text. |
| Rampart | `Harmony` | Passive luck, spell-resistance support, and creature-line synergy for Dwarves, Unicorns, and Dragons. | Resistance composition and aura UI require static tracing before use; do not make the skill revolve around Grass/native-terrain bonuses. |
| Tower | `Artifice` | Construct Attack benefits from hero Spell Power, and construct Defense benefits from hero Knowledge, at 20/40/60% by rank. | Define the construct unit set and verify hero-stat-scaling creature buffs can be expressed in data or traced safely. |
| Inferno | `Gating` | Active summon places Imps on a target hex based on army strength, using the Hive larvae-egg summon flow as the donor pattern. | Trace the native Hive summon/session path before adapting it to Imps. |
| Necropolis | OE native `Necromancy` (`skill_faction_undead`) | Reuse the Undead native faction skill for post-battle undead HP conversion. | Native Necromancy currently works on vanilla undead; HoMM3 undead may need faction/unit eligibility adjustment. |
| Dungeon | `Triumvirate's Strength` (`skill_faction_homm3_dungeon` if cloned) | Preserve the once-per-round Attack, Defense, or Spell Power stance identity, but replace native-terrain damage with Dungeon creature-cadre bonuses. | Verify native Dungeon stance mechanics before cloning; do not carry over native-terrain subskills for `homm3_dungeon`. |
| Fortress | `Hunting Grounds` | Battle wins fill a Trophy meter (cap 8/7/6). Trophies add a creeping enemy -Initiative/-Speed penalty. A full meter restocks this week's visited weekly sites once. | Implemented by trophy hero buffs plus `Homm3FortressHuntingGroundsHook`; runtime unproven. Petrify, death-stare, poison and hydra behavior remain separate static-trace items. |
| Conflux | `Elemental Conjury` | Start Focus plus elemental Focus ability Attack/Spell Power scaling. Subskill SIDs use `elemental_conjury` (not `summon_elementals`). | Keep player text honest: this is not a summon button. A future true summon would be a separate design pass. |
| Cove | `Cannoneering` | Heroic Strike becomes a cannon blast; adjacent units take 20/40/60% splash damage by rank. | Bring in the HoMM3/HotA Cannon sprite through the Cove asset-source lane; Cannon visuals and targeting need review. |

## Status Vocabulary

- `exact`: HoMM3/HotA behavior is directly specified and should be reproduced.
- `oe_data_target`: expected to be expressible with known Olden Era data rows.
- `hook_required`: exact behavior likely needs a narrow runtime hook after static tracing.
- `manual_design_required`: needs a concrete design decision before implementation.
- `asset_review_required`: art/map/placement can be generated, but must be reviewed by eye.
- `static_trace_required`: do not implement by runtime probing; trace native/donor paths first.

## Common Defaults

- Target faction SIDs use `homm3_<faction>`.
- Target city SIDs use `homm3_<faction>_city`.
- Target unit SIDs use the base HoMM3 creature name as the SID family, with `_upg` and `_upg_alt` variants.
- HoMM3 base/upgraded creatures map to base/upg. `_upg_alt` should use the mined Tears of Ashan creature spec when a ToA alternate exists; only design new OE-only alternates when ToA has no usable source row.
- Unit stats, costs, growth, shots, movement mode, creature size, AI/fight value, and special abilities should use Horn of the Abyss values over vanilla Complete values when HotA has an entry.
- Probability-based HoMM3, HotA, or Tears of Ashan on-hit/on-attack effects should become guaranteed focus-point-costing active abilities in Olden Era. Preserve the source effect, legal target, duration, resist/immunity rules, and effect strength as much as practical, but do not ship hidden RNG passives for these mechanics.
- Every `_upg_alt` row must have at least one passive or active ability differentiator from `_upg`; pure stat changes are not enough.
- Dwelling upgrade costs should use HoMM3 cost flavor plus the OE dust ladder from Stronghold: T1..T7 = 10, 20, 30, 40, 50, 75, 100.
- Every faction needs complete scaffolding: units, views, squads, barracks, heroes, subclasses, quick-game tables, map objects, city rows, laws, localization, info scripts, import manifests, previews, icons, release overlay, and release UI registry entries.
- Every faction needs a release asset deployment lane in addition to Core.zip data. Core.zip rows do not ship Unity bundles, `homm3_import.json`, portrait PNGs/manifests, faction card/icon PNGs, town-scene reference art, building icons/layers, hero portraits, city/dwelling map-object frames, or HotA-only assets. A faction is not release-ready until the Steam plugin payload is populated and verified under `BepInEx/plugins/OfflineUnlockMod/`.
- Every town layer and `positions.json` row is manual review territory.
- Cove and any other HotA-only factions need a separate local HotA asset-source lane; HoMM3 Complete `H3sprite.lod` is not sufficient.
