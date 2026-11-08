# HoMM3 idle cadence vs native Olden Era

Status: **approved by the user for the whole roster on 2026-09-25; rolled out; generated artifact
only.**

- All 256 def_retarget units have a retimed idle GLB under
  `artifacts/homm3_idle_cadence/roster/<unit>/`.
- They are checked by `tools/validate_homm3_idle_cadence_contract.py`, which is wired into the
  OfflineUnlockMod build.
- Nothing here is imported into Unity, bundled, installed or seen in game. **No def_retarget bundle
  builder exists to consume the retimed GLBs** (see "Missing hook"), so the proof tier stays
  *generated artifact*.

Tools: `tools/homm3_idle_cadence/`. Data and review media: `artifacts/homm3_idle_cadence/`.

## Question

Our DEF-retarget idles looked too fast in game. How does native Olden Era idle cadence compare
with ours, and what single rule makes ours match?

## Method

`idle_metrics.cadence()` measures native and ours with one rule. It uses local bone rotations
resampled at 60 Hz, which makes it independent of scale and skeleton. For each clip it reports:

| Metric | Definition |
|---|---|
| loop length (s) | the clip's own loop |
| moving bones | bones that leave their loop-mean rotation by more than 0.5 deg |
| mean angular speed | per moving bone, the time-mean local angular speed (deg/s); median over the moving bones |
| peak angular speed | per moving bone, the highest local angular speed (deg/s); median over the moving bones |
| amplitude | per moving bone, the largest angle from its loop-mean rotation (deg); median over the moving bones |
| beats | the dominant number of cycles per loop of the first principal component of the pose trajectory; one breathe-in plus breathe-out, or one sway, is one beat |
| beat period | loop length divided by beats |

### Native measurement

`measure_native_idles.py` reads the installed `resources.assets` with UnityPy. It is read-only.

- It selects every `AnimatorOverrideController` whose base is `_Battle_Unit_Anim_ctrl_v2`: 104
  `22.Idle` and 103 `23.Idle_Rare` overrides.
- It decodes the muscle-clip streamed, dense and constant curves.
- It fails closed if any streamed curve is discontinuous, which would indicate a decoder error.

### Our measurement

`measure_glb_idles.py` measures `Unit_Idle` in all 257
`artifacts/homm3_def_retarget/<unit>/<unit>_def_retarget.glb`. Fifteen probe/variant folders
(`*_nocs`, `*_probe`, `oceanid_cs*`, and similar) have no GLB under their folder name. They are
listed in the report's `errors` and are not measured.

### How the idle plays in game

Both native and our idles play through the base controller's `idle` / `rareIdle 0` states:

- state speed 1.0, multiplied by the float parameter `battleSlowIdle` (default 1.0);
- `idle -> rareIdle 0` fires on the `rareIdle` trigger, which game code sets;
- `rareIdle 0` returns at exit time 1.0.

Our lab builder maps both `22.Idle` and `23.Idle_Rare` to our one idle clip. The plugin does not
rescale battle idle playback. `Animator.speed` is only touched for map-adventure walk timing and
for the billboard lane. So at `battleSlowIdle = 1`, the GLB clip length is the in-game loop
period, and any runtime `battleSlowIdle` change scales native and ours equally.

## Results

### Summary

`artifacts/homm3_idle_cadence/native_idles.json` and `ours_idles_before.json` give these
values (median, with p10-p90 in brackets):

| | native `22.Idle` (n=104) | native `23.Idle_Rare` (n=103) | ours before (n=257) |
|---|---|---|---|
| loop length | **3.27 s** (2.13-7.61) | 4.53 s (3.20-7.70) | **0.83 s** (0.67-0.92) |
| beats per loop | 1 (1-2) | 1 (1-2) | 1 (1-1) |
| beat period | **2.67 s** (1.60-5.03) | 3.73 s | **0.83 s** (0.67-0.92) |
| mean angular speed | **14.3 deg/s** (5.6-28.3) | 41.0 | **31.5 deg/s** (11.5-52.5) |
| peak angular speed | 28.5 deg/s (10.3-73.2) | 195 | 65.1 deg/s (18.9-104) |
| amplitude | 9.1 deg (4.6-18.6) | 27.7 | 5.6 deg (2.4-8.9) |

What the summary shows:

- **Native idle is one slow breath or sway every 2.67 s.** That exact value is the mode: 80 frames
  at 30 fps. Loops of 5.33 s hold two beats.
- **Ours is one DEF cycle keyed at 12 fps**, 8 to 11 frames long, so 0.67 to 0.92 s. The user's
  guess is right: **our idle tempo is about 3.2x native.**
- Our motion is also *smaller* than native, 5.6 deg against 9.1 deg. The high speed therefore
  comes entirely from tempo, not from amplitude.
- Native `Idle_Rare` is a separate, larger fidget: about 3x the speed and amplitude of `Idle`,
  with 4.5 s loops.

### Per unit, native `22.Idle`

| controller | loop | beats | beat period | mean deg/s | peak deg/s | amp deg |
|---|---|---|---|---|---|---|
| Esquire_ctrl (small infantry) | 1.60 | 1 | 1.60 | 19.8 | 32.2 | 7.0 |
| halfling_ctrl (small) | 1.60 | 1 | 1.60 | 27.9 | 47.1 | 9.2 |
| peasant_ctrl (small) | 5.33 | 2 | 2.67 | 12.7 | 19.5 | 8.3 |
| crossbowman_ctrl | 5.33 | 2 | 2.67 | 10.5 | 18.3 | 7.4 |
| medusa_ctrl | 2.13 | 1 | 2.13 | 47.3 | 94.8 | 24.1 |
| pixie_ctrl (hovering flyer) | 3.00 | 2 | 1.50 | 23.3 | 50.4 | 11.9 |
| wasp_ctrl (hovering flyer) | 5.33 | 40 (wing buzz) | 0.13 | 25.1 | 37.6 | 13.1 |
| griffin_ctrl (flyer) | 2.67 | 1 | 2.67 | 17.8 | 28.0 | 11.9 |
| h_angel_ctrl (flyer) | 2.67 | 1 | 2.67 | 20.1 | 51.8 | 10.3 |
| unicorn_ctrl | 4.00 | 1 | 4.00 | 11.3 | 49.5 | 11.8 |
| ent_ctrl (large) | 5.33 | 2 | 2.67 | 12.8 | 25.4 | 8.5 |
| giant_turtle_ctrl (large) | 2.67 | 1 | 2.67 | 10.5 | 16.3 | 4.4 |
| hydra_ctrl (large) | 3.33 | 1 | 3.33 | 10.0 | 15.9 | 6.3 |
| titan_ctrl (large) | 3.33 | 1 | 3.33 | 5.8 | 8.4 | 4.3 |
| black_dragon_ctrl (large flyer) | 5.33 | 2 | 2.67 | 8.7 | 16.9 | 7.1 |
| dragon_ctrl (large flyer) | 2.67 | 1 | 2.67 | 5.3 | 7.3 | 3.1 |

Body size:

- Large units move *slower*: dragons and the Titan run at 5 to 9 deg/s, against 13 to 28 deg/s for
  infantry.
- Large units do **not** have a longer beat. Most units of every size sit at 2.67 s; two small
  humanoids are at 1.6 s, and the Titan and Hydra at 3.33 s.

Idle variants: every unit has one `Idle` and one `Idle_Rare`. How often `Idle_Rare` plays is
decided by game code (the `rareIdle` trigger), not by the controller, so these data cannot show
it. Each unit view's `rareIdleTime` is usually 1.5 to 3.0 s. It does not equal the rare clip's
length (griffin: 1.5 against 4.37 s), and its meaning is unproven.

### Pilots, before and after

Pilots: `h3_griffin` (flyer), `h3_pikeman` (small infantry), `h3_hydra` (large). Their natives
are griffin, Esquire/swordsman and hydra. Data:
`artifacts/homm3_idle_cadence/pilots/ours_idles_after.json`.

| unit | loop | mean deg/s | peak deg/s | amp deg | native counterpart |
|---|---|---|---|---|---|
| h3_griffin before | 0.75 | 36.5 | 72.5 | 5.7 | griffin 2.67 s, 17.8 / 28.0, 11.9 deg |
| h3_griffin after | **2.40** | **11.8** | **28.2** | 5.9 | |
| h3_pikeman before | 0.75 | 37.0 | 69.1 | 5.6 | Esquire 1.60 s, 19.8 / 32.2, 7.0 deg |
| h3_pikeman after | **2.40** | **12.1** | **25.2** | 5.7 | |
| h3_hydra before | 0.67 | 6.3 | 10.1 | 0.9 | hydra 3.33 s, 10.0 / 15.9, 6.3 deg |
| h3_hydra after | **2.13** | **2.1** | **3.5** | 0.9 | |

After the retime, the loop period and peak speed of the griffin and the pikeman land inside the
native range. Their mean speed sits slightly below native, because their amplitude is below
native.

The hydra's DEF idle barely moves at all (0.9 deg). Retiming makes it nearly still. That is an
amplitude gap in its retarget, not a tempo question, so this rule does not treat it.

## Recommendation and rule

**Use one global idle time scale of 3.2, applied with easing.** 3.2 is the native median beat
period (2.667 s) divided by our median loop length (0.833 s).

- Native beat period barely depends on body size, so a per-size factor would encode noise.
- Our amplitude is already below native, so reducing amplitude would be the wrong fix.
- Plain frame holds would make our 12 fps keys even steppier. Instead, the retime resamples with
  easing:
  - each stretched clip gets a loop-periodic, time-parameterised Catmull-Rom (cubic Hermite)
    curve at 30 Hz through **every original key**, so every DEF pose is still hit exactly;
  - corrective-smooth morph weights, which are one-hot per key, are resampled linearly so they
    stay in [0, 1];
  - constant two-key STEP channels stay constant.

The rule lives in `tools/homm3_idle_cadence/idle_cadence_rule.py`: `IDLE_TIME_SCALE = 3.2`,
`RESAMPLE_HZ = 30`. It is applied by `retime_idle.py <in.glb> <out.glb> --unit <unit>` (the unit selects its exceptions-table treatment) and, for the roster, by `rollout_idle.py`. The retime:

- rewrites only `Unit_Idle`, by appending new accessors;
- leaves every other animation, mesh, skin and image byte-identical (checked on all three pilots:
  the binary prefix is identical and only `Unit_Idle` changed);
- never writes its input, because the def_retarget GLB is hash-stamped by the unit-look lane;
- fails closed on an open loop, a non-constant STEP channel, a CUBICSPLINE channel, or a sampler
  shared by several channels.

Unit tests: see "Validator" below.

The existing mocap-v2 delivery (`experiments/homm3_mocap_v2/delivery_style.py`) independently
stretches Idle by 2.5. That gives about 2.1 s for a 0.83 s DEF idle: inside the native range, but
faster than the native median. This experiment does not change that lane.

## Pilot review media (1x real time, 8 s, looped)

In `artifacts/homm3_idle_cadence/pilots/<unit>/`:

- `<unit>_idle_review.mp4`:
  - top row: Blender Workbench mesh render, ours before and ours after;
  - bottom row: stick figures of native, before and after, each with its pose-PC1 trace and a
    playhead.
- `<unit>_idle_sticks.mp4`: the stick-figure row on its own. Native is forward kinematics of the
  native clip on the prefab's Transform hierarchy, with bindings matched by CRC32 of the path.

These pilot videos came from the pre-rollout script. `make_review.sh <unit> <native_prefab>
<native_ctrl>` now renders from a unit's roster report into `artifacts/homm3_idle_cadence/review/`
(see "Review media" below). The script runs `memgate.py` before each Blender launch.

The native panel shows the native *skeleton*, not the native mesh. Native and ours are drawn from
different views: native from the side, ours from the front.

## Roster rollout (approved 2026-09-25)

The user reviewed the pilots and approved the rule for the larger set, asking for outliers to be
resolved case by case. Rollout: `python tools/homm3_idle_cadence/rollout_idle.py [unit ...]`.

### Input and pipeline order

Delivered chain per unit: **def_retarget build -> emphasis pass -> idle retime -> unit look.**

- `idle_cadence_rule.resolve_input(unit)` is the one place the retime input is chosen. It is the
  unit's `<unit>_def_retarget.glb` as the unit-look lane resolves it (`look.resolve_source`):
  look's superseded un-prebaked original when the GLB on disk is look's stamped delivery (216 units
  at rollout), else the GLB itself (40).
- The emphasis pass (`docs/homm3_def_retarget_emphasis.md`) delivers by replacing the build GLB, so
  its rewritten clips are what the retime reads. It leaves `Unit_Idle` alone.
- Currency is keyed on `anim_sha256`: a hash of every animation's channels, samplers and accessor
  values in the input. It is recorded as `srcAnimSha256` in the report and in the retimed GLB's
  `asset.extras.homm3IdleCadence`.
  - When emphasis (or a rebuild) rewrites any clip, the output is **stale**. The validator fails it
    and the rollout regenerates it.
  - A look texture bake changes no animation (and may move the input to its superseded path), so it
    does not make an output stale.
  - During the rollout this caught three units rebuilt mid-run (`h3_giant_upg`, `h3_fire_elemental`,
    `h3_air_elemental`). It also caught the first emphasis deliveries (`h3_amalek`,
    `h3_ancient_behemoth`, `h3_angel`, `h3_arch_devil`), whose outputs had been made from
    pre-emphasis clips. All of them were regenerated from the new input.
- So once emphasis has delivered a unit, its outputs are always made from the emphasised clips.
  Rerun `rollout_idle.py` after an emphasis delivery; it only redoes units whose input changed.

### Outlier detector

`idle_cadence_rule.detect()` runs on every source idle. Its thresholds come from the native
`22.Idle` distribution (`native_idles.json`). Native and our units share no size-class labels, so
the "speed far outside native" check uses the whole-roster native p95, not a per-size range.

| flag | rule |
|---|---|
| `static` | no bone moves more than 0.5 deg |
| `nearStatic` | the p90 bone's swing is below 3.13 deg, the quietest native idle's median-bone swing |
| `fastAfterRule` | after the 3.2x rule, the median-bone mean speed is above 41.8 deg/s or the p90-bone peak is above 330.7 deg/s (both native p95) |
| `wingFlutter` | bones named `*wing*` swing at least 15 deg (p90) and beat at least 2 times per source loop |

The rollout **refuses**:
- a flagged unit with no entry in the exceptions table;
- a unit whose recorded flags differ from what the detector finds now.

So an outlier is never retimed by default without a recorded decision.

### Exceptions table

`tools/homm3_idle_cadence/idle_exceptions.json` is the one table of per-unit decisions
(unit -> treatment, flags, reason). The rule, the rollout, `retime_idle.py --unit` and the
validator all read it. The full reasons, with the DEF evidence, are in the JSON.

Treatments:
- `rule`: the global factor, recorded because the unit is flagged;
- `factor`: a different factor;
- `wingDecouple`;
- `exclude`.

DEF silhouette motion is the mean per-frame change of the DEF idle's alpha mask (roster median
0.013, p25 0.0066). It separated "the DEF is quiet" from "the retarget lost the motion".

| unit(s) | flags | treatment | why |
|---|---|---|---|
| `h3_damsel_fly`, `h3_dragon_fly`, `h3_serpent_fly` | wingFlutter | `wingDecouple`, `wingBones ["Wing"]`, `wingCycles 3` | The DEF idle is a hover buzz: wings swing 29 deg, 3 beats per 0.5 s loop. Native hoverers keep a fast buzz over a slow body (wasp: 0.13 s wing beat). The body takes 3.2x (0.5 -> 1.6 s); the wing bones play their source loop 3 times over it (wing beat 0.167 -> 0.178 s). |
| `h3_elf_wardancer`, `h3_lich_master` | static | `rule` | The DEF idle is one still pose (2 keys, silhouette change 0.0), so the retime is a visual no-op. |
| `h3_fargazer`, `h3_hurricane_elemental` | fastAfterRule | `rule` | Still 54 / 127 deg/s mean after 3.2x, above native p95. Their DEF idles are among the most-moving in the roster (0.058, rank 238/255; 0.079, rank 246): continuous eyestalk writhe / whirlwind swirl, with no like-for-like native unit. The speed is motion content, not tempo; a larger factor would read as slow motion. Confirmed on the review renders: the fargazer is one 2.67 s splay-and-close pulse with a body tilt; the hurricane is one 2.93 s twist of the column. |
| `hota_bulwark_mammoth`, `hota_bulwark_war_mammoth`, `h3_mammoth_upg_alt` | nearStatic | `rule` | The DEF idle itself is nearly still (0.005, bottom quartile). Faithful; not boosted. |
| `h3_genie_upg`, `h3_ogre_mage` | nearStatic | `rule` | 2026-09-28, user-approved: on the hand-keyed identity-mesh lane (33c1fc508b) the p90 swing is 2.758 / 2.502 deg. Accepted as quiet, not boosted; kept on the tempo rule because `exclude` would make the slice freeze's `retime_idle.py --unit` refuse the unit. |
| `h3_peasant` | nearStatic | `rule` | 2026-10-09, coordinator decision: p90 swing 2.16 deg. The DEF idle is a sub-pixel breath (fork 0.56 px, head 0.2 px on an 82 px body); its silhouette change 0.0126 reads high because edge flicker weighs more on a small sprite, and at the same scale our sprite already changes about 2x the DEF. Faithful; not boosted. |
| `h3_troll` | nearStatic | `rule` | 2026-10-09, coordinator decision: p90 swing 3.09 deg (threshold 3.13). The DEF idle is a gentle breath (1-1.7 px edge sway, silhouette change 0.0216); at the same scale ours already matches or exceeds it on every edge. Faithful; not boosted. |
| `h3_sharpshooter` | nearStatic | `rule` | 2026-10-09, coordinator decision: p90 swing 2.54 deg. The DEF moves only its cape; ours now does too (lower cape skinned to Spine1 to the hem; hem mean 4.3 cm vs about 4.7 cm in the DEF), motion the bone-swing detector cannot see. Not boosted (2.7x the DEF). |

Flies re-decided 2026-09-28 (user-approved): after the 2026-09-27 rebuild (98c0319977) their source idle is a single 32.2 deg wing beat per 0.5 s loop, so the detector no longer flags `wingFlutter` (fewer than 2 beats). The entries keep `wingDecouple` x3 with `flags: []`: the three wing cycles over the 1.6 s body idle are now a deliberate tripling of that one beat (wing beat about 0.53 s), not a playback of the DEF's own three beats.

Counts:
- 256 units retimed.
- 246 are unflagged and use the global rule.
- 10 were flagged at the 2026-09-25 rollout, all decided in the table: 3 `wingDecouple`, 7 `rule`. 2026-09-28: `h3_genie_upg` and `h3_ogre_mage` added as nearStatic `rule`; the three flies keep `wingDecouple` with no detector flag (see below the table).
- 17 units that were flagged `nearStatic` / `static` because the retarget lost the DEF's idle motion
  are unflagged since 2026-09-25 by the retarget-side fix below ("Retarget amplitude").
- 0 excluded, 0 refused, 0 open loops.

### Result, whole roster

From `artifacts/homm3_idle_cadence/roster/roster_report.json` (median, with p10-p90 in brackets):

| | native `22.Idle` | ours before | ours after |
|---|---|---|---|
| loop length | 3.27 s (2.13-7.61) | 0.83 s (0.67-0.92) | 2.67 s (2.13-2.93) |
| mean angular speed | 14.3 deg/s (5.6-28.3) | 32.0 (11.5-52.5) | 10.3 (3.7-16.8) |
| peak angular speed | 28.5 deg/s (10.3-73.2) | 65.2 (19.5-104.5) | 25.3 (7.2-42.3) |
| amplitude | 9.1 deg (4.6-18.6) | 5.6 (2.4-8.9) | 5.7 (2.4-9.1) |

- After the retime, loop length and peak speed sit inside the native range.
- Mean speed is a little below native, because our amplitude is below native. That is an amplitude
  gap in the retarget, which this lane deliberately leaves alone.
- After treatment, only these remain above native p95:
  - the two `fastAfterRule` units, accepted above;
  - the three flies' wing peaks, which are the intended buzz.

### Outputs

In `artifacts/homm3_idle_cadence/roster/` (GLBs are not in git):

- `<unit>/<unit>_idle_retimed.glb`: the input with `Unit_Idle` retimed. Every other clip, and the
  mesh, skin and images, are identical. `asset.extras.homm3IdleCadence` records the input
  animation hash and the treatment.
- `<unit>/report.json`: input path and kind, `srcAnimSha256`, flags, treatment, factor, wing
  cycles and nodes, before/after cadence (loop, beats, mean/peak deg/s, swing), and wing-only
  cadence.
- `roster_report.json`: the whole run.
- `detect_report.json`: the detector alone.

### Validator

`tools/validate_homm3_idle_cadence_contract.py [--unit U ...] [--require-complete]` is wired into
`OfflineUnlockMod.csproj` as `ValidateHomm3IdleCadenceContract` (skip it with
`-p:SkipHomm3IdleCadenceContract=true`). It checks:

- the exceptions table (schema, known treatments, reasons, ranges);
- every roster report, against the input as resolved now:
  - **not stale**: the input's animation hash equals the report's (otherwise ERROR: rerun the
    rollout);
  - the report's treatment, factor and wing cycles equal what the rule and table give now;
  - the idle lasts exactly factor x the source idle (1e-4 s);
  - every idle transform channel closes its loop (1e-3);
  - body channels hit every source key pose at its stretched time (1e-4);
  - every other animation has identical channels, interpolation and accessor bytes. The
    comparison is against the emphasised input, so emphasis changes are expected there and any
    other change is not;
  - nodes, meshes and skins are identical;
  - **look texture/VFX idle layers keep time with the retimed idle** (`texture_idle_errors`).
    The unit-look VFX manifest keys every `Unit_Idle` layer per DEF idle frame at 12 fps, in the
    *un-retimed* time base: uvAtlas cell lists (the conflux elementals' and cove nymph's
    `element_flow`, the oceanid's `water_flow`), defFlipbook sheets, effectLight curves and
    volumetricFire intensities. Neither `rollout_idle.py` nor `look.py` rewrites those lists, and
    neither should. The one consumer that pairs them with the retimed GLB is
    `tools/homm3_def_retarget_delivery/ship_def_retarget_slice.py`: its `make_time_map` sends
    every idle window through the retime's own `t0 + (t - t0) x factor` before the lab bakes the
    cells into the clip, and it fails closed if the retimed span disagrees. The runtime
    (`Homm3UnitLookVfxRuntime.cs`) adds no timing of its own. The validator checks:
    - the manifest is 12 fps;
    - every key sits on its DEF frame's window;
    - per-frame layers list exactly the DEF idle's frames (`frames.json` `loops`);
    - the source idle spans those frames plus the loop's `transitionKeys`, over which the plan
      holds the last cell;
    - the delivery's own `make_time_map`, imported rather than copied, lands the source idle end
      on the retimed idle end and every key on a retimed key (1e-4 s).

    Cells left at source tempo against the stretched idle ("texture 3.2x faster than the bones")
    fail this check. So does a cell list shorter than the DEF idle, with a pointer to
    `tools/homm3_vfx/element_flow_scores.py <unit>`. Both failures were exercised against
    `h3_earth_elemental`.

    At the 2026-09-26 run, 34 idle layers on 27 units passed. That covers all 15 conflux
    `element_flow` layers, the nymph, the oceanid and the phoenix `fire_boil` (after
    `h3_fire_elemental`'s retime was regenerated from its rebuilt mesh). This is a
    generated-artifact check; in-game phase is not proven.
- With `--require-complete`: every def_retarget unit has an output or an `exclude` entry.

A report whose GLBs are absent locally (a fresh clone) is a note. The full roster takes about 13 s.

Unit tests: `python -m unittest tools/homm3_idle_cadence/test_retime_idle.py` (5 tests, including
wing decouple).

### Review media

`bash tools/homm3_idle_cadence/review_roster.sh` renders each exception class and six normal units,
each against the nearest native idle. For each unit it writes
`artifacts/homm3_idle_cadence/review/<unit>/<unit>_idle_review.mp4`, 8 s at 1x real time:
- ours before and after, as Workbench mesh renders;
- native / before / after stick figures.

It also writes `review/exceptions_grid.mp4`, all exception reviews in one grid.

| unit | class | native reference (prefab / controller) |
|---|---|---|
| `h3_dragon_fly`, `h3_damsel_fly`, `h3_serpent_fly` | wingDecouple | wasp / wasp_ctrl |
| `h3_fargazer` | fastAfterRule | world_watcher / world_watcher |
| `h3_hurricane_elemental` | fastAfterRule | eldritch_flyer / eldritch_flyer_ctrl |
| `h3_hydra` | nearStatic (retarget lost motion; fixed in the retarget 2026-09-25) | hydra / hydra_ctrl |
| `h3_basilisk` | nearStatic (retarget lost motion; fixed in the retarget 2026-09-25) | giant_turtle / giant_turtle_ctrl |
| `hota_bulwark_mammoth` | nearStatic (quiet DEF) | giant_turtle / giant_turtle_ctrl |
| `hota_cove_nix` | nearStatic (mesh had no tail; fixed by a mesh regeneration 2026-09-26) | naiad / Naiad_ctrl |
| `h3_elf_wardancer`, `h3_automaton_upg_alt` | static (automaton fixed in the retarget 2026-09-25) | blade_dancer / blade_dancer_ctrl; Animated_Armor / animated_armor_ctrl |
| `h3_angel`, `h3_skeleton`, `h3_black_dragon`, `h3_unicorn`, `h3_troglodyte`, `h3_crossbowman` | normal | angel / h_angel_ctrl; Skeleton / Skeleton_Anim; black_dragon / black_dragon_ctrl; Unicorn / unicorn_ctrl; troglodyte / troglodyte_unit__ctrl; crossbowman / crossbowman_ctrl |

What the renders show:
- **Flies**: the wings keep a visible buzz (9 wing beats per 1.6 s loop) while the body sways slowly.
- **Fargazer and hurricane**: large, continuous motion at a native-like beat.
- **Near-static units**: they read nearly frozen. The nix and hydra PC1 traces now have the native
  tempo but a tiny swing. (Renders from before the 2026-09-25 retarget fix and the 2026-09-26 nix mesh
  regeneration; neither stays near-static now.)
- **Static units**: unchanged, as expected.
- **Normal units**: one slow sway per 2.1-2.9 s, against native 2.67 s.

The native panel is the native skeleton, drawn from a different view.

## Open questions

- **Idle_Rare.** Native plays a larger fidget clip for `Idle_Rare`. Ours reuses the retimed idle.
  A DEF-derived fidget (for example the Mouseover clip) is a separate question.
- **Retarget amplitude (fixed for 17 units, 2026-09-25; generated artifact, not in game).** 18
  `nearStatic` units plus `h3_automaton_upg_alt` had lost their DEF idle motion in the retarget. The
  fix is in the retarget, not in this lane: the shared extension
  `tools/homm3_def_retarget/ext/idle_cycle.py` (listed last in a unit's `extensions`, configured by
  its `idleCycle` block) replaces the Unit_Idle loop's per-frame fit jitter with the fitted DEF frame 0
  pose plus an authored periodic cycle: a neck/head nod, tail waves, wing sway, a breathing lift, and,
  for the automatons, a new rigid `Rotor` bone cut from the skin and spun once per loop (the DEF idle
  is a spinning rotor the rig had no bone for). Every shape is zero at frame 0, so the other clips
  still blend from the fitted pose; only the Unit_Idle segment changes (other clips' IoU unchanged).
  Root causes: Fortress procedural chain rigs (hydras, basilisks, gorgons, wyvern, paokai) whose
  placeholder idle spread a few degrees over long chains; Rampart quadrupeds (manticore, scorpicore)
  with a 3 deg nod and a thin tail sway; the automatons' boneless rotor; hand-keyed / cove units
  (sacred phoenix, nix praetorian) whose idle was fit jitter. Result: p90 swing 0.9-3.1 -> 3.4-8.9 deg
  (automatons: rotor spin), idle IoU within -0.022 (ruinous hydra) to +0.012, no new edges past 2x
  except one 0.016-unit neck-fork edge on the ruinous hydra (2.01 -> 2.77, from the corrective-smooth
  morph at the rest-of-nod pose) and one on the hydra (NeckR_06, 2.27). The flags and exceptions
  entries were removed; the 17 units were re-emphasised, re-rolled and re-looked. The automaton
  rotor silhouette is nearly round, so its spin reads mostly through the texture.
  `hota_cove_nix`, `hota_cove_nix_warrior` (fixed 2026-09-26; generated artifact, not in game): the DEF
  idle is a tail swish (about 8 px) and the old Meshy meshes had no tail. Both meshes were regenerated
  with the tail (paid Meshy concept edit + image-to-3d), the tail rigged as a `QTail_` chain, turned
  into view by `ext/cove_tailyaw.py`, and waved by `idle_cycle`. Swing p90 2.7 / 2.1 -> 5.0 / 5.0 deg;
  both flags and exceptions entries removed.
- **Wing morph weights.** For the flies, the corrective morph weights follow the body timeline,
  not the tiled wing loop.

## Missing hook, and what remains for in-game proof

- A def_retarget bundle builder now exists (`docs/homm3_unit_look_pipeline.md`, "def_retarget
  delivery"), exercised by the two-unit cove slice. It applies the same mapping,
  `t' = t0 + (t - t0) * factor`, to the *look-delivered* GLB. Its idle animation hash equals the
  roster retime's.
  - Nothing yet consumes `artifacts/homm3_idle_cadence/roster/*/*_idle_retimed.glb` directly.
  - In the agreed order the unit-look lane runs *after* the retime. So either look must read the
    retimed GLB as its source, or the bundle builder must apply the retimed `Unit_Idle` to look's
    delivery. Neither is wired.
  - The validator's stale check is what such a consumer must require.
- The shared `tools/homm3_def_retarget/` scripts were not edited. `build_unit.py` keys one key per
  DEF frame at 12 fps (`scene.render.fps = 12`). A build-time `idleTimeScale` unit-config key is
  the alternative hook, but a delivery-time post-process keeps the build faithful to the DEF.
- Proof status:
  - done: generated artifact (256 retimed GLBs, validator, measurements, Blender renders of the
    retimed GLBs);
  - not done: Unity import, bundle, install, battle appearance, and whether game code ever sets
    `battleSlowIdle` to anything other than 1.
