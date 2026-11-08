# Surface: Mage hero battle ability

## Intent

Change the magic-class hero commander attack (`skill_mage_ability`): Focus cost, cooldown, damage numbers, specialization scaling, projectile presentation — while keeping the contract distinct from warrior presentation but aligned with the same absolute-damage model.

## Ownership preference

Same as warrior: **native Core ability + script + specialization deltas**. Mage is a **distinct SID and presentation**, not a separate damage pipeline.

## Touch points

| Kind | Path / SID / key |
| --- | --- |
| Ability SID | `skill_mage_ability` |
| Grant | specialization `heroBattleAbility` → `["skill_mage_ability","0"]` when `class_type == "magic"` |
| Spec deltas | `specializations_skill_mage_ability_base_bonus`, `specializations_skill_mage_ability_level_bonus` |
| Script | Shared family in `hero_ability.script` (same `hero_ability_skill_damage_ability` / level-bonus tokens used by hero ability tooltips) |
| Stock presentation | Projectile config + `heroes_magic_*` VFX (vs warrior slash) |
| Debuff buffs table | `DB/buffs/sub_skills_battle_hero_ability_buffs.json` includes `sub_skill_mage_*_debuff` rows (subskill effects, not the base commander attack itself) |

## Can change / cannot

**Can:** same data knobs as warrior (`energyLevel`, `cd`, base damage, per-level multiplier, VFX/projectile, specialization mage deltas).

**Cannot:**

- Treat mage ability as spell-school magic (mana/cooldown spellbook). It is a Focus hero ability with `absolute_damage`.
- Assume mage uses Spell Power only. Script damage ability sums offence + defence + spellPower + intelligence when that expression is used.
- Swap warrior↔mage SIDs on heroes without updating class_type / specialization common bonuses.

## Requirements

- Overlay-owned ability/specialization rows.
- Deployed Core readback after change.
- UI icon path for custom faction hero actions still goes through generated ability rows + icon cache (see archived warnings; verify current cache load counts).

## Pitfalls

- Stock name/description tokens are shared with warrior (`skill_hero_attack_ability_*`). Changing one loc token changes both unless you fork tokens.
- `ignoreCasterOffence` / `ignoreEnemyDefence` are true on stock mage row as well — same absolute contract as Heroic Strike.
- Nature law clones (`skill_mage_ability_law_nature_base_*`) are ability-info deltas, not free-standing new pipelines.

## Proof labels

| Claim | Label |
| --- | --- |
| Distinct SID + projectile presentation vs warrior | `deployed` |
| Same absolute_damage / ignore offence+defence flags | `deployed` |
| Mage specialization delta SIDs present in hero_abilities_infos | `deployed` |

## Open unknowns

- Whether any custom faction intentionally replaces mage ability with a non-absolute design without updating the script path.
- Shared tooltip token fork policy for future “different mage attack text” work.

## Do-not-miss checklist

- [ ] Confirm hero class_type is magic before expecting `skill_mage_ability`.
- [ ] Do not edit only warrior specialization bonuses for mage heroes.
- [ ] After loc edits, check both warrior and mage tooltips if tokens are shared.
