# Conflux (`homm3_conflux_city`) building pass

Source of current rows: installed GE Core.zip `DB/objects_logic/cities/homm3_conflux_city.json` (extract in `V:/olden_port_work/building_pass/claude_shf/conflux_city.json`). Mechanics rows: `custom_factions/source_mechanics/homm3_conflux.json`.

## 1. Special buildings

| SID | Source building (HoMM3/HotA effect) | Current effect | Status | Proposed build | Player text | Cost/power note |
|---|---|---|---|---|---|---|
| Build_Spring_of_Life (grail slot) | Aurora Borealis: this town's Mage Guild offers every spell of each level it has built (plus the standard grail growth). | "Prismatic Beacon": NatureGraal (empire +1 growth, city +100%). Substituted. | Substituted | Fully native, the same effect as vanilla's Unfrozen grail:<br>- `graalType: "UnfrozenGraal"`;<br>- `cityBonuses: [{"type":"magicGuildExpandMagics"}, {"type":"cityUnitsIncrementPer","parameters":["all","1.0"]}]`;<br>- `sideBonuses: []`.<br>Rename it "Aurora Borealis" and mark the mechanics row exact. The forbidden texts "all spells", "every spell" and "Aurora Borealis" only blocked claims the substitute could not keep; remove them. | Vanilla wording: "Building a Mage Guild in this city unlocks all spells of the corresponding tier. This city's dwellings produce +100% units." | Grail cost unchanged. It drops the empire +1 growth for the real effect. The Conflux Mage Guild reaches L5, so it is at full value. |
| Build_Bank | Magic University: a visiting hero may learn Air, Earth, Fire or Water Magic (Basic) for 2000 gold each. Needs Mage Guild 1. | "Magic University": heroBonusBanks `spellPower 1`, <- MG1. Substituted. | Substituted | Plugin hook `Homm3ConfluxMagicUniversityRuntime` (section 3) offers OE's 4 magic school skills, one for one with HoMM3's 4 schools: `skill_magic_day`, `skill_magic_night`, `skill_magic_space` and `skill_magic_primal`.<br>- Only schools the hero lacks are offered, and only while the hero has a free skill slot.<br>- Preferred UI: the native map-University picker (`selectionWindowType "skillsRewardSet"`, `HeroSkillAdditionReward [skillSid,"true"]`, `rewardCost` gold); fallback: a plugin picker.<br>- Row: section `banks`, `bonuses: []`, text override.<br>Mechanics row becomes exact (the school mapping is OE's own; the existing forbidden HoMM3 school names stay). | "Allows each visiting hero to learn Day, Night, Space or Primal Magic for 2500 Gold each." | Building cost kept (2500 gold, 5 wood, 5 ore). Price per skill: HoMM3 2000 scaled to OE's map University price, 2500. The user note "500 astrology daily" conflicts (owner decision 1). |
| Build_Resource_Depot | Resource Silo: +1 mercury. | +1 mercury, 2000 gold. Row says substituted. | Effect exact, row stale | No data change. Reclassify the row as exact. | Unchanged. | Unchanged. |
| Build_Mother_Nature | Garden of Life: +10 Pixie growth. | `h3_pixie 0.715`. | Exact | No change. | Unchanged. | Unchanged. |
| Build_Resource_Depot_level_2 | Owner-added "Vault of Ashes": +1 Firebird. | `h3_firebird 1.01`, <- T6:1. | Exact (owner) | No change. | Unchanged. | Unchanged. |
| Build_Mycelium_Roots | Owner-added "Elemental Conflux": +1 each elemental. | +1 air/water/fire/earth growth, <- T2 + T3 + T4 + T5. | Exact (owner) | Effect unchanged; tree fix only. | Unchanged. | Unchanged. |
| Build_Treasury | Blacksmith (First Aid Tent, a war machine). | "Blacksmith": 2000 gold. | Substituted (honest) | Keep, per the 2026-10-01 decision. Reason: "Olden Era has no war machines; the slot is the shared Treasury." | Unchanged. | Unchanged. |

Specials changed: 2 (Aurora Borealis, Magic University). Resource Silo gets a row reclassification only.

## 2. Tree changes

Slot roles:
- `Build_Bank` is a special (Magic University), so Conflux has no economic Bank.
- `Build_Treasury` is the economic Treasury.

| Level | Current prerequisites | Proposed prerequisites | Why (convention) |
|---|---|---|---|
| Build_Main:2 | Main:1, Tavern:1 | Main:1 | Town Hall L2 needs only the previous level. |
| Build_Main:3 | Main:2, Magic_Guild:1, Market:1 | Main:2 | Removes the HoMM3 Capitol gate. |
| Build_Market:1 | (none) | Tavern:1 | Vanilla: Market needs Tavern. |
| Build_Tier_6:2 | Tier_6:1, Magic_Guild:2 | Tier_6:1 | Only a T7 upgrade may carry a Mage Guild prerequisite. |
| Build_Treasury:1 | Bank:1 (Magic University, a special), Wall:1 | Main:2, Wall:1 | Treasury should not depend on a special; Main:2 stands in for the absent economic Bank. |
| Build_Mycelium_Roots:1 | Tier_2:1, Tier_3:1, Tier_4:1, Tier_5:1 | Magic_Guild:1 | Four prerequisites is denser than any vanilla special. One base-level shared prerequisite fits the elemental theme (owner decision 3). |

Kept on purpose:
- T2:1 / T3:1 <- T1 + MG1: HoMM3 flavour; vanilla Unfrozen T4 also needs MG1.
- T4:1 <- T2, T5:1 <- T3, T6:1 <- T4 + T5 and T7:1 <- T6.
- Garden of Life <- T1:1 and Vault of Ashes <- T6:1, because a horde needs its dwelling.
- Magic University <- MG1 (HoMM3 requirement, one base-level shared prerequisite).
- Depot <- Market (there is no economic Bank to add).

The layout loses edges and adds no nodes, so it still fits columns 0..8 x 5 rows.

Levels without outside prerequisites (of 35): 19 before, 21 after.

## 3. Plugin work

1. **`Homm3ConfluxMagicUniversityRuntime.cs`** (new, `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/`).
   - Opens from the building's city-screen click when a hero is in the town (precedent `Homm3DungeonWarCaptivesWindow.cs`).
   - Preferred path: build a native reward selection like the map University event bank (`skillsRewardSet`, `rewardSetApplyType "OnlySelected"`, `HeroSkillAdditionReward`, gold `rewardCost`) and hand it to the game's selection window, so the native skill-add and its UI are reused.
   - Fallback: a plugin list that charges gold and adds the skill through the same reward class.
   - No plugin "add skill to hero" helper exists yet.
   - Risk: medium. Building a native reward object outside a map object may need a dummy context. IL2CPP generic/list interop applies (see the `project_il2cpp_generic_method_crash` memory: write fields, avoid generic overrides).
2. **Tools (not plugin):**
   - `homm3_city_building_descriptions.py` needs the UnfrozenGraal shape (`magicGuildExpandMagics` + growth) with the vanilla sentence, and a text override for Magic University.
   - The tree validator must accept Treasury <- Main:2 + Fort for towns whose `Build_Bank` is a special.
   - The Town Hall / City Hall gate removal is shared by all 12 towns.

## 4. Owner decisions

1. **Magic University effect.** Option A: the HoMM3 effect (buy a magic school skill, 2500 gold each). Option B: the earlier note in `docs/mechanics_audit/user edit of faction mechanics.csv`, "Give 500 astrology points daily instead". Option B is not the source effect.
   - Recommendation: A.
2. **Aurora Borealis drops the empire +1 growth.**
   - Recommendation: yes. The full Mage Guild is the defining effect, and +100% city growth keeps it grail-strength.
3. **Elemental Conflux gate.** Option A: Magic_Guild:1 (shared, thematic). Option B: one dwelling, Tier_2:1.
   - Recommendation: A, which follows the "specials take a shared prerequisite" convention.
