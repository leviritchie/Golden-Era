# Faction law pass: cross-faction review (2026-11-21)

Inputs: the 12 drafts in this folder (`<faction>.md`), checked against `BASELINE.md` and `BRIEF.md`.

## 1. Shape and power check

| Faction | Laws | Skill (S) | Cost r0 / r1 / r2 / r3 / r4 | Total |
|---|---|---|---|---|
| Castle | 30 | 5 | 22 / 27 / 34 / 40 / 26 | 149 |
| Rampart | 30 | 5 | 25 / 27 / 29 / 35 / 29 | 145 |
| Tower | 30 | 5 | 22 / 30 / 30 / 33 / 25 | 140 |
| Inferno | 30 | 5 | 21 / 27 / 29 / 23 / 31 | 131 |
| Necropolis | 30 | 5 | 23 / 30 / 30 / 25 / 32 | 140 |
| Dungeon | 30 | 5 | 25 / 27 / 29 / 34 / 25 | 140 |
| Stronghold | 30 | 5 | 22 / 28 / 36 / 37 / 23 | 146 |
| Fortress | 30 | 5 | 22 / 29 / 35 / 32 / 29 | 147 |
| Conflux | 30 | 4 | 21 / 33 / 26 / 33 / 28 | 141 |
| Cove | 30 | 5 | 25 / 30 / 35 / 26 / 27 | 143 |
| Factory | 30 | 5 | 20 / 28 / 38 / 31 / 27 | 144 |
| Bulwark | 30 | 4 | 22 / 31 / 25 / 32 / 30 | 140 |
| **Vanilla band** | 30-35 | 1-7 | 19-30 / 25-33 / 25-42 / 22-47 / 21-44 | |

- Every rank of every faction is inside the vanilla band. Law count is 30 everywhere, at the bottom of vanilla's 30-35.
- Every faction now has 4-5 laws that act on its unique skill, one at r0-r1 and one at r3-r4; before the pass it had none.
- The clone laws are gone from all 12 factions. These were the Human drills, Arcane Exercises, Quartermaster Ledgers, Swift Reflexes, Native Mastery, the formation laws and Encouragement.
- The out-of-band values are fixed:
  - Castle movement: +200 becomes +10/+20.
  - Sight: +2/4/6 at r0 becomes +1 or +1/+2.
  - Morale: +2 becomes +1.
  - The +10% all-damage laws at r0-r1 are removed.
  - Law points: +20/40/60% becomes +10/20/30%.
  - Extra building per day: cost 6 becomes 3.
  - Learn-every-tier laws cost 3 at r4.
- Every line has one Elite law, placed in its tier's rank band. Each Elite law gives growth plus an extra effect taken from that unit's kit.

## 2. Cross-faction collisions and what I changed

Vanilla itself repeats shapes across factions: five tables have +1 building per day, two have enemy spell cooldown +1, two have the no-escape law. So the rule I applied is this: a shape may appear in at most two factions. When two factions share the same law at the same rank and value, one of them is changed to differ. Within a faction, near-duplicates were already removed in the drafts.

| Collision | Factions | Decision |
|---|---|---|
| Enemy hero gets 1 less Focus per round | Inferno, Fortress, Conflux | **Conflux Planar Static → Astral Conduit**: your heroes' spells cost -10%/-20% Mana (`manaCostBonus`), r4, cost 4. Inferno and Fortress keep theirs. |
| +damage vs stacks that have not acted | Dungeon 5/10% r0, Fortress 10/20% r1, Cove (ranged only) | **Fortress Hunters of the Mire → Bog Mist**: enemy creatures deal -10%/-20% ranged Damage (`modifierSet outDmgMods shoot_attack` on enemies), r1 A, 3/3. Fortress already carries two prey damage laws (Scent of Blood, Pack Kill); this gives it a defensive swamp law instead. |
| Damage over time +25/+50% at r0 | Inferno, Fortress | **Inferno Hellfire Brands becomes outgoing**: damage over time dealt by Inferno creatures +25%/+50% (`outDmgMods overTime_effect` on Inferno receivers). Fortress Swamp Venom stays incoming on enemies from every source, including spells. |
| Positive effects last 1 more round, r0 A | Castle, Tower | **Tower Overclocked Spellworks → Unravelling Wards**: positive effects on enemy creatures last 1 round less (`inComingBuffDuration -1`, enemy). Castle keeps the liturgy law. |
| Enemy heroes lose 1 level in every school (copy of vanilla Undead's law) | Rampart, Necropolis | **Necropolis keeps Deathly Silence.** **Rampart Pegasus Winds → Wellspring of Life**: healing on friendly creatures +25%/+50% (`finalHealingBonusPercent`), r4 K, 3/3. |
| +damage vs stacks below half Health | Stronghold 10/20% r4, Necropolis 5/10% r4 | **Stronghold No Mercy cut to 5%/10%**, so the same law has the same strength. Stronghold also has Gang Up and Smell of Blood. |
| No mixed-army Morale penalty | Dungeon, Necropolis | Owner decision Q3. |
| Accepted (2 factions, different ranks, values or identity) | | Enemy spell cooldown +1 (Stronghold, Factory). Own spell cooldown -1 (Tower, Fortress). Focus limit +1 (Tower, Bulwark). Home-area Attack/Defence (Castle, Bulwark; Necropolis has the "not your area" inverse). External dwellings +50/100% (Stronghold, Bulwark). No escape (Dungeon, Fortress). Fallen-stack scaling (Stronghold, Necropolis). +1 Morale (5 factions, vanilla-common). |

## 3. Decisions I made (not owner questions)

- **Tower and Factory manifests:** `factionSkillName` gets the live skill names, Artificing and Logistics Network. The old names were Arcane Battery and Split Assembly.
- **Row 13 runtime:** the counterattack-doctrine plugin family stays only where a draft keeps it.
  - Kept: Tower Reactive Wards, Necropolis Death Grip, Cove Boarding Hooks.
  - Every other faction that reuses index 13 or another family index (2, 15, 18, 19, 21, 22, 25, 27, 28, 33, 34) for a new law is removed from that family's per-faction profile. Old effects therefore never fire under new text.
  - The hidden Conflux hero-stat effect on 18/19/27 is retired.
- **Dungeon:** Dungeon's law-22 morale profile is removed. Dread of the Deep (#23) is the single source of enemy Morale -1.
- **Conflux, Perfect Conjunction:** ships at 95%/100% as drafted. It is an r4 capstone at 8 points.
- **Bulwark, Runes Carved in Advance:** ships at Rune Level 1/2; cut it to 1 only if round-1 Bulwark plays too strong.
- **Bulwark, Elder Runes:** gets new Rune buff rows 10-12, so the higher cap carries stats.
- **Fortress, Beastmaster's Eye:** kept. Making sorted pairing the skill's default is a separate later change.
- **Builder choices on the drafts' open questions:**
  - Tower: Twin Grafts at r2, Warded Grafts as drafted.
  - Inferno: Legion Gate at r2, Gate Sigils L2.
  - Rampart: Call of the Grove at r3.
  - Cove: King's Ransom +20/40/60%.
  - Factory: Salvage Crews at r4.
  - Dungeon: Overlord's Due at half strength, never Enslave or Recruit.
- **Laws with no lever are left out:** Castle Gate, Cover of Darkness.

## 4. Owner decisions (asked before building)

1. **Stronghold Elite Orcs:** Orc-line shots raise the Warcry, for this one line only. This reverses the 2026-11-18 ruling that shots don't raise it. Fallback rider: +3/+6 Attack.
2. **Laws that widen a skill past its current boundary:**
   - Castle Grand Strategem: Spread and Compress against enemy hero armies, and Ambush at L2.
   - Necropolis Lords of the Dead: the player's heroes of other factions raise at 5%.
   - Necropolis Unearthed Graves: hero-less town garrisons raise at 5%.
   - Cove Crew Ashore: heroes without the skill collect map pieces.
3. **The mixed-army Morale exemption,** removed from Dungeon's skill ranks on 2026-11-19: bring it back as a paid law for Dungeon (Many Races Below), for Necropolis (Legion Without Banner), for both, or for neither.

## 5. Build plan

1. **Law overrides:** each faction's `custom_factions/law_overrides/homm3_<f>.json` gets every tree law's text and levels, plus a top-level `lawTree` (explicit ranks and columns, new overlay support). Unused indices get `enabled: false`.
2. **Overlay:**
   - `VANILLA_LAW_CLONE_SOURCES` follows the new clones.
   - The dormant-sid list is cleaned.
   - Law-granted buff rows (B) are added.
   - Rune buff rows 10-12 are added.
3. **Plugin:**
   - Add the generic `CustomLawRank` reader (done in this pass).
   - Hook each (S) law into its skill runtime.
   - Add law-switched kit rules (C).
   - Retire the family profiles listed in section 3.
4. **Validators:** update the law tree layout check, the clone pins and the runtime index coverage to the new trees.
5. **Text and install:** translate the changed law text into all 15 locales, then install into GE with Core and DLL backups and the payload_abi sidecar.

## 6. Owner answers (2026-11-21)

1. **Stronghold Elite Orcs.** Refused: the Warcry subskill already lets shots raise the Warcry. The rider is +3/+6 Attack, so Stronghold has 4 (S) laws.
2. **Skill-widening laws.** Castle Grand Strategem and Necropolis Unearthed Graves are approved. Necropolis Lords of the Dead and Cove Crew Ashore are rejected because they are irrelevant in single hero mode, the most popular mode. Every law must matter with one hero, so:
   - Lords of the Dead and Crew Ashore get single-hero (S) replacements.
   - Cove Letters of Marque (a hero hiring discount) becomes Privateers' Pact (neutral creatures more willing to join).
3. **Mixed-army Morale exemption.** Dungeon only (Many Races Below). Necropolis Legion Without Banner becomes Grave Chill: enemy creatures -1 Initiative.
4. **Conflux Elemental Balance** (coordinator decision). Native +5% dealt / -5% taken for Conflux creatures, with no composition condition.
