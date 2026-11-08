# HoMM3 Custom Unit Ability Catalog

Status: generated from the active Golden Era `Core.zip` unit logic/view rows and English `unitsAbility.json` / `units.json` localization.

Proof tier: **installed payload readback** for names, descriptions, Focus costs, cooldowns, and hire costs present in Core. This is not a claim that every listed mechanic is runtime-behavior proven.

Generated: 2026-07-22.

Browse UI:

```powershell
$env:PYTHONUTF8 = '1'
python tools/unit_ability_catalog/server.py
```

Regenerate markdown + JSON with:

```powershell
$env:PYTHONUTF8 = '1'
python tools/generate_homm3_custom_unit_ability_catalog.py
```

## How to read this catalog

- **Active**: action-bar ability from the unit `abilities` bucket. Cost is Focus (`energyLevel`) unless marked no-energy. Cooldown is `cd` in rounds.
- **Passive**: card-visible row from the unit `passives` bucket. Passives have no Focus cost.
- **Alt attack**: alternate attack mode (usually melee for shooters). These are no-energy attack modes, not Focus actives.
- **Hire cost**: town recruitment `unitCost` from logic, not the ability Focus cost.
- **Intended (override)**: when `custom_factions/ability_overrides` has an enabled special whose editor text differs from live Core localization, that intended wording is shown under the live Core text.
- When a live localization key is missing, the catalog falls back to ability-override editor text, then a humanized key label.
- Common generic cards such as Melee Attack / Ranged Attack are listed briefly; unique identity abilities are listed in full.

Related docs (not replacements for this catalog):

- Per-faction HotA source specs: `docs/homm3_faction_plans/`
- Mechanics debt / exact-behavior audit: `docs/homm3_custom_unit_mechanics_trace.md`
- Ability override editor notes: `docs/ability_editor_agent_notes.md`

## Summary

| Faction | Units | With actives | With passives |
| --- | ---: | ---: | ---: |
| `homm3_castle` | 21 | 11 | 21 |
| `homm3_rampart` | 21 | 9 | 21 |
| `homm3_tower` | 21 | 13 | 20 |
| `homm3_inferno` | 21 | 10 | 21 |
| `homm3_necropolis` | 21 | 13 | 21 |
| `homm3_dungeon` | 21 | 12 | 21 |
| `homm3_stronghold` | 21 | 7 | 21 |
| `homm3_fortress` | 21 | 13 | 21 |
| `homm3_conflux` | 21 | 10 | 21 |
| `homm3_cove` | 21 | 11 | 21 |
| `homm3_factory` | 24 | 17 | 24 |
| `homm3_bulwark` | 21 | 16 | 21 |
| **Total** | **255** | **142** | **254** |

## homm3_castle

### Pikeman (`h3_pikeman`)

- Tier 1 | Hire cost: 60 gold | Branch: base-line | Source mechanic: `castle.pikeman_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Halberdier (`h3_pikeman_upg`)

- Tier 1 | Hire cost: 75 gold | Branch: standard-upgrade | Source mechanic: `castle.pikeman_line`

**Actives**

- **Halberd Hook** — Focus: 2; Cooldown: 2; Rank: 3; Attack type: melee
  - Effect: Spend 2 Focus to strike, stagger, and stun an enemy for 1 round.
  - Logic: buff `gorilla_stun`; damageType `magic_pure`; pattern `attack_single_x100`; tags magic_damage, ability
  - Intended (override): **Halberd Hook** — Spend 2 Focus in melee range to strike, stagger, and stun an enemy for 1 round.
  - Intended cost: Focus 2, CD 2

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Glaivier (`h3_pikeman_upg_alt`)

- Tier 1 | Hire cost: 75 gold | Branch: alternate-upgrade | Source mechanic: `castle.pikeman_line`

**Actives**

- **Execute** — Focus: 1; Cooldown: 1; Rank: 3; Attack type: melee
  - Effect: Spend 1 Focus in melee range to deal pure damage based on 30% of the target creature's max HP, capped by stack size.
  - Logic: buff `magic_decimate_effect`; damageType `magic_pure`; pattern `attack_single_x100`; tags magic_damage, decimate_damage

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Guard Formation** — Cost: none (passive)
  - Effect: This creature takes 10% less damage from basic attacks.

### Archer (`h3_archer`)

- Tier 2 | Hire cost: 100 gold | Branch: base-line | Source mechanic: `castle.archer_line`

**Actives:** none

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1

### Marksman (`h3_archer_upg`)

- Tier 2 | Hire cost: 150 gold | Branch: standard-upgrade | Source mechanic: `castle.archer_line`

**Actives**

- **Piercing Shot** — Focus: 1; Cooldown: 1; Rank: 1; Attack type: shoot
  - Effect: Spend 1 Focus to shoot an enemy for 50% normal damage and make it take 25% more damage until the end of the round.
  - Logic: buff `crossbowman_debuff`; damageType `normal`; statDmgMult `0.5`; pattern `attack_single_x100`; tags normal_damage, ability, debuff_ability

**Passives**

- **Ranged Attack** — Cost: none (passive)
  - Effect: Can attack enemies at range. Adjacent melee attacks deal reduced damage.
  - Logic: sequence=add_attack_after_counter_shoot
- **Double Shot** — Cost: none (passive)
  - Effect: Strikes twice when performing Ranged attacks.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1

### Crossbowman (`h3_archer_upg_alt`)

- Tier 2 | Hire cost: 150 gold | Branch: alternate-upgrade | Source mechanic: `castle.archer_line`

**Actives**

- **Fine Bolts** — Focus: 2; Cooldown: 2; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to give this stack +20% ranged attack damage for 2 rounds.
  - Logic: buff `crossbowman_buff_1`; pattern `attack_single_buff`; tags ability, buff_ability, charge_ability

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.
- **Sharpshooter** — Cost: none (passive)
  - Effect: Ranged attacks deal full Ranged Damage at any range.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=0.0

### Griffin (`h3_griffin`)

- Tier 3 | Hire cost: 200 gold | Branch: base-line | Source mechanic: `castle.griffin_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.
- **Alert I** — Cost: none (passive)
  - Effect: Can counterattack up to twice per round.

### Royal Griffin (`h3_griffin_upg`)

- Tier 3 | Hire cost: 240 gold | Branch: standard-upgrade | Source mechanic: `castle.griffin_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.
- **Alert II** — Cost: none (passive)
  - Effect: Can counterattack unlimited times per round.

### Battle Griffin (`h3_griffin_upg_alt`)

- Tier 3 | Hire cost: 240 gold | Branch: alternate-upgrade | Source mechanic: `castle.griffin_line`

**Actives:** none

**Passives**

- **Melee Attack** — Cost: none (passive)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.
  - Logic: sequence=add_attack_after_counter_melee
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.
- **Double Strike** — Cost: none (passive)
  - Effect: Strikes twice when performing attacks.

### Swordsman (`h3_swordsman`)

- Tier 4 | Hire cost: 300 gold | Branch: base-line | Source mechanic: `castle.swordsman_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Guard Formation** — Cost: none (passive)
  - Effect: This creature takes 10% less damage from basic attacks.

### Crusader (`h3_swordsman_upg`)

- Tier 4 | Hire cost: 400 gold | Branch: standard-upgrade | Source mechanic: `castle.swordsman_line`

**Actives:** none

**Passives**

- **Melee Attack** — Cost: none (passive)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.
  - Logic: sequence=add_attack_after_counter_melee
- **Double Strike** — Cost: none (passive)
  - Effect: Strikes twice when performing attacks.

### Guardsman (`h3_swordsman_upg_alt`)

- Tier 4 | Hire cost: 400 gold | Branch: alternate-upgrade | Source mechanic: `castle.swordsman_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Alert I** — Cost: none (passive)
  - Effect: Can counterattack up to twice per round.
- **Guard Formation** — Cost: none (passive)
  - Effect: This creature takes 10% less damage from basic attacks.

### Monk (`h3_monk`)

- Tier 5 | Hire cost: 400 gold | Branch: base-line | Source mechanic: `castle.monk_line`

**Actives:** none

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.
- **Coordinated Volley** — Cost: none (passive)
  - Effect: This creature deals 10% more ranged attack damage.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1

### Zealot (`h3_monk_upg`)

- Tier 5 | Hire cost: 450 gold | Branch: standard-upgrade | Source mechanic: `castle.monk_line`

**Actives:** none

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.
- **Duelist** — Cost: none (passive)
  - Effect: Receives no penalty in Melee range, dealing full Damage.
- **Coordinated Volley** — Cost: none (passive)
  - Effect: This creature deals 10% more ranged attack damage.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1

### Priest (`h3_monk_upg_alt`)

- Tier 5 | Hire cost: 550 gold | Branch: alternate-upgrade | Source mechanic: `castle.monk_line`

**Actives**

- **Blessing** — Focus: 2; Cooldown: 2; Rank: 1; Attack type: cast
  - Effect: Spend 2 Focus to give an allied stack +3 Morale and +3 Luck for 2 rounds.
  - Logic: buff `inquisitor_buff`; damageType `none`; pattern `attack_single_x100`; tags ability, buff_ability

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.
- **Sharpshooter** — Cost: none (passive)
  - Effect: Ranged attacks deal full Ranged Damage at any range.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1

### Cavalier (`h3_cavalier`)

- Tier 6 | Hire cost: 1000 gold | Branch: base-line | Source mechanic: `castle.cavalier_line`

**Actives**

- **Cavalry Press** — Focus: 2; Cooldown: 2; Rank: 1; Attack type: melee
  - Effect: Spend 2 Focus to charge for 75% melee damage and give the target -2 Attack and -2 Defense for 2 rounds.
  - Logic: buff `magic_shorten_shadow_effect_1`; damageType `normal`; statDmgMult `0.75`; pattern `attack_single_x100`; tags melee_attack, normal_damage, basic_attack, ability, armed_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Jousting Charge** — Cost: none (passive)
  - Effect: Melee attacks deal more damage for each hex this unit moved before attacking.

### Champion (`h3_cavalier_upg`)

- Tier 6 | Hire cost: 1200 gold | Branch: standard-upgrade | Source mechanic: `castle.cavalier_line`

**Actives**

- **Rapid Assault** — Focus: 1; Cooldown: 1; Rank: 1; Attack type: melee
  - Effect: Spend 1 Focus to strike an adjacent enemy for 100% normal damage without provoking a counterattack.
  - Logic: damageType `normal`; pattern `attack_single_x100`; tags melee_attack, normal_damage, basic_attack, ability, armed_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Jousting Charge** — Cost: none (passive)
  - Effect: Melee attacks deal more damage for each hex this unit moved before attacking.

### Justiciar (`h3_cavalier_upg_alt`)

- Tier 6 | Hire cost: 1200 gold | Branch: alternate-upgrade | Source mechanic: `castle.cavalier_line`

**Actives**

- **Command: Fear** — Focus: 2; Cooldown: 2; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to force an enemy creature to move to a free hex within 4 hexes.
  - Logic: pattern `attack_single_buff`; tags ability, movement_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Jousting Charge** — Cost: none (passive)
  - Effect: Melee attacks deal more damage for each hex this unit moved before attacking.

### Angel (`h3_angel`)

- Tier 7 | Hire cost: 3000 gold, 1 gemstones | Branch: base-line | Source mechanic: `castle.angel_flying_resurrection`

**Actives**

- **Angelic Blessing** — Focus: 2; Cooldown: 2; Rank: 1; Attack type: cast
  - Effect: Spend 2 Focus to give an allied stack +3 Morale and +3 Luck for 2 rounds.
  - Logic: buff `inquisitor_buff`; damageType `none`; pattern `attack_single_x100`; tags ability, buff_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.

### Archangel (`h3_angel_upg`)

- Tier 7 | Hire cost: 5000 gold, 3 gemstones | Branch: standard-upgrade | Source mechanic: `castle.angel_flying_resurrection`

**Actives**

- **Rewind Life** — Focus: 2; Cooldown: -1; Rank: 4; Charges: 1; Attack type: cast
  - Effect: Spend 2 Focus to revive an allied stack, up to its starting creature count.
  - Logic: damageType `none`; pattern `attack_single_x100`; tags ability, heal

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.

### Seraph (`h3_angel_upg_alt`)

- Tier 7 | Hire cost: 5000 gold, 3 gemstones | Branch: alternate-upgrade | Source mechanic: `castle.angel_flying_resurrection`

**Actives**

- **Reality Distortion** — Focus: 3; Cooldown: 3; Rank: 5; Attack type: cast
  - Effect: Spend 3 Focus to delay 80% of an allied stack's incoming damage until the next round.
  - Logic: buff `magic_reality_distortion_effect_1`; damageType `none`; pattern `attack_single_x100`

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.

## homm3_rampart

### Centaur (`h3_centaur`)

- Tier 1 | Hire cost: 70 gold | Branch: base-line | Source mechanic: `rampart.centaur_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Centaur Captain (`h3_centaur_captain`)

- Tier 1 | Hire cost: 90 gold | Branch: standard-upgrade | Source mechanic: `rampart.centaur_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Centaur Ranger (`h3_centaur_ranger_upg_alt`)

- Tier 1 | Hire cost: 90 gold | Branch: alternate-upgrade | Source mechanic: `rampart.centaur_line`

**Actives:** none

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5

### Battle Dwarf (`h3_battle_dwarf`)

- Tier 2 | Hire cost: 150 gold | Branch: standard-upgrade | Source mechanic: `rampart.dwarf_line`

**Actives**

- **Runic Guard** — Focus: 2; Cooldown: 2; Rank: 3; Attack type: cast
  - Effect: Spend 2 Focus without ending the turn to ignore attackers' Attack values for 1 round.
  - Logic: buff `minos_buff`; damageType `none`; statDmgMult `0`; pattern `attack_single_x100`; tags ability, buff_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Dwarf (`h3_dwarf`)

- Tier 2 | Hire cost: 120 gold | Branch: base-line | Source mechanic: `rampart.dwarf_line`

**Actives**

- **Shield Set** — Focus: 2; Cooldown: 2; Rank: 3; Attack type: cast
  - Effect: Spend 2 Focus without ending the turn to give this stack +5 Attack and +1 Initiative for 2 rounds.
  - Logic: buff `griffin_selfbuff_1`; damageType `none`; statDmgMult `0`; pattern `attack_single_x100`; tags ability, buff_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Guard Formation** — Cost: none (passive)
  - Effect: This creature takes 10% less damage from basic attacks.

### Dwarf Battlerager (`h3_dwarf_battlerager_upg_alt`)

- Tier 2 | Hire cost: 150 gold | Branch: alternate-upgrade | Source mechanic: `rampart.dwarf_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Elf Wardancer (`h3_elf_wardancer_upg_alt`)

- Tier 3 | Hire cost: 225 gold | Branch: alternate-upgrade | Source mechanic: `rampart.wood_elf_line`

**Actives:** none

**Passives**

- **Melee Attack** — Cost: none (passive)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.
  - Logic: sequence=add_attack_after_counter_melee
- **Double Strike** — Cost: none (passive)
  - Effect: Strikes twice when performing attacks.

### Grand Elf (`h3_grand_elf`)

- Tier 3 | Hire cost: 255 gold | Branch: standard-upgrade | Source mechanic: `rampart.wood_elf_line`

**Actives:** none

**Passives**

- **Ranged Attack** — Cost: none (passive)
  - Effect: Can attack enemies at range. Adjacent melee attacks deal reduced damage.
  - Logic: sequence=add_attack_after_counter_shoot
- **Double Shot** — Cost: none (passive)
  - Effect: Strikes twice when performing Ranged attacks.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1

### Wood Elf (`h3_wood_elf`)

- Tier 3 | Hire cost: 200 gold | Branch: base-line | Source mechanic: `rampart.wood_elf_line`

**Actives:** none

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1

### Gold Pegasus (`h3_gold_pegasus_upg_alt`)

- Tier 4 | Hire cost: 350 gold | Branch: alternate-upgrade | Source mechanic: `rampart.pegasus_line`

**Actives**

- **Misfortune** — Focus: 1; Cooldown: 1; Rank: 1; Attack type: cast
  - Effect: Spend 1 Focus to set an enemy's Morale and Luck to minimum and its Attack and Defense to 0 for 1 round.
  - Logic: buff `magic_nairas_kiss_effect_1_old`; damageType `none`; pattern `attack_single_x100`; tags ability, debuff_ability
- **Hourglass** — Focus: 3; Cooldown: 3; Rank: 3; Attack type: cast
  - Effect: Spend 3 Focus to prevent the enemy hero from using active abilities until the end of the round.
  - Logic: pattern `attack_single_buff`; tags ability, energy_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.
- **Melee Attack** — Cost: none (passive)
  - Effect: Can only attack adjacent enemies. <b>Enemies do not counterattack.</b>
- **Swift Strike** — Cost: none (passive)
  - Effect: Enemies do not counterattack.

### Pegasus (`h3_pegasus`)

- Tier 4 | Hire cost: 325 gold | Branch: base-line | Source mechanic: `rampart.pegasus_line`

**Actives**

- **Misfortune** — Focus: 1; Cooldown: 1; Rank: 1; Attack type: cast
  - Effect: Spend 1 Focus to set an enemy's Morale and Luck to minimum and its Attack and Defense to 0 for 2 rounds.
  - Logic: buff `magic_nairas_kiss_effect_1_old`; damageType `none`; pattern `attack_single_x100`; tags ability, debuff_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.

### Silver Pegasus (`h3_silver_pegasus`)

- Tier 4 | Hire cost: 275 gold | Branch: standard-upgrade | Source mechanic: `rampart.pegasus_line`

**Actives**

- **Misfortune** — Focus: 1; Cooldown: 1; Rank: 1; Attack type: cast
  - Effect: Spend 1 Focus to set an enemy's Morale and Luck to minimum and its Attack and Defense to 0 for 2 rounds.
  - Logic: buff `magic_nairas_kiss_effect_1_old`; damageType `none`; pattern `attack_single_x100`; tags ability, debuff_ability
- **Rivulet Retreat** — Focus: none (dontUseEnergy); Cooldown: 1; Rank: 2; Attack type: end_move_attack
  - Effect: Spend 1 Focus to move to a free hex within 4 hexes.
  - Logic: pattern `attack_single_buff`; tags ability, movement_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.

### Dendroid Guard (`h3_dendroid_guard`)

- Tier 5 | Hire cost: 350 gold | Branch: base-line | Source mechanic: `rampart.dendroid_guard_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Binding** — Cost: none (passive)
  - Effect: Melee attacks root the target for 2 rounds, ending if the Dendroid moves or dies.

**Default attack notes:** on-hit buff `ent_root`

### Dendroid Shaman (`h3_dendroid_shaman_upg_alt`)

- Tier 5 | Hire cost: 550 gold | Branch: alternate-upgrade | Source mechanic: `rampart.dendroid_guard_line`

**Actives**

- **Animate Dead** — Focus: 2; Cooldown: 3; Rank: 3; Attack type: cast
  - Effect: Spend 2 Focus to revive an allied stack, up to its starting creature count.
  - Logic: damageType `none`; pattern `attack_single_x100`; tags ability, heal_ability, undead_immunities

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Binding** — Cost: none (passive)
  - Effect: Melee attacks root the target for 2 rounds, ending if the Dendroid moves or dies.

**Default attack notes:** on-hit buff `ent_root`

### Dendroid Soldier (`h3_dendroid_soldier`)

- Tier 5 | Hire cost: 425 gold | Branch: standard-upgrade | Source mechanic: `rampart.dendroid_guard_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Binding** — Cost: none (passive)
  - Effect: Melee attacks root the target for 2 rounds, ending if the Dendroid moves or dies.

**Default attack notes:** on-hit buff `ent_root`

### Pristine Unicorn (`h3_pristine_unicorn_upg_alt`)

- Tier 6 | Hire cost: 1050 gold | Branch: alternate-upgrade | Source mechanic: `rampart.unicorn_line`

**Actives**

- **Radiant Armor** — Focus: 3; Cooldown: 3; Rank: 4; Attack type: cast
  - Effect: Spend 3 Focus to reduce incoming damage to an allied stack by 30% for 1 round.
  - Logic: buff `magic_radiant_armor_effect_1`; damageType `none`; pattern `attack_single_x100`

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Unicorn (`h3_unicorn`)

- Tier 6 | Hire cost: 850 gold | Branch: base-line | Source mechanic: `rampart.unicorn_line`

**Actives**

- **Blinding Strike** — Focus: 3; Cooldown: 3; Rank: 3; Attack type: melee
  - Effect: Spend 3 Focus to attack for 100% normal damage and blind the enemy for 2 rounds, removed if it takes damage.
  - Logic: buff `unicorn_blind`; damageType `normal`; pattern `attack_single_x100`; tags melee_attack, normal_damage, basic_attack, ability, armed_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### War Unicorn (`h3_war_unicorn`)

- Tier 6 | Hire cost: 950 gold | Branch: standard-upgrade | Source mechanic: `rampart.unicorn_line`

**Actives**

- **Blinding Strike** — Focus: 2; Cooldown: 3; Rank: 3; Attack type: melee
  - Effect: Spend 2 Focus to attack for 100% normal damage and blind the enemy for 2 rounds, removed if it takes damage.
  - Logic: buff `unicorn_blind`; damageType `normal`; pattern `attack_single_x100`; tags melee_attack, normal_damage, basic_attack, ability, armed_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Diamond Dragon (`h3_diamond_dragon_upg_alt`)

- Tier 7 | Hire cost: 2 crystals, 4000 gold | Branch: alternate-upgrade | Source mechanic: `rampart.green_dragon_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.
- **Dragonbreath Strike** — Cost: none (passive)
  - Effect: Deals Damage to the target and <b>any creature</b> on the hex directly behind it.
- **Magic Immunity III** — Cost: none (passive)
  - Effect: Immune to tier‑3 and lower spells.

### Gold Dragon (`h3_gold_dragon`)

- Tier 7 | Hire cost: 2 crystals, 4000 gold | Branch: standard-upgrade | Source mechanic: `rampart.green_dragon_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.
- **Dragonbreath Strike** — Cost: none (passive)
  - Effect: Deals Damage to the target and <b>any creature</b> on the hex directly behind it.
- **Magic Immunity IV** — Cost: none (passive)
  - Effect: Immune to tier‑4 and lower spells.

### Green Dragon (`h3_green_dragon`)

- Tier 7 | Hire cost: 1 crystals, 2400 gold | Branch: base-line | Source mechanic: `rampart.green_dragon_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.
- **Dragonbreath Strike** — Cost: none (passive)
  - Effect: Deals Damage to the target and <b>any creature</b> on the hex directly behind it.
- **Magic Immunity III** — Cost: none (passive)
  - Effect: Immune to tier‑3 and lower spells.

## homm3_tower

### Gremlin (`h3_gremlin`)

- Tier 1 | Hire cost: 35 gold | Branch: base-line | Source mechanic: `tower.gremlin_line`

**Actives:** none

**Passives:** none beyond basic attack presentation (if any)

### Master Gremlin (`h3_gremlin_upg`)

- Tier 1 | Hire cost: 40 gold | Branch: standard-upgrade | Source mechanic: `tower.gremlin_line`

**Actives:** none

**Passives**

- **Ranged Attack** — Cost: none (passive)
  - Effect: Shoots at enemy units. Master Gremlins have 8 shots in the Heroes III baseline.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1

### Gremlin Saboteur (`h3_gremlin_upg_alt`)

- Tier 1 | Hire cost: 40 gold | Branch: alternate-upgrade | Source mechanic: `tower.gremlin_line`

**Actives**

- **Repair** — Focus: 2; Cooldown: 2; Rank: 2; Charges: 2; Attack type: cast
  - Effect: Spend 2 Focus without ending the turn to restore 10% health to an allied stack, with resurrection; 2 charges per battle.
  - Logic: damageType `none`; pattern `attack_single_x100`; tags ability, heal_ability, revive_ability, charge_ability
- **Repair** — Focus: 2; Cooldown: 2; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to restore 50% health to an allied stack.
  - Logic: damageType `none`; pattern `attack_single_x100`; tags ability, heal_ability, construct_immunities

**Passives**

- **Repair** — Cost: none (passive)
  - Effect: Can use Repair twice per battle to restore 10% health with resurrection, plus a 50% repair action for allied stacks.

### Stone Gargoyle (`h3_gargoyle`)

- Tier 2 | Hire cost: 130 gold | Branch: base-line | Source mechanic: `tower.gargoyle_line`

**Actives**

- **Granite Dive** — Focus: 2; Cooldown: 2; Rank: 3; Attack type: melee
  - Effect: Spend 2 Focus to dive for 75% normal damage and suppress 1 retaliation.
  - Logic: damageType `normal`; statDmgMult `0.75`; pattern `attack_single_x100`; tags melee_attack, normal_damage, basic_attack, ability

**Passives**

- **Flying** — Cost: none (passive)
  - Effect: Can fly over obstacles and units when moving.
- **Bloodless** — Cost: none (passive)
  - Effect: Counts as non-living for life drain, poison, disease, and resurrection effects.

### Obsidian Gargoyle (`h3_gargoyle_upg`)

- Tier 2 | Hire cost: 160 gold | Branch: standard-upgrade | Source mechanic: `tower.gargoyle_line`

**Actives**

- **Obsidian Drop** — Focus: 2; Cooldown: 2; Rank: 3; Attack type: melee
  - Effect: Spend 2 Focus to slam an enemy for 85% normal damage and stun it for 1 round.
  - Logic: buff `gorilla_stun`; damageType `normal`; statDmgMult `0.85`; pattern `attack_single_x100`; tags melee_attack, normal_damage, basic_attack, ability

**Passives**

- **Flying** — Cost: none (passive)
  - Effect: Can fly over obstacles and units when moving.
- **Bloodless** — Cost: none (passive)
  - Effect: Counts as non-living for life drain, poison, disease, and resurrection effects.

### Runed Gargoyle (`h3_gargoyle_upg_alt`)

- Tier 2 | Hire cost: 160 gold | Branch: alternate-upgrade | Source mechanic: `tower.gargoyle_line`

**Actives**

- **Carapace** — Focus: 2; Cooldown: 2; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to shield an allied stack with a 1-hit barrier for 1 round.
  - Logic: buff `magic_carapace_effect_0`; damageType `none`; pattern `attack_single_x100`

**Passives**

- **Elemental Carapace** — Cost: none (passive)
  - Effect: Has the Gargoyle construct profile, flies, takes 50% less Air, Earth, Fire, and Water spell damage, and is immune to Stone Gaze.

### Stone Golem (`h3_golem`)

- Tier 3 | Hire cost: 210 gold | Branch: base-line | Source mechanic: `tower.golem_line`

**Actives**

- **Repair** — Focus: 2; Cooldown: 2; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to restore 40% health to an allied construct stack.
  - Logic: damageType `none`; pattern `attack_single_x100`; tags ability, heal_ability, construct_immunities

**Passives**

- **Spell Damage Reduction** — Cost: none (passive)
  - Effect: Takes 50% less magic damage.
- **Golem** — Cost: none (passive)
  - Effect: Neutral Morale and Luck; immune to life drain and corpse-heal effects.
- **Passive 2** — Cost: none (passive)
  - Effect: *(no English unitsAbility text)*
- **Passive 3** — Cost: none (passive)
  - Effect: *(no English unitsAbility text)*
- **Passive 4** — Cost: none (passive)
  - Effect: *(no English unitsAbility text)*

### Iron Golem (`h3_golem_upg`)

- Tier 3 | Hire cost: 200 gold | Branch: standard-upgrade | Source mechanic: `tower.golem_line`

**Actives**

- **Repair** — Focus: 2; Cooldown: 2; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to restore 60% health to an allied construct stack.
  - Logic: damageType `none`; pattern `attack_single_x100`; tags ability, heal_ability, construct_immunities

**Passives**

- **Spell Damage Reduction** — Cost: none (passive)
  - Effect: Takes 75% less magic damage.
- **Golem** — Cost: none (passive)
  - Effect: Neutral Morale and Luck; immune to life drain and corpse-heal effects.
- **Passive 2** — Cost: none (passive)
  - Effect: *(no English unitsAbility text)*
- **Passive 3** — Cost: none (passive)
  - Effect: *(no English unitsAbility text)*
- **Passive 4** — Cost: none (passive)
  - Effect: *(no English unitsAbility text)*

### Steel Golem (`h3_golem_upg_alt`)

- Tier 3 | Hire cost: 200 gold | Branch: alternate-upgrade | Source mechanic: `tower.golem_line`

**Actives**

- **Web** — Focus: 2; Cooldown: 2; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to give an enemy -2 Speed for 1 round.
  - Logic: buff `magic_web_effect_0`; damageType `none`; pattern `attack_single_x100`; tags web, slow

**Passives**

- **Magnetic Slow** — Cost: none (passive)
  - Effect: Can spend 2 Focus to give an enemy -2 Speed for 1 round; also has construct spell restrictions.
- **Passive 1** — Cost: none (passive)
  - Effect: *(no English unitsAbility text)*
- **Passive 2** — Cost: none (passive)
  - Effect: *(no English unitsAbility text)*

### Mage (`h3_mage`)

- Tier 4 | Hire cost: 350 gold | Branch: base-line | Source mechanic: `tower.mage_line`

**Actives**

- **Silence** — Focus: 2; Cooldown: 2; Rank: 3; Attack type: cast
  - Effect: Spend 2 Focus to prevent an enemy from using active abilities or gaining Focus for 1 round.
  - Logic: buff `magic_silence_effect`; damageType `none`; pattern `attack_single_x100`; tags embodiment_immunities, construct_immunities

**Passives**

- **Ranged Attack** — Cost: none (passive)
  - Effect: Shoots at enemy units with 24 shots.
- **No Melee or Obstacle Penalty** — Cost: none (passive)
  - Effect: Ranged attacks are not penalized in melee or by range/obstacle falloff.
- **Magic Channeler** — Cost: none (passive)
  - Effect: Reduces allied hero combat spell costs by 2 while this stack is present.
- **Duelist** — Cost: none (passive)
  - Effect: Receives no penalty in Melee range, dealing full Damage.
- **Ranged Attack** — Cost: none (passive)
  - Effect: Can attack enemies at any range. 
Targets {0} or more hexes away take –{1}% Damage per hex (up to –{2}%).
- **Sharpshooter** — Cost: none (passive)
  - Effect: Ranged attacks deal full Ranged Damage at any range.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=0.0

### Arch Mage (`h3_mage_upg`)

- Tier 4 | Hire cost: 450 gold | Branch: standard-upgrade | Source mechanic: `tower.mage_line`

**Actives:** none

**Passives**

- **Ranged Attack** — Cost: none (passive)
  - Effect: Shoots at enemy units with 24 shots.
- **No Melee or Obstacle Penalty** — Cost: none (passive)
  - Effect: Ranged attacks are not penalized in melee or by range/obstacle falloff.
- **Magic Channeler** — Cost: none (passive)
  - Effect: Reduces allied hero combat spell costs by 2 while this stack is present.
- **Duelist** — Cost: none (passive)
  - Effect: Receives no penalty in Melee range, dealing full Damage.
- **Ranged Attack** — Cost: none (passive)
  - Effect: Can attack enemies at any range. 
Targets {0} or more hexes away take –{1}% Damage per hex (up to –{2}%).
- **Sharpshooter** — Cost: none (passive)
  - Effect: Ranged attacks deal full Ranged Damage at any range.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=0.0

### Battle Mage (`h3_mage_upg_alt`)

- Tier 4 | Hire cost: 500 gold | Branch: alternate-upgrade | Source mechanic: `tower.mage_line`

**Actives**

- **Silence** — Focus: 2; Cooldown: 2; Rank: 3; Attack type: cast
  - Effect: Spend 2 Focus to prevent an enemy from using active abilities or gaining Focus for 1 round.
  - Logic: buff `magic_silence_effect`; damageType `none`; pattern `attack_single_x100`; tags embodiment_immunities, construct_immunities

**Passives**

- **Battle Mage Spells** — Cost: none (passive)
  - Effect: Shoots with 24 shots, reduces allied hero combat spell costs by 2, and can cast 3 bolt spells per battle.
- **Duelist** — Cost: none (passive)
  - Effect: Receives no penalty in Melee range, dealing full Damage.
- **Ranged Attack** — Cost: none (passive)
  - Effect: Can attack enemies at any range. 
Targets {0} or more hexes away take –{1}% Damage per hex (up to –{2}%).

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=0.0

### Genie (`h3_genie`)

- Tier 5 | Hire cost: 550 gold | Branch: base-line | Source mechanic: `tower.genie_line`

**Actives**

- **Command: Reposition** — Focus: 2; Cooldown: 2; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to move an allied non-self creature to a free hex within 4 hexes.
  - Logic: pattern `attack_single_buff`; tags ability, movement_ability

**Passives**

- **Flying** — Cost: none (passive)
  - Effect: Can fly over obstacles and units when moving.
- **Efreet Hate** — Cost: none (passive)
  - Effect: Deals 150% damage to Efreet-line enemies.

### Master Genie (`h3_genie_upg`)

- Tier 5 | Hire cost: 600 gold | Branch: standard-upgrade | Source mechanic: `tower.genie_line`

**Actives**

- **Refract and Reflect** — Focus: 1; Cooldown: 2; Rank: 1; Attack type: cast
  - Effect: Spend 1 Focus to copy this stack's positive effects to another allied stack.
  - Logic: pattern `attack_single_buff`; tags ability, buff_ability

**Passives**

- **Flying** — Cost: none (passive)
  - Effect: Can fly over obstacles and units when moving.
- **Efreet Hate** — Cost: none (passive)
  - Effect: Deals 150% damage to Efreet-line enemies.
- **Spellcaster** — Cost: none (passive)
  - Effect: Can cast a beneficial spell up to 3 times per battle.

### Vizier Genie (`h3_genie_upg_alt`)

- Tier 5 | Hire cost: 650 gold | Branch: alternate-upgrade | Source mechanic: `tower.genie_line`

**Actives**

- **Command: Switch Places** — Focus: 2; Cooldown: 2; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to swap a non-self creature with another non-self creature within 8 hexes.
  - Logic: pattern `attack_single_buff`; tags ability, movement_ability

**Passives**

- **Vizier's Misfortune** — Cost: none (passive)
  - Effect: Flies, deals 150% damage to Efreet-line enemies, takes 50% less Air spell damage, and can cast Misfortune for 1 Focus.

### Naga (`h3_naga`)

- Tier 6 | Hire cost: 1100 gold | Branch: base-line | Source mechanic: `tower.naga_line`

**Actives:** none

**Passives**

- **No Retaliation** — Cost: none (passive)
  - Effect: Enemy units do not retaliate against this unit's melee attacks.
- **Fixed Damage** — Cost: none (passive)
  - Effect: Always deals fixed damage instead of rolling a damage range.
- **Melee Attack** — Cost: none (passive)
  - Effect: Can only attack adjacent enemies. <b>Enemies do not counterattack.</b>
- **Swift Strike** — Cost: none (passive)
  - Effect: Enemies do not counterattack.

### Naga Queen (`h3_naga_upg`)

- Tier 6 | Hire cost: 1600 gold | Branch: standard-upgrade | Source mechanic: `tower.naga_line`

**Actives:** none

**Passives**

- **No Retaliation** — Cost: none (passive)
  - Effect: Enemy units do not retaliate against this unit's melee attacks.
- **Fixed Damage** — Cost: none (passive)
  - Effect: Always deals fixed damage instead of rolling a damage range.
- **Melee Attack** — Cost: none (passive)
  - Effect: Can only attack adjacent enemies. <b>Enemies do not counterattack.</b>
- **Swift Strike** — Cost: none (passive)
  - Effect: Enemies do not counterattack.

### Temple Guard (`h3_naga_upg_alt`)

- Tier 6 | Hire cost: 1600 gold | Branch: alternate-upgrade | Source mechanic: `tower.naga_line`

**Actives:** none

**Passives**

- **Three-Headed Attack** — Cost: none (passive)
  - Effect: Melee attacks hit three adjacent targets for fixed damage, and enemies do not retaliate.
- **Melee Attack** — Cost: none (passive)
  - Effect: Can only attack adjacent enemies. <b>Enemies do not counterattack.</b>
- **Swift Strike** — Cost: none (passive)
  - Effect: Enemies do not counterattack.
- **Dragonbreath Strike** — Cost: none (passive)
  - Effect: Deals Damage to the target and <b>any creature</b> on the hex directly behind it.

### Giant (`h3_giant`)

- Tier 7 | Hire cost: 2000 gold, 1 gemstones | Branch: base-non-shooter | Source mechanic: `tower.giant_titan_shooter_split`

**Actives:** none

**Passives**

- **Mind Spell Immunity** — Cost: none (passive)
  - Effect: Immune to mind spells.

### Titan (`h3_giant_upg`)

- Tier 7 | Hire cost: 5000 gold, 2 gemstones | Branch: standard-shooter | Source mechanic: `tower.giant_titan_shooter_split`

**Actives:** none

**Passives**

- **Ranged Attack** — Cost: none (passive)
  - Effect: Shoots at enemy units with 24 shots and no melee penalty.
- **Mind Spell Immunity** — Cost: none (passive)
  - Effect: Immune to mind spells.
- **Black Dragon Hate** — Cost: none (passive)
  - Effect: Deals 150% damage to Black Dragons.
- **Duelist** — Cost: none (passive)
  - Effect: Receives no penalty in Melee range, dealing full Damage.
- **Ranged Attack** — Cost: none (passive)
  - Effect: Can attack enemies at any range. 
Targets {0} or more hexes away take –{1}% Damage per hex (up to –{2}%).
- **Sharpshooter** — Cost: none (passive)
  - Effect: Ranged attacks deal full Ranged Damage at any range.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=0.0

### Storm Titan (`h3_giant_upg_alt`)

- Tier 7 | Hire cost: 5000 gold, 2 gemstones | Branch: alternate-non-shooter | Source mechanic: `tower.giant_titan_shooter_split`

**Actives**

- **Judgement** — Focus: 3; Cooldown: 3; Rank: 5; Attack type: cast
  - Effect: Spend 3 Focus to strike up to 4 enemies for 200 pure damage plus 30 per stack, split across targets.
  - Logic: damageType `magic_pure`; pattern `attack_single_x100`; tags magic_damage

**Passives**

- **Thunderbolt** — Cost: none (passive)
  - Effect: After attacking, has a 40% chance to cast Thunderbolt for 25 damage per Colossus.
- **Mind Spell Immunity** — Cost: none (passive)
  - Effect: Immune to mind spells.

## homm3_inferno

### Imp (`h3_imp`)

- Tier 1 | Hire cost: 50 gold | Branch: base-line | Source mechanic: `inferno.imp_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Familiar (`h3_imp_upg`)

- Tier 1 | Hire cost: 60 gold | Branch: standard-upgrade | Source mechanic: `inferno.imp_line`

**Actives**

- **Energize** — Focus: 1; Cooldown: 2; Rank: 1; Attack type: cast
  - Effect: Spend 1 Focus to give an allied stack +1 Focus.
  - Logic: damageType `none`; pattern `attack_single_x100`

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Vermin (`h3_imp_upg_alt`)

- Tier 1 | Hire cost: 65 gold | Branch: alternate-upgrade | Source mechanic: `inferno.imp_line`

**Actives**

- **Familiar's Gift** — Focus: 1; Cooldown: 2; Rank: 2; Attack type: cast
  - Effect: Spend 1 Focus to transfer 2-6 mana from the enemy hero to your hero.
  - Logic: damageType `none`; pattern `attack_single_x100`; tags ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.
- **Melee Attack** — Cost: none (passive)
  - Effect: Can only attack adjacent enemies. <b>Enemies do not counterattack.</b>
- **Swift Strike** — Cost: none (passive)
  - Effect: Enemies do not counterattack.

### Gog (`h3_gog`)

- Tier 2 | Hire cost: 125 gold | Branch: base-line | Source mechanic: `inferno.gog_line`

**Actives:** none

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1

### Magog (`h3_gog_upg`)

- Tier 2 | Hire cost: 175 gold | Branch: standard-upgrade | Source mechanic: `inferno.gog_line`

**Actives**

- **Magma Shot** — Focus: 2; Cooldown: 2; Rank: 3; Attack type: cast
  - Effect: Spend 2 Focus to hurl a focused blast for 150% pure magic damage.
  - Logic: damageType `magic_pure`; statDmgMult `1.5`; pattern `attack_single_x100`; tags magic_damage, ability

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1

### Amalek (`h3_gog_upg_alt`)

- Tier 2 | Hire cost: 175 gold | Branch: alternate-upgrade | Source mechanic: `inferno.gog_line`

**Actives**

- **Hellfire Burst** — Focus: 1; Cooldown: 2; Rank: 3; Attack type: cast
  - Effect: Spend 1 Focus to throw a quicker blast for 120% pure magic damage.
  - Logic: damageType `magic_pure`; statDmgMult `1.2`; pattern `attack_single_x100`; tags magic_damage, ability

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1

### Hell Hound (`h3_hell_hound`)

- Tier 3 | Hire cost: 200 gold | Branch: base-line | Source mechanic: `inferno.hell_hound_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Cerberus (`h3_hell_hound_upg`)

- Tier 3 | Hire cost: 250 gold | Branch: standard-upgrade | Source mechanic: `inferno.hell_hound_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Melee Attack** — Cost: none (passive)
  - Effect: Can only attack adjacent enemies. <b>Enemies do not counterattack.</b>
- **Swift Strike** — Cost: none (passive)
  - Effect: Enemies do not counterattack.
- **Dragonbreath Strike** — Cost: none (passive)
  - Effect: Deals Damage to the target and <b>any creature</b> on the hex directly behind it.

### Fire Hound (`h3_hell_hound_upg_alt`)

- Tier 3 | Hire cost: 250 gold | Branch: alternate-upgrade | Source mechanic: `inferno.hell_hound_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Dragonbreath Strike** — Cost: none (passive)
  - Effect: Deals Damage to the target and <b>any creature</b> on the hex directly behind it.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Performs an alternative Melee attack.

### Demon (`h3_demon`)

- Tier 4 | Hire cost: 250 gold | Branch: base-line | Source mechanic: `inferno.demon_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Horned Demon (`h3_demon_upg`)

- Tier 4 | Hire cost: 270 gold | Branch: standard-upgrade | Source mechanic: `inferno.demon_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Gore Demon (`h3_demon_upg_alt`)

- Tier 4 | Hire cost: 350 gold | Branch: alternate-upgrade | Source mechanic: `inferno.demon_line`

**Actives**

- **Sapping Strike** — Focus: 1; Cooldown: 1; Rank: 1; Attack type: cast
  - Effect: Spend 1 Focus to weaken an enemy's Attack and Defense for 2 rounds.
  - Logic: buff `magic_shorten_shadow_effect_1`; damageType `none`; pattern `attack_single_x100`; tags ability, debuff_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** tags=melee_attack,normal_damage,basic_attack,counter_attack

### Pit Fiend (`h3_pit_fiend`)

- Tier 5 | Hire cost: 500 gold | Branch: base-line | Source mechanic: `inferno.pit_fiend_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Pit Lord (`h3_pit_fiend_upg`)

- Tier 5 | Hire cost: 700 gold | Branch: standard-upgrade | Source mechanic: `inferno.pit_fiend_line`

**Actives**

- **Animate Dead** — Focus: 2; Cooldown: 3; Rank: 3; Attack type: cast
  - Effect: Spend 2 Focus to revive an allied stack, up to its starting creature count.
  - Logic: damageType `none`; pattern `attack_single_x100`; tags ability, heal_ability, undead_immunities

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Pit Spawn (`h3_pit_fiend_upg_alt`)

- Tier 5 | Hire cost: 700 gold | Branch: alternate-upgrade | Source mechanic: `inferno.pit_fiend_line`

**Actives**

- **Animate Dead** — Focus: 1; Cooldown: 2; Rank: 3; Attack type: cast
  - Effect: Spend 1 Focus to revive an allied stack, up to its starting creature count.
  - Logic: damageType `none`; pattern `attack_single_x100`; tags ability, heal_ability, undead_immunities

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Efreeti (`h3_efreeti`)

- Tier 6 | Hire cost: 900 gold | Branch: base-line | Source mechanic: `inferno.efreeti_line`

**Actives**

- **Ifrit Spark** — Focus: 2; Cooldown: 2; Rank: 3; Attack type: cast
  - Effect: Spend 2 Focus to sear an enemy for 150% pure magic damage.
  - Logic: damageType `magic_pure`; statDmgMult `1.5`; pattern `attack_single_x100`; tags magic_damage, ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.

### Efreet Sultan (`h3_efreeti_upg`)

- Tier 6 | Hire cost: 1100 gold | Branch: standard-upgrade | Source mechanic: `inferno.efreeti_line`

**Actives**

- **Sultan's Flame** — Focus: 2; Cooldown: 2; Rank: 3; Attack type: cast
  - Effect: Spend 2 Focus to splash nearby enemies for 90% pure magic damage.
  - Logic: damageType `magic_pure`; statDmgMult `0.9`; pattern `attack_rumble_x1_x100`; tags magic_damage, ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.

### Efreet Sufi (`h3_efreeti_upg_alt`)

- Tier 6 | Hire cost: 1200 gold | Branch: alternate-upgrade | Source mechanic: `inferno.efreeti_line`

**Actives**

- **Vengeance** — Focus: 3; Cooldown: 3; Rank: 4; Attack type: cast
  - Effect: Spend 3 Focus to mark an allied stack for 3 rounds; melee attackers take 60 pure damage plus 15 per stack.
  - Logic: buff `magic_vengeance_effect_0`; damageType `none`; pattern `attack_single_x100`

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.

### Devil (`h3_devil`)

- Tier 7 | Hire cost: 1 mercury, 2700 gold | Branch: base-line | Source mechanic: `inferno.devil_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Blink** — Cost: none (passive)
  - Effect: Teleports directly to destination hex, ignoring obstacles and traps.
- **Melee Attack** — Cost: none (passive)
  - Effect: Can only attack adjacent enemies. <b>Enemies do not counterattack.</b>
- **Swift Strike** — Cost: none (passive)
  - Effect: Enemies do not counterattack.

### Arch Devil (`h3_devil_upg`)

- Tier 7 | Hire cost: 2 mercury, 4500 gold | Branch: standard-upgrade | Source mechanic: `inferno.devil_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Blink** — Cost: none (passive)
  - Effect: Teleports directly to destination hex, ignoring obstacles and traps.
- **Melee Attack** — Cost: none (passive)
  - Effect: Can only attack adjacent enemies. <b>Enemies do not counterattack.</b>
- **Swift Strike** — Cost: none (passive)
  - Effect: Enemies do not counterattack.

### Arch Demon (`h3_devil_upg_alt`)

- Tier 7 | Hire cost: 5000 gold, 2 mercury | Branch: alternate-upgrade | Source mechanic: `inferno.devil_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Blink** — Cost: none (passive)
  - Effect: Teleports directly to destination hex, ignoring obstacles and traps.
- **Melee Attack** — Cost: none (passive)
  - Effect: Can only attack adjacent enemies. <b>Enemies do not counterattack.</b>
- **Swift Strike** — Cost: none (passive)
  - Effect: Enemies do not counterattack.

## homm3_necropolis

### Skeleton (`h3_skeleton`)

- Tier 1 | Hire cost: 60 gold | Branch: base-line | Source mechanic: `necropolis.skeleton_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Passive 1** — Cost: none (passive)
  - Effect: *(no English unitsAbility text)*

### Skeleton Warrior (`h3_skeleton_upg`)

- Tier 1 | Hire cost: 70 gold | Branch: standard-upgrade | Source mechanic: `necropolis.skeleton_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Passive 1** — Cost: none (passive)
  - Effect: *(no English unitsAbility text)*

### Skeleton Archer (`h3_skeleton_upg_alt`)

- Tier 1 | Hire cost: 70 gold | Branch: alternate-upgrade | Source mechanic: `necropolis.skeleton_line`

**Actives:** none

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.
- **Sharpshooter** — Cost: none (passive)
  - Effect: Ranged attacks deal full Ranged Damage at any range.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=0.0

### Walking Dead (`h3_walking_dead`)

- Tier 2 | Hire cost: 100 gold | Branch: base-line | Source mechanic: `necropolis.walking_dead_line`

**Actives**

- **Shambling Grasp** — Focus: 2; Cooldown: 2; Rank: 1; Attack type: melee
  - Effect: Spend 2 Focus in melee range to give an enemy -2 Attack and -2 Defense for 1 round.
  - Logic: buff `magic_shorten_shadow_effect_1`; damageType `none`; pattern `attack_single_x100`; tags ability, debuff_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Passive 1** — Cost: none (passive)
  - Effect: *(no English unitsAbility text)*

### Zombie (`h3_walking_dead_upg`)

- Tier 2 | Hire cost: 125 gold | Branch: standard-upgrade | Source mechanic: `necropolis.walking_dead_line`

**Actives**

- **Zombie Clutch** — Focus: 1; Cooldown: 1; Rank: 3; Attack type: melee
  - Effect: Spend 1 Focus in melee range to give an enemy -2 Attack and -2 Defense for 2 rounds.
  - Logic: buff `magic_shorten_shadow_effect_1`; damageType `none`; pattern `attack_single_x100`; tags ability, debuff_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Passive 1** — Cost: none (passive)
  - Effect: *(no English unitsAbility text)*

### Rot Zombie (`h3_walking_dead_upg_alt`)

- Tier 2 | Hire cost: 150 gold | Branch: alternate-upgrade | Source mechanic: `necropolis.walking_dead_line`

**Actives**

- **Rotting Ray** — Focus: 1; Cooldown: 1; Rank: 1; Attack type: melee
  - Effect: Spend 1 Focus without ending the turn to permanently reduce the target's Defense by 1.
  - Logic: buff `pet_debuff`; damageType `none`; pattern `attack_single_x100`; tags ability, debuff_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Passive 1** — Cost: none (passive)
  - Effect: *(no English unitsAbility text)*

### Wight (`h3_wight`)

- Tier 3 | Hire cost: 200 gold | Branch: base-line | Source mechanic: `necropolis.wight_line`

**Actives:** none

**Passives**

- **Melee Attack** — Cost: none (passive)
  - Effect: Attacks an adjacent enemy unit.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.
- **Regeneration** — Cost: none (passive)
  - Effect: Restores health at the start of the unit's turn.

### Wraith (`h3_wight_upg`)

- Tier 3 | Hire cost: 230 gold | Branch: standard-upgrade | Source mechanic: `necropolis.wight_line`

**Actives**

- **Mana Channel** — Focus: 2; Cooldown: 2; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to transfer 2-6 mana from the enemy hero to your hero.
  - Logic: damageType `none`; pattern `attack_single_x100`; tags ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.
- **Regeneration** — Cost: none (passive)
  - Effect: Restores health at the start of the unit's turn.

### Banshee (`h3_wight_upg_alt`)

- Tier 3 | Hire cost: 300 gold | Branch: alternate-upgrade | Source mechanic: `necropolis.wight_line`

**Actives**

- **Psychic Scream** — Focus: 2; Cooldown: 2; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus without ending the turn to deal 40 pure damage plus 8 per stack.
  - Logic: damageType `absolute`; pattern `attack_single_x100`; tags absolute_damage

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.
- **Regeneration** — Cost: none (passive)
  - Effect: Restores health at the start of the unit's turn.

### Vampire (`h3_vampire`)

- Tier 4 | Hire cost: 360 gold | Branch: base-line | Source mechanic: `necropolis.vampire_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.
- **Melee Attack** — Cost: none (passive)
  - Effect: Can only attack adjacent enemies. <b>Enemies do not counterattack.</b>
- **Swift Strike** — Cost: none (passive)
  - Effect: Enemies do not counterattack.

### Vampire Lord (`h3_vampire_upg`)

- Tier 4 | Hire cost: 500 gold | Branch: standard-upgrade | Source mechanic: `necropolis.vampire_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.
- **Melee Attack** — Cost: none (passive)
  - Effect: Can only attack adjacent enemies. <b>Enemies do not counterattack.</b>
- **Swift Strike** — Cost: none (passive)
  - Effect: Enemies do not counterattack.
- **Vampirism** — Cost: none (passive)
  - Effect: Each attack restores {0}% of Damage dealt as HP to this creature. This can revive fallen units.

### Vampire Prince (`h3_vampire_upg_alt`)

- Tier 4 | Hire cost: 500 gold | Branch: alternate-upgrade | Source mechanic: `necropolis.vampire_line`

**Actives**

- **Blinding Strike** — Focus: 3; Cooldown: 3; Rank: 3; Attack type: melee
  - Effect: Spend 3 Focus to attack for 100% normal damage and blind the enemy for 2 rounds, removed if it takes damage.
  - Logic: buff `unicorn_blind`; damageType `normal`; pattern `attack_single_x100`; tags melee_attack, normal_damage, basic_attack, ability, armed_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.
- **Melee Attack** — Cost: none (passive)
  - Effect: Can only attack adjacent enemies. <b>Enemies do not counterattack.</b>
- **Swift Strike** — Cost: none (passive)
  - Effect: Enemies do not counterattack.
- **Vampirism** — Cost: none (passive)
  - Effect: Each attack restores {0}% of Damage dealt as HP to this creature. This can revive fallen units.

### Lich (`h3_lich`)

- Tier 5 | Hire cost: 550 gold | Branch: base-line | Source mechanic: `necropolis.lich_line`

**Actives:** none

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.
- **Area Strike** — Cost: none (passive)
  - Effect: Deals Damage to the target and <b>all hexes</b> around it.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1

### Power Lich (`h3_lich_upg`)

- Tier 5 | Hire cost: 600 gold | Branch: standard-upgrade | Source mechanic: `necropolis.lich_line`

**Actives:** none

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.
- **Area Strike** — Cost: none (passive)
  - Effect: Deals Damage to the target and <b>all hexes</b> around it.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1

### Lich Master (`h3_lich_upg_alt`)

- Tier 5 | Hire cost: 600 gold | Branch: alternate-upgrade | Source mechanic: `necropolis.lich_line`

**Actives**

- **Animate Dead** — Focus: 2; Cooldown: 3; Rank: 3; Attack type: cast
  - Effect: Spend 2 Focus to revive an allied stack, up to its starting creature count.
  - Logic: damageType `none`; pattern `attack_single_x100`; tags ability, heal_ability, undead_immunities

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.
- **Sharpshooter** — Cost: none (passive)
  - Effect: Ranged attacks deal full Ranged Damage at any range.
- **Area Strike** — Cost: none (passive)
  - Effect: Deals Damage to the target and <b>all hexes</b> around it.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=0.0

### Black Knight (`h3_black_knight`)

- Tier 6 | Hire cost: 1200 gold | Branch: base-line | Source mechanic: `necropolis.black_knight_line`

**Actives**

- **Curse** — Focus: 2; Cooldown: 2; Rank: 1; Attack type: melee
  - Effect: Spend 2 Focus to reduce an enemy's normal damage by 20% and force minimum damage for 1 round.
  - Logic: buff `magic_unnatural_calm_effect_1_special`; damageType `none`; pattern `attack_single_x100`; tags ability, debuff_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Passive 1** — Cost: none (passive)
  - Effect: *(no English unitsAbility text)*

### Dread Knight (`h3_black_knight_upg`)

- Tier 6 | Hire cost: 1500 gold | Branch: standard-upgrade | Source mechanic: `necropolis.black_knight_line`

**Actives**

- **Dread Curse** — Focus: 1; Cooldown: 1; Rank: 1; Attack type: melee
  - Effect: Spend 1 Focus to reduce an enemy's normal damage by 20% and force minimum damage for 2 rounds.
  - Logic: buff `magic_unnatural_calm_effect_1_special`; damageType `none`; pattern `attack_single_x100`; tags ability, debuff_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Passive 1** — Cost: none (passive)
  - Effect: *(no English unitsAbility text)*

### Dreadtaur (`h3_black_knight_upg_alt`)

- Tier 6 | Hire cost: 1500 gold | Branch: alternate-upgrade | Source mechanic: `necropolis.black_knight_line`

**Actives**

- **Vulnerability** — Focus: 2; Cooldown: 2; Rank: 4; Attack type: cast
  - Effect: Spend 2 Focus to make an enemy take 30% more damage for 1 round.
  - Logic: buff `magic_vulnerability_effect_1`; damageType `none`; pattern `attack_single_x100`

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Passive 1** — Cost: none (passive)
  - Effect: *(no English unitsAbility text)*

### Bone Dragon (`h3_bone_dragon`)

- Tier 7 | Hire cost: 1800 gold | Branch: base-line | Source mechanic: `necropolis.bone_dragon_line`

**Actives**

- **Aging Curse** — Focus: 1; Cooldown: 1; Rank: 1; Attack type: melee
  - Effect: Spend 1 Focus to reduce an enemy's normal damage by 20% and force minimum damage for 2 rounds.
  - Logic: buff `magic_unnatural_calm_effect_1_special`; damageType `none`; pattern `attack_single_x100`; tags ability, debuff_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.

### Ghost Dragon (`h3_bone_dragon_upg`)

- Tier 7 | Hire cost: 1 mercury, 3000 gold | Branch: standard-upgrade | Source mechanic: `necropolis.bone_dragon_line`

**Actives**

- **Ghostly Curse** — Focus: 1; Cooldown: 1; Rank: 1; Attack type: melee
  - Effect: Spend 1 Focus to reduce an enemy's normal damage by 20% and force minimum damage for 3 rounds.
  - Logic: buff `magic_unnatural_calm_effect_1_special`; damageType `none`; pattern `attack_single_x100`; tags ability, debuff_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.

### Spectral Dragon (`h3_bone_dragon_upg_alt`)

- Tier 7 | Hire cost: 3500 gold, 2 mercury | Branch: alternate-upgrade | Source mechanic: `necropolis.bone_dragon_line`

**Actives**

- **Naira's Kiss** — Focus: 2; Cooldown: 2; Rank: 5; Attack type: cast
  - Effect: Spend 2 Focus to mark an enemy for 1 round; when it acts, it takes 200 pure damage plus 15 per stack.
  - Logic: buff `magic_nairas_kiss_effect_1`; damageType `none`; pattern `attack_single_x100`

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.

## homm3_dungeon

### Troglodyte (`h3_troglodyte`)

- Tier 1 | Hire cost: 50 gold | Branch: base-line | Source mechanic: `dungeon.troglodyte_line`

**Actives**

- **Cave Bash** — Focus: 3; Cooldown: 3; Rank: 3; Attack type: melee
  - Effect: Spend 3 Focus to club an enemy for 50% normal damage and suppress 1 retaliation.
  - Logic: damageType `normal`; statDmgMult `0.5`; pattern `attack_single_x100`; tags melee_attack, normal_damage, basic_attack, ability
  - Intended (override): **Cave Bash** — Spend 3 Focus to club an enemy into a one-round stun.
  - Intended cost: Focus 3, CD 3

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Infernal Troglodyte (`h3_troglodyte_upg`)

- Tier 1 | Hire cost: 65 gold | Branch: standard-upgrade | Source mechanic: `dungeon.troglodyte_line`

**Actives**

- **Tunnel Breaker** — Focus: 2; Cooldown: 2; Rank: 3; Attack type: melee
  - Effect: Spend 2 Focus to stagger an enemy for 75% normal damage and suppress 1 retaliation.
  - Logic: damageType `normal`; statDmgMult `0.75`; pattern `attack_single_x100`; tags melee_attack, normal_damage, basic_attack, ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Chthonian (`h3_troglodyte_upg_alt`)

- Tier 1 | Hire cost: 75 gold | Branch: alternate-upgrade | Source mechanic: `dungeon.troglodyte_line`

**Actives**

- **Transport** — Focus: 2; Cooldown: 2; Rank: 1; Attack type: cast
  - Effect: Spend 2 Focus to teleport an allied unit to a free hex within 4 hexes.
  - Logic: pattern `attack_single_buff`; tags magic, teleport

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Blink** — Cost: none (passive)
  - Effect: Moves through obstacles when moving

### Harpy (`h3_harpy`)

- Tier 2 | Hire cost: 130 gold | Branch: base-line | Source mechanic: `dungeon.harpy_line`

**Actives**

- **Hit and Run** — Focus: none (dontUseEnergy); Cooldown: 0; Rank: 1; Attack type: melee
  - Effect: Attack for 50% normal damage, then return to this unit's original position.
  - Logic: damageType `normal`; statDmgMult `0.5`; pattern `attack_single_x100`; tags melee_attack, normal_damage, basic_attack, armed_ability, armed_ability_assassin

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.

### Harpy Hag (`h3_harpy_upg`)

- Tier 2 | Hire cost: 170 gold | Branch: standard-upgrade | Source mechanic: `dungeon.harpy_line`

**Actives:** none

**Passives**

- **Melee Attack** — Cost: none (passive)
  - Effect: Attacks an adjacent enemy unit.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.
- **Melee Attack** — Cost: none (passive)
  - Effect: Can only attack adjacent enemies. <b>Enemies do not counterattack.</b>
- **Swift Strike** — Cost: none (passive)
  - Effect: Enemies do not counterattack.

**Alternate attacks**

- **Hit and Run** — Focus: none (`ability_no_energy`)
  - Effect: Attack for 50% normal damage, then return to this unit's original position.

### Fury (`h3_harpy_upg_alt`)

- Tier 2 | Hire cost: 170 gold | Branch: alternate-upgrade | Source mechanic: `dungeon.harpy_line`

**Actives:** none

**Passives**

- **Melee Attack** — Cost: none (passive)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.
  - Logic: sequence=add_attack_after_counter_melee
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.
- **Double Strike** — Cost: none (passive)
  - Effect: Strikes twice when performing attacks.

**Alternate attacks**

- **Hit and Run** — Focus: none (`ability_no_energy`)
  - Effect: Attack, then retreat

### Beholder (`h3_beholder`)

- Tier 3 | Hire cost: 250 gold | Branch: base-line | Source mechanic: `dungeon.beholder_line`

**Actives:** none

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.
- **Ranged Attack** — Cost: none (passive)
  - Effect: Can attack enemies at any range. 
Targets {0} or more hexes away take –{1}% Damage per hex (up to –{2}%).
- **Duelist** — Cost: none (passive)
  - Effect: Receives no penalty in Melee range, dealing full Damage.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1

### Evil Eye (`h3_beholder_upg`)

- Tier 3 | Hire cost: 280 gold | Branch: standard-upgrade | Source mechanic: `dungeon.beholder_line`

**Actives:** none

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.
- **Ranged Attack** — Cost: none (passive)
  - Effect: Can attack enemies at any range. 
Targets {0} or more hexes away take –{1}% Damage per hex (up to –{2}%).
- **Duelist** — Cost: none (passive)
  - Effect: Receives no penalty in Melee range, dealing full Damage.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1

### Fargazer (`h3_beholder_upg_alt`)

- Tier 3 | Hire cost: 300 gold | Branch: alternate-upgrade | Source mechanic: `dungeon.beholder_line`

**Actives:** none

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.
- **Ranged Attack** — Cost: none (passive)
  - Effect: Can attack enemies at any range. 
Targets {0} or more hexes away take –{1}% Damage per hex (up to –{2}%).
- **Duelist** — Cost: none (passive)
  - Effect: Receives no penalty in Melee range, dealing full Damage.
- **Sharpshooter** — Cost: none (passive)
  - Effect: Ranged attacks deal full Ranged Damage at any range.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=0.0

### Medusa (`h3_medusa`)

- Tier 4 | Hire cost: 300 gold | Branch: base-line | Source mechanic: `dungeon.medusa_line`

**Actives**

- **Stone Gaze** — Focus: 2; Cooldown: 2; Rank: 2; Attack type: melee
  - Effect: Spend 2 Focus to petrify an enemy for 1 round.
  - Logic: buff `medusa_stone`; damageType `none`; pattern `attack_single_x100`; tags ability, dragon_immunities, embodiment_immunities

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.
- **Ranged Attack** — Cost: none (passive)
  - Effect: Can attack enemies at any range. 
Targets {0} or more hexes away take –{1}% Damage per hex (up to –{2}%).
- **Duelist** — Cost: none (passive)
  - Effect: Receives no penalty in Melee range, dealing full Damage.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1

### Medusa Queen (`h3_medusa_upg`)

- Tier 4 | Hire cost: 400 gold | Branch: standard-upgrade | Source mechanic: `dungeon.medusa_line`

**Actives**

- **Stone Gaze** — Focus: 2; Cooldown: 1; Rank: 2; Attack type: melee
  - Effect: Spend 2 Focus to petrify an enemy for 1 round.
  - Logic: buff `medusa_stone`; damageType `none`; pattern `attack_single_x100`; tags ability, dragon_immunities, embodiment_immunities

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.
- **Ranged Attack** — Cost: none (passive)
  - Effect: Can attack enemies at any range. 
Targets {0} or more hexes away take –{1}% Damage per hex (up to –{2}%).
- **Duelist** — Cost: none (passive)
  - Effect: Receives no penalty in Melee range, dealing full Damage.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1

### Medusa Warrior (`h3_medusa_upg_alt`)

- Tier 4 | Hire cost: 360 gold | Branch: alternate-upgrade | Source mechanic: `dungeon.medusa_line`

**Actives**

- **Slither Away** — Focus: 1; Cooldown: 1; Rank: 1; Attack type: move
  - Effect: Spend 1 Focus to move to another reachable hex.
  - Logic: pattern `attack_single_buff`; tags ability, movement_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Ranged Attack** — Cost: none (passive)
  - Effect: Can attack enemies at any range. 
Targets {0} or more hexes away take –{1}% Damage per hex (up to –{2}%).
- **Duelist** — Cost: none (passive)
  - Effect: Receives no penalty in Melee range, dealing full Damage.

### Minotaur (`h3_minotaur`)

- Tier 5 | Hire cost: 500 gold | Branch: base-line | Source mechanic: `dungeon.minotaur_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Minotaur King (`h3_minotaur_upg`)

- Tier 5 | Hire cost: 575 gold | Branch: standard-upgrade | Source mechanic: `dungeon.minotaur_line`

**Actives**

- **Unyielding Will** — Focus: 2; Cooldown: 2; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to ignore attackers' Attack values until the end of the round.
  - Logic: buff `minos_buff`; pattern `attack_single_buff`; tags ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Minotaur Taskmaster (`h3_minotaur_upg_alt`)

- Tier 5 | Hire cost: 700 gold | Branch: alternate-upgrade | Source mechanic: `dungeon.minotaur_line`

**Actives**

- **Earthshatter** — Focus: 2; Cooldown: 2; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to make enemies target this stack until the end of the round.
  - Logic: buff `ent_taunt_buff`; pattern `attack_single_buff`; tags ability, buff_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Manticore (`h3_manticore`)

- Tier 6 | Hire cost: 850 gold | Branch: base-line | Source mechanic: `dungeon.manticore_line`

**Actives**

- **Barbed Pounce** — Focus: 3; Cooldown: 3; Rank: 3; Attack type: melee
  - Effect: Spend 3 Focus to pounce for 75% normal damage and paralyze the target for 1 round.
  - Logic: buff `gorilla_stun`; damageType `normal`; statDmgMult `0.75`; pattern `attack_single_x100`; tags melee_attack, normal_damage, basic_attack, ability, armed_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.

### Scorpicore (`h3_manticore_upg`)

- Tier 6 | Hire cost: 1050 gold | Branch: standard-upgrade | Source mechanic: `dungeon.manticore_line`

**Actives**

- **Scorpion Maul** — Focus: 2; Cooldown: 2; Rank: 3; Attack type: melee
  - Effect: Spend 2 Focus to maul for 85% normal damage and paralyze the target for 1 round.
  - Logic: buff `gorilla_stun`; damageType `normal`; statDmgMult `0.85`; pattern `attack_single_x100`; tags melee_attack, normal_damage, basic_attack, ability, armed_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.

### Chimera (`h3_manticore_upg_alt`)

- Tier 6 | Hire cost: 1250 gold | Branch: alternate-upgrade | Source mechanic: `dungeon.manticore_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.
- **Dragonbreath Strike** — Cost: none (passive)
  - Effect: Deals Damage to the target and <b>any creature</b> on the hex directly behind it.

### Red Dragon (`h3_red_dragon`)

- Tier 7 | Hire cost: 1 mercury, 2500 gold | Branch: base-line | Source mechanic: `dungeon.red_dragon_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.
- **Dragonbreath Strike** — Cost: none (passive)
  - Effect: Deals Damage to the target and <b>any creature</b> on the hex directly behind it.
- **Magic Immunity III** — Cost: none (passive)
  - Effect: Immune to tier‑3 and lower spells.

### Black Dragon (`h3_red_dragon_upg`)

- Tier 7 | Hire cost: 2 mercury, 4000 gold | Branch: standard-upgrade | Source mechanic: `dungeon.red_dragon_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.
- **Dragonbreath Strike** — Cost: none (passive)
  - Effect: Deals Damage to the target and <b>any creature</b> on the hex directly behind it.
- **Magic Immunity V** — Cost: none (passive)
  - Effect: Immune to tier‑5 and lower spells.

### Shadow Dragon (`h3_red_dragon_upg_alt`)

- Tier 7 | Hire cost: 4000 gold, 2 mercury | Branch: alternate-upgrade | Source mechanic: `dungeon.red_dragon_line`

**Actives**

- **Poison Sting** — Focus: 1; Cooldown: 1; Rank: 1; Attack type: melee
  - Effect: Spend 1 Focus to attack for 100% normal damage and reduce the target's maximum health by 20% for 1 round.
  - Logic: buff `magic_fatal_decay_effect_1`; damageType `normal`; pattern `attack_single_x100`; tags melee_attack, normal_damage, basic_attack, ability, poison

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.
- **Dragonbreath Strike** — Cost: none (passive)
  - Effect: Deals Damage to the target and <b>any creature</b> on the hex directly behind it.
- **Magic Immunity V** — Cost: none (passive)
  - Effect: Immune to tier‑5 and lower spells.

## homm3_stronghold

### Goblin (`h3_goblin`)

- Tier 1 | Hire cost: 40 gold | Branch: base-line | Source mechanic: `stronghold.goblin_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Hobgoblin (`h3_goblin_upg`)

- Tier 1 | Hire cost: 50 gold | Branch: standard-upgrade | Source mechanic: `stronghold.goblin_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Alert I** — Cost: none (passive)
  - Effect: Can counterattack up to twice per round.

### Goblin Trapper (`h3_goblin_upg_alt`)

- Tier 1 | Hire cost: 60 gold | Branch: alternate-upgrade | Source mechanic: `stronghold.goblin_line`

**Actives**

- **Snare Trap** — Focus: 1; Cooldown: 1; Rank: 1; Attack type: cast
  - Effect: Spend 1 Focus to place a snare trap on a target hex.
  - Logic: damageType `none`; pattern `attack_single_x100`; tags ability, trap_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Wolf Rider (`h3_wolf_rider`)

- Tier 2 | Hire cost: 100 gold | Branch: base-line | Source mechanic: `stronghold.wolf_rider_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Wolf Raider (`h3_wolf_rider_upg`)

- Tier 2 | Hire cost: 140 gold | Branch: standard-upgrade | Source mechanic: `stronghold.wolf_rider_line`

**Actives:** none

**Passives**

- **Melee Attack** — Cost: none (passive)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.
  - Logic: sequence=add_attack_after_counter_melee
- **Ferocity** — Cost: none (passive)
  - Effect: After this unit counterattacks in melee, it immediately makes one extra melee attack.

### Boar Rider (`h3_wolf_rider_upg_alt`)

- Tier 2 | Hire cost: 140 gold | Branch: alternate-upgrade | Source mechanic: `stronghold.wolf_rider_line`

**Actives**

- **Boar Charge** — Focus: 1; Cooldown: 1; Rank: 1; Attack type: melee
  - Effect: Spend 1 Focus to make a 100% melee attack and give the target -5 Luck for 1 round.
  - Logic: buff `h3_wolf_rider_upg_alt_charge_debuff`; damageType `normal`; pattern `attack_single_x100`; tags melee_attack, normal_damage, ability, debuff_ability, armed_ability, armed_ability_h3_wolf_rider_upg_alt, charge

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Orc (`h3_orc`)

- Tier 3 | Hire cost: 150 gold | Branch: base-line | Source mechanic: `stronghold.orc_line`

**Actives**

- **Hamstring** — Focus: 1; Cooldown: 1; Rank: 1; Attack type: shoot
  - Effect: Spend 1 Focus to make a 50% ranged attack and give the target -2 Speed for 1 round.
  - Logic: buff `h3_orc_hamstring_debuff`; damageType `normal`; statDmgMult `0.5`; pattern `attack_single_x100`; tags normal_damage, ability, debuff_ability, armed_ability, armed_ability_h3_orc, hamstring

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1

### Orc Chieftain (`h3_orc_upg`)

- Tier 3 | Hire cost: 165 gold | Branch: standard-upgrade | Source mechanic: `stronghold.orc_line`

**Actives**

- **Hamstring** — Focus: 1; Cooldown: 1; Rank: 1; Attack type: shoot
  - Effect: Spend 1 Focus to make a 100% ranged attack and give the target -3 Speed for 1 round.
  - Logic: buff `h3_orc_upg_hamstring_debuff`; damageType `normal`; pattern `attack_single_x100`; tags normal_damage, ability, debuff_ability, armed_ability, armed_ability_h3_orc_upg, hamstring

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.
- **Command Shot** — Cost: none (passive)
  - Effect: This creature deals 10% more ranged attack damage while directing the volley.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1

### Orc Berserker (`h3_orc_upg_alt`)

- Tier 3 | Hire cost: 180 gold | Branch: alternate-upgrade | Source mechanic: `stronghold.orc_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

**Alternate attacks**

- **Crude Chop** — Focus: none (`ability_no_energy`)
  - Effect: Melee attack for half damage when adjacent to the target.

### Ogre (`h3_ogre`)

- Tier 4 | Hire cost: 300 gold | Branch: base-line | Source mechanic: `stronghold.ogre_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Guard Formation** — Cost: none (passive)
  - Effect: This creature takes 10% less damage from basic attacks.

### Ogre Mage (`h3_ogre_upg`)

- Tier 4 | Hire cost: 400 gold | Branch: standard-upgrade | Source mechanic: `stronghold.ogre_line`

**Actives**

- **Bloodlust** — Focus: 2; Cooldown: 2; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus without ending the turn to give an allied stack +6 Attack for 2 rounds.
  - Logic: buff `h3_ogre_upg_bloodlust`; pattern `attack_single_buff`; tags ability, buff_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Ogre Brute (`h3_ogre_upg_alt`)

- Tier 4 | Hire cost: 400 gold | Branch: alternate-upgrade | Source mechanic: `stronghold.ogre_line`

**Actives**

- **Brutal Rush** — Focus: 2; Cooldown: 1; Rank: 2; Attack type: melee
  - Effect: Spend 2 Focus to attack in melee for 100% normal damage, then return to the starting hex.
  - Logic: damageType `normal`; pattern `attack_single_x100`; tags ability, melee_attack, normal_damage, armed_ability, armed_ability_h3_ogre_upg_alt, attack_and_return

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Roc (`h3_roc`)

- Tier 5 | Hire cost: 600 gold | Branch: base-line | Source mechanic: `stronghold.roc_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.

### Thunderbird (`h3_roc_upg`)

- Tier 5 | Hire cost: 700 gold | Branch: standard-upgrade | Source mechanic: `stronghold.roc_line`

**Actives**

- **Lightning Strike** — Focus: 2; Cooldown: 2; Rank: 2; Attack type: melee
  - Effect: Spend 2 Focus without ending the turn to strike one enemy for 120% normal damage.
  - Logic: damageType `normal`; statDmgMult `1.2`; pattern `attack_single_x100`; tags ability, armed_ability_h3_roc, lightning_strike, dragon_immunities, embodiment_immunities

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.

### Shahrokh (`h3_roc_upg_alt`)

- Tier 5 | Hire cost: 700 gold | Branch: alternate-upgrade | Source mechanic: `stronghold.roc_line`

**Actives:** none

**Passives**

- **Melee Attack** — Cost: none (passive)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.
  - Logic: sequence=add_attack_after_counter_melee
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.
- **Double Strike** — Cost: none (passive)
  - Effect: Strikes twice when performing attacks.

### Cyclops (`h3_cyclops`)

- Tier 6 | Hire cost: 750 gold | Branch: base-line | Source mechanic: `stronghold.cyclops_line`

**Actives:** none

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5

### Cyclops King (`h3_cyclops_upg`)

- Tier 6 | Hire cost: 1100 gold | Branch: standard-upgrade | Source mechanic: `stronghold.cyclops_line`

**Actives:** none

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5

### Blood-Eyed Cyclops (`h3_cyclops_upg_alt`)

- Tier 6 | Hire cost: 1000 gold | Branch: alternate-upgrade | Source mechanic: `stronghold.cyclops_line`

**Actives:** none

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.
- **Ranged Attack** — Cost: none (passive)
  - Effect: Can attack enemies at any range. Replaced with a weaker Melee attack if an enemy is adjacent. –{0}% Melee Damage.
- **Siege Thrower** — Cost: none (passive)
  - Effect: Ranged attacks ignore distance penalties.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5

### Behemoth (`h3_behemoth`)

- Tier 7 | Hire cost: 1500 gold | Branch: base-line | Source mechanic: `stronghold.behemoth_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Armor Rend** — Cost: none (passive)
  - Effect: Attacks ignore 40% of enemy Attack.

### Ancient Behemoth (`h3_behemoth_upg`)

- Tier 7 | Hire cost: 1 crystals, 3000 gold | Branch: standard-upgrade | Source mechanic: `stronghold.behemoth_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Ancient Armor Rend** — Cost: none (passive)
  - Effect: Attacks ignore 80% of enemy Attack.

### Ghost Behemoth (`h3_behemoth_upg_alt`)

- Tier 7 | Hire cost: 2 crystals, 3000 gold | Branch: alternate-upgrade | Source mechanic: `stronghold.behemoth_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.
- **Ghostly Armor Rend** — Cost: none (passive)
  - Effect: Attacks ignore 60% of enemy Attack.

## homm3_fortress

### Gnoll (`h3_gnoll`)

- Tier 1 | Hire cost: 50 gold | Branch: base-line | Source mechanic: `fortress.gnoll_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Gnoll Marauder (`h3_gnoll_upg`)

- Tier 1 | Hire cost: 70 gold | Branch: standard-upgrade | Source mechanic: `fortress.gnoll_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Gnoll Shaman (`h3_gnoll_upg_alt`)

- Tier 1 | Hire cost: 70 gold | Branch: alternate-upgrade | Source mechanic: `fortress.gnoll_line`

**Actives**

- **Shorten Shadow** — Focus: 1; Cooldown: 2; Rank: 1; Attack type: cast
  - Effect: Spend 1 Focus to lower an enemy's Attack and Defense for 1 round.
  - Logic: buff `magic_shorten_shadow_effect_0`; damageType `none`; pattern `attack_single_x100`

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Lizardman (`h3_lizardman`)

- Tier 2 | Hire cost: 110 gold | Branch: base-line | Source mechanic: `fortress.lizardman_line`

**Actives:** none

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1

### Lizard Warrior (`h3_lizardman_upg`)

- Tier 2 | Hire cost: 140 gold | Branch: standard-upgrade | Source mechanic: `fortress.lizardman_line`

**Actives:** none

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1

### Lizard Assassin (`h3_lizardman_upg_alt`)

- Tier 2 | Hire cost: 170 gold | Branch: alternate-upgrade | Source mechanic: `fortress.lizardman_line`

**Actives**

- **Poison Shot** — Focus: 1; Cooldown: 1; Rank: 1; Attack type: melee
  - Effect: Spend 1 Focus to attack for 100% normal damage and poison the target for 24 pure damage plus 6 per stack for 2 rounds.
  - Logic: buff `frog_poison`; damageType `normal`; pattern `attack_single_x100`; tags melee_attack, normal_damage, basic_attack, ability, poison

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1

### Serpent Fly (`h3_serpent_fly`)

- Tier 3 | Hire cost: 220 gold | Branch: base-line | Source mechanic: `fortress.serpent_fly_line`

**Actives**

- **Dispel Strike** — Focus: 1; Cooldown: 1; Rank: 1; Attack type: melee
  - Effect: Spend 1 Focus without ending the turn to strike for 100% normal damage and remove positive effects from the enemy.
  - Logic: damageType `normal`; pattern `attack_single_x100`; tags melee_attack, normal_damage, basic_attack, ability, dispel_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.

### Dragon Fly (`h3_serpent_fly_upg`)

- Tier 3 | Hire cost: 240 gold | Branch: standard-upgrade | Source mechanic: `fortress.serpent_fly_line`

**Actives**

- **Weakening Dispel** — Focus: 1; Cooldown: 1; Rank: 1; Attack type: melee
  - Effect: Spend 1 Focus without ending the turn to strike for 100% normal damage, remove positive effects, and weaken the enemy for 1 round.
  - Logic: buff `magic_shorten_shadow_effect_1`; damageType `normal`; pattern `attack_single_x100`; tags melee_attack, normal_damage, basic_attack, ability, dispel_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.

### Damsel Fly (`h3_serpent_fly_upg_alt`)

- Tier 3 | Hire cost: 240 gold | Branch: alternate-upgrade | Source mechanic: `fortress.serpent_fly_line`

**Actives**

- **Dispel Strike** — Focus: 1; Cooldown: 1; Rank: 1; Attack type: melee
  - Effect: Spend 1 Focus without ending the turn to strike for 100% normal damage and remove positive effects from the enemy.
  - Logic: damageType `normal`; pattern `attack_single_x100`; tags melee_attack, normal_damage, basic_attack, ability, dispel_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.

### Basilisk (`h3_basilisk`)

- Tier 4 | Hire cost: 325 gold | Branch: base-line | Source mechanic: `fortress.basilisk_line`

**Actives**

- **Stone Gaze** — Focus: 2; Cooldown: 2; Rank: 2; Attack type: melee
  - Effect: Spend 2 Focus to petrify an enemy for 1 round.
  - Logic: buff `medusa_stone`; damageType `none`; statDmgMult `0.0`; pattern `attack_single_x100`; tags ability, dragon_immunities, embodiment_immunities

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Greater Basilisk (`h3_basilisk_upg`)

- Tier 4 | Hire cost: 400 gold | Branch: standard-upgrade | Source mechanic: `fortress.basilisk_line`

**Actives**

- **Stone Gaze** — Focus: 2; Cooldown: 1; Rank: 2; Attack type: melee
  - Effect: Spend 2 Focus to petrify an enemy for 1 round.
  - Logic: buff `medusa_stone`; damageType `none`; statDmgMult `0.0`; pattern `attack_single_x100`; tags ability, dragon_immunities, embodiment_immunities

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Basilisk Flamespitter (`h3_basilisk_upg_alt`)

- Tier 4 | Hire cost: 400 gold | Branch: alternate-upgrade | Source mechanic: `fortress.basilisk_line`

**Actives**

- **Handcuffs** — Focus: 1; Cooldown: 2; Rank: 1; Attack type: cast
  - Effect: Spend 1 Focus to prevent an enemy creature from using active abilities for 2 rounds.
  - Logic: buff `succubus_debuff_1`; pattern `attack_single_buff`; tags ability, debuff_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Gorgon (`h3_gorgon`)

- Tier 5 | Hire cost: 525 gold | Branch: base-line | Source mechanic: `fortress.gorgon_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Mighty Gorgon (`h3_gorgon_upg`)

- Tier 5 | Hire cost: 600 gold | Branch: standard-upgrade | Source mechanic: `fortress.gorgon_line`

**Actives**

- **Death Stare** — Focus: 2; Cooldown: 2; Rank: 2; Attack type: melee
  - Effect: Spend 2 Focus to attack for 100% normal damage and kill 1-7 additional creatures in the target stack.
  - Logic: damageType `normal`; pattern `attack_single_x100`; tags melee_attack, normal_damage, basic_attack, ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Corrosive Gorgon (`h3_gorgon_upg_alt`)

- Tier 5 | Hire cost: 600 gold | Branch: alternate-upgrade | Source mechanic: `fortress.gorgon_line`

**Actives**

- **Inner Flame** — Focus: 3; Cooldown: 3; Rank: 3; Attack type: cast
  - Effect: Spend 3 Focus to deal 30 pure magic damage plus 10 per stack to melee attackers for 2 rounds.
  - Logic: buff `black_dragon_buff`; pattern `attack_single_buff`; tags ability, buff_ability, charge_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Wyvern (`h3_wyvern`)

- Tier 6 | Hire cost: 800 gold | Branch: base-line | Source mechanic: `fortress.wyvern_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.

### Wyvern Monarch (`h3_wyvern_upg`)

- Tier 6 | Hire cost: 1100 gold | Branch: standard-upgrade | Source mechanic: `fortress.wyvern_line`

**Actives**

- **Swarm of Bees** — Focus: 2; Cooldown: 2; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to deal 16 normal damage plus 4 per stack, then repeat that damage for 3 rounds.
  - Logic: buff `druid_bees`; damageType `normal`; statDmgMult `0.0`; pattern `attack_single_x100`; tags ability, normal_damage, debuff_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.

### Paokai (`h3_wyvern_upg_alt`)

- Tier 6 | Hire cost: 1300 gold | Branch: alternate-upgrade | Source mechanic: `fortress.wyvern_line`

**Actives**

- **Dragonflight** — Focus: 2; Cooldown: 2; Rank: 5; Attack type: end_move_attack
  - Effect: Spend 2 Focus to fly to a target hex, deal 100% normal damage to enemies in the landing area, and push them back.
  - Logic: damageType `normal`; pattern `attack_swirl_x1_x100`; tags ability, armed_ability, normal_damage, basic_attack, melee_attack

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.

### Hydra (`h3_hydra`)

- Tier 7 | Hire cost: 2200 gold | Branch: base-line | Source mechanic: `fortress.hydra_line`

**Actives:** none

**Passives**

- **No Retaliation** — Cost: none (passive)
  - Effect: Melee attacks do not provoke counterattacks.
- **Sweeping Strike** — Cost: none (passive)
  - Effect: Deals Damage to the target and two adjacent enemies to its sides.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Performs an alternative Melee attack.

### Chaos Hydra (`h3_hydra_upg`)

- Tier 7 | Hire cost: 3500 gold, 1 mercury | Branch: standard-upgrade | Source mechanic: `fortress.hydra_line`

**Actives:** none

**Passives**

- **No Retaliation** — Cost: none (passive)
  - Effect: Melee attacks do not provoke counterattacks.
- **Sweeping Strike** — Cost: none (passive)
  - Effect: Deals Damage to the target and two adjacent enemies to its sides.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Performs an alternative Melee attack.

### Ruinous Hydra (`h3_hydra_upg_alt`)

- Tier 7 | Hire cost: 4000 gold, 2 mercury | Branch: alternate-upgrade | Source mechanic: `fortress.hydra_line`

**Actives**

- **Hksmilla's Rampage** — Focus: 3; Cooldown: 3; Rank: 5; Attack type: cast
  - Effect: Spend 3 Focus to give an allied stack Double Strike, +10% damage dealt, and +10% damage taken for 1 round.
  - Logic: buff `magic_hksmillas_rampage_effect_0`; damageType `none`; pattern `attack_single_x100`

**Passives**

- **No Retaliation** — Cost: none (passive)
  - Effect: Melee attacks do not provoke counterattacks.
- **Sweeping Strike** — Cost: none (passive)
  - Effect: Deals Damage to the target and two adjacent enemies to its sides.
- **Regeneration** — Cost: none (passive)
  - Effect: At the start of its turn, restores up to 25% of maximum stack health without reviving defeated creatures.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Performs an alternative Melee attack.

## homm3_conflux

### Pixie (`h3_pixie`)

- Tier 1 | Hire cost: 35 gold | Branch: base-line | Source mechanic: `conflux.pixie_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.

### Sprite (`h3_pixie_upg`)

- Tier 1 | Hire cost: 30 gold | Branch: standard-upgrade | Source mechanic: `conflux.pixie_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.
- **Melee Attack** — Cost: none (passive)
  - Effect: Can only attack adjacent enemies. <b>Enemies do not counterattack.</b>
- **Swift Strike** — Cost: none (passive)
  - Effect: Enemies do not counterattack.

### Faerie (`h3_pixie_upg_alt`)

- Tier 1 | Hire cost: 90 gold | Branch: alternate-upgrade | Source mechanic: `conflux.pixie_line`

**Actives**

- **Leeching Hop** — Focus: 2; Cooldown: 2; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to transfer 2-6 mana from the enemy hero to your hero.
  - Logic: pattern `attack_single_buff`; tags ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.
- **Sweeping Strike** — Cost: none (passive)
  - Effect: Deals Damage to the target and two adjacent enemies to its sides.

### Air Elemental (`h3_air_elemental`)

- Tier 2 | Hire cost: 190 gold | Branch: base-line | Source mechanic: `conflux.air_elemental_line`

**Actives**

- **Air Spark** — Focus: 2; Cooldown: 2; Rank: 3; Attack type: cast
  - Effect: Spend 2 Focus to strike an enemy for 150% pure magic damage.
  - Logic: damageType `magic_pure`; statDmgMult `1.5`; pattern `attack_single_x100`; tags magic_damage, ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Storm Elemental (`h3_air_elemental_upg`)

- Tier 2 | Hire cost: 275 gold | Branch: standard-upgrade | Source mechanic: `conflux.air_elemental_line`

**Actives**

- **Thunderbolt** — Focus: 2; Cooldown: 2; Rank: 3; Attack type: cast
  - Effect: Spend 2 Focus without ending the turn to deal 25 pure magic damage plus 10 per stack.
  - Logic: damageType `magic_pure`; pattern `attack_single_x100`; tags magic_damage, primal_1_magic_thunderbolt_damage

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1

### Hurricane Elemental (`h3_air_elemental_upg_alt`)

- Tier 2 | Hire cost: 230 gold | Branch: alternate-upgrade | Source mechanic: `conflux.air_elemental_line`

**Actives**

- **Haste** — Focus: 2; Cooldown: 2; Rank: 3; Attack type: cast
  - Effect: Spend 2 Focus without ending the turn to give an allied stack +2 Speed for 1 round.
  - Logic: buff `magic_haste_effect_0`; damageType `none`; pattern `attack_single_x100`; tags haste

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.

### Water Elemental (`h3_water_elemental`)

- Tier 3 | Hire cost: 300 gold | Branch: base-line | Source mechanic: `conflux.water_elemental_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Ice Elemental (`h3_water_elemental_upg`)

- Tier 3 | Hire cost: 375 gold | Branch: standard-upgrade | Source mechanic: `conflux.water_elemental_line`

**Actives**

- **Blinding Strike** — Focus: 3; Cooldown: 3; Rank: 3; Attack type: melee
  - Effect: Spend 3 Focus to attack for 100% normal damage and blind the enemy for 2 rounds, removed if it takes damage.
  - Logic: buff `unicorn_blind`; damageType `normal`; pattern `attack_single_x100`; tags melee_attack, normal_damage, basic_attack, ability, armed_ability

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1

### Frost Elemental (`h3_water_elemental_upg_alt`)

- Tier 3 | Hire cost: 350 gold | Branch: alternate-upgrade | Source mechanic: `conflux.water_elemental_line`

**Actives:** none

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1

### Fire Elemental (`h3_fire_elemental`)

- Tier 4 | Hire cost: 350 gold | Branch: base-line | Source mechanic: `conflux.fire_elemental_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Energy Elemental (`h3_fire_elemental_upg`)

- Tier 4 | Hire cost: 400 gold | Branch: standard-upgrade | Source mechanic: `conflux.fire_elemental_line`

**Actives**

- **Jumpstart** — Focus: 2; Cooldown: 2; Rank: 3; Attack type: cast
  - Effect: Spend 2 Focus without ending the turn to give an allied stack +3 Initiative for 1 round.
  - Logic: buff `magic_early_start_effect_0`; damageType `none`; pattern `attack_single_x100`

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.

### Plasma Elemental (`h3_fire_elemental_upg_alt`)

- Tier 4 | Hire cost: 425 gold | Branch: alternate-upgrade | Source mechanic: `conflux.fire_elemental_line`

**Actives**

- **Chain Lightning** — Focus: 3; Cooldown: 3; Rank: 3; Attack type: cast
  - Effect: Spend 3 Focus to deal 100 pure magic damage plus 20 per stack, then jump within 3 hexes for 50% damage.
  - Logic: damageType `magic_pure`; pattern `attack_single_x100`; tags magic_damage, primal_12_magic_chain_lightning_damage

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.

### Earth Elemental (`h3_earth_elemental`)

- Tier 5 | Hire cost: 400 gold | Branch: base-line | Source mechanic: `conflux.earth_elemental_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Guard Formation** — Cost: none (passive)
  - Effect: This creature takes 10% less damage from basic attacks.

### Magma Elemental (`h3_earth_elemental_upg`)

- Tier 5 | Hire cost: 500 gold | Branch: standard-upgrade | Source mechanic: `conflux.earth_elemental_line`

**Actives**

- **Fireball** — Focus: 3; Cooldown: 3; Rank: 3; Attack type: cast
  - Effect: Spend 3 Focus to deal 50 pure magic area damage plus 10 per stack.
  - Logic: damageType `magic_pure`; pattern `attack_rumble_x1_x100`; tags magic_damage, primal_4_magic_fire_globe_damage

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Lava Elemental (`h3_earth_elemental_upg_alt`)

- Tier 5 | Hire cost: 650 gold | Branch: alternate-upgrade | Source mechanic: `conflux.earth_elemental_line`

**Actives**

- **Firewall** — Focus: 2; Cooldown: 3; Rank: 3; Attack type: cast
  - Effect: Spend 2 Focus to place 2 fire-wall traps that last 2 rounds.
  - Logic: pattern `attack_single_x100`

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Psychic Elemental (`h3_psychic_elemental`)

- Tier 6 | Hire cost: 750 gold | Branch: base-line | Source mechanic: `conflux.psychic_elemental_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Melee Attack** — Cost: none (passive)
  - Effect: Can only attack adjacent enemies. <b>Enemies do not counterattack.</b>
- **Swift Strike** — Cost: none (passive)
  - Effect: Enemies do not counterattack.
- **Sweeping Strike** — Cost: none (passive)
  - Effect: Deals Damage to the target and two adjacent enemies to its sides.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Performs an alternative Melee attack.

### Magic Elemental (`h3_psychic_elemental_upg`)

- Tier 6 | Hire cost: 800 gold | Branch: standard-upgrade | Source mechanic: `conflux.psychic_elemental_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Melee Attack** — Cost: none (passive)
  - Effect: Can only attack adjacent enemies. <b>Enemies do not counterattack.</b>
- **Swift Strike** — Cost: none (passive)
  - Effect: Enemies do not counterattack.
- **Sweeping Strike** — Cost: none (passive)
  - Effect: Deals Damage to the target and two adjacent enemies to its sides.
- **Magic Immunity V** — Cost: none (passive)
  - Effect: Immune to tier‑5 and lower spells.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Performs an alternative Melee attack.

### Astral Elemental (`h3_psychic_elemental_upg_alt`)

- Tier 6 | Hire cost: 1450 gold | Branch: alternate-upgrade | Source mechanic: `conflux.psychic_elemental_line`

**Actives**

- **Misfortune** — Focus: 1; Cooldown: 1; Rank: 1; Attack type: cast
  - Effect: Spend 1 Focus to set an enemy's Morale and Luck to minimum and its Attack and Defense to 0 for 2 rounds.
  - Logic: buff `magic_nairas_kiss_effect_1_old`; damageType `none`; pattern `attack_single_x100`; tags ability, debuff_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Melee Attack** — Cost: none (passive)
  - Effect: Can only attack adjacent enemies. <b>Enemies do not counterattack.</b>
- **Swift Strike** — Cost: none (passive)
  - Effect: Enemies do not counterattack.

### Firebird (`h3_firebird`)

- Tier 7 | Hire cost: 1500 gold | Branch: base-line | Source mechanic: `conflux.firebird_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.
- **Dragonbreath Strike** — Cost: none (passive)
  - Effect: Deals Damage to the target and <b>any creature</b> on the hex directly behind it.

### Phoenix (`h3_firebird_upg`)

- Tier 7 | Hire cost: 1 mercury, 2000 gold | Branch: standard-upgrade | Source mechanic: `conflux.firebird_line`

**Actives:** none

**Passives**

- **Melee Attack** — Cost: none (passive)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.
  - Logic: xHomm3PortNote=Phoenix-style rebirth for h3_firebird_upg via h3_firebird_upg_phoenix_heart.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.
- **Dragonbreath Strike** — Cost: none (passive)
  - Effect: Deals Damage to the target and <b>any creature</b> on the hex directly behind it.
- **Immortal** — Cost: none (passive)
  - Effect: Leaves a pile of ash upon death. At the start of the following round, {0} units are revived from that pile (no more than the original amount). Each stack can only be revived once per battle this way.
The pile is destroyed upon taking Damage {1} times. Units revived this way are permanent.

### Sacred Phoenix (`h3_firebird_upg_alt`)

- Tier 7 | Hire cost: 4000 gold, 2 mercury | Branch: alternate-upgrade | Source mechanic: `conflux.firebird_line`

**Actives:** none

**Passives**

- **Melee Attack** — Cost: none (passive)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.
  - Logic: xHomm3PortNote=Phoenix-style rebirth for h3_firebird_upg_alt via h3_firebird_upg_alt_phoenix_heart.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.
- **Dragonbreath Strike** — Cost: none (passive)
  - Effect: Deals Damage to the target and <b>any creature</b> on the hex directly behind it.
- **Immortal** — Cost: none (passive)
  - Effect: Leaves a pile of ash upon death. At the start of the following round, {0} units are revived from that pile (no more than the original amount). Each stack can only be revived once per battle this way.
The pile is destroyed upon taking Damage {1} times. Units revived this way are permanent.

## homm3_cove

### Nymph (`h3_nymph`)

- Tier 1 | Hire cost: 35 gold | Branch: base-line | Source mechanic: `cove.nymph_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Blink** — Cost: none (passive)
  - Effect: Teleports directly to destination hex, ignoring obstacles and traps.
- **Ice Immunity** — Cost: none (passive)
  - Effect: Immune to Ice Bolt and Avalanche spell damage.

### Nereid (`h3_nymph_upg_alt`)

- Tier 1 | Hire cost: 90 gold | Branch: alternate-upgrade | Source mechanic: `cove.nymph_line`

**Actives**

- **Healing Water** — Focus: 1; Cooldown: 2; Rank: 1; Charges: 2; Attack type: cast
  - Effect: Spend 1 Focus to heal an allied living stack for 50 health plus 5 per stack. Can be used twice per battle.
  - Logic: damageType `none`; pattern `attack_single_x100`; tags heal, undead_immunities, embodiment_immunities, construct_immunities, avatar_immunities

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Blink** — Cost: none (passive)
  - Effect: Teleports directly to destination hex, ignoring obstacles and traps.
- **Ice Immunity** — Cost: none (passive)
  - Effect: Immune to Ice Bolt and Avalanche spell damage.

### Oceanid (`h3_oceanid`)

- Tier 1 | Hire cost: 45 gold | Branch: standard-upgrade | Source mechanic: `cove.nymph_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Blink** — Cost: none (passive)
  - Effect: Teleports directly to destination hex, ignoring obstacles and traps.
- **Ice Immunity** — Cost: none (passive)
  - Effect: Immune to Ice Bolt and Avalanche spell damage.

### Crew Mate (`h3_crew_mate`)

- Tier 2 | Hire cost: 110 gold | Branch: base-line | Source mechanic: `cove.crew_mate_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Swashbuckler (`h3_crew_mate_upg_alt`)

- Tier 2 | Hire cost: 150 gold | Branch: alternate-upgrade | Source mechanic: `cove.crew_mate_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Gold Producer** — Cost: none (passive)
  - Effect: At side day start, each Swashbuckler in a hero army produces 15 Gold.

### Seaman (`h3_seaman`)

- Tier 2 | Hire cost: 140 gold | Branch: standard-upgrade | Source mechanic: `cove.crew_mate_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Corsair (`h3_corsair`)

- Tier 3 | Hire cost: 275 gold | Branch: standard-upgrade | Source mechanic: `cove.pirate_line`

**Actives:** none

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.
- **Ranged Attack** — Cost: none (passive)
  - Effect: Can attack enemies at any range. 
Targets {0} or more hexes away take –{1}% Damage per hex (up to –{2}%).
- **Duelist** — Cost: none (passive)
  - Effect: Receives no penalty in Melee range, dealing full Damage.
- **Melee Attack** — Cost: none (passive)
  - Effect: Can only attack adjacent enemies. <b>Enemies do not counterattack.</b>
- **Swift Strike** — Cost: none (passive)
  - Effect: Enemies do not counterattack.
- **Piercing Shot** — Cost: none (passive)
  - Effect: This creature deals 10% more ranged attack damage with disciplined shots.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1

### Pirate (`h3_pirate`)

- Tier 3 | Hire cost: 225 gold | Branch: base-line | Source mechanic: `cove.pirate_line`

**Actives:** none

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.
- **Ranged Attack** — Cost: none (passive)
  - Effect: Can attack enemies at any range. 
Targets {0} or more hexes away take –{1}% Damage per hex (up to –{2}%).
- **Duelist** — Cost: none (passive)
  - Effect: Receives no penalty in Melee range, dealing full Damage.
- **Piercing Shot** — Cost: none (passive)
  - Effect: This creature deals 10% more ranged attack damage with disciplined shots.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1

### Sea Dog (`h3_sea_dog`)

- Tier 3 | Hire cost: 375 gold | Branch: alternate-upgrade | Source mechanic: `cove.gunpowder_warehouse_sea_dog`

**Actives**

- **Guillotine Shot** — Focus: 2; Cooldown: 2; Rank: 1; Attack type: cast
  - Effect: Spend 2 Focus to deal pure damage based on 30% of the target creature's max HP, with a 25% execution threshold.
  - Logic: buff `magic_decimate_effect`; damageType `magic_pure`; pattern `attack_single_x100`; tags ability, magic_damage, decimate_damage

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.
- **Ranged Attack** — Cost: none (passive)
  - Effect: Can attack enemies at any range. 
Targets {0} or more hexes away take –{1}% Damage per hex (up to –{2}%).
- **Duelist** — Cost: none (passive)
  - Effect: Receives no penalty in Melee range, dealing full Damage.
- **Melee Attack** — Cost: none (passive)
  - Effect: Can only attack adjacent enemies. <b>Enemies do not counterattack.</b>
- **Swift Strike** — Cost: none (passive)
  - Effect: Enemies do not counterattack.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1

### Ayssid (`h3_ayssid`)

- Tier 4 | Hire cost: 325 gold | Branch: standard-upgrade | Source mechanic: `cove.stormbird_line`

**Actives**

- **Stormbird Shock** — Focus: 2; Cooldown: 2; Rank: 3; Attack type: melee
  - Effect: Spend 2 Focus in melee range to strike an enemy for 150% pure magic damage.
  - Logic: damageType `magic_pure`; statDmgMult `1.5`; pattern `attack_single_x100`; tags magic_damage, ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.

### Stormbird (`h3_stormbird`)

- Tier 4 | Hire cost: 275 gold | Branch: base-line | Source mechanic: `cove.stormbird_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.

### Halcyon (`h3_stormbird_upg_alt`)

- Tier 4 | Hire cost: 350 gold | Branch: alternate-upgrade | Source mechanic: `cove.stormbird_line`

**Actives**

- **Tempest Talon** — Focus: 1; Cooldown: 2; Rank: 3; Attack type: melee
  - Effect: Spend 1 Focus in melee range to rake an enemy for 120% pure magic damage.
  - Logic: damageType `magic_pure`; statDmgMult `1.2`; pattern `attack_single_x100`; tags magic_damage, ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.

### Sea Witch (`h3_sea_witch`)

- Tier 5 | Hire cost: 515 gold | Branch: base-line | Source mechanic: `cove.sea_witch_line`

**Actives:** none

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.
- **Ranged Attack** — Cost: none (passive)
  - Effect: Can attack enemies at any range. 
Targets {0} or more hexes away take –{1}% Damage per hex (up to –{2}%).
- **Duelist** — Cost: none (passive)
  - Effect: Receives no penalty in Melee range, dealing full Damage.
- **Weakening Shot** — Cost: none (passive)
  - Effect: Ranged attacks reduce the target's normal damage by 20% for 1 round after damage is dealt.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1; on-hit buff `magic_unnatural_calm_effect_0`

### Tidecaller (`h3_sea_witch_upg_alt`)

- Tier 5 | Hire cost: 575 gold | Branch: alternate-upgrade | Source mechanic: `cove.sea_witch_line`

**Actives**

- **Summon Fangarms** — Focus: 2; Cooldown: 99; Rank: 2; Charges: 1; Attack type: cast
  - Effect: Spend 2 Focus without ending the turn, once per battle, to summon Fangarms on an adjacent hex at 50% Power.
  - Logic: damageType `none`; pattern `attack_single_buff`; tags ability, summon_ability

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.
- **Weakening Shot** — Cost: none (passive)
  - Effect: Ranged attacks reduce the target's normal damage by 20% for 1 round after damage is dealt.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1; on-hit buff `magic_unnatural_calm_effect_0`

### Sorceress (`h3_sorceress`)

- Tier 5 | Hire cost: 565 gold | Branch: standard-upgrade | Source mechanic: `cove.sea_witch_line`

**Actives:** none

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.
- **Ranged Attack** — Cost: none (passive)
  - Effect: Can attack enemies at any range. 
Targets {0} or more hexes away take –{1}% Damage per hex (up to –{2}%).
- **Duelist** — Cost: none (passive)
  - Effect: Receives no penalty in Melee range, dealing full Damage.
- **Weakening Shot** — Cost: none (passive)
  - Effect: Ranged attacks reduce the target's normal damage by 20% for 1 round after damage is dealt.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1; on-hit buff `magic_unnatural_calm_effect_1`

### Nix (`h3_nix`)

- Tier 6 | Hire cost: 1000 gold | Branch: base-line | Source mechanic: `cove.nix_line`

**Actives**

- **Abyssal Hook** — Focus: 2; Cooldown: 2; Rank: 3; Attack type: melee
  - Effect: Spend 2 Focus to hook an enemy for 75% normal damage and suppress 1 retaliation.
  - Logic: damageType `normal`; statDmgMult `0.75`; pattern `attack_single_x100`; tags melee_attack, normal_damage, basic_attack, ability, armed_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Attack Ignore** — Cost: none (passive)
  - Effect: Ignores 30% of the enemy's Attack when this creature is damaged.

### Nix Praetorian (`h3_nix_upg_alt`)

- Tier 6 | Hire cost: 1300 gold | Branch: alternate-upgrade | Source mechanic: `cove.nix_line`

**Actives**

- **Tidebreak** — Focus: 3; Cooldown: 3; Rank: 3; Attack type: melee
  - Effect: Spend 3 Focus to attack for 125% normal damage and root the enemy for 2 rounds.
  - Logic: buff `ent_root`; damageType `normal`; statDmgMult `1.25`; pattern `attack_single_x100`; tags melee_attack, normal_damage, basic_attack, ability, armed_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Attack Ignore** — Cost: none (passive)
  - Effect: Ignores 30% of the enemy's Attack when this creature is damaged.

### Nix Warrior (`h3_nix_warrior`)

- Tier 6 | Hire cost: 1300 gold | Branch: standard-upgrade | Source mechanic: `cove.nix_line`

**Actives**

- **Harpoon Break** — Focus: 2; Cooldown: 2; Rank: 3; Attack type: melee
  - Effect: Spend 2 Focus to attack for 75% normal damage and permanently reduce the target's Defense by 1.
  - Logic: buff `pet_debuff`; damageType `normal`; statDmgMult `0.75`; pattern `attack_single_x100`; tags melee_attack, normal_damage, basic_attack, ability, armed_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Attack Ignore** — Cost: none (passive)
  - Effect: Ignores 60% of the enemy's Attack when this creature is damaged.

### Haspid (`h3_haspid`)

- Tier 7 | Hire cost: 4000 gold, 2 mercury | Branch: standard-upgrade | Source mechanic: `cove.sea_serpent_line`

**Actives**

- **Haspid Venom** — Focus: 1; Cooldown: 1; Rank: 1; Attack type: melee
  - Effect: Spend 1 Focus to attack for 100% normal damage and reduce the target's maximum health by 20% for 1 round.
  - Logic: buff `magic_fatal_decay_effect_1`; damageType `normal`; pattern `attack_single_x100`; tags melee_attack, normal_damage, basic_attack, ability, poison

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Sea Serpent (`h3_sea_serpent`)

- Tier 7 | Hire cost: 2200 gold, 1 mercury | Branch: base-line | Source mechanic: `cove.sea_serpent_line`

**Actives**

- **Venomous Decay** — Focus: 1; Cooldown: 1; Rank: 1; Attack type: melee
  - Effect: Spend 1 Focus to attack for 75% normal damage and reduce the target's maximum health by 20% for 1 round.
  - Logic: buff `magic_fatal_decay_effect_1`; damageType `normal`; statDmgMult `0.75`; pattern `attack_single_x100`; tags melee_attack, normal_damage, basic_attack, ability, poison

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Abyss Serpent (`h3_sea_serpent_upg_alt`)

- Tier 7 | Hire cost: 4000 gold, 2 mercury | Branch: alternate-upgrade | Source mechanic: `cove.sea_serpent_line`

**Actives**

- **Whirlpool** — Focus: 2; Cooldown: 2; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to give an enemy -2 Speed and -2 Initiative for 3 rounds.
  - Logic: buff `aqualotl_debuff_1`; pattern `attack_single_x100`; tags magic_damage, ability, debuff_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Fearless** — Cost: none (passive)
  - Effect: Immune to Cove Fearsome's 10% skip-action effect.

## homm3_factory

### Halfling (`h3_halfling`)

- Tier 1 | Hire cost: 40 gold | Branch: base-line | Source mechanic: `factory.halfling_line`

**Actives:** none

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.
- **Positive Luck** — Cost: none (passive)
  - Effect: Luck cannot fall below +1.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5

### Halfling Grenadier (`h3_halfling_grenadier`)

- Tier 1 | Hire cost: 60 gold | Branch: standard-upgrade | Source mechanic: `factory.halfling_line`

**Actives**

- **Bombardier Mark** — Focus: 1; Cooldown: 2; Rank: 1; Attack type: cast
  - Effect: Spend 1 Focus to weaken an enemy's Attack and Defense for 2 rounds.
  - Logic: buff `magic_shorten_shadow_effect_0`; damageType `none`; pattern `attack_single_x100`

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.
- **Positive Luck** — Cost: none (passive)
  - Effect: Luck cannot fall below +1.
- **Defense Pierce** — Cost: none (passive)
  - Effect: Attacks ignore 30% of the target's Defense.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5

### Firebug (`h3_halfling_upg_alt`)

- Tier 1 | Hire cost: 60 gold | Branch: alternate-upgrade | Source mechanic: `factory.halfling_line`

**Actives**

- **Ember Canister** — Focus: 1; Cooldown: 2; Rank: 1; Attack type: cast
  - Effect: Spend 1 Focus to mark an enemy so it takes extra damage for 2 rounds.
  - Logic: buff `magic_vulnerability_effect_0`; damageType `none`; pattern `attack_single_x100`

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.
- **Positive Luck** — Cost: none (passive)
  - Effect: Luck cannot fall below +1.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5

### Engineer (`h3_engineer`)

- Tier 2 | Hire cost: 170 gold | Branch: standard-upgrade | Source mechanic: `factory.mechanic_line`

**Actives**

- **Field Drive** — Focus: 2; Cooldown: 3; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to grant an allied stack +2 Speed for 1 round.
  - Logic: buff `magic_haste_effect_0`; damageType `none`; pattern `attack_single_x100`; tags haste

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Dragonbreath Strike** — Cost: none (passive)
  - Effect: Deals Damage to the target and <b>any creature</b> on the hex directly behind it.

### Mechanic (`h3_mechanic`)

- Tier 2 | Hire cost: 140 gold | Branch: base-line | Source mechanic: `factory.mechanic_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Dragonbreath Strike** — Cost: none (passive)
  - Effect: Deals Damage to the target and <b>any creature</b> on the hex directly behind it.

### Tinker (`h3_mechanic_upg_alt`)

- Tier 2 | Hire cost: 170 gold | Branch: alternate-upgrade | Source mechanic: `factory.mechanic_line`

**Actives**

- **Overclock** — Focus: 2; Cooldown: 3; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to grant an allied stack +3 Initiative for 1 round.
  - Logic: buff `magic_early_start_effect_0`; damageType `none`; pattern `attack_single_x100`

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Long Reach** — Cost: none (passive)
  - Effect: Has an attack that targets the hex directly behind an adjacent hex. It doesn’t provoke counterattacks and doesn’t move the attacker next to their target.

**Alternate attacks**

- **Long Reach** — Focus: none (`ability_no_energy`)
  - Effect: Has an attack that targets the hex directly behind an adjacent hex. It doesn’t provoke counterattacks and doesn’t move the attacker next to their target.

### Armadillo (`h3_armadillo`)

- Tier 3 | Hire cost: 200 gold | Branch: base-line | Source mechanic: `factory.armadillo_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Plated Armadillo (`h3_armadillo_upg_alt`)

- Tier 3 | Hire cost: 230 gold | Branch: alternate-upgrade | Source mechanic: `factory.armadillo_line`

**Actives**

- **Taunting Plate** — Focus: 2; Cooldown: 3; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to force nearby enemies to target this stack.
  - Logic: damageType `none`; pattern `attack_single_x100`

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Bellwether Armadillo (`h3_bellwether_armadillo`)

- Tier 3 | Hire cost: 230 gold | Branch: standard-upgrade | Source mechanic: `factory.armadillo_line`

**Actives**

- **Shoulder Check** — Focus: 1; Cooldown: 2; Rank: 2; Attack type: cast
  - Effect: Spend 1 Focus to move an adjacent enemy to a free hex within 1 hex of its position.
  - Logic: pattern `attack_single_buff`; tags ability, movement_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Automaton (`h3_automaton`)

- Tier 4 | Hire cost: 350 gold | Branch: base-line | Source mechanic: `factory.automaton_line`

**Actives**

- **Blow Up** — Focus: 2; Cooldown: 3; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to self-destruct, dealing Magic Damage to all adjacent creatures.
  - Logic: damageType `magic_pure`; statDmgMult `0.0`; pattern `attack_rumble_x1_x100`; tags ability, magic_damage, lava_larva_damage, lava_larva_explosion_attack

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Passive 1** — Cost: none (passive)
  - Effect: *(no English unitsAbility text)*

### Clockwork Automaton (`h3_automaton_upg_alt`)

- Tier 4 | Hire cost: 450 gold | Branch: alternate-upgrade | Source mechanic: `factory.automaton_line`

**Actives**

- **Wind-Up** — Focus: 2; Cooldown: 3; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to empower this stack with an extra attack for 1 round.
  - Logic: damageType `none`; pattern `attack_single_x100`

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Melee Attack** — Cost: none (passive)
  - Effect: Can only attack adjacent enemies. <b>Enemies do not counterattack.</b>
- **Swift Strike** — Cost: none (passive)
  - Effect: Enemies do not counterattack.

### Sentinel Automaton (`h3_sentinel_automaton`)

- Tier 4 | Hire cost: 450 gold | Branch: standard-upgrade | Source mechanic: `factory.automaton_line`

**Actives**

- **Blow Up** — Focus: 2; Cooldown: 3; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to self-destruct, dealing Magic Damage to all adjacent creatures.
  - Logic: damageType `magic_pure`; statDmgMult `0.0`; pattern `attack_rumble_x1_x100`; tags ability, magic_damage, lava_larva_damage, lava_larva_explosion_attack

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Melee Attack** — Cost: none (passive)
  - Effect: Can only attack adjacent enemies. <b>Enemies do not counterattack.</b>
- **Swift Strike** — Cost: none (passive)
  - Effect: Enemies do not counterattack.

### Olgoi-Khorkhoi (`h3_olgoi_khorkhoi`)

- Tier 5 | Hire cost: 650 gold | Branch: standard-upgrade | Source mechanic: `factory.sandworm_line`

**Actives**

- **Devour Corpses** — Focus: 2; Cooldown: 3; Rank: 2; Attack type: jump
  - Effect: Spend 2 Focus to jump onto a corpse within range and devour it, gaining Attack, Defense, Speed, and Initiative until the end of battle.
  - Logic: damageType `none`; pattern `attack_single_buff`; tags ability, buff_ability, movement_ability, undead_immunities, embodiment_immunities, construct_immunities

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Blink** — Cost: none (passive)
  - Effect: Teleports directly to destination hex, ignoring obstacles and traps.
- **Magic Immunity III** — Cost: none (passive)
  - Effect: Immune to tier‑3 and lower spells.

### Sandworm (`h3_sandworm`)

- Tier 5 | Hire cost: 575 gold | Branch: base-line | Source mechanic: `factory.sandworm_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Blink** — Cost: none (passive)
  - Effect: Teleports directly to destination hex, ignoring obstacles and traps.
- **Magic Immunity III** — Cost: none (passive)
  - Effect: Immune to tier‑3 and lower spells.

### Glassworm (`h3_sandworm_upg_alt`)

- Tier 5 | Hire cost: 650 gold | Branch: alternate-upgrade | Source mechanic: `factory.sandworm_line`

**Actives**

- **Shatter** — Focus: 2; Cooldown: 3; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to shred an enemy's Attack and Defense for 2 rounds.
  - Logic: buff `magic_shorten_shadow_effect_0`; damageType `none`; pattern `attack_single_x100`

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Blink** — Cost: none (passive)
  - Effect: Teleports directly to destination hex, ignoring obstacles and traps.
- **Magic Immunity III** — Cost: none (passive)
  - Effect: Immune to tier‑3 and lower spells.

### Bounty Hunter (`h3_bounty_hunter`)

- Tier 6 | Hire cost: 1100 gold | Branch: standard-upgrade | Source mechanic: `factory.gunslinger_line`

**Actives**

- **Bounty Mark** — Focus: 2; Cooldown: 3; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to make an enemy more vulnerable for 2 rounds.
  - Logic: buff `magic_vulnerability_effect_0`; damageType `none`; pattern `attack_single_x100`

**Passives**

- **Ranged Attack** — Cost: none (passive)
  - Effect: Can attack enemies at range. Adjacent melee attacks deal reduced damage.
  - Logic: sequence=counter_before_attack
- **Alert II** — Cost: none (passive)
  - Effect: Can counterattack unlimited times per round.
- **Parry** — Cost: none (passive)
  - Effect: When attacked, this creature’s counterattack strikes first.
- **Countershot** — Cost: none (passive)
  - Effect: Counterattacks when struck with a Ranged attack.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5

### Gunslinger (`h3_gunslinger`)

- Tier 6 | Hire cost: 800 gold | Branch: base-line | Source mechanic: `factory.gunslinger_line`

**Actives:** none

**Passives**

- **Ranged Attack** — Cost: none (passive)
  - Effect: Can attack enemies at range. Adjacent melee attacks deal reduced damage.
  - Logic: sequence=counter_before_attack
- **Parry** — Cost: none (passive)
  - Effect: When attacked, this creature’s counterattack strikes first.
- **Countershot** — Cost: none (passive)
  - Effect: Counterattacks when struck with a Ranged attack.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5

### Marshal (`h3_gunslinger_upg_alt`)

- Tier 6 | Hire cost: 1100 gold | Branch: alternate-upgrade | Source mechanic: `factory.gunslinger_line`

**Actives**

- **Suppressing Fire** — Focus: 2; Cooldown: 3; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to place a trap on a free hex. When triggered, it deals Pure Damage equal to 150% of this stack's normal attack.
  - Logic: damageType `none`; pattern `attack_single_x100`; tags ability, trap_ability

**Passives**

- **Ranged Attack** — Cost: none (passive)
  - Effect: Can attack enemies at range. Adjacent melee attacks deal reduced damage.
  - Logic: sequence=counter_before_attack
- **Alert II** — Cost: none (passive)
  - Effect: Can counterattack unlimited times per round.
- **Parry** — Cost: none (passive)
  - Effect: When attacked, this creature’s counterattack strikes first.
- **Countershot** — Cost: none (passive)
  - Effect: Counterattacks when struck with a Ranged attack.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5

### Couatl (`h3_couatl`)

- Tier 7 | Hire cost: 2000 gold | Branch: base-line | Source mechanic: `factory.couatl_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.

### Jade Coatl (`h3_couatl_upg_alt`)

- Tier 7 | Hire cost: 3500 gold, 1 crystals | Branch: alternate-upgrade | Source mechanic: `factory.couatl_line`

**Actives**

- **Jade Ward** — Focus: 2; Cooldown: 3; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to shield an allied stack with Carapace, negating the next instance of Damage.
  - Logic: buff `magic_carapace_effect_0`; damageType `none`; pattern `attack_single_x100`

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.

### Crimson Couatl (`h3_crimson_couatl`)

- Tier 7 | Hire cost: 3500 gold, 1 crystals | Branch: standard-upgrade | Source mechanic: `factory.couatl_line`

**Actives**

- **Meditation** — Focus: 2; Cooldown: 3; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to shield this stack with Carapace, negating the next instance of Damage.
  - Logic: buff `magic_carapace_effect_0`; damageType `none`; pattern `attack_single_x100`

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Flying** — Cost: none (passive)
  - Effect: Movement ignores obstacles and traps.

### Dreadnought (`h3_dreadnought`)

- Tier 7 | Hire cost: 2200 gold, 1 crystals | Branch: base-line | Source mechanic: `factory.dreadnought_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Passive 1** — Cost: none (passive)
  - Effect: *(no English unitsAbility text)*

### Ironclad (`h3_dreadnought_upg_alt`)

- Tier 7 | Hire cost: 3500 gold, 2 crystals | Branch: alternate-upgrade | Source mechanic: `factory.dreadnought_line`

**Actives**

- **Fortress Mode** — Focus: 2; Cooldown: 3; Rank: 3; Attack type: cast
  - Effect: Spend 2 Focus to brace this stack with a defensive carapace. While braced, it becomes a stationary bunker.
  - Logic: buff `magic_carapace_effect_0`; damageType `none`; pattern `attack_single_x100`

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Passive 1** — Cost: none (passive)
  - Effect: *(no English unitsAbility text)*

### Juggernaut (`h3_juggernaut`)

- Tier 7 | Hire cost: 3500 gold, 2 crystals | Branch: standard-upgrade | Source mechanic: `factory.dreadnought_line`

**Actives**

- **Boiler Rampage** — Focus: 3; Cooldown: 3; Rank: 3; Attack type: cast
  - Effect: Spend 3 Focus to empower an allied stack for 1 round.
  - Logic: damageType `none`; pattern `attack_single_x100`

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Sweeping Strike** — Cost: none (passive)
  - Effect: Deals Damage to the target and two adjacent enemies to its sides.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Performs an alternative Melee attack.

## homm3_bulwark

### Kobold (`h3_kobold`)

- Tier 1 | Hire cost: 40 gold | Branch: base-line | Source mechanic: `bulwark.kobold_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Kobold Foreman (`h3_kobold_foreman`)

- Tier 1 | Hire cost: 60 gold | Branch: standard-upgrade | Source mechanic: `bulwark.kobold_line`

**Actives**

- **Foreman Cadence** — Focus: 2; Cooldown: 3; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to brace an allied stack with Radiant Armor, reducing damage taken for 1 round.
  - Logic: buff `magic_radiant_armor_effect_0`; damageType `none`; pattern `attack_single_x100`

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Kobold Runebearer (`h3_kobold_upg_alt`)

- Tier 1 | Hire cost: 60 gold | Branch: alternate-upgrade | Source mechanic: `bulwark.kobold_line`

**Actives**

- **Rune Brand** — Focus: 2; Cooldown: 3; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to brand this stack with Radiant Armor. Extra Rune Level gains from this brand remain runtime-pending until Bulwark Runes is exact.
  - Logic: buff `magic_radiant_armor_effect_0`; damageType `none`; pattern `attack_single_x100`

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Argali (`h3_argali`)

- Tier 2 | Hire cost: 170 gold | Branch: standard-upgrade | Source mechanic: `bulwark.mountain_ram_line`

**Actives**

- **Frost Fracture** — Focus: 1; Cooldown: 2; Rank: 1; Attack type: cast
  - Effect: Spend 1 Focus to lower an enemy's Attack and Defense for 1 round.
  - Logic: buff `magic_shorten_shadow_effect_0`; damageType `none`; pattern `attack_single_x100`

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Ice Immunity** — Cost: none (passive)
  - Effect: Immune to Ice Bolt and Avalanche spell damage.

**Default attack notes:** tags=melee_attack,normal_damage,basic_attack,elf_tracker_melee_attack

### Mountain Ram (`h3_mountain_ram`)

- Tier 2 | Hire cost: 135 gold | Branch: base-line | Source mechanic: `bulwark.mountain_ram_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** tags=melee_attack,normal_damage,basic_attack,elf_tracker_melee_attack

### Aurora Ram (`h3_mountain_ram_upg_alt`)

- Tier 2 | Hire cost: 170 gold | Branch: alternate-upgrade | Source mechanic: `bulwark.mountain_ram_line`

**Actives**

- **Aurora Bound** — Focus: 1; Cooldown: 2; Rank: 2; Attack type: cast
  - Effect: Spend 1 Focus to blink this stack to a free hex within 4 hexes.
  - Logic: damageType `none`; pattern `attack_single_buff`; tags ability, movement_ability, teleport

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Ice Immunity** — Cost: none (passive)
  - Effect: Immune to Ice Bolt and Avalanche spell damage.

**Default attack notes:** tags=melee_attack,normal_damage,basic_attack,elf_tracker_melee_attack

### Snow Elf (`h3_snow_elf`)

- Tier 3 | Hire cost: 230 gold | Branch: base-line | Source mechanic: `bulwark.snow_elf_line`

**Actives:** none

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.
- **Ranged Attack** — Cost: none (passive)
  - Effect: Can attack enemies at any range. 
Targets {0} or more hexes away take –{1}% Damage per hex (up to –{2}%).
- **Duelist** — Cost: none (passive)
  - Effect: Receives no penalty in Melee range, dealing full Damage.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1

### Pine Elf (`h3_snow_elf_upg_alt`)

- Tier 3 | Hire cost: 260 gold | Branch: alternate-upgrade | Source mechanic: `bulwark.snow_elf_line`

**Actives**

- **Cold Shackles** — Focus: 2; Cooldown: 3; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to prevent an enemy from counterattacking for 1 round.
  - Logic: buff `magic_shackles_effect_0`; damageType `none`; pattern `attack_single_x100`

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.
- **Ranged Attack** — Cost: none (passive)
  - Effect: Can attack enemies at any range. 
Targets {0} or more hexes away take –{1}% Damage per hex (up to –{2}%).
- **Duelist** — Cost: none (passive)
  - Effect: Receives no penalty in Melee range, dealing full Damage.
- **Sharpshooter** — Cost: none (passive)
  - Effect: Ranged attacks deal full Ranged Damage at any range.
- **Frost Shot** — Cost: none (passive)
  - Effect: Ranged attacks apply Ice Bolt's Initiative reduction to the target after damage is dealt.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1; on-hit buff `magic_ice_bolt_effect`

### Steel Elf (`h3_steel_elf`)

- Tier 3 | Hire cost: 260 gold | Branch: standard-upgrade | Source mechanic: `bulwark.snow_elf_line`

**Actives**

- **Frost Needle** — Focus: 2; Cooldown: 3; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to strike an enemy with Ice Bolt.
  - Logic: damageType `none`; pattern `attack_single_x100`

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.
- **Ranged Attack** — Cost: none (passive)
  - Effect: Can attack enemies at any range. 
Targets {0} or more hexes away take –{1}% Damage per hex (up to –{2}%).
- **Duelist** — Cost: none (passive)
  - Effect: Receives no penalty in Melee range, dealing full Damage.
- **Sharpshooter** — Cost: none (passive)
  - Effect: Ranged attacks deal full Ranged Damage at any range.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1

### Yeti (`h3_yeti`)

- Tier 4 | Hire cost: 325 gold | Branch: base-line | Source mechanic: `bulwark.yeti_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Yeti Runemaster (`h3_yeti_runemaster`)

- Tier 4 | Hire cost: 400 gold | Branch: standard-upgrade | Source mechanic: `bulwark.yeti_line`

**Actives**

- **Rune Surge** — Focus: 2; Cooldown: 3; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to shed movement-impairing effects from this stack and brace it.
  - Logic: buff `inquisitor_selfbuff_2`; pattern `attack_single_buff`; tags ability, buff_ability, dispel_ability, charge_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Yeti Stormcaller (`h3_yeti_upg_alt`)

- Tier 4 | Hire cost: 400 gold | Branch: alternate-upgrade | Source mechanic: `bulwark.yeti_line`

**Actives**

- **Storm Frost** — Focus: 2; Cooldown: 3; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus without ending the turn to strike an enemy with Ice Bolt.
  - Logic: damageType `none`; pattern `attack_single_x100`

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Great Shaman (`h3_great_shaman`)

- Tier 5 | Hire cost: 600 gold | Branch: standard-upgrade | Source mechanic: `bulwark.shaman_line`

**Actives**

- **Air Ward** — Focus: 2; Cooldown: 3; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to shield an allied stack with Optical Illusion, reducing Ranged Damage taken for 1 round.
  - Logic: buff `magic_optical_illusion_effect`; damageType `none`; pattern `attack_single_x100`

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1

### Shaman (`h3_shaman`)

- Tier 5 | Hire cost: 450 gold | Branch: base-line | Source mechanic: `bulwark.shaman_line`

**Actives**

- **Air Ward** — Focus: 2; Cooldown: 3; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to shield an allied stack with Optical Illusion, reducing Ranged Damage taken for 1 round.
  - Logic: buff `magic_optical_illusion_effect`; damageType `none`; pattern `attack_single_x100`

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1

### Frost Speaker (`h3_shaman_upg_alt`)

- Tier 5 | Hire cost: 600 gold | Branch: alternate-upgrade | Source mechanic: `bulwark.shaman_line`

**Actives**

- **Freezing Hex** — Focus: 2; Cooldown: 3; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to strike an enemy with Ice Bolt.
  - Logic: damageType `none`; pattern `attack_single_x100`

**Passives**

- **Ranged Attack** — Can attack enemies at range. Adjacent melee attacks deal reduced damage.
- **Freezing Shot** — Cost: none (passive)
  - Effect: Ranged attacks apply Ice Bolt's Initiative reduction to the target after damage is dealt.

**Alternate attacks**

- **Melee Attack** — Focus: none (`ability_no_energy`)
  - Effect: Can only attack adjacent enemies. Provokes counterattacks.

**Default attack notes:** shootRange=-1; shootThreshold=4; shootRedCount=5; shootDmgBuff=-0.1; on-hit buff `magic_ice_bolt_effect`

### Mammoth (`h3_mammoth`)

- Tier 6 | Hire cost: 850 gold | Branch: base-line | Source mechanic: `bulwark.mammoth_line`

**Actives:** none

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Tundra Mammoth (`h3_mammoth_upg_alt`)

- Tier 6 | Hire cost: 1000 gold | Branch: alternate-upgrade | Source mechanic: `bulwark.mammoth_line`

**Actives**

- **Frost Wall** — Focus: 2; Cooldown: 3; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to shroud this stack with Optical Illusion, reducing Ranged Damage taken for 1 round.
  - Logic: buff `magic_optical_illusion_effect`; damageType `none`; pattern `attack_single_x100`

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### War Mammoth (`h3_war_mammoth`)

- Tier 6 | Hire cost: 1000 gold | Branch: standard-upgrade | Source mechanic: `bulwark.mammoth_line`

**Actives**

- **Tusker Guard** — Focus: 2; Cooldown: 3; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to brace this stack with Radiant Armor, reducing damage taken for 1 round.
  - Logic: buff `magic_radiant_armor_effect_0`; damageType `none`; pattern `attack_single_x100`

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.

### Jotunn (`h3_jotunn`)

- Tier 7 | Hire cost: 2000 gold | Branch: base-line | Source mechanic: `bulwark.jotunn_line`

**Actives**

- **Clan Warp** — Focus: 2; Cooldown: 2; Rank: 2; Charges: 1; Attack type: cast
  - Effect: Spend 2 Focus once per battle to move an allied non-self creature to a free hex within 4 hexes.
  - Logic: pattern `attack_single_buff`; tags ability, movement_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Frostbound Skies** — Cost: none (passive)
  - Effect: Enemy flying creatures begin combat with reduced Speed while this stack is present.

### Jotun Frostlord (`h3_jotunn_upg_alt`)

- Tier 7 | Hire cost: 3500 gold, 1 gemstones | Branch: alternate-upgrade | Source mechanic: `bulwark.jotunn_line`

**Actives**

- **Avalanche** — Focus: 3; Cooldown: 3; Rank: 3; Attack type: cast
  - Effect: Spend 3 Focus to strike the battlefield with Circle of Winter.
  - Logic: damageType `none`; pattern `attack_single_x100`

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Frostbound Skies** — Cost: none (passive)
  - Effect: Enemy flying creatures begin combat with reduced Speed while this stack is present.

### Jotunn Warlord (`h3_jotunn_warlord`)

- Tier 7 | Hire cost: 3500 gold, 1 gemstones | Branch: standard-upgrade | Source mechanic: `bulwark.jotunn_line`

**Actives**

- **Clan Warp** — Focus: 2; Cooldown: 2; Rank: 2; Attack type: cast
  - Effect: Spend 2 Focus to move an allied non-self creature to a free hex within 4 hexes.
  - Logic: pattern `attack_single_buff`; tags ability, movement_ability

**Passives**

- **Melee Attack** — Can only attack adjacent enemies. Provokes counterattacks.
- **Frostbound Skies** — Cost: none (passive)
  - Effect: Enemy flying creatures begin combat with reduced Speed while this stack is present.

