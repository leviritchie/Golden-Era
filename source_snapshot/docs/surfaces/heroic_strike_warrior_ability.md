# Surface: Heroic Strike / warrior hero battle ability

## Intent

Change the might-class hero commander attack commonly called **Heroic Strike**: Focus cost, cooldown, base damage, per-level scaling, specialization bonuses, VFX, or tooltip text — without inventing a second damage owner.

## Ownership preference

1. **Native Core ability row** `skill_warrior_ability` in `DB/heroes_abilities/heroes_abilities_base/hero_abilities.json`.
2. **Native info script** `DB/info/info_hero_ability/hero_ability.script` for tooltip / damage expression tokens.
3. **Specialization deltas** via `battleSubskillBonus` → `specializations_skill_warrior_ability_base_bonus` / `_level_bonus` (entries in `hero_abilities_infos.json` are `targetAbilitySid` + `deltaAbilitySid` pairs).
4. **HeroStat field** `heroicStrikeDamagePerLevelBonus` only when Core already wires it (script already does).
5. Do **not** use Direct State / committed-damage Harmony to “add Defense scaling” unless the user explicitly expands scope after proving the script path cannot express the design.

## Touch points

| Kind | Path / SID / key |
| --- | --- |
| Ability SID | `skill_warrior_ability` |
| Grant on heroes | specialization common bonus `heroBattleAbility` → `["skill_warrior_ability","0"]` (overlay) |
| Spec scaling helper | `heroic_strike_specialization_level_bonuses()` in `tools/release_port/apply_release_core_overlay.py` |
| Spec bonus type | `battleSubskillBonus` params `["hero_ability","specializations_skill_warrior_ability_level_bonus"]` (and base twin) |
| Script | Installed `DB/info/info_hero_ability/hero_ability.script` → `hero_ability_skill_damage_ability`, `hero_ability_damageMultiplerPerHeroLevelPerc_new` |
| Recovered field | `experiments/olden_cs_recovery/recovered/Hex/Configs/DataModels/HeroStat.cs` → `heroicStrikeDamagePerLevelBonus` |
| Hero overrides | `custom_factions/hero_overrides/homm3_*.json` |
| Class choice | Overlay: non-magic → warrior ability |

## Can change / cannot

**Can (data / overlay):**

- `energyLevel`, `cd`, `charges`, VFX/effect paths, base `minBaseDmg` / `maxBaseDmg`, `damageMultiplerPerHeroLevel`.
- Specialization stacks of warrior ability base/level bonus rows.
- Localization tokens for name/description (generator-owned).

**Cannot (without new proof):**

- Assume classic HoMM **Attack − Defense gap** controls this ability. Stock row sets `ignoreCasterOffence: true`, `ignoreEnemyDefence: true`, tags include `absolute_damage`.
- Silently fallback to stale damage method names.
- Mutate damage mid-pipeline with DS while also owning the same hit via training-damage law runtime.

## Requirements

- Overlay / Core deploy: `apply_release_core_overlay.py` (no hand-edit of Steam Core).
- Manifest / specialization validators when changing hero overrides.
- Proof labels: data change = `generated` / `deployed` after install readback; combat feel = `user-visible gameplay`.

## Pitfalls

- Mage and warrior abilities share the same English name/description tokens (`skill_hero_attack_ability_*`) in stock Core — presentation differs (melee slash vs projectile), not the absolute-damage contract.
- `heroOFF` and `heroDEF` appear in the script as **equal addends** in `summHeroStat`, not as an Attack-vs-Defense differential against the target.
- Cove “Cannon replaces Heroic Strike” style designs are separate ability SIDs / heroBattleAbility grants — do not casually overwrite `skill_warrior_ability` for one faction without an explicit design owner.

## Proof labels (current)

| Claim | Label |
| --- | --- |
| Stock warrior ability absolute damage + ignore offence/defence | `deployed` (Golden Era Core readback) |
| Script uses `heroicStrikeDamagePerLevelBonus` and sums offence/defence/SP/INT | `deployed` + recovered `source/static` field |
| Specialization bonus SIDs exist as ability-info deltas | `deployed` |
| Live IL evaluator type for the script | **open** (`hypothesis` until pinned) |

## Open unknowns

- Exact runtime type that executes `hero_ability.script` expressions at cast time.
- Whether any live HeroStat writer currently sets `heroicStrikeDamagePerLevelBonus` from specialization rows other than documented battle subskill deltas (trace before relying on the float alone).
- Per-faction replacement abilities that still share the warrior slot vs add a second button.

## Do-not-miss checklist

- [ ] Read installed `skill_warrior_ability` row and script before proposing formula changes.
- [ ] If the request is “scale with Defense,” map it onto the **script sum model** or an explicit new design — do not pretend gap math already exists.
- [ ] Keep specialization bonus types inside the supported set.
- [ ] Verify deployed Core after overlay, not only worktree JSON.
