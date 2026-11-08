# Custom Faction Attribute Reference

This page explains how to read the faction pages and what each documented attribute currently means.

## Identity Attributes

- `Faction SID` is the Core faction id used by unit, hero, law, city, and runtime registry rows.
- `City SID` is the custom city object logic id.
- `Donor faction/city` is the native scaffold used for Core shape, UI routes, or scene compatibility. It is not a license to globally alias donor rows.
- `Native biome` and runtime biome identify the faction terrain assignment. Custom biomes require both Core rows and runtime renderer registration.
- `Faction skill` is the hero skill SID assigned by hero overrides and law/skill icon routing.
- `Law prefix` owns the faction law ids in `DB/fractions_laws`.

## Unit Attributes

- `Cost`, `squadValue`, `expBonus`, `ai`, and combat stats come directly from live unit logic JSON.
- `Default attack` and `Alt attack` summarize the live attack payloads: attack kind, damage type, attack pattern, damage multiplier, and whether the attack triggers counters.
- `Passives` and `Abilities` are compact JSON summaries of implemented live mechanics. Empty means no explicit payload exists in the unit row.
- `Upgrade` is the current `upgradeSid`. Standard upgrade chains are gameplay data; do not remove them to hide UI problems.

## Hero Attributes

- Hero rows come from `custom_factions/hero_overrides/<faction>.json`.
- `Start squad`, `Alt squad`, `Start skills`, and specialization payloads are current manifest-owned gameplay data used by the release overlay.
- Specialization text and mechanics are both shown because text can drift from payloads during generator work.

## Building Attributes

- `Section` is the city JSON section that supplies native behavior. This matters as much as the row SID.
- `Construction` lists level costs and prerequisites from `parametersPerLevel`.
- `Current mechanics` is generated from live payload fields such as `bonuses`, `bonusesPerLevel`, `unitsHire`, `viewRadius`, `trainingStats`, `sideBonuses`, `cityBonuses`, `conversionPairs`, `rollChances`, and artifact-market charge settings.
- Rows that show native section behavior only may still work through the native section handler. Verify the section and row-specific fields before changing behavior.

## Law Attributes

- Laws are listed exactly as live `fractions_laws_table_homm3_*` rows.
- Each level shows current law cost and raw bonus payload. Text placeholders such as `{0}` are retained when the live localization keeps them.

## Documentation Boundary

These pages describe the live data state. They do not prove every runtime hook surface, animation, or UI presentation path works; use runtime notes and agent references for those surfaces.
