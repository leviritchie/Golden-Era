# HoMM3 walk stride match (delivery-time Move transform)

Status (2026-09-27):
- **User-visible gameplay proven for Castle.** The user watched the castle slice's stride-matched Move in game and
  approved it for every faction ("the stride change for castle units looked great in that last run").
- **Generated artifact validated only** for the other factions. That covers the per-unit knobs (`highHarmonicKeep`,
  `maxDrop`) and every unit not yet frozen and installed with the stride-matched Move. For those units, runtime
  proof comes only with their own install.
- Stride match stays in the `fleet_rebuild.py` route for every faction, with the gates below unchanged
  (slip <= 0.686, required/actual <= 1.4, cadence <= 1.6).

## Problem

OE moves a battle unit across the ground at its view config's `moveSpeed` (world units per second). Our HoMM3
views use pikeman 4.3, swordsman 3.5, wood elf 5.2, unicorn 6.9, centaur 6.0 and griffin 7. Meanwhile OE plays
the Move clip in place:

- Stock prefabs have Animator `m_ApplyRootMotion: 0`.
- In `_Battle_Unit_Anim_ctrl_v2`, and in the owned copy `StockEsquireBattle.controller`, state `move 0` has
  `m_Speed 0.8` and speed parameter `battleSpeed`.
- `Homm3OwnedSkinnedLabBuild` maps `01.Walk` / `04.Fly` to `Unit_Move`.

So the clip is **not** time-scaled to the distance travelled. A DEF-retargeted walk whose feet sweep back slower
than the ground passes slides its feet (source/static evidence, not runtime).

The user wants longer strides, not slower units. So `moveSpeed` stays and the clip changes.

## Move speed normalization (2026-09-28)

User directive: "A previous pass lowered the speed of units rather than increasing their stride. This affected
stronghold heavily, but is the wrong approach. Those units need their speed normalized to similar olden era units
and their strides adjusted accordingly."

**The retired slow-down path.** `Homm3SkinnedStrideLocomotion` (plugin, runtime) rewrote a ground row's native
`UnitViewConfig.moveSpeed` to `battleMoveStrideBindUnits x fitted scale / battleMoveCycleSeconds` from
`homm3_import.json`. The 17 Stronghold walker rows carried those fields from the old mocap delivery manifests, so in
game (BepInEx log, 2026-09-28) h3_orc went 5.8 -> 0.791, h3_goblin 4.0 -> 1.330, h3_wolf_rider 3.33 -> 1.290 and
h3_wolf_rider_upg 3.33 -> 1.739, while their DEF-retarget Move had already been stride matched to the Core speed: the
units crawled and their feet swept backward faster than they moved. The class, its call sites and the three
`homm3_import.json` fields are removed; `Homm3ImportVisuals` logs an error for a row that still carries them.

**Normalization.** The Core view rows of custom units inherit `moveSpeed` from a donor (Stronghold: orc = blade dancer
5.8, wolf rider = assassin 3.33, behemoth = black dragon 7.0), which is not a speed decision.
`custom_factions/unit_move_speed_normalization.json` maps a game sid to a class; a class names vanilla OE units of a
similar body plan, size and role, a reason, and pins `targetMoveSpeed = round(mean(refs' moveSpeed), 3)`. One table,
two consumers:
- `apply_release_core_overlay.py` (`normalize_custom_unit_view_move_speeds`) writes the target into the view row;
- `stride_match_glb.py` (`move_speed_source`) matches the Move stride to the same target (stamp `moveSpeedSource`
  `normalized:<class>`; an unlisted unit keeps its Core view row, stamped `coreView`). freeze_slice's stride gate and
  fleet_rebuild's no-regression gate measure at the same speed.
Only `units` is consumed (`proposed` holds mappings awaiting review; the Stronghold walkers and every Core flier were adopted 2026-09-28 after the user approved the pilot). Gate:
`tools/validate_unit_move_speed_normalization_contract.py` (wired into the OfflineUnlockMod build): refs are vanilla
rows, targets equal their mean, fliers only in a flier class, the slow-down fields and any `TrySetUnitViewConfigMoveSpeed` call
are absent; `--require-installed` reads the installed Core back.

| class | refs (installed moveSpeed) | target |
|---|---|---|
| small_humanoid_infantry (goblins) | trogl 4.0, undead_peasant 4.0, esquire 4.3 | 4.1 |
| medium_humanoid_infantry (orcs) | esquire 4.3, crossbowman 3.5, unfrozen_cultist 4.5 | 4.1 |
| large_humanoid_brute (ogres, cyclopes) | minos 2.7, ent 2.83 | 2.765 |
| mounted_beast_rider (wolf riders) | sunlight_cavalry 6.0, frostworm_rider 5.0 | 5.5 |
| large_beast_quadruped (behemoths) | unicorn 6.5, qilin 6.9, gorilla 5.0 | 6.133 |
| small_flier (sprites, dragonflies, vermin) | pixie 6, twinkle 7, flicker 7, wasp 7.33 | 6.832 |
| medium_flier (one-hex fliers: gargoyles to pegasi, genies, vampires) | griffin 7, kitten_horn 6, vampire 6 | 6.333 |
| large_flier (dragons, angels, rocs, wyverns, couatls, ghost behemoth) | angel 7, phoenix 6, dragon 7, black_dragon 7 | 6.75 |

**Fliers.** Every class declares `moveType` (`walk` / `fly`). A listed unit's Core `units_logics` `stats.moveType`
and, where it has a DEF-retarget lab unit, `reference/homm3_fliers.json` must agree with its class (fliers only in a
flier class), and so must the refs. stride_match does not stride match a flier (exit 3, as before): a flown Move has
no planted contact, and OE plays every Move clip at 0.8 x battleSpeed whatever the moveSpeed (vanilla pixie 6 and
angel 7 fly at one clip rate), so there is no native wing-cadence coupling to match; a flier's speed is a speed
decision only. Not listed, because the two sources disagree (settle the class first): h3_crystal_dragon (Core fly,
HoMM3 walker) and h3_devil line, h3_troglodyte_upg_alt, h3_lizardman_upg_alt, h3_nymph line, h3_oceanid,
h3_sandworm line, h3_olgoi_khorkhoi (HoMM3 flier/teleporter lab, Core walker). The table's `notNormalized` records them.

Pilot (2026-09-28, generated artifact; fleet_rebuild of each unit, stride match at the target, every gate unchanged):

| unit | speed | before (old Move at the new speed) | after |
|---|---|---|---|
| h3_orc_chieftain (h3_orc_upg) | 5.8 -> 4.1 | slip 0.41, required/actual 0.74 | slip 0.07, ratio 1.04, cadence 1.0 |
| h3_wolf_raider (h3_wolf_rider_upg) | 3.33 -> 5.5 | slip 0.69, required/actual 1.83 (fails 0.686 / 1.4) | slip 0.50, ratio 1.12, cadence 1.48 |

Sheet: `artifacts/claude_takeover_20260927/stride_speed/pilot_move_sheet.png`.

Rollout (2026-09-28, user approved the pilot; generated artifact, every gate unchanged). Rebuilt OK at the target:
goblin, hobgoblin, goblin trapper (4.1; slip 0.12 / 0.30 / 0.13), ogre, ogre mage, ogre brute, cyclops, cyclops king,
blood-eyed cyclops (2.765; slip 0.02-0.14, cadence 1.0), ancient behemoth (6.133; slip 0.03, cadence 1.6). Sheet:
`artifacts/claude_takeover_20260927/stride_speed/rollout_move_sheet.png`. Held in `proposed` (the table's
`proposedHeld` gives the measured refusal; the transaction restored each delivered GLB): h3_wolf_rider (new
articulation:jittery fault at 5.5), toa_orc_berserker and h3_behemoth (ground_glb P2: RightLeg-owned geometry under
the planted soles), and game sid h3_orc (no stride-matched DEF-retarget delivery). Relative to the Core donor value the
orcs and behemoths are slower (5.8 -> 4.1, 7.0 -> 6.133); relative to what the game played they are 3-5x faster.
Not yet built into bundles, deployed or seen in game.

## Vanilla reference

`tools/homm3_def_retarget_delivery/measure_native_walk_stride.py` writes
`tools/homm3_def_retarget_delivery/reference/native_walk_stride.json`. It reads the installed assets statically
with UnityPy; it is not a runtime capture.

- With battleSpeed = 1, the stock walks' required/actual kinematic stride has median **1.657** (range 1.29 to 2.23)
  over esquire, crossbowman, inquisitor, cavalry, ent, unicorn, halfling, ghoul, skeleton, troglodyte and minos.
- A factor that is common to every stock unit is a playback factor, not a stride defect. So it is used as the
  effective battleSpeed: playback = 0.8 x 1.657.
- Calibrated this way, vanilla lands in the band 0.78 to 1.34, with slip median 0.467 and p75 **0.686**. Vanilla
  feet slide too.

## Metrics (`stride_gait.py`)

**Kinematic stride.** world scale x the backward sweep of the contact point, divided by the fraction of the cycle it
spends moving backward.

**Slip ratio.** The contact point's world speed while it is on its floor, relative to body speed. The contact
band is the lowest 25% of its lift. 0 means planted; 1 means dragged along at body speed.

**World scale.** `battleHeightHexes x 0.978 / skinned Unit_Idle t0 height`, matching
`FitSkinnedBattleMesh`. It matches the live pikeman and swordsman logs.

## Measured (calibrated, before the transform)

| unit | required / actual stride | slip |
|---|---|---|
| pikeman | 7.41 (marches in place) | 0.98 |
| swordsman | 1.31 | 0.88 |
| wood elf | 2.76 | 0.85 |
| unicorn | 2.13 | 0.69 |
| centaur | 3.06 | 0.83 |
| griffin | airborne move: flown, not walked, nothing to match | - |

## Transform: `stride_match_glb.py apply` (default `--mode plant`)

This is a capped blend of a longer stride first and a faster rate second.

1. **Step phase.** Each grounded hip-knee-ankle chain keeps its own step phase from the source: its longest
   backward run. When the source is unreliable, it uses the paired leg + 0.5, or else the height minimum.
2. **Stance.** The foot sweeps backward at exactly ground speed, on its own floor, centred under its hip.
3. **Swing.** The foot returns with a smoothstep and lifts at least max(0.04 H, 0.1 x sweep).
4. **Sweep caps.** Each stance sweep is capped by 0.75 H (vanilla humanoid p90 excursion) and by the leg's own reach
   with the pelvis sunk at most 0.15 x leg length.
   - The stance is shortened first, down to 0.30 of the cycle.
   - Only then is the whole Move clip sped up (`--max-cadence`, 1.6).
   - Anything beyond that stays as residual slip.
5. **Leg solve.** Legs are re-solved by two-bone IK in each source frame's bend plane. Straight frames bend the way
   the chain's bent frames do. The ankle keeps the source world rotation, and toes and hoof follow the source phase.
5a. **Clearance (2026-09-28).** No planted chain may go below the Idle floor: not its whole limb (vertices weighted
   >= 0.5 to the hip's subtree) while it swings, and not its sole while it stands. The check runs on the pose as it
   will be written, with the harmonic trim included. A key that dips has its ankle target raised by the deficit and is
   re-solved; after `CLEARANCE_ITERS` passes a limb that is still below the floor is refused.
   - Why: `ground_glb.py` stands the Move's lowest geometry on the floor. A dip lifts the whole loop, and a foot near
     the 0.04 band leaves it, so P2 refuses the unit. h3_hell_hound and hota_cove_swashbuckler were refused for
     stance soles only 0.001-0.002 H under the floor.
   - A chain that never dips keeps its keys bit for bit. Of 10 units re-run from their exact pre-stride sources, only
     h3_demon was unchanged. P2 went from fail to ok on hell_hound, swashbuckler, colossus and fire_hound.
     hota_bulwark_mammoth, hota_factory_armadillo and hota_bulwark_yeti_runemaster still fail P2: their lowest
     geometry there is not a planted sole (stance-leg flesh, and the mammoth's head).
   - Proof tier: generated artifact.
6. **Hold removal.** Leg keys are read at the source phase, which removes the 1/12 s hold before the exporter's
   first Move key. The body keeps that hold.
7. **Body types.**
   - Walking chains: every dedicated leg (humanoid UpLeg pair, `Q??_00/01/02`, the mount rig's `HFL/HFR/HHL/HHR 0..2`,
     the stronghold_quadruped `FL/FR/RL/RR 1..3`) is a leg, each planted on its own floor. A humanoid rig's arms are
     forelegs only beside UpLeg legs and only where they reach the legs' floor band. The plant set equals the scored
     set (2026-09-27): apply picks it on the source Move, and where the pelvis drop brings an arm into `measure()`'s
     band (h3_armadillo_upg_alt: forelegs slid at slip 1.72 unplanted) it re-plans from the source with that arm
     planted on the legs' floor, until the sets agree or it fails closed. The stamp records
     `transform.plantedChains`, and `measure()` of a stamped GLB fails if the chains it scores differ from them
     (older stamps: the transform report's chain keys). A floor-touching foot is never left unmeasured. A four-leg mount set replaces the
     rider's chains (the wolf rider's arms were once stride-matched as legs); `Q??` front legs join a centaur's UpLeg
     hind legs. Arms alone are arms.
   - Fliers (2026-09-27): the class is a HoMM3 fact, never inferred from the Move. `reference/homm3_fliers.json`
     (`build_homm3_flier_table.py`) joins each unit's exact battle DEF (`units_inventory.json` provenance) to the VCMI
     core / HotA / ToA / third-upgrades creature animating it and reads its own FLYING bonus (teleporters included).
     A flier exits 3; a unit missing or unresolved in the table is refused. Before this, 26 walkers (goblin,
     hobgoblin, wolf rider, pit lord, walking dead, kobold, ...) skipped the stride match because one foot's lowest
     point sat 0.06-0.12 H above the other's, and 24 fliers (devils, genies, wraiths, ...) were measured as walkers.
   - Legless walkers (serpents, nagas, medusas, floating elementals): the unit config declares
     `"strideExempt": "<reason>"`; the rig must then have no leg chain, and `apply` exits 3. A legged body that
     never touches the ground (fire elemental: floats in HoMM3) is exempted the same way and also lists the chains
     it acknowledges in `"strideExemptLegs"`, which must equal `chains_of` on the rig. A legged walker whose chains
     `chains_of` cannot read is refused, never skipped.
   - Reported, not refused: `floorLiftFlag` (Move floor > 0.05 H above the Idle floor: fargazer 0.07, ruinous
     hydra 0.06; the fire elemental's 0.30 is its HoMM3 float and it is exempt) and `legFloorGap` (a leg that never comes down to the lowest leg's floor).

Per-unit smoothing: `"strideMatch": {"highHarmonicKeep": k, "reason": "..."}` (0 < k < 1, plant mode only).
Every rewritten Move channel's spectrum above the articulation gate's jitter cutoff (4 Hz) is scaled by k before
the keys are written. Any other key, a k outside (0, 1), or an empty reason is refused. The stamp records k, the
reason, and `strideShareBelowFull.residualRatio`.

Why: a short DEF Move sped up to the cadence cap puts the planted gait's own step harmonics above 4 Hz. The
nomad's 5-frame Move at cadence 1.6 is a 0.26 s cycle with a 3.8 Hz fundamental, so its solved legs read as
jitter (FL3 0.58 against the 0.35 cap).
- Not clamping per-key reach does not fix it. Capping each sweep at the leg's reach still gave jitter 0.43, with
  slip 0.686 and ratio 2.63.
- Dropping the cadence does not fix it either: 1.0 gave jitter 0.54.
- Removing the high harmonics entirely passes jitter (0.13) but leaves ratio 1.74.

k = 0.55 is the value that passes every gate. It trades stride share for smoothness, and the shortfall shows in
the ratio, not in a loosened gate. Nomad results (generated artifact):

| setting | slip | ratio | jitterP90 |
|---|---|---|---|
| as solved | 0.225 | 1.157 | 0.58 |
| k = 0.55 | 0.206 | 1.388 | 0.31 |

The ratio margin is thin (1.388 against 1.4).

Per-unit pelvis drop: `"strideMatch": {"maxDrop": d, "reason": "..."}` (0.15 < d <= 0.35, plant mode only; may share
one reason with `highHarmonicKeep`). The pelvis may then sink up to d x leg length instead of the default 0.15, which
is what sets each leg's reach. An explicit `--max-drop` that disagrees with the config is refused; the stamp's
`maxDrop` is the effective value and `transform.maxDrop` / `strideMatchReason` record the knob.

Why: a walker whose source Move keeps its legs near straight has no reach at the default drop. The hip sits about
one leg length above the planted ankle for more than 10% of the cycle, so the reach cap is 0, the stance sweep
stays at the source's, and the cadence cap runs out. Raising the cadence cap instead fails the articulation gate
(dwarf at cadence 2.59: jitter 0.41). Scratch exports of the canonical .blend (emphasis leaves Move alone), crouch
checked on side/front Move strips against the DEF walk:

| unit | setting | slip | ratio | cadence | jitterP90 | max pelvis drop / H |
|---|---|---|---|---|---|---|
| dwarf | default 0.15 | 0.526 | 1.82 (fail) | 1.6 | 0.16 | 0.055 |
| dwarf | maxDrop 0.25 | 0.214 | 1.117 | 1.6 | 0.12 | 0.084 |
| battle dwarf | default 0.15 | 0.644 | 1.27 | 1.6 | 0.15 | 0.050 |
| battle dwarf | maxDrop 0.30 | 0.491 | 1.111 | 1.55 | 0.15 | 0.092 |
| dendroid soldier | default 0.15 | 0.359 | 1.50 (fail) | 1.6 | 0.10 | 0.049 |
| dendroid soldier | maxDrop 0.20 | 0.083 | 1.069 | 1.35 | 0.04 | 0.065 |
| war unicorn | default 0.15 | 0.083 | 1.11 | 1.6 | 0.39 (artic fail) | 0.043 |
| war unicorn | maxDrop 0.25 | 0.055 | 1.058 | 1.24 | 0.16 | 0.067 |
| pristine unicorn | default 0.15 | 0.207 | 1.12 | 1.6 | 0.61 (artic fail) | 0.062 |
| pristine unicorn | maxDrop 0.25 | 0.112 | 1.063 | 1.46 | 0.27 | 0.067 |

The war unicorn's jitter was the cadence it needed for the missing reach, so maxDrop removes the cause where
highHarmonicKeep would only smooth it. Battle dwarf at 0.22 / 0.25 moved slip only (0.57), not the ratio.

Declared forelegs: `"strideMatch": {"foreLegs": ["LeftArm", "RightArm"], "reason": "..."}` (plant mode only). The
named arm chains are planted from the first pass. Without it, `grounded_chains` judges an arm by its hand joint.
On a hoofed foreleg that joint hangs well above the hoof: on h3_mighty_gorgon the source Move holds it 0.16-0.18 H over
the Idle floor. The forelegs were therefore never planted, and their hooves dipped 0.01-0.036 H under the planted hind
soles, so ground_glb refused the Move under P2. A declared foreleg that is not in the floor band after the plant is
refused like any other planted chain that left it. The stamp records `transform.foreLegs` and
`transform.plantedDeclaredForeLegs`. For mighty_gorgon (2026-09-30):

- slip 0.815 -> 0.162, ratio 1.08, pelvis drop 0.057 H at the default maxDrop;
- ground_glb and every freeze gate OK after fleet_rebuild.

A heel that the shin owns is a skin fault, not a stride one. The fix is the build extension
`tools/homm3_def_retarget/ext/foot_sole.py`, listed in the unit's `extensions`: below each Foot joint, the shin weight
moves to the Foot. Results on 2026-09-30:

- h3_earth_elemental: ground_glb P2 at +0.073 before; after the fix, slip 0.83 -> 0.12 and every gate OK.
- h3_magma_elemental: ground_glb P2 at +0.042 before; after the fix, slip 0.83 -> 0.27 and every gate OK.

Even a 0.004 H dip from a partial-weight heel matters. Once any Move offset is positive, a swinging sole that passes
through the gate's 0.04 H band edge is flagged as lifted.

Clearance step (2026-09-30): each clearance pass raises a dipping key's ankle target by its deficit divided by the
lift the previous raise actually bought per unit raised (floored at `CLEARANCE_MIN_GAIN` = 0.25). A reach-clamped key
lifts only part of each raise, so the plain deficit step shrank it geometrically and never reached the tolerance:
h3_basilisk's RightArm (3 clamped keys) was refused with 0.0003 H left after 12 passes, h3_greater_basilisk with
0.0001 H after 16. The tolerance and the pass budget are unchanged; a key's first raise is the plain deficit, so a
unit that cleared in one pass is bit-identical.

`--mode gain` scales the ankles' fore-aft offsets instead. It is kept only as a negative for comparison: swordsman
slip went 0.885 to 0.866, and pikeman got worse (0.98 to 1.21), because DEF feet are not planted to begin with.

## Results

The source GLBs are frozen `look_delivered.glb` inputs. The outputs are
`artifacts/homm3_stride_match/<u>/<u>_stride_matched.glb`, and the sheet is
`artifacts/homm3_stride_match/contact_sheet.png`.

| unit | slip before -> after | stride ratio before -> after | cadence | max pelvis drop / H |
|---|---|---|---|---|
| pikeman | 0.98 -> **0.06** | 7.41 -> 1.08 | 1.0 | 0.043 |
| swordsman | 0.88 -> **0.18** | 1.31 -> 1.07 | 1.0 | 0.048 |
| wood elf | 0.85 -> **0.22** | 2.76 -> 1.09 | 1.2 | 0.044 |
| unicorn | 0.69 -> **0.10** | 2.13 -> 1.08 | 1.6 (needed 1.67) | 0.047 |
| centaur | 0.83 -> **0.21** | 3.06 -> 1.22 | 1.6 (needed 2.13) | 0.035 |

All five still pass the articulation gate's `gate()` (`flyer_articulation.py`), and leg swing rose on every one.
For example, pikeman went from 21.6 to 81.9 degrees.

## Gates

- `stride_match_glb.py check <glb...>` re-measures a stamped GLB. It fails when slip is above 0.686 (vanilla p75)
  or the stride ratio is above 1.4.
- `tools/homm3_def_retarget_delivery/test_stride_match_glb.py` has a synthetic biped that must plant (slip at most
  0.25), a cadence-cap case, the flier class coming from the table (a lifted walk is still a walk), every retarget
  unit config classified, mount legs replacing a rider's arms, and stance-phase detection. It also runs `check` on
  every GLB on disk. `freeze_slice.py` applies the same class (and strideExempt) before a slice ships.

## Integration point (not wired)

In `tools/homm3_def_retarget_delivery/fleet_rebuild.py` `rebuild()`, add a step right after the `deyaw` step and
before `look.py <u> --force`:

```
stride_match_glb.py apply <u>
```

It runs in place on `artifacts/homm3_def_retarget/<u>/<u>_def_retarget.glb`.

- A flier's or strideExempt unit's exit 3 counts as "skipped", not a failure.
- look.py checks only geometry, so the rewritten Move keys pass through it.
- The stamp refuses double application.

## Open risks

- **The 1.657 factor is inferred.** The effective battleSpeed comes from vanilla assets, not from a runtime read
  of `battleSpeed`. If runtime battleSpeed differs, every required stride scales with it.
- **Transition pops.** Corrective-smooth morph keys are left as they were, so they may not suit the new leg poses.
  The first Move key's ankle shifts by up to 0.19 H, which can pop at the MoveStart/MoveEnd transitions.
- **Cadence side effects.** Units at the cadence cap (unicorn, centaur) play their whole Move faster, body bob
  included. Centaur's forelegs still deliver only 0.75 to 0.83 of the stride.
- **Adventure map not measured.** The map uses mapMesh (ratio 0.714), presumably with the same clip.
- **Not handled:**
  - Unity's nlerp versus the offline slerp.
  - A flyer's move cadence.
  - The griffin's world scale disagreeing with an older live log.
- **Double correction.** Stronghold mocap rows already rewrite moveSpeed down. If this lands for them, drop those
  stride fields so the two corrections do not stack.
