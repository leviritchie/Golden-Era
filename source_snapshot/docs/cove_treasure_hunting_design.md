# Cove Treasure Hunting: buried treasure, map pieces, digging

Status: built and installed 2026-11-17 (pieces, markers, Dig, payout, popups, the five runtime picks); in-game
testing is under way, see 10.1 and `docs/ingame_check_queue.md`. The user wrote the rules (2026-11-17); this doc turns
them into data, formulas and runtime pieces, and marks what is proven, likely or unknown in the current build.

Replaced the earlier `skill_faction_homm3_cove` content: the 0-mana Groundsight variants and Plunder (chests/mines)
are both retired and no longer installed (section 11).

## 1. Rules (user spec, 2026-11-17)

- Every map region has one buried treasure. Its value scales with the region's resource richness.
- Digging: stand on the exact tile and spend most of a day's movement (see 6.3).
- Each region has **5 map pieces** stashed in interactable objects or guarded stacks.
- A Cove hero's **search radius** = half the hero's *base* vision, ignoring vision upgrades. Base `viewRadius` is 6 in
  every hero row checked (`DB/heroes/*/*.json`), so the search radius is **3 tiles**.
- Map piece holders inside a Cove hero's search radius are revealed to that side.
- Visiting the object or beating the stack grants the piece.
- Piece count → treasure candidates shown (visible through fog): 1 → 4 candidates, 2 → 3, 3 → 2, 4 → 1 (exact). The 5th
  piece is buffer.
- If a non-Cove hero removes a holder, the piece stays on that empty tile for a Cove hero. Non-Cove heroes can never
  collect pieces or dig.
- Pieces and treasure candidates are spread apart, with a spacing guard that relaxes when the terrain forces it.
- Every map, random or hand-made, needs this data (a Cove hero can be hired as a secondary), so it must not slow loading
  in non-Cove games.

## 2. Vanilla facts this rests on

| Fact | Source |
|---|---|
| Regions are native `MapData.areas[] {id, keyObjectId, rootNode, nodes[], neighbors[], biome}`; `nodes` are tile indices | finished `.map` files; `GameSymbols.cs` ~6642; `docs/plans/2026-07-09-zone-choke-atlas.md` |
| Hand-made maps have regions (Thirst for Power 6, Broken Alliance 16, Mysterious Island 75), but H3 stock imports and `c_M1` have **one area for the whole map** | map survey |
| Template richness exists only during generation: `guardedContentValue`, `unguardedContentValue`, `resourcesValue` per zone in `StreamingAssets/map_templates/*.rmg.json`; nothing is saved per area | Blitz.rmg.json |
| Runtime per-area value: `DataArea.pickableObjectsValuesLeft`, `objectsByType` | `docs/gameplay_surface_evidence_matrix.md:290` (not read in game yet) |
| Common value currency = gold: generator `value` / item `goodsValue` / Pandora `variants[].value` | `generator/generator_config.json`, `DB/objects_logic/chests/pandora_box.json` |
| No "nonliving" unit tag (only stray `undead`/`construct` tags) | `DB/units/units_logics/**` |

## 3. Value model

### 3.1 Unit prices (gold equivalents)

| Item | Gold value | Basis |
|---|---|---|
| Gold | 1 | Pandora 5000 gold = value 5000 |
| Wood, ore | 200 | market 250; reward-choice tables 125–210 |
| Gemstones, crystals, mercury | 400 | market 500; reward tables 250–417 |
| Dust | 125 | market 250, but every reward table prices it at 100–150 |
| Artifact | its own `goodsValue` (common 3000, rare 6000, epic 12000, legendary 24000) | equals market `costInGold` |
| Unit | `squadValue` × count | matches guarded unit banks within about ±10% |

These are face values. They deliberately skip the generator's 0.5–0.8× pickup discount, because the dig already costs a
turn and the map pieces cost exploration.

### 3.2 Region richness → treasure value

Richness is measured the same way on every map, at runtime:

`R(area)` = the area's `pickableObjectsValuesOnStart`. It is set when the map is generated and does not drop as objects
are picked up (`pickableObjectsValuesLeft` does: after one turn an AI start region had already fallen from 528,350 to
426,050). Fallback if the field is empty: the sum of `goodsValue` of every object and guarded stack in the area.

`V(area) = clamp(k · R(area), 2000, 40000)`, rounded to 250.

`k` is fixed so that **the Cove start region on Blitz gives V = 8000**. Measured in game on 2026-11-17 (build 26615913,
Blitz, 128x128, 17 regions, map total 7,900,450): the Cove start region has R = 558,525, so `k = 8000 / 558525`
(`Homm3CoveTreasurePlan.AnchorK`). The same game gives:

| Blitz region (that game) | tiles | R | V |
|---|---|---|---|
| Cove start (area 0) | 1618 | 558,525 | **8000** (anchor) |
| Enemy start (area 1) | 1637 | 528,350 | 7500 |
| Poorest (area 2) | 1051 | 246,250 | 3500 |
| Typical mid region (areas 8-14) | 630-760 | 412,500-476,600 | 6000-6750 |
| City region (area 15) | 942 | 787,750 | 11250 |
| Richest (area 16) | 1492 | 1,150,250 | 16500 |

All 17 treasures together are worth about 113,000 gold. The runtime values are on a different scale from the template
`guardedContentValue` + `unguardedContentValue` + `resourcesValue` sums (145k for a start zone), so only the runtime
field is used.

The clamp floor stops tiny regions from producing a worthless dig. The ceiling stops 8M-value regions on huge templates
from producing absurd hoards. Both are tuning knobs.

### 3.3 Composition

Each treasure is rolled from a seeded RNG (seed = map seed ⊕ area id), so the same map always buries the same treasure.

1. **Unit roll, 1/3 chance (about 2/3 have no units).** Budget is 25% of V. Pick one unit SID from the nonliving
   whitelist whose `squadValue` ≤ budget, preferring the highest tier where count ≥ 3.
   Count = floor(budget / squadValue). If nothing fits, skip the units and return the budget to the pool.
2. **Artifact roll, 2/3 chance (1/3 have no artifact).** Budget is up to 45% of what remains. Pick the highest rarity whose
   typical value fits (3000/6000/12000/24000), then a random artifact of that rarity with `goodsValue` ≤ budget. If no
   common artifact fits (V too small), skip it.
3. **Gold and resources always get the rest.** Gold takes 55–70% of the remainder, rounded to 100. Resources take the rest,
   spread over 1–3 random resource types at the 3.1 prices, at least 1 unit of each type picked.

Worked examples at V = 8000 (Blitz start):

- No units, no artifact: 5000 gold + 7 wood + 4 crystals (5000 + 1400 + 1600 = 8000).
- Artifact: a rare (6000) doesn't fit the 3600 budget, so a common artifact (3000) + 3000 gold + 5 ore + 2 mercury
  (3000 + 3000 + 1000 + 800 = 7800).
- Unit and artifact: 8 h3_golem (2000 at `squadValue` 250) + a common artifact worth ≤ 2700 (say 2500) + 2200 gold +
  4 wood + 1 gemstone (2000 + 2500 + 2200 + 800 + 400 = 7900).

### 3.4 Nonliving unit whitelist (explicit, no tag exists)

Base SIDs; `_upg` / `_upg_alt` variants are allowed at their own `squadValue`.

- Undead (vanilla): skeleton, flicker, pet, graverobber, lich, avatar_of_war, vampire.
- Necropolis (HoMM3): h3_skeleton, h3_walking_dead, h3_wight, h3_vampire, h3_lich, h3_black_knight, h3_bone_dragon.
- Constructs: h3_gargoyle, h3_golem, h3_automaton, h3_sentinel_automaton, h3_dreadnought, h3_juggernaut, animated_armor,
  h3_steel_golem, mech_guard, sentinel.
- Elementals: h3_air, h3_water, h3_fire, h3_earth, h3_psychic. Conflux fusions are excluded.
- Other: h3_mummy, mummy, kitten_skeleton.
- Excluded: lich_dragon (tier 8), and anything outside the neutral or player-recruitable pools.

## 4. Placement (per region)

### 4.1 Lazy and deterministic: no load cost for non-Cove games

- Nothing is computed at map load. A region's plan (piece holders, true tile, 3 false tiles, treasure contents) is
  computed the first time a Cove hero (of any side) needs it: entering the region, its search radius touching the
  region, or Archivist.
- A plan is a pure function of (map seed, area id, initial map state), so it never has to be saved. Save games only
  store progress bits (section 8).
- "Initial map state" means the holder list is taken from objects that exist on day 1. To keep the plan stable after
  objects are removed, the day-1 holder list is built the first time *any* hero (not just Cove) removes an object or a
  stack, cached per map. That costs one walk of the object list, once, and only if a Cove hero is in the game.
- Precedent: the Logistics per-map grid cache (`Homm3FactoryLogisticsMap.cs:67-120`), built once per map key and timed.

### 4.2 Holders (5 per region)

- Candidates: interactable map objects (chests, resource piles, artifacts, visitable buildings, Pandora boxes) and
  guarded neutral stacks whose node is in the region. Exclude towns, mines, gates/portals, quest-critical campaign
  objects, and objects in a region's spawn ring (the 5-tile ring around a player start).
- If a region has fewer than 5 candidates, the shortfall becomes "loose" pieces on empty passable tiles. These follow the
  same rules as dropped pieces (4.5).

- **Guard quota (user, 2026-11-17):** at least 2 of the 5 pieces are guarded and at least 1 is unguarded; the other 2
  are random. Guarded means a neutral stack, or an object with a neutral stack within 2 tiles. A quota the region
  cannot fill falls back to the whole pool. Fight buildings (event banks) are not holders yet, see below.
- **First build scope:** holders are chests, resource piles, artifacts on the ground and neutral stacks, because their
  removal is readable from data (`DataObject.released`, `DataSquad.released`). Visited-but-persistent buildings need a
  visit hook and come later. The candidate pool is read from the static `MapData.objects` / `MapData.squads` lists, so
  it does not change as the game goes on.

### 4.3 Treasure tiles (1 true + 3 false)

- Candidates: passable land tiles in the region with no object, not road, not water, not inside a town footprint.
- The true tile and the 3 false ones are drawn from the same candidate pool, so their position gives nothing away.

### 4.4 Spacing guard with automatic relaxation

The user's rule is "not right next to each other, and relax when the terrain forces it". This uses greedy farthest-point
sampling with a minimum distance d:

- d starts at max(4, round(0.5 · sqrt(regionTiles / 9))). The 9 is the 5 holders + 4 treasure tiles.
- Pick the first point at random (seeded). Each next point is a random candidate at least d (hex distance) from every
  chosen point, across holders and treasure tiles together.
- If no candidate fits, d -= 1 and retry the remaining picks. Stop at d = 1.
- Cost: O(points × candidates), with at most a few thousand tiles per region. Microseconds to low milliseconds, and only
  for regions a Cove hero touches.

### 4.5 Dropped pieces

- When an object or stack holding an uncollected piece disappears (a non-Cove hero visits, defeats or picks it up), the
  piece stays on that node.
- A Cove hero who steps on that node gets it. Non-Cove heroes are ignored.

### 4.6 One-area maps

H3 stock imports and some campaign maps have a single area covering the whole map, which would give one treasure total.
Fallback: split the single area into pseudo-regions with a Voronoi partition seeded at towns and mines, merging cells
smaller than about 400 tiles. Same lazy and deterministic rules apply.

## 5. Visibility

- **Search reveal:** at each step, a Cove hero reveals any undiscovered holder within 3 tiles. Revealed holders get a
  map-piece marker for that side. The marker stays visible through fog (it is an overlay, not a fog write).
- **Treasure candidates:** shown to the side with ≥ 1 piece in that region, as overlay markers visible through fog. The
  shown set shrinks by one false lead per extra piece, in a seeded order.
- Overlay precedent (proven): screen-space badges projected node → world through the map's `MapNodeToWorld` pin
  (removed `Homm3FactoryLogisticsMapBadges.cs`, git `cec5dd5136^`). They render regardless of fog.

## 6. Actions

### 6.1 Collecting a piece

Triggered by visiting a holder object (object-interaction postfix, as Plunder does) or winning a battle against a
holder stack (shared battle-result hook). Only a Cove hero collects. Pieces are per side, per region.

### 6.2 Digging

- UI: a 0-mana adventure spell "Dig", cloned from the native world spell the way Logistics, Fusion and Elite Strategem do
  (proven pattern). It casts on the hero's own tile.
- Correct tile: pays out the treasure and marks the region as dug for that side. Each region's treasure can be dug once
  per map, whoever gets there first.
- Wrong tile: costs the movement anyway and leaves a hole marker (HoMM3 feel). That tile is then no longer a candidate
  for anyone.

### 6.3 Movement cost

Proposal: Dig needs at least 2/3 of the hero's daily maximum movement left, and sets movement to 0. That is "most of a
turn", and also stops the "dig at the end of a full day" trick. Tireless Captain removes both the requirement and the
cost.

## 7. Skill tree

| Rank / pick | Effect |
|---|---|
| Basic+ (the skill itself) | Search radius, map pieces, candidate markers, Dig |
| Native-terrain bonus | +10% (the standard faction subskill) |
| Archivist | The first time a hero with Archivist enters a region (counting from when it was learned), its side gets a bonus piece there. One bonus per side per region, however many Archivist heroes the side has. The bonus piece is extra; it does not use up a holder |
| Lay of the Land | Side has ≥ 1 piece in the region: no terrain movement penalty there. ≥ 2 pieces: +1 Speed to this hero's units in battles fought in that region |
| Expert: Collector of Secrets | Each successful dig: +2 to every primary stat for this hero, permanent and stacking |
| Expert: Tireless Captain | Dig costs no movement and does not end movement |
| Expert: Ancient Curses | In regions where your side dug the treasure, every enemy unit starts combat with level 2 Despair, ignoring immunities |

## 8. Persistence

Only progress is stored. Per side, per region: piece bits (5 + 1 Archivist), dug flag, and hole tiles. Per map: which
holders have been revealed per side. Carrier: hidden side buff with packed values, as Logistics does
(`Homm3FactoryLogisticsState.cs`), keyed by area id. Collector of Secrets stat gains are real hero buffs, so the game
saves them itself. Save/load of these carriers is **unproven** for both existing users.

As built (2026-11-17, `Homm3CoveTreasureSave.cs`, installed, not yet tested in game): one carrier per map, the hidden
side buff `homm3_cove_treasure_store` (Core row in `DB/logic_side_buffs`), on the side that already has it or else the
first side. It stores more than progress: for every planned region the five holders (tile, kind, loose flag, revealed
and collected sides), the treasure tile, the false leads and the value, plus pieces per side, dug state, Archivist and
visited sides, and every hole. The plan is stored because the runtime builds the holder pool from the objects alive
when the region is first planned, so a rebuilt plan after a reload would pick different holders. Treasure contents are
not stored: they now come from their own random stream (seed, region id), so they re-roll the same. Records are
26-bit values with a version, a map tag and a checksum; a carrier that fails a check is left untouched and that map
plays unsaved. The write runs from the marker host's Update, about once a second, only when the records changed.

## 9. Runtime building blocks

| Need | Status | Precedent |
|---|---|---|
| Skill rank / subskill read | proven | `Homm3DungeonDraconicDominionHook.ResolveHeroSkillRank :223`, `HasHeroSubSkill :240` |
| Day-start per hero | proven | `Homm3SwashbucklerGoldHook.TryRegisterDayStartHeroConsumer :62` |
| Per-step hook (search reveal, dropped pieces, region entry) | likely | `etc.bhcd(int)` enter-node postfix (`Homm3HomecomingWaterTraversalBridge.cs:85`) |
| Read `MapData.areas` / `DataArea` in game | **unknown, first probe** | diagnostic only, `Homm3MapObjectPropCityResolver.cs:740-790` |
| Objects and stacks with nodes | likely | `Homm3FactoryLogisticsMap.cs:333`, `Homm3FactoryLogisticsEffects.cs:156-237` |
| Overlay markers through fog | proven | Logistics badges (removed, recoverable from git) |
| Dig as a world spell | proven pattern | `Homm3FactoryLogisticsRuntime.cs:282-292`, `PrefixSpellCast :1376` |
| Write movement points | **unknown** | `etj.bhfs(int)` retired symbol, `GameSymbols.cs:753-771` |
| Gold, resources, units | proven | `Homm3RewardEconomyNativeAdapter.TryAddResourceValue :273`; `AddUnits ecn$$bces` |
| Grant an artifact | **unknown** | none |
| +2 all stats | likely | hero buff rows with `heroStat` (Logistics overlay :249) |
| Object visit / battle win hooks | likely / proven | Plunder chest-open postfix; `PrefixBattleResultCleanup :1060` |
| Despair at battle start | likely | `BattleLogic.Init` postfix + `TryAddBuffSidFromReceiver` (Predator Instinct); `magic_despair_effect_1` = level 2 (probably) |
| Ignore immunity | unknown, probably yes | direct buff-manager add skips the cast path |
| No terrain penalty in one region | likely | `additionalStats.landscapePenaltyPerBonus` write (`Homm3HomecomingWaterTraversalBridge.cs:347-395`), toggled per step |
| +1 Speed in region battles | likely | battle-start buff, gated on battle node → area |
| Save/load of progress | **unproven** | Logistics side-buff carrier |

## 10. Build order

1. **Probe slice (no gameplay):** read `MapData.areas` and `DataArea.pickableObjectsValuesLeft` on Blitz, a hand-made map
   and an H3 stock map. Log area count, tile counts and R per area. Fixes `k` and confirms the richness source.
2. Ghidra lookups for the three unknowns: writing movement points, granting an artifact, and the despair/immunity path.
3. Plan generator (pure C#, unit-testable offline against `.map` files through the existing Python map reader). Golden
   tests for spacing relaxation and determinism.
4. Pieces + search reveal + markers. Then Dig + payout. Then subskills. Then persistence.
5. Core rows: skill text, subskill rows, Dig spell row, despair buff row. Retire the Groundsight variants.

### 10.1 Status and static findings (2026-11-17, build 26615913)

- Dig is installed (2026-11-17, DLL 4867a5cf, Core b095fae5), build-proven only. As built:
  - Spell `homm3_cove_dig` in `DB/magics/world_neutral_magics.json`, a Necromancer Will clone with parameter
    `homm3_cove_dig`, the only spell the three skill ranks grant. The Groundsight variant rows are removed from Core
    and the Plunder patches are no longer registered (third install, 2026-11-17).
    Icon (2026-11-17): `homm3_skill_icons/homm3_cove_dig.png`, the vanilla Graverobber shovel emblem recoloured (silver shovel, gold impact, Cove teal disc) by `tools/cove_treasure/build_dig_icon.py`. Handler: `Homm3CoveTreasureDig.cs`.
  - Refusals cost nothing: no skill, no treasure map, road/water/gate tile, tile already dug, under 2/3 movement.
  - Daily maximum movement is approximated by the most movement points the hero was seen with that day (no new pinned
    symbol needed). A hero that gained movement mid-day raises its own bar.
  - Wrong tile: movement set to 0, hole marker for every side, a false lead on that tile disappears. Right tile:
    movement set to 0, region marked dug for every side, payout.
  - Payout: gold and resources through the Plunder grant; units into a same-type or free army slot; the artifact through
    `WorldHero.Method_Public_Boolean_String_Int32_0` (not yet verified in game). A full army or a failed artifact grant
    pays that part's value in gold instead. The banner names artifacts and units by prettified sid for now.
  - Contents come from `homm3_ui/cove_treasure/treasure_catalog.tsv` (315 artifacts, 76 nonliving units), built from
    the installed Core by `tools/cove_treasure/build_treasure_catalog.py`; re-run it when Core prices or items change.
  - Values doubled 2026-11-17 (user: "not quite worth the effort"): the anchor is now 16000, floor 4000, ceiling
    80000. Every value figure and worked example above this note is the old, halved scale. Saves written by the
    first persistence build (store version 1) have their stored values doubled on load.
  - Base value (2026-11-18, user: "a substantial base modifier to all treasures regardless of area richness"):
    every treasure holds 8000 gold's worth on top of its richness share (`Plan.BaseValue`). The Blitz Cove start
    region is 24000, the floor 12000, the ceiling 88000. Saves from store versions 1 and 2 get the base on load.
  - Chart click to jump (2026-11-18, installed, untested in game): clicking a tile on the Treasure Chart moves the
    map camera there (`BhWorldCamera.Method_Public_Void_Vector3_0`) and closes the chart on button release.
  - AI digging (2026-11-17, `Homm3CoveTreasureAi.cs`, installed, untested in game): a computer hero with the skill
    that steps within 3 tiles of a treasure site its side's pieces show digs that site. One dig per hero per day, no
    movement spent, no walking to the site. A false lead leaves a hole; the true tile pays the treasure to that side
    (to the hero if it is still on the map, else as gold). Computer heroes still never go looking for pieces or sites.
  - Not done: the Core install was a four-member splice of the Dig rows into
    the installed Core (the full generator output also differed in hero bio text and two neutral `expBonus` values that
    belong to other work).

- Step 3 is done: `Homm3CoveTreasurePlan.cs` plus `tools/cove_treasure/plan_harness` (all checks pass, 0.05-0.2 ms per
  region). Step 1 is installed as `Homm3CoveTreasureProbe.cs` (logging only, day-start hero bus) and waits for an in-game
  run. Build the plugin with `-p:UseLiveInteropOnly=true`.
- Step 2 answers (Ghidra `tools/ghidra_oe/oe_ghidra.py --build 26615913` plus interop):
  - Movement: controller `fgl` from the world hero's `_cqfa_k__BackingField`. Add a clamped delta with
    `Method_Public_Void_Int32_4(int)`, set absolute with `Method_Public_Void_Int32_1(int)` (pinned
    `MovePointControllerSetWorldMovePoints`), try-spend with `Method_Public_Boolean_Int32_3(int)`. Max daily points:
    `HeroStat.Method_Public_Int32_0()` from the world hero's `Method_Public_get_HeroStat_1`.
  - Artifact: `bool WorldHero.Method_Public_Boolean_String_Int32_0(string itemSid, int count)`. With the native reward
    window: build a `DataRewardSet` (`ERewardType` HeroItemReward 0x18, SideResReward 1) and queue it on the side logic.
  - Despair: there is no `magic_despair_effect_2`. Level 2 Despair is buff `magic_despair_effect` with duration 2.
    Immunity tags sit on the spell dealer, so adding the buff directly through the buff manager skips them (inferred,
    needs an in-game check against an immune unit).
  - Region of a node: area manager `fef` on the BhWorld singleton, `Method_Public_..._Int32_1(int node)`; the world hero
    caches its current area. Enter-node hook: `Method_Public_EEnterNodeResult_Int32_0(int node)`, already patched in
    `Homm3HomecomingWaterTraversalBridge.cs`.

## 11. Decisions (user, 2026-11-17)

- Plunder is **retired**. Done 2026-11-17: its patches are no longer registered and its skill text is gone. The class
  `Homm3CovePlunderHook` stays only for `Grant` and the native-class helpers other features call.
- Picks as built (2026-11-17, `Homm3CoveTreasureSubskills.cs`): Home Waters is a native Core bonus (10% damage dealt/taken on native terrain). Archivist gives one
  bonus piece per region, when an Archivist hero first stands in it. Lay of the Land: no terrain penalty in regions
  with a piece, +1 Speed in battles there with two. Collector of Secrets: +2 to all four primary stats per treasure
  dug, cap 30 treasures. Tireless Captain: Dig needs and spends no movement. Ancient Curses: enemy units start battles
  with Despair for 3 turns (native duration 4) in regions whose treasure the hero's side dug up.
- Dig cost follows 6.3: needs at least 2/3 of max daily movement and ends movement.
- A wrong-tile dig costs the movement, leaves a hole and removes that lead for everyone (6.2).
- Still a tuning knob, not a decision: the clamp range in 3.2 (2000–40000).
- One-area maps are deferred (2026-11-17): hand-made and imported H3 maps wait until region detection is added to the
  H3 map generator. `SplitSingleArea` (section 4.6) stays as an untested fallback; the first build targets maps with
  native regions only.
- Guard quota for pieces: at least 2 guarded, at least 1 unguarded, the rest random (2026-11-17, section 4.2).
- Status 2026-11-17: `Homm3CoveTreasureRuntime.cs` (pieces, search reveal, collection, dropped pieces, lead queries) is
  built but not installed; state is in memory only. Markers wait for approval of
  `artifacts/cove_treasure/marker_mockup.png` (`tools/cove_treasure/marker_mockup.py`).
