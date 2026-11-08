# HoMM3 Tower: Artificing (faction-skill rework)

Status: groundwork only, **disabled** (`custom_factions/tower_artificing/artificing_policy.json` `enabled: false`).
Tower still ships Arcane Battery. Proof tier: source, generated data, build, and contract validator.
The runtime is unproven: nothing has run in Golden Era yet.

## Design (from the request, 2026-10-25)

- **Transcribe** (hero combat action, 2 Focus, cooldown 2, any living stack, friend or foe). It writes that
  creature's *unique* passives into the hero's **Schematic Book**. Generic traits (attack type, movement type,
  creature class) are never written.
- **Arcane Essence.** A won battle gives the winning Artificing hero essence for every enemy creature
  defeated, weighted by tier (`1/2/3/5/8/12/20` for T1..T7). It works like necromancy's lost-stack accounting.
- **Grafts.** Essence copies a book passive onto a Tower unit line. Each line holds **1/1/2** grafts at
  Basic/Advanced/Expert. Cost depends on both the source tier and the target tier (table below). A graft
  covers every variant of the line (base, upgrade, alternate upgrade).
- **Counterplay.** Grafts are applied as battle buffs to that hero's units in each of the hero's combats, and
  they **can be purged**.

All tunables live in `artificing_policy.json`. Nothing else hard-codes them.

## Observation replaces Transcribe (approved 2026-10-26; specs + diagnostic probe built, rolls not yet)

Passives enter the book when they are **observed**: they changed the outcome of a combat event in a battle
that has an Artificing hero. Transcribe and its hero action are removed.

- **Roll.** One roll per passive per battle, on its first observation, at 15/25/35% by Artificing rank. Rolls
  are seeded by battle key + schematic (replays agree) and written to the ledger at battle end, alongside
  essence. AI heroes and auto-resolve get the same path.
- **Who.** Native units on either side. Grafted carriers are never observed. The source tier recorded is the
  observed unit's tier.
- **Predicates, not counterfactuals.** Each category has a rule that is only true when the passive changed
  the result (Melee Defense: its holder took melee damage; poison: the debuff stuck; drain: heal > 0).
- **Map cards.** Proxies where a combat event exists (XP award; max mana and spell level when that hero
  casts); sight, terrain and gold fall back to presence in the battle.
- **Policy.** Every graftable row gets an `observe` spec; the builder refuses a graftable row without one.

### Spike: passive-effect attribution (2026-10-26, source/static)

- Native passive `actions` run as `ejh` (interop `ObjectPublicObckBuObckInObckObckUnique`), built from one
  `Hex.Configs.BuffActionConfig` each. `ejh.befm` subscribes by the trigger string; `ejh.befp`
  (`Method_Private_Void_Object_BattleEventArgs_PDM_0`) is the trigger handler. It checks the trigger
  conditions, gathers targets, then casts through `ekc.bejx` with the `ejh` itself as caster and cast source.
  So every damage, buff and heal it produces carries that `ejh`, and a prefix/postfix on `befp` is an exact
  attribution scope. `ejh.bdwr` is not the executor (it only logs).
- `InCastArgs` exposes `dealer`, `caster`, `castSource`, `affectTargets` and `immuneObjectsOut`, which also gives
  immunity observations for cast-time blocks.
- Mapping a catalog row to the native block: 54 of 87 (schematic, source unit) links match exactly one native
  passive action (`passives[i].actions[j]`), with none ambiguous. The 33 misses have no native unit passive
  action: auras and hero-mana cards come from laws or buff tables (observe by native buff sid + caster), and
  Death Stare / Piercing Sting / Slimy Touch / Aga'Shoth's Help come from attack definitions (observe by the
  damage event's `fromMech` + caster).
- Unproven: that `befp`'s `BuffActionConfig` is the same instance as the unit config's action (config
  identity), and the `ejh` field that holds it (`+0x38` in the body). Needs a diagnostic log in Golden Era.

### Built so far (2026-10-26): observe specs and the attribution probe

- **Specs.** `tools/tower_artificing/observe_specs.py` derives each graftable row's `observe` list from its
  payload and the source units' Core logic. Policy `observeOverrides` replaces the derivation where the native
  mechanic lives elsewhere (32 rows). Two kinds were added for those rows: `aura` (logic `aura` /
  `globalPassives` tags) and `side_modifier` (hero side modifiers and unit-set hero bonuses). The builder
  refuses a graftable row whose payload actions match no native action, or match only some source units,
  unless it has an override. All 159 graftable rows are observable. The review doc has an `observe` column.
- **Tables.** `Homm3TowerArtificingCatalog.g.cs` carries `ObservationChanceByRank`, `ObservationDiagnostics`,
  `ObservationDiagnosticLogLines`, `ObserveKindsBySchematic`, `ObservedPassiveActionsByUnitSid` (unit ->
  passive/action -> schematic), and buff / aura / side-modifier tag -> schematic maps.
- **Probe.** `Homm3TowerArtificingObservation` is diagnostic only. It is registered whenever
  `policy.observation.diagnostics` is true, even while `enabled` is false. It never rolls and never writes
  the book. It patches:
  - a prefix and postfix on `ejh.befp`, opening a thread-local scope;
  - the unit buff add;
  - the ObjectTookDamage dispatcher.

  Each scope that hits a catalog-linked action or produces an effect logs one line:

  ```
  befp unit=<sid> passive=i action=j trigger=<t> identity=match|miss|owner:not-a-registered-unit
  schematic=<n:key|none> effects=[buff:<sid>[:refused], dmg:<n>[:immune][:killedN]:src=runner|other]
  ```

  Outside any scope, it also logs damage whose castSource is a recently fired runner (`deferred`) and buff
  adds whose sid is an observe tag. It stops after `diagnosticLogLines` lines per launch.
- **In-game check reads.** `identity=match` on linked units proves config identity. `src=runner` inside the
  scope proves in-scope casting. Tagged-buff lines name the native aura buff sids, if auras apply buffs
  under their tag. Rolls, the ledger write and the Transcribe removal come after that check.

## Pieces

| Piece | File | Notes |
| --- | --- | --- |
| Policy | `custom_factions/tower_artificing/artificing_policy.json` | Slots, essence, cost formula, ledger layout, generic rules, curated payloads, exclusions |
| Catalog generator | `tools/tower_artificing/build_schematic_catalog.py` | Reads Core (default: the GE install) and writes the three outputs below. Runs in about 0.5 s |
| Catalog | `custom_factions/tower_artificing/schematic_catalog.json` | One row per view passive; indices are stable and never reused |
| Review table | `docs/generated/homm3_tower_artificing_schematics.md` | For curating payloads |
| C# catalog | `OfflineUnlockMod/Homm3TowerArtificingCatalog.g.cs` | Constants, cost matrix, unit tiers, graftable schematics per unit, `Enabled` |
| Core rows | `tools/release_port/homm3_tower_artificing_core_overlay.py` | Called from the `homm3_tower` overlay block |
| Runtime | `OfflineUnlockMod/Homm3TowerArtificingRuntime.cs` | Ledger, battle-start grafts, runtime grafts (on hit, vampirism, first round), essence, Transcribe capture, `TryGraft` |
| Validator | `tools/validate_homm3_tower_artificing_contract.py` | Full build tier (`-p:FullValidation=true`). Core-free |

Regenerate after any policy edit with `python tools/tower_artificing/build_schematic_catalog.py`.
`--check` compares against a fresh Core read. `--check-derived` is the Core-free check the build uses.

## Schematics: what can be copied

The catalog has one row per **view passive**, the `{name, description}` card a unit shows. View passives
are display labels. They are not index-aligned with the unit's logic passive blocks (365 of 424 units
mismatch), and their mechanics often live elsewhere (stats such as `numCounters`, `moveType`, attack
`targetMechanics`). So payloads are **curated, never inferred**:

- `generic`: matched by `genericRules` (attack type, movement type, creature class). Never transcribed.
- `excluded`: `excludedKeys`. Attack shapes a buff cannot change, and the Peasant's pet flavour card.
- `copyable`: `graftable` only once `manualPayloads` gives it a buff-compatible payload
  (`data` limited to stats, disablers, immunities, sequenceEffect, alwaysMinDmg; plus `actions` and
  `statOverrides`), helper rows, a `runtime` effect or a `perUnit` rule (see Runtime grafts). Unmapped rows list `candidates`, the distinct non-class logic blocks of the units that
  show the passive, as review hints.

Current numbers: 191 schematics, 24 generic, 8 excluded, **159 graftable**, 0 still needing a payload.
Transcribe records only graftable schematics.

Curation (2026-10-25) read each source unit's raw Core logic. A passive's mechanics turned out to live in one of
four places, and that decided the outcome:

| Where the mechanic lives | Outcome | Examples |
| --- | --- | --- |
| Logic passive block (`data`, `actions`) | Copied verbatim, split when one block holds two cards | Regeneration, Anointed for X, Embodiment immunities |
| Unit `stats` (`inDmgMods`, `armorPen`, `damagePerHex`, `energyPer*`, ...) | Copied as buff `data.stats` (delta vs the h3 default where additive) | Melee/Ranged/Magic Defense, Piercing Strike, Jousting |
| Attack definition: on-hit buff, vampirism | Runtime graft (on hit) | Poison/wound on hit, Life Drain |
| Attack definition: `kill_stacks`, pure damage | Native `unit_took_damage` action on the graft buff (Holy Arms shape) | Death Stare, Frost Breath |
| Attack shape (attack pattern, reach, multi-target) | Excluded | Area Strike, Rumble, Swipe |
| Nowhere in the unit config: auras | Graft buff instacast `global_buff` or a radius `attack_swirl` action + `{graft}_aura` helper | Inspiring, Purity Aura |
| Nowhere in the unit config: hero mana / spell power | Side buff helper (`heroStat` delta) applied each round | Mushroom Magic |
| Count/faction synergies, per-unit numbers | Runtime first-round graft, or a `perUnit` variant row per carrier | Hive Queen, Godslayer, Rebirth |
| Native unit set (`DB/unit_sets`): hero map stats | Map graft: hero buff with the set's bonuses | Sight, Experience, Terrain, Max Mana, Spell Level |
| Plugin day-start grant | Map graft: tier-scaled daily gold | Swashbuckler gold, Peasant taxes |
| Unit `abilities` (active card) | Ability graft: the source ability injected at Unit.Init | Golem Web, Gremlin Repair |

`excludedKeys` (8) holds the attack shapes (6), `base_passive_countershot` (needs a StepQueue push from a buff)
and `peasant_passive_2` (flavour tied to the Peasant's pet). The out-of-battle and active cards are map and
ability grafts (below). `druid_passive_2` became a map graft: its native effect is the
`druid_upg_alt_globalbuff` unit set (`magicSchoolSet` hero stats), not the unit's `sideModifiers`.

## Runtime grafts

Every runtime graft still needs its graft buff on the carrier (`CarrierStillGrafted`), so purge ends it too.

- **On hit** (`OnHitBySchematic`): ObjectTookDamage dispatcher postfix. A carrier's damaging hit whose dealer
  tags hold `basic_attack` (counters included), optionally filtered to `melee_attack` / `shoot_attack` /
  `range_attack`, adds the source debuff to an enemy receiver. Fangarm then runs native
  `MechBerserk.ApplyBerserk` (the MechRevengeBerserk event-time call) when its berserk debuff stuck.
- **Vampirism** (`VampirismBySchematic`): native `UnitHealer.Heal(round(damage x rate), EHealType)` on the
  carrier (Flicker, Vampire) or every other ally (Lich). Revive stays false.
- **First round** (`BattleStartBySchematic`), once per battle on the first RoundStarted: Hive Queen gets a buff
  per enemy base faction present; Demon gets `hive_n` for n distinct allied demon kinds (cap 7); Bulwark flyer
  slow puts the Frostbound Skies slow on every enemy flyer once per side.
- **Per unit** (`GraftVariantBuffSid`): Godslayer (+50% vs units above the carrier's tier, so nothing on T7),
  Duelist (the melee penalty offset, only h3_gremlin_upg has one) and Rebirth (a heart obstacle that respawns
  the carrier's own sid; `OncePerBattleSchematics` keeps it off units initialized after round 1).

Known approximations: native on-damage actions also fire on ability damage; aura helpers stack with real
native auras; a radius aura can linger until round end after moving away; Hive Queen covers the six base
factions; Eldritch energy block lasts until round end; Weakening Shot copies only the weakness half; side
buffs add to native modifiers.

Proof tier: source only. Native buff rows in Core already use every `data.stats` key family above except
`luckMin`/`luckMax`/`moralMin`, `crit`, `damagePerHex`, `damagePerDeltaLevel*`, `outDmgModsByTargetTags`,
`overkillProtection` and `additionalActionChanceModifier`. Those are unit stat fields that a buff has never
carried in vanilla. The same goes for the `maxInComingNegativeBuffDuration` override (Primal Stubbornness) and for
the `assist_ability` / `add_attack_after_counter_melee` sequence effects, which appear only on units. `Homm3BuffDebuffNativeAdapter` folds only speed/initiative/offence/defence (+perc), so
everything else relies on native buff aggregation. Check in Golden Era before enabling.

## Map and ability grafts

Out-of-battle cards (approved 2026-10-25). Their battle graft buff is only a label: dispelling it in battle
changes nothing, and its text says "(Artificing graft.)" without the dispel note.

- **Hero stats** (`MapHeroBuffBySchematic`): a visible, dispellable hero map buff `homm3_tower_graft_{i}_map`
  carrying the source unit set's own bonuses (the builder checks they match Core). The hero holds it while the
  army has a stack of a line carrying that graft. It is skipped while the army has a native unit of that unit
  set, because native set bonuses do not stack. Reconciled in a `Logic.Hero.RecalculateStats` postfix (native
  `UnitSets` calls it on every army change and at load), at day start and after `TryGraft`. Only the graft slot
  bits are read, cached per hero, and re-read on rank change. AI heroes get it the same way.

  | Card | Source set | Hero stat |
  | --- | --- | --- |
  | crossbowman_passive_1 | crossbowman_globalbuff | viewRadius +1 |
  | lich_passive_2 | lich_globalbuff | expPerBonus +0.10 |
  | frostworm_rider_passive_1 | frostworm_rider_globalbuff | landscapePenaltyPerBonus -0.5 |
  | arbitrator_passive_3 | arbitrator_globalbuff | manaBonus +20 |
  | druid_passive_2 | druid_upg_alt_globalbuff | magicSchoolSet day/night/space/primal (+1 level) |

- **Daily gold** (`DailyGoldBySchematic`): per carrier creature, added to the side's day-start grant through a
  `Homm3SwashbucklerGoldHook` consumer. It is tier-scaled by weekly growth,
  `round(gold x source growth / line growth)`, using city dwelling `weeklyIncrement` (the Peasant's comes from its
  hire site). The native income forecast does not show it.

  | Card | Base | T1 | T2 | T3 | T4 | T5 | T6 | T7 |
  | --- | --- | --- | --- | --- | --- | --- | --- | --- |
  | Swashbuckler (growth 14) | 15 | 12 | 15 | 30 | 35 | 70 | 105 | 210 |
  | Peasant taxes (growth 60) | 10 | 33 | 43 | 86 | 100 | 200 | 300 | 600 |

- **Abilities** (`InjectedAbilitiesBySchematic`): at `Unit.Init`, after the graft buff sticks, the runtime
  appends fresh copies of the source unit's `abilities[i]` to the carrier's `AbilitiesSet[Ability]` array. It
  mirrors `AbilitiesSet.InitAbilityArray`: a new Ability, caster first, then
  `Init(logic, view, AbilityID{Ability, n})`. The configs come from the catalog's embedded source JSON through
  `JsonUtility.FromJsonOverwrite`, so each carrier owns its copy. It skips the source unit itself and anything
  past the 5 HUD skill slots (alternative attacks + abilities). Golem Web is 1 ability; Gremlin Repair is 2,
  the first with 2 charges. Dispel does not remove an injected ability.

## Ledger (save-safe, no managed cache)

The ledger is stored as hidden, bonus-less hero map buffs in `DB/heroes_buffs/heroes_buffs.json`, saved with the
hero. This is the Dungeon Captives pattern, and the state is rebuilt from the buffs on every read.

| Field | Buff sids | Encoding |
| --- | --- | --- |
| Essence | `homm3_tower_artificing_essence_bit_{0..15}` | 0..65535 (capped) |
| Book | `homm3_tower_artificing_schematic_{i}_bit_{0..2}` | lowest source tier seen, 0 = not known |
| Grafts | `homm3_tower_artificing_graft_l{line}_s{slot}_bit_{0..8}` | schematic index + 1, 0 = empty |

The rows must be `isDispellable: true`, because native hero-buff Remove only drops dispellable configs. That
means a map-level hero dispel would wipe the ledger; Captives carries the same risk. Each graftable schematic
adds 3 rows; the 159 graftable schematics, essence and graft slots come to 619 hidden ledger rows.

## Battle flow

1. `BattleLogic.Init` prefix. For each side whose hero has `skill_faction_homm3_tower`, read the graft slots.
   Only the first `graftSlotsByRank[rank]` slots of each line are active; higher slots stay stored but inactive
   until the hero ranks up.
2. Shared `Unit.Init` consumer. A unit of a grafted Tower line, matched by its battle-local side index, gets
   `homm3_tower_graft_{i}`: canDispel, infinite, `addition: data`, carrying the passive's own data. It is added
   through `Homm3BuffDebuffNativeAdapter`, so purge removes it natively.
3. Transcribe. The ability applies the 1-round marker `homm3_tower_transcribe_effect`. A postfix on the unit
   buff add (`dzv.bbgf`) records the marked unit's graftable schematics for the caster's hero. The caster hero
   is the caster's `TransferSide.logicHero`; if that cannot be read, it is the only Artificing hero in the
   battle. If both sides have one, the cast is refused and logged.
4. Battle result. The shared prefix (`Homm3RuntimeMechanicHooks.PrefixBattleResultCleanup`) adds essence to
   the winner. Essence is creatures lost by every other side × tier essence, deduped per battle key.
   Untiered units (summons, specials) give nothing and are logged.

## Graft cost

`round_to(25 × tierWeight[source] × tierWeight[target], 5)`, with tierWeight `1, 1.5, 2, 3, 4, 5.5, 7`.

| src \ dst | T1 | T2 | T3 | T4 | T5 | T6 | T7 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| T1 | 25 | 40 | 50 | 75 | 100 | 140 | 175 |
| T2 | 40 | 55 | 75 | 110 | 150 | 205 | 260 |
| T3 | 50 | 75 | 100 | 150 | 200 | 275 | 350 |
| T4 | 75 | 110 | 150 | 225 | 300 | 410 | 525 |
| T5 | 100 | 150 | 200 | 300 | 400 | 550 | 700 |
| T6 | 140 | 205 | 275 | 410 | 550 | 755 | 960 |
| T7 | 175 | 260 | 350 | 525 | 700 | 960 | 1225 |

- **Source tier:** the lowest tier the passive was transcribed from. Transcribing a cheaper source later
  lowers the price.
- **Replacing a graft:** pays the full new cost, with no refund.
- **Reference point:** one won fight against 20 T3 creatures is worth 60 essence.

## Enabling (in order)

1. **Spend UI.** `TryGraft(logicHero, line, slot, schematic)` exists, but nothing calls it. The surface
   (town building, hero screen, or world spell) is a user decision, and the mockup needs approval before install.
2. **Payloads are curated** (159 graftable). Countershot still needs a new native surface.
3. **Flip `enabled: true`** and regenerate. The overlay then grants Transcribe at every rank and renames the skill
   Artificing. The runtime registers only when `Homm3TowerArtificingCatalog.Enabled` is true.
   `validate_homm3_tower_arcane_battery_contract.py` still expects Arcane Battery level grants. Retire or branch it
   in the same change.
4. **Golden Era check:**
   - the caster TransferSide read on a hero-ability caster
   - graft buffs visible and purgeable
   - whether `statOverrides` (Alert, Unlimited Retaliation) and `sequenceEffect` (Parry) take effect from a
     buff added at `Unit.Init`. The adapter folds only four `data.stats` fields; immunities are the safest graft kind.
   - one graft per payload kind: inDmgMods (Melee Defense), a vanilla-unseen stat (Jousting `damagePerHex`),
     `disable_counter` (Swift Strike), and an `actions` trigger (Regeneration)
   - essence after auto-resolve
   - runtime grafts: the `basic_attack` dealer tag on melee, shots and counters; on-hit debuff + Fangarm berserk;
     vampirism heal amounts; the first RoundStarted fires after every Unit.Init; side-buff mana cost and
     spell power; aura helpers refresh each round; Rebirth heart respawns the right sid
   - map grafts: `Method_Public_Void_1` really is RecalculateStats (static proof: caller counts); the hero buff
     appears and leaves with the carrier stack; no reentrancy loop; non-stacking with a native set unit;
     manaBonus / magicSchoolSet read from a hero buff; daily gold on the side's day start
   - ability grafts: JsonUtility fills the configs (a `damageDealer`-less parse is skipped and logged); the HUD
     shows the injected skill; cast animation index 2 on carriers; charges reset per battle; the unit info
     window may not list the injected ability

## Open questions

- **Spend UI location** (see above).
- **Arcane Battery subskills.** When enabled, the faction skill grants only Transcribe. The existing Arcane Battery
  subskills (Arcane Curriculum, Chronomancy with Borrowed Time) still exist; they could stay, be reworked
  into Artificing subskills, or be retired.
- **Per-line or per-unit grafts.** The current design is per line (upgrades keep grafts). Changing it needs a
  ledger migration.
- **Simulated battles.** Auto-resolve and AI-vs-AI run the real battle logic (`law_runtime_hooks_20261021.md`).
  The battle key dedupes repeated result prefixes for one BattleLogic, but whether essence should come from
  simulations at all is a design decision.
- **AI heroes.** Transcribe has `aiValue 0`, so AI heroes never cast it and never spend essence. That is a
  deliberate human-only advantage for now.
- **Enemy-only Transcribe.** The current design allows friendly targets, so a hero can transcribe their own army
  for free. If that is too strong, Transcribe could be enemy-only or cost essence.
