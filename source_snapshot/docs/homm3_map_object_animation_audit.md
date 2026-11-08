# HoMM3 adventure-map object animation audit

Status: active contract data, audited 2026-09-26. Proof tier: generated artifact (DEF decode, ground
truth aggregation, UnityPy read of the installed prefabs). No in-game observation backs any row.

This audit answers two questions:
- Are the motion labels on the 108 map-building rows right?
- Which animated HoMM3 map objects do translated maps show today, and does what they show move?

Owners:

| Purpose | File |
|---|---|
| Inventory motion parts (Part A) | `tools/homm3_map_building_meshes/map_building_anim.py` (`MOTION_PARTS`, `PLANNED_LANE`) and `map_building_anim_inventory.json` |
| Census of animated placed DEFs | `tools/homm3_map_building_meshes/map_object_anim_census.json` (`audit_map_object_animation.py census`) |
| Plan per object (Part B) and the Part A label corrections | `tools/homm3_map_building_meshes/map_object_anim_coverage.json` |
| Native prefab evidence | `tools/homm3_map_building_meshes/oe_native_prefab_anim.json` (`audit_map_object_animation.py probe-native`) |
| Contact sheets | `artifacts/map_building_anim/audit/<def>_audit.png` and `measurements.json` (`audit_map_object_animation.py sheets`) |

Gates:
- `tools/validate_map_building_anim_contract.py` (`ValidateMapBuildingAnimContract`). Every animated
  inventory row lists its moving parts, and no row is newly planned as a DEF flipbook.
- `tools/validate_map_object_anim_coverage_contract.py` (`ValidateMapObjectAnimCoverageContract`).
  - Every animated placed DEF in the census has exactly one plan.
  - A `native_covered` stand-in must actually carry an Animator or ParticleSystem.
  - A new animated object found by a census re-run fails the build until it is audited.

## Method

1. **Contact sheets.** Every animated DEF gets a sheet showing:
   - all frames;
   - a motion heat mask;
   - an enlarged strip of the moving region;
   - per-component bbox, loop period, centroid path and hue.
2. **Classification.** Each sheet is read by eye. Suspect regions are zoomed further, with per-frame
   difference masks.
3. **Luminance split for noisy DEFs.** Some DEFs are dithered renders: avggolm0, and AVGkbl01's rock
   pile. For these, large luminance changes are separated from ±1-index dither, because dither is
   not motion.
4. **Static rows.** All 78 static rows have exactly one frame, so no motion is hidden in them.
   Palette cycling was not checked: HoMM3 applies it to terrain, not object DEFs.
5. **Census.** It aggregates every placement in the 86 raw_translation ground-truth files (dated
   2026-08-04). Creatures, heroes, resources, artifacts and random placeholders are excluded.
   - 974 placed DEFs; 206 of them animate.
   - Each animated DEF is recorded with its Olden Era SID and emit status.

## Part A: the 30 animated inventory rows

**14 labels were wrong or incomplete.** 7 were wrong in kind, parts or lane. 7 had incomplete notes.

**Lane policy change for all 22 planned effect rows:** `flipbook` → `vanilla_style_effect`. The user
rejected HoMM3 sprite flipbooks on flat panels. The two flipbook pilots (AVGauto, avgbhmt0) were
replaced on 2026-09-27, and all 24 effect rows are now delivered as vanilla Olden Era map-object
ParticleSystems on anchors measured on the mesh (`docs/homm3_map_building_animation.md`).

| DEF | before | after | finding |
|---|---|---|---|
| avggrem0 | articulated_rigid: clock wheel + pendulum | **pendulum** | Only the pendulum moves. The clock face is identical in all 16 frames. The pivot is the top of the rod under the floor (~(61,56) px). The bob swings x 59.9 → 67.1 (f7) → 60.1 (f15), one out-and-back per loop. Commit b10ecfcafc over-corrected. |
| avggolm0 | smoke | **rotor (2 flywheels)** + smoke | Two rivet rings rotate. The first is the front flywheel: rim ellipse ~9x18 px at (60,98), counter-clockwise on screen, about 4 rivet pitches per 20-frame loop. The second is a smaller wheel seen edge-on at the right. The stack steam stays an effect. This mechanical animation had been missed. |
| HASPHTPL | water_rotation → rotor ("water wheel") | water → effect | A flat whirlpool in a basin. It has no wheel or axle. |
| AVGworm | fire (lava pit) | glow_pulse | Green vent lights pulse on the dome. |
| AVGerth0 | glow_pulse (lava) | water | Bubbling mud pool. |
| AVGpixie | glow_particles (sparkles) | water + glow_pulse | Pond ripple and cascade under the house, plus a window flicker. |
| AVGdfly0 | glow_particles | glow_pulse | Red tree-trunk hollows pulse. |
| AVGkbl01 | articulated_rigid "arm swings a load" | articulated_rigid, refined | The jib slews about the vertical mast: held toward the viewer f0-20, out parallel to the screen f28-41, back by f50 (tip-tracked). The ore bucket rides the jib at a fixed rope length. The rock-pile flicker is dither. |
| AVGarma | rotor "4 paddles" | rotor | A multi-blade windpump rotor, not 4 paddles. |
| avggogs0 | fire "forge fire and smoke" | fire | Lava pours from the cauldron spout into the lava basin. There is no smoke. |
| AVGfbrd, AVGelp, avgefre0, AVCfacZ0 | — | refined notes | Lightning arcs; mirror cloud swirl; molten gold bed; window flicker. |

Rows confirmed as labelled: AVGair0, AVGfire0, AVGwatr0, NIMPHFO, AVGrdrg0, AVGauto, AVGmecha,
avghydr0, both capitols, avgimp0, avgpit0, AVGpega0, avgbhmt0, avghalf and avglprch.

## Part B: animated objects outside the 108 rows

The census has 206 animated DEFs. They are grouped into 63 coverage rows. Presentation today is taken
from the ground truth.

| lane | rows | meaning |
|---|---|---|
| `inventory_row` | 5 | The DEF is, or is shown as, a Part A inventory row. |
| `native_covered` | 33 | A native Olden Era stand-in carries its own Animator or particles. The probe shows which. |
| `not_presented` | 17 | The map draws nothing, or unrelated scenery. Animation is moot until the object is presented. |
| `vanilla_style_effect` | 6 | Effect needed. The stand-in is inert, or the object is terrain decoration. |
| `bob` | 1 | Ocean bottle, currently shown as flowers. |
| `creature_deferred` | 1 | Swan pond. The native knowledge_garden stand-in is inert. |

### Mechanical animations in Part B

**None needs a mesh-surgery build today:**
- **Windmill.** The native windmill (`NewMill_ctrl`) spins its sails.
- **Water wheel (109).** Shown as that same native windmill. The windmill moves, but a water wheel
  is never shown. Kept as the windmill by user decision (decision 3); no build.
- **Star axis (61).** Its HoMM3 wheel spins. It is shown as `altar_of_magic_1`, which has its own
  Animator. Covered, but with different motion.
- **Rally flag (64)** and **buoy (11).** Shown as `quixs_path`, which has an Animator.
- **Sawmill, ore mine and sulfur dune.** Their HoMM3 DEFs are single-frame (static). The native
  clones animate anyway.
- **Flotsam, sea chest and survivor boat.** These bob in HoMM3. Their native stand-ins have
  particles but do not bob.

### Effect-only gaps on inert native stand-ins (vanilla_style_effect)

- Mercenary camp campfire (`stinging_sword` stand-in: no Animator, no particles).
- Imp cache and Medusa stores brazier and glow (`shady_den` stand-in: inert).
- Low-priority decoration: kelp, lava lakes/flows, rocks-in-water surf, volcano crater and smoke.

### Not presented

These objects animate in HoMM3, but the translated maps draw nothing (or unrelated scenery) for
them. The causes, fixes and open decisions are in the next section.

## Objects that draw nothing (2026-09-26)

`tools/homm3_map_building_meshes/map_object_presentation.py census` reads every raw_translation
placement ground truth (87 missions) and writes `map_object_presentation_census.json`.
`map_object_presentation_ledger.json` gives each draw-nothing id a cause and a status.
`tools/validate_map_object_presentation_contract.py` (build target
`ValidateMapObjectPresentationContract`, skip `SkipMapObjectPresentationContract`) fails the
OfflineUnlockMod build when a draw-nothing id has no ledger row, a row goes stale, a pending fix is
not in the substitution source, or a `not_presented` coverage DEF is unledgered.

**Why nothing was drawn.** Almost every case was `blocked_by_substitution`: the substitution map
(`build_homecoming_entity_substitution_map.py`) had no Olden Era SID for the object, so nothing was
emitted. The invisible `homm3_pathing_blocker` gap fill still sealed the HoMM3 non-visit cells, so
passability was kept but the object and its function were lost.

**After the 2026-09-26 regenerations** (all 87 maps; not installed): 18 ids / 386 placements
still draw nothing, down from 50 ids / 21783 placements, and 566 placements are drawn as visual-only
DEF billboards (below). Proof tier: generated artifact.

| HoMM3 object | now | notes |
|---|---|---|
| Trading post (99, 221) | `market` | |
| Dragon Utopia (25) | `dragon_utopia` | |
| Magic spring (48) | `mana_well` | |
| Crypt (84) | `overgrown_grave` | |
| Cartographer (13) | `watchtower` | |
| Black market (7) | `forge` | |
| Corpse (22) | `abandoned_corpse` | |
| Oasis (56), watering hole (110) | `fountain` | |
| Wagon (105) | `peasant_cart` | |
| Warrior's tomb (108) | `heros_crypt` | |
| Two-way monolith avxmn4b0 (45) | `portal_N` | added to the exact monolith table |
| HotA and rough decorations (117, 155, 199, 206-211) | native biome scenery | cells were already sealed; no gameplay change |
| HotA terrain overlays (223, 224, 226-231) | static native stand-ins (`dead_stones_*`, `fx_fog`, `fx_fireflies_*`, `fx_map_fire`, flowers, stones) | point-anchored; no terrain effect |
| Border guard (9), border gate (212) | Core `campaign_FX_block` (smoke, one blocked cell) with a propEntities SID | per colour, a hidden QuestScript `Counter(<mission>_border_key_<c>,"=",1)` runs `DeleteEntity` on every block of that colour |
| Keymaster's tent (10) | invisible `Zone 1x1` marker + DEF billboard | Dialog before, `CounterSet` key after. The tent is drawn as a billboard of its own `avxkey<c>0` DEF on an inert host at the tent's body cell; the marker stays on the walkable visit cell. 91 of 157 tents are drawn (see billboards). |
| Freelancer's guild (213) | `unit_trade_lab_kitten_horn` | **Behaviour change, accepted by the user 2026-09-26.** HoMM3's guild buys any creature for resources. The native building is a 3x3 trade lab that hires kitten_horn units, 1 unit for 1 crystal (Core `objects_logic/unit_res_trade_labs/unit_res_trade_lab.json`). A trade building in the same place, not the same trade. 35 placements. |

Border-gate details (`raw_translation/border_guard_gates.py`, gate `tools/validate_border_key_gate_contract.py`):

- **Behaviour difference (accepted by the user 2026-09-26 as a deliberate difference from HoMM3):** a
  block is deleted for every side once any side visits the tent, not only for the key holder. A colour with guards but no tent stays closed, as in HoMM3. Border Gates (212)
  are included; Quest Gates (215) are not.
- The pickup anchoring pass keeps resource-pile bodies off gate passages and tent cells
  (`surface_emit.key_gate_reserved_cells`), the same clearance it gives mine bodies.
- When a larger Olden body covers a tent's visit cell (a town, an artifact or camp-fire body), the
  marker moves to the first free passable neighbour, front first (`visitNodeRelocation`, 7 tents).
- A guard block may hold one GATE of a subterranean portal's scorched ring (graduation_exercise);
  the other GATEs stay clear, as HoMM3 left the entrance reachable from its other sides
  (`landon_access.keyGateHeldGates`). A portal whose every GATE is held fails.
- Runtime `DeleteEntity` of these blocks is unproven on these maps.

**Functional-clone anchoring (fixed 2026-09-26).** duke_alarice used to fail closed: its border
gate `0:19:11` passage lay under a sawmill clone body. `homm3_xfp_f_*` clones and land-on cities were
anchored by the legacy size-grid formula while occupancy used the native pivot model
(`docs/native_static_footprint_model.md`), so every clone GATE sat off its HoMM3 visit cell. Now every
Interact SID with a `generatorConfig` is anchored by the inverse of the native projection
(`native_footprint_model.native_anchor_for_local_cell`, used by
`exact_homm3_footprint.anchor_for_config_local_cell`), and the forward check is the same model. A
second fault was fixed with it: on two-layer maps, post-passes and the ground truth clipped native
footprints to the middle strip of the atlas, so objects outside it had empty cells. The clip now
uses the envelope of the layer the anchor sits in (`surface_emit.SOURCE_LAYER_ENVELOPES`).

After both fixes all 87 maps regenerate, and every xfp_f clone and subterranean portal has its GATE
on the HoMM3 visit cell. The entrance-occupancy and gate-face passes now also see the objects that
used to be clipped, so they clear more scenery from GATE cells. Against the previous census, about 1,180 more
decoration placements (ids 116-211) are `approach_cleared` and about 220 more are `fer_omitted`. Two campfires (12) are
removed by the gate-face pass's non-keeper clear, and one treasure chest at homecoming (42,31)
clears mountain 118. Those removals are owned by those passes and ledgered.

**Visual-only DEF billboards (built 2026-09-26, user decision).** These objects have no Olden Era
function. Each is drawn as a static sprite of the first frame of its own HoMM3 DEF.

- **Host.** One inert SID per DEF, `homm3_objbb_<def>`. It is the `homm3_seer_hut` shell (Interact,
  `interactive/wise_owl` donor, 2x2, generatorConfig) with `nodes [1,0,0,0]` (one blocked cell, no
  GATE) and no `objects_logic` row, so there is nothing to visit and the cursor treats it as scenery.
  The rows go to the mission core overlay `DB/map/objects/4_interactables.json`. A custom Interact
  host in `homecoming_custom_objects.json` got no Init (seer-hut history).
- **Cell.** `raw_translation/object_billboards.py` puts the host on one of the object's own HoMM3
  non-visit blocked cells, bottom row first, then nearest the centre. It prefers a cell that holds a
  synthetic 1x1 gap fill and replaces the gap fill, so pathing is unchanged. Otherwise it takes a free
  cell that is no GATE or marker and leaves every adjacent GATE or marker at least two open
  approaches. One-way monoliths and the obelisk have only their visit cell, so the host takes that
  cell. It is blocked in HoMM3 too and has no function here. Garrisons and tents never use the visit cell (the
  passage and the key marker).
- **Unplaced.** A placement with no usable cell stays undrawn. Its cells and the reason are listed
  in `install_manifest.json` `objectBillboards.unplaced`. Nearly always the Olden Era GATE area of a
  nearby pickup, chest, squad or artifact covers the cell (the row projection folds neighbouring
  HoMM3 rows together). Blocking another object's GATE would break that object. The rest hold
  overlapping HoMM3 scenery or would seal an adjacent GATE.
- **Art.** `tools/build_homm3_object_billboard_assets.py` extracts each DEF from `H3sprite.lod`,
  strips the DEF shadow, crops, and writes
  `OfflineUnlockMod/homm3_runtime_assets/map_object_refs/homm3_object_billboards/<sid>/00_00.png` plus
  `manifest.json` (36 SIDs). They deploy with the normal plugin build, not the opt-in
  `homm3_bundles` lane.
- **Runtime.** `Homm3ArtifactMapBillboard.cs` handles the `homm3_objbb_` prefix on the same
  placed-object Init postfix as artifacts and the seer hut. The quad height is the PNG height at the
  seer-hut scale (1.35 units per 59 px), so HoMM3's relative sizes hold. A missing folder, a missing
  or undecodable PNG, or a failed draw is a `LogError`. The sprite is centred on the host cell, so an
  object whose host is not its centre column (a tent's left cell) draws up to half a cell off its
  HoMM3 position.
- **Gate.** `tools/validate_homm3_object_billboard_contract.py` (build target
  `ValidateHomm3ObjectBillboardContract`, skip `SkipHomm3ObjectBillboardContract`) checks the catalog
  against the PNGs, the host row shape, the runtime prefix and LogErrors, and that every generated map
  has its hosts at the reported nodes, their overlay rows, and no `objects_logic` row for them. The
  presentation validator checks that each ledger row's `visualBillboard.placed` equals the census.

| HoMM3 object | drawn | not drawn |
|---|---|---|
| Keymaster's tent (10) | 91 | 66 |
| Cover of darkness (15) | 28 | 7 |
| Derelict ship (24) | 37 | 5 |
| Garrison (33) / vertical (219) | 102 / 39 | 30 / 12 |
| One-way monolith entrance (43) / exit (44) | 24 / 28 | 48 / 37 |
| Mermaids (52) | 20 | 1 |
| Obelisk (57) | 1 | 6 |
| Pyramid (63) | 13 | 9 |
| Shipwreck (85) | 91 | 21 |
| Sirens (92) | 17 | 2 |
| War machine factory (106) | 75 | 46 |

**What to look for in game** (after install; nothing here is runtime-proven):

- The BepInEx log at startup should have
  `HoMM3 object billboard: 36 staged sid(s) in '...homm3_object_billboards': homm3_objbb_avadlic0,...`.
  If it has `HoMM3 object billboard: image folder ... is missing` instead, the PNGs were not deployed.
- On a map with these objects, one `HoMM3 object billboard: applied sid='homm3_objbb_<def>' ... height=...`
  line per SID. Any `HoMM3 object billboard: FAILED to draw`, `missing image` or `could not decode`
  line is a failure, and that object is invisible.
- On the map: garrisons, tents, shipwrecks and the rest standing as flat HoMM3 sprites facing the camera,
  roughly their HoMM3 size. Clicking one should do nothing (scenery cursor) and it should not be
  visitable. A red-circle cursor is expected. A visit dialog, a load failure, or an object that swallows a hero's
  path where HoMM3 had open ground are bugs.
- Good places to look: duke_alarice (tents and a war machine factory), any SoD map with shipwrecks
  on the shore, and garrison chokepoints.

**Still a decision.** The options are in the ledger.

| HoMM3 object | why it is open |
|---|---|
| Favorable winds (225), river deltas (143) | Flat terrain overlays. An upright billboard would misrepresent them, so they stay undrawn. |

**Accepted.** A few placements of crystal, plains shrine, sawmill, resources and chests (21, 46, 53,
76, 79, 101) are removed by the approach-clearing pass, which owns that policy.

**Meshes.** The `homm3_map_building_meshes` lane has meshes for towns and dwellings only. The
visual-only objects above use DEF billboards, not meshes. Meshy was not used.

### Substitutions visible in Part B

- **SoD elemental dwellings** (`avg2el*`) show the HotA conflux meshes.
- **Elemental Conflux** (`avgelem0`) shows the AVGelp mesh.
- **Faerie dragon dwelling** (`avgfdrg`) shows the static AVGgdrg0 dragon cliffs, so its sparkles are
  lost.

## Mechanical build list (surgery on the shipped Meshy meshes, no Meshy credits)

All three were built on 2026-09-26 (see `docs/homm3_map_building_animation.md`, Pilots). The
estimates below were the plan; the notes record what the measurement and the sculpt turned out to be.

| lane | object | parts | result |
|---|---|---|---|
| `pendulum` (new lane) | avggrem0 gremlin workshop | 1 hinged rod + bob | Delivered. +-13.2 deg first-harmonic swing, 16 frames. |
| `articulated_rigid` | AVGkbl01 kobold crane | jib (slew about a vertical axis) | Delivered as one slewing part. Re-measured: holds f0-20 / f28-41 / f50-71. The "bucket hoist" was a misreading: the bucket hangs at a fixed rope length and only appears once the jib tip clears the rock pile. The sculpt has no bucket, and none is added. |
| `rotor` | avggolm0 golem factory | flywheels | Delivered as five wheels. The sculpt has three riveted flywheels on the -X side and two spiked wheels on the +X side, all as separable welded pieces. The riveted discs are ovals and are spun as ovals. |

Every other row is an effect (`vanilla_style_effect`), `native_covered`, or not presented.

## Decisions for the user

1. **Flipbook pilots.** Decided (2026-09-26): pulled. AVGauto smoke and the avgbhmt0 cave fire are
   vanilla-style effects, and the `flipbook` lane is refused by the gate and the runtime parser.
2. **Billboard dwellings.** Decided: kept. avghalf and avglprch repaint the billboard itself from DEF
   frames. The billboard is already a flat sprite, so this is not a quad flipbook.
3. **Water wheel (109).** It is shown as a windmill. **Decided (user, 2026-09-26): keep it as the
   Olden Era windmill.** No water-wheel building is built. The user considers the water wheel a
   mistake the maps do not really use.
4. **Not-presented objects.** The native mappings and border key gates are regenerated (all 87
   maps, not installed). Decided (user, 2026-09-26): the border-gate all-sides behaviour is kept,
   213 maps to `unit_trade_lab_kitten_horn`, visual-only DEF billboards are built (tents included),
   and the functional-clone anchoring is fixed. All four are delivered as generated artifacts.

## Proof tiers

| Item | Tier |
|---|---|
| Labels, census, coverage, native probe | Generated artifact, from DEF decode, ground truth and UnityPy |
| Validators | Wired into the OfflineUnlockMod build |
| Native mappings, border key gates, 213 trade lab | Generated artifact (all 87 maps); not installed; runtime unproven |
| Object billboards | Generated artifact (maps, overlays, PNGs); C# compiled against Golden Era interop with no new live-interop gaps; not deployed or installed; runtime unproven |
| In-game animation of any row | Unproven |
