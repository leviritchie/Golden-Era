# Surface: Specialization bonus row types

## Intent

Author hero specializations that the release overlay will accept and emit into `DB/heroes_specializations/specializations_homm3_*.json` — without silently dropping fields or inventing unsupported bonus types.

## Ownership preference

1. **Author** in `custom_factions/hero_overrides/<faction>.json` (ability editor / prefill tools).
2. **Clean/validate** through `clean_custom_specialization_bonuses` in `apply_release_core_overlay.py`.
3. Generator merges **common** rows (`heroBattleAbility` warrior/mage + siege + magicSchoolSet) separately from designer specialty bonuses.

## Touch points

| Kind | Path / symbol |
| --- | --- |
| Allowed specialty types | `CUSTOM_SPECIALIZATION_BONUS_TYPES` in `apply_release_core_overlay.py` |
| Common grants | `default_specialization_common_bonuses` / `custom_specialization_common_bonuses` |
| Hero overrides | `custom_factions/hero_overrides/homm3_*.json` |
| Editor note | `docs/ability_editor_agent_notes.md` (preserve bonus types; do not restore heroStat-only whitelist) |
| Masterful spells | `heroMagicReplace` + disposition metadata in overrides |
| Heroic Strike stacks | `battleSubskillBonus` → warrior ability base/level bonus SIDs |
| Core output | `DB/heroes_specializations/specializations_homm3_*.json` |

### Supported specialty bonus types (overlay clean)

From `CUSTOM_SPECIALIZATION_BONUS_TYPES`:

- `battleSubskillBonus`
- `cityUnitsIncrement`
- `heroMagicReplace`
- `heroStat`
- `heroStatBattle`
- `sideRes`
- `unitStat`

Also present on rows but owned as **common** machinery (not free-form specialty invention without understanding merge rules):

- `heroBattleAbility` (warrior/mage commander attack, siege attack, faction extras like Avenger/Gating/Arcane Battery)

## Can change / cannot

**Can:**

- Express growth specialists (`cityUnitsIncrement`), stat specialists (`unitStat` / `heroStat`), resource specialists (`sideRes`), Heroic Strike specialists (`battleSubskillBonus`), masterful spell specialists (`heroMagicReplace`).

**Cannot:**

- Emit arbitrary new `type` strings through the clean path — overlay raises.
- Let overlay silently replace masterful rows after overrides (split source of truth — archived AGENT_REFERENCE warning; keep ownership in overrides).
- Assume empty specialization payloads in overrides are “fine specialty text” — they are audit debt.

## Requirements

- Override schema must round-trip through editor validators.
- After overlay, specialization descriptions in hero info should derive from final bonus rows (archived note; verify if touching description generation).

## Pitfalls

- `heroBattleAbility` in specialty JSON is easy to confuse with the common warrior/mage grant — know which layer you edit.
- `unitStatTiers` / exotic shapes may appear in law tables or generator helpers; specialty clean path is the allowlist above.
- Class magic vs might selects mage vs warrior ability in common bonuses.

## Proof labels

| Claim | Label |
| --- | --- |
| Allowlist enforced in overlay clean | `source/static` |
| Common warrior/mage grant by class_type | `source/static` |
| Individual specialty combat/economy effect | per-hero; often only `deployed` until playtest |

## Open unknowns

- Exhaustive runtime proof matrix for every bonus type × parameter shape (matrix covers many surfaces as proven-static only).
- Whether additional bonus types exist in vanilla specialization files that custom clean deliberately rejects (treat rejection as intentional until overlay is extended).

## Do-not-miss checklist

- [ ] Use only allowlisted specialty types in overrides.
- [ ] Keep masterful specialists in `hero_overrides`.
- [ ] Confirm class_type matches intended warrior/mage ability grant.
- [ ] Do not strip unknown-but-generator-owned fields in editor validators.
