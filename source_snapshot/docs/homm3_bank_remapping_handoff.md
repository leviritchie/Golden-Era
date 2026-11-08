# HoMM3 Bank Remapping Handoff

Status: isolated opt-in pass is **source/static validated**. The remapping module
exists and is wired as a candidate-only generator step. Default generation is
unchanged. Custom exact-footprint bank SIDs and reward overlays are **not**
implemented. Generated-map, install, startup, and runtime encounter proof remain
open.

## Why this belongs in the broad map-generation line

The raw-translation pipeline is the preferred campaign-map generation lane
because it starts from the original HoMM3 terrain, object placement, blocker
masks, roads, gates, and map topology. Its main purpose is not merely to make
a map that looks similar. It is to preserve the routes that were usable in
HoMM3.

The relevant production sequence is:

1. Read the HoMM3 campaign mission and its object/template records.
2. Translate those records into Olden Era map objects.
3. Apply isolated compatibility and cleanup passes.
4. Apply terrain/scenery randomization and presentation changes.
5. Validate, package, install, and separately test the installed map.

The bank remapping pass sits after main raw object translation and gate-face
cleanup, and **before** both HoMM3 footprint compatibility and visual/scenery
randomization. It is opt-in (`--enable-homm3-bank-remapping`) so a failure
cannot silently alter the established default generation lane.

Implementation:

- `experiments/campaign_port_poc/raw_translation/homm3_bank_remapping.py`
- Gate: `tools/validate_homm3_bank_remapping_contract.py`

## The current problem

HoMM3 object ID `16` is a generic creature-bank record type. The actual bank
is identified by its template animation/subtype. Examples include:

- `AVXbnk10.def`: Cyclops Stockpile
- `AVXbnk20.def`: Dwarven Treasury
- `AVXbnk30.def`: Griffin Conservatory
- `AVXbnk40.def`: Imp Cache
- `AVXbnk50.def`: Medusa Stores
- `AVXbnk60.def`: Naga Bank
- `AVXbnk70.def`: Dragon Fly Hive
- `AVXbnk80.def`: Wolf Raider Picket
- `AVXbnk90.def`: Experimental Shop

The current substitution map keys the direct blocked-object family primarily
by object ID and routes object `16` to `shady_den`. It also maps HoMM3 object
`97`, Den of Thieves, to `shady_den`.

That creates two kinds of loss:

- Different HoMM3 banks become the same Olden Era object, so the source bank's
  visual identity, guards, and reward are lost.
- Den of Thieves becomes a guarded resource bank even though its HoMM3
  function is scouting/thieves-guild information.

Bashing Skulls demonstrates the issue directly. Its source contains multiple
  object-16 bank variants, but the current translation consolidates them into
  the same Olden Era SID. The resulting footprint audit then sees repeated
  `shady_den` placements and reports them as if they were one object family.

## Olden Era bank candidates

The active Golden Era catalog has two relevant guarded-bank families.

### Creature-reward banks

`boreal_call`, `jousting_range`, `petrified_memorial`, `point_of_balance`,
`ritual_pyre`, `the_gorge`, `underground_lair`, `unforgotten_grave`, and
`vanguard`.

All currently use a `3x3` object envelope with `4` native blocking cells.
Their pivots vary, so the SID alone is not enough to infer an anchor without
reading its ObjectConfig.

### Guarded resource banks with creature guards

- `2x2`, `1` blocker: `abandoned_mansion`, `black_tower`, `mereas_shrine`
- `3x3`, `4` blockers: `abnormal_structure`, `alvars_eye`, `circle_of_life`,
  `cursed_old_house`, `iridescent_abbey`, `legions_memorial`,
  `overgrown_grave`, `prismatic_lair`, `raiders_camp`, `shady_den`,
  `testing_grounds`, `troglodyte_throne`, `twilight_bloom`, `uncanny_rite`
- `4x4`, `9` blockers: `dragon_utopia`, `research_laboratory`,
  `unstable_ruins`

These dimensions and counts describe native ObjectConfig geometry: the full
object envelope is not necessarily all blocked cells. Value `1` in the native
`nodes` grid is a blocker; value `2` is a gate/interaction cell.

## Implemented remapping policy

Assignments are global and deterministic for a fixed map and input stamp.

### 1. Identify the exact HoMM3 source object

Object-16 records are keyed by normalized template animation. Object `97`
`AVXdent.def` is treated as Den of Thieves / scouting, never as a creature bank.

### 2. Prioritize footprint compatibility

Each candidate SID is scored from its native OCC projection at the current
emit node, and for single-OCC candidates also at trial anchors that place the
OCC onto each source non-visitable blocker (or visit cell when the bank has no
non-visitable blockers).

Accept only when:

- every source non-visitable blocker cell is covered by native OCC;
- no native OCC lands on a source-passable cell (outside the H3 block mask).

Reject otherwise. Do **not** fall back to `shady_den` merely because it is listed.

### 3. Preserve function where possible

Among geometry-valid candidates:

- Griffin Conservatory / Dragon Fly Hive → guarded unit banks;
- other known `AVXbnk*` families → guarded resource banks;
- Den of Thieves → `watchtower` scouting candidate only.

### 4. Balance the distribution

Equal geometry ranks use deterministic least-used assignment so multiple source
families do not collapse onto one SID when several candidates fit.

### 5. Keep reward logic separate from map placement

Current assignments reuse the selected native SID as `rewardLogicSid`. Per-source
bank custom rewards still require dedicated SIDs and Core logic rows. The pass
records the intended reward SID but does not invent overlay reward definitions.

When no native candidate is geometry-valid, the pass fails closed with
`nextStep=create_dedicated_custom_sid_with_exact_h3_footprint_and_separate_reward_logic`.

## Relationship to footprint compatibility

Bank remapping runs before:

`experiments/campaign_port_poc/raw_translation/homm3_footprint_compatibility.py`

because choosing the wrong bank SID changes the native footprint being audited.

Guarded banks remain hero-removable encounters after combat. Treat them as
temporary guarded geometry for pathing-before-clear, not as permanent
unremovable buildings under narrower building audits.

## Required diagnostics

Every assignment/failure reports:

- source object ID, animation, and subtype;
- source bank name/function;
- original translated SID;
- selected SID and reason (or rejection reasons);
- source and selected blocker masks;
- source and selected gate/approach cells;
- reward-logic SID;
- native vs custom assignment kind;
- candidate rejection reasons when none fit.

## Validation plan

### Static and generated validation

- Gate: `tools/validate_homm3_bank_remapping_contract.py`
  - known animation families;
  - object-16 identity not collapsed in catalog;
  - native compact assignment rewrites away from `shady_den`;
  - Den of Thieves never uses resource-bank SIDs;
  - fail-closed without rewriting objects when no geometry-valid candidate;
  - deterministic least-used diversification.
- Generated maps: opt-in regenerate Bashing Skulls / Homecoming and inspect
  `homm3BankRemapping` report on the emit manifest.
- Run footprint compatibility after remapping when that opt-in is also enabled.

### Map-specific regression set

At minimum, regenerate and compare Bashing Skulls and Homecoming. Include
maps containing each available object-16 animation family, Den of Thieves,
map-edge placements, and placements adjacent to permanent scenery/buildings.

### Proof boundaries

- Source/static validators: proven for the module fixtures above.
- Generated artifact: unproven until an opt-in emit is run and read back.
- Installed payload / startup / runtime guards-rewards-removal: unproven.

No gameplay or installation claim should be made from this handoff alone.

## Remaining work

1. Custom exact-footprint bank SIDs for multi-cell banks (for example Dwarven
   Treasury `AVXbnk20`) that have no native geometry-valid OE donor.
2. Core overlay object + objects_logic rows for those SIDs with per-family
   rewards, not shared native bank tables.
3. Opt-in emit on Bashing Skulls / Homecoming, install, startup, and focused
   encounter proof.
4. Classification update so temporary banks are not mistaken for permanent
   building failures in the footprint-compatibility audit when that is desired.

## Primary references

- `experiments/campaign_port_poc/raw_translation/homm3_bank_remapping.py`
- `tools/validate_homm3_bank_remapping_contract.py`
- `experiments/campaign_port_poc/build_homecoming_entity_substitution_map.py`
- `experiments/campaign_port_poc/vanilla_stock/substitution_table.json`
- `experiments/campaign_port_poc/raw_translation/homm3_footprint_compatibility.py`
- `docs/homm3_footprint_compatibility_postpass.md`
- `docs/native_static_footprint_model.md`
- `artifacts/campaign_port_poc/ab_sod_campaigns/bashing_skulls/layered_ir/bashing_skulls.object_walk.json`
- `artifacts/campaign_port_poc/olden_entity_catalog/olden_core_map_valid_entity_catalog.json`
- active install: `V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era`
