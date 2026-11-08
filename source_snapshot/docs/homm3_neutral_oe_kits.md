# HoMM3 neutral OE kits

Status: **generated-artifact validated** (scratch Core readback, 2026-09-26). Balance, AI use, and runtime casting of the new actives/aura are **unproven until played**.

## What owns what

- Data: `tools/homm3_import/faction_concepts/homm3_neutral.json`. Each unit has `tier`, `stats` and an `oeKit` block (profile, actives, mechanics, `homm3Identity`, `design`, `gaps`).
- Generator: `apply_homm3_neutral_oe_kits` in `tools/release_port/apply_release_core_overlay.py`. It runs right after `add_homm3_neutral_core_overlay` and before multilingual Lang sync. The donor row keeps only the attack/animation shell. Stats, passives, aura, actives, view cards and the class card are all rebuilt from library surfaces. Nothing else comes from the donor.
- Library additions:
  - `fortune_spell` in `STRONG_VANILLA_ACTIVE_SPECS`, with the buff `homm3_neutral_fortune_effect` (+2 Luck).
  - Own-text passives, keyed `<sid>_passive_<mech>_*`.
  - Own-text actives, keyed `<sid>_ability_<kind>_*`.
- Gate: `tools/validate_homm3_neutral_catalog_contract.py`.
  - Static checks: the kit schema; a pinned intended kit per sid (`EXPECTED_NEUTRAL_KITS`); tier bands; the per-tier maximum number of actives; dwelling cost equal to unit gold. These also run from `validate_custom_faction_manifests.py`.
  - Core readback, via `--core-zip`, or via `validate_custom_faction_manifests.py --core`, which is wired into the build. It checks:
    - stats, tier, squad value and gold against the catalog;
    - the kit marker;
    - logic and view ability parity;
    - every active buff exists in `DB/buffs`;
    - no donor mechanic stats survive;
    - each mechanic is present in the logic;
    - own card text exists in `unitsAbility.json`;
    - the pinned native bands, recomputed from the Core, have not drifted.

## Design rules

- **Tier:** the HoMM3/HotA level. Troll moves from t4 to t5.
- **Stat bands:** every stat, squad value and gold must sit inside the native OE tier band, with 20% tolerance on each bound.
  - Bands are computed over the six native factions plus native neutrals.
  - Excluded: avatars, peasants, `undead_peasant` and `lich_dragon`.
  - HoMM3 numbers are kept wherever they already fit.
- **Dragons:** compressed onto the t7 band and anchored on the native Sentinel boss (400 HP, 40/40, squad value 7000, 5000 gold). HoMM3 AI-value order is kept: Rust < Faerie < Crystal < Azure.
- **Actives:** at most the native count for the tier. t1 has none; t2 has one; t3–t6 have up to two; t7 has up to four.
- **Surfaces:** kits use only native or library surfaces:
  - the `STRONG_VANILLA` active kinds;
  - a native unit `aura` (the shape used by angel, esquire and qilin);
  - `heal_percent` regeneration (the native Hydra shape);
  - `inDmgMods` magic resistance;
  - `magic_level` immunity;
  - `triggerCounter=false`;
  - the sharpshooter and free-shooting stat flags.
- **No engine hooks.** HoMM3 abilities with no native surface are listed as gaps, not approximated silently.

## Per-unit table

| Unit | Tier | HP | Att/Def | Dmg | Ini/Spd | Squad value / gold | Profile | Actives | Mechanics |
|---|---|---|---|---|---|---|---|---|---|
| Peasant | 1 | 5 | 1/1 | 1-1 | 3/3 | 15 / 15 | native_donor | none | none (native peasant passives) |
| Halfling | 1 | 6 | 4/2 | 1-3 | 5/5 | 75 / 40 | living | none | positive_luck |
| Boar | 2 | 15 | 6/5 | 2-3 | 6/6 | 145 / 150 | living | none | none |
| Rogue | 2 | 10 | 8/3 | 2-4 | 6/6 | 135 / 100 | living | none | no_retaliation |
| Leprechaun | 2 | 15 | 8/5 | 3-5 | 5/5 | 190 / 100 | living | fortune_spell | luck_aura +1 |
| Nomad | 3 | 30 | 9/8 | 3-6 | 7/7 | 300 / 200 | living | none | none |
| Mummy | 3 | 30 | 7/7 | 3-5 | 5/5 | 270 / 300 | undead | curse | none |
| Sharpshooter | 4 | 25 | 12/10 | 8-10 | 9/8 | 585 / 400 | living | none | sharpshooter |
| Satyr | 4 | 35 | 10/11 | 6-10 | 7/7 | 518 / 300 | living | mirth_spell | none |
| Steel Golem | 4 | 45 | 10/11 | 6-8 | 6/6 | 597 / 400 | construct | none | magic_resistance 0.8 |
| Troll | 5 | 45 | 14/10 | 10-15 | 7/7 | 1024 / 500 | living | none | regeneration 1.0 |
| Fangarm | 5 | 50 | 12/12 | 8-12 | 6/6 | 929 / 600 | hand_authored | Hypnotic Strike (Cove) | Cove kit |
| Enchanter | 6 | 60 | 19/15 | 14-14 | 9/9 | 1400 / 750 | living | bless_spell, magnetic_slow | free_shooting |
| Rust Dragon | 7 | 320 | 30/30 | 50-50 | 15/10 | 5800 / 4000 | dragon | disrupting_ray ("Acid Breath") | none |
| Faerie Dragon | 7 | 250 | 22/22 | 25-35 | 13/9 | 6200 / 4000 | native_donor | native fairy_dragon actives + thunderbolt | native fairy_dragon passives/aura |
| Crystal Dragon | 7 | 360 | 36/36 | 55-65 | 14/9 | 7000 / 4500 | dragon | none | magic_resistance 0.2 |
| Azure Dragon | 7 | 400 | 40/40 | 60-75 | 16/11 | 8000 / 5000 | dragon | fearsome | magic_level_immunity 3, fearless |

## Per-unit reasoning

- **Peasant** (`h3_peasant`)
  - HoMM3: plain level-1 filler.
  - OE: uses the native OE peasant body and its own native passives, which are the OE design for the same creature. HP raised from 1 to 5 to match it.
  - Band exempt: the native OE peasant is itself below every tier band.
- **Halfling** (`h3_neutral_halfling`)
  - HoMM3: level-1 shooter with positive luck.
  - OE: HP raised from 4 to 6 (the t1 floor). No actives, like native t1 units. A Luck floor of +1 carries the identity.
- **Boar** (`h3_boar`)
  - HoMM3: plain level-2 beast.
  - OE: gold raised from 60 to 150, the native t2 neutral anchor. Donor Wolf Rider luck removed. Deliberately plain.
- **Rogue** (`h3_rogue`)
  - HoMM3: enemies do not retaliate.
  - OE: melee with no retaliation via `triggerCounter=false`. Donor Swordsman guard damage reduction removed.
  - Gap: Spy is adventure-map scouting only.
- **Leprechaun** (`h3_leprechaun`)
  - HotA: Fortune three times per battle, and doubles the army's luck.
  - OE: Fortune active (3 charges, +2 Luck for 6 rounds), plus a native adjacent-ally aura of +1 Luck.
  - Gaps: the aura stands in for army-wide luck doubling. The donor shell is the native Halfling shooter, while the HotA Leprechaun is melee.
- **Nomad** (`h3_nomad`)
  - HoMM3: sand walker.
  - OE: damage changed from 2-6 to 3-6 and squad value from 345 to 300, both inside the t3 band. Donor Cavalier jousting (`damagePerHex`) removed.
  - Gap: sand walking is map movement. `nativeBiome` is Sand.
- **Mummy** (`h3_mummy`)
  - HoMM3: undead, curses on attack.
  - OE: undead profile with morale locked, and Curse as a Focus active.
  - Gap: HoMM3 Curse is a 50% on-hit chance.
- **Sharpshooter** (`h3_sharpshooter`)
  - HoMM3: no range or obstacle penalty.
  - OE: HP raised from 15 to 25 (t4 floor 30, tolerance 24). Speed lowered from 9 to 8, the t4 cap. Library sharpshooter flags. Donor Marksman double shot removed.
- **Satyr** (`h3_satyr`)
  - HotA: Mirth.
  - OE: library Mirth ally buff.
- **Steel Golem** (`h3_steel_golem`)
  - HotA: non-living, 80% spell damage reduction.
  - OE: construct profile. Magic damage -0.8 continues the port's golem ladder (Stone -0.5, Iron -0.75).
- **Troll** (`h3_troll`)
  - HoMM3: level 5, fully regenerates the top creature.
  - OE: moved to t5. HP raised from 40 to 45 and Defense from 7 to 10, keeping it a low-Defense bruiser. Regeneration uses `heal_percent max_unit 1.0`, as the native Hydra does.
- **Fangarm** (`h3_fangarm`)
  - HotA: hypnotize, flying, unlimited retaliation.
  - OE: keeps the Cove hand-authored kit. Only stats are pinned from the catalog.
- **Enchanter** (`h3_enchanter`)
  - HoMM3: level 6; mass buffs and Slow; no obstacle penalty.
  - OE: body lifted onto the t6 band. HP 30 to 60, Attack 17 to 19, Defense 12 to 15, squad value 1210 to 1400. Free Shooting, plus Blessing and Magnetic Slow, replace the donor Tower channeler passive.
  - Gap: HoMM3 casts mass versions; OE actives are single-target.
- **Rust Dragon** (`h3_rust_dragon`)
  - HoMM3: acid breath, no spell immunity.
  - OE: breath shell kept. The donor spell immunity is removed and only the dragon cast class is kept. "Acid Breath" is the native permanent -Defense debuff.
- **Faerie Dragon** (`h3_faerie_dragon`)
  - HoMM3: offensive spells, Magic Mirror.
  - OE: keeps the native OE fairy_dragon passives, aura and actives, and adds Thunderbolt.
  - Gap: Magic Mirror has no native unit surface.
- **Crystal Dragon** (`h3_crystal_dragon`)
  - HoMM3: 20% magic resistance, generates crystal.
  - OE: resistance as `inDmgMods magic_damage -0.2`, replacing the donor's spell-level immunity.
  - Gap: crystal income is map economy.
- **Azure Dragon** (`h3_azure_dragon`)
  - HoMM3: strongest neutral; fear; immune to spell levels 1-3.
  - OE: top of the t7 band. Level-3 immunity, Fearsome, and Fearless.
  - Gap: HoMM3 fear is a passive on every enemy; OE uses the library Focus debuff.

## Open proof

- Runtime is untested. The luck aura (an aura carrying `stats.luck`), the Fortune buff, and cast animations on the owned meshes (`animationIndex` 2) have not been exercised in a battle.
- AI casting behaviour and balance are unproven. The squad values follow the native neutral anchors, but no battle has been played.
