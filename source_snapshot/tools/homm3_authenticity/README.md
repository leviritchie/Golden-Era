# HoMM3 authenticity board

Review instrument for the unit animation authenticity pass (`docs/homm3_unit_authenticity_pass.md`). It renders the
GLB the game ships next to every DEF frame of every clip. Blender-free, Unity-free, one process, torch on CUDA.

```
python tools/homm3_authenticity/board.py <unit> [--glb <path>] [--out <dir>] [--clips Idle,Move] [--device cuda|cpu] [--view-yaw <deg>]
python tools/homm3_authenticity/test_board.py      # CPU reference vs CUDA parity (~6 s)
```

`<unit>` is a lab sid or its retarget source unit (`fleet_census.SOURCE_UNIT`, e.g. `toa_boar_rider` <- `h3_boar_rider`).
The default output is `V:/olden_port_work/authenticity/<labSid>/boards/`, which is outside the git tree and not on F:.

## Outputs

| file | content |
|---|---|
| `clip_<clip>.png` | One column per DEF frame, with frame index and GLB time. Rows: **DEF**, **sprite**, **overlay**, **battle**, **preview**. The DEF, sprite and overlay rows share one px scale and one crop box, so silhouettes compare 1:1. In the overlay row, red is DEF only, blue is render only and grey is both; it also shows the IoU. |
| `overview.png` | Up to six key frames per clip in the DEF, sprite, battle and preview rows, at most 1600 px wide. |
| `clip_<clip>.gif` | DEF, sprite and battle side by side at game timing (20 fps). The GLB is sampled continuously; the DEF panel holds frame `floor((t - start) / step)`. |
| `board.json` | Per clip: timing (start, end, step, retime factor), sprite mapping, and per frame the DEF/sprite silhouette IoU, both bboxes' w/h and their ratio, and the centroid offset in px and as a fraction of the DEF height. It also records the GLB path, sha256 and candidates, camera notes, missing clips, wall time, peak RSS and peak VRAM. |

Silhouettes compare the DEF alpha >= 200 (HoMM3 shadow pixels are black at alpha 64/128 and are excluded) against
render coverage >= 0.5, at DEF px.

## Which GLB (`sources.py`)

Default: the frozen `<selection out>/<labSid>/delivered_idle_retimed.glb` of a live delivery selection
(`tools/homm3_def_retarget_delivery/*_slice_v1.json`, not `supersededBy`). It must hash to the row's
`frozen.idleRetimedGlbSha256`. This is the master that `ship_def_retarget_slice.py` hands the lab builder. A
`.color0.glb` displacement master is the same GLB plus COLOR_0.

- **Several selections:** if more than one live selection carries the lab sid, the newest `bundle_build.json` that names the unit wins. Every candidate is listed.
- **Albedo:** the selection's `inputs/basecolor.png`, which is the shipped albedo.
- **No selection:** the board falls back to `artifacts/homm3_def_retarget/<unit>/<unit>_def_retarget.glb` and writes a `FALLBACK` note.
- **`--glb`:** renders a candidate and records the shipped GLB for reference.
- **Rubble:** the gargoyle line's `*_Rubble` mesh is not rendered, because the delivery defers it. The body vanishes at the shatter frame, as it does in game.

## Timing

DEF groups come from the linked master (`master_sequence.json`) and the build's `frames.json`, which holds the PNGs the
sprite camera was calibrated on, plus the loop facts. A DEF group maps to the clip `Unit_<contractSuffix>`.

DEF frame `i` sits at `start + i * step`, where `step = duration / m`:

- **One-shot clip:** `m = n - 1`.
- **Idle/Move loop:** `m = n + transitionKeys` (the closing key plus the seam keys).
- **Start time:** `start` is the most common first-key time over the clip's channels. Stride matching prepends 0 s keys to a few channels.

The retime is read from the GLB itself. For example, the idle shows `x3.2 of 12 fps`.

## Cameras

| row | camera | status |
|---|---|---|
| sprite | `build_unit.py` SpriteCam from `<unit>_def_retarget.blend.spritecam.json`. The Blender basis is converted to glTF, and the pixel mapping is `x = ox + s*dot(p,right)`, `y = oy - s*dot(p,up)`. If the GLB carries a deyaw stamp, the camera is turned by the same `Ry(-yawDeg)`. | **Exact.** The board re-derives the camera's rest-mesh calibration (`sprite_info.json` bbox0) from the GLB's bind pose: 0.00 px on the pilots. It also reproduces the build's own Blender render of pikeman idle 0 within 0.6 px. If the rest check fails, each clip falls back to a 2D similarity fitted on its own frame 0, and `board.json` says so. |
| battle | `tools/homm3_prebake/render_passes.py` battle_faces_right: orthographic, 40 deg elevation, azimuth -60 from glTF +Z. | Exact for the unit-look lane's rule. |
| preview | `UiConstants.UnitCamParams`: perspective, angle 13.7, distance 25, yOffset 1.95. It uses the fleet preview facing: root yaw 22, Orientation 150, bind -60, so the camera sits 68 deg to the unit's right. The world scale comes from `owned_preview_framing.json`. | **Approximate.** The FOV is unknown, so the box is crop-normalised. yOffset is read as the look-at height. |

Each view uses one fixed camera box per clip (the union over all its frames), so travel and bounce stay visible. The
px per unit is fixed per unit across clips.

The sprite camera and the `--view-yaw` turn live in `spritecam.py` (numpy only), shared by board.py, keypoints.py and
joint_coverage.py.

### DEF view (`--view-yaw`)

The build's SpriteCam is one generic camera, and it does not see every rig from the DEF's side. On the griffin line
it views the body about 60-70 deg off the nose (nearly front-on, the same side as the battle camera), while the HoMM3
griffin is drawn about 20 deg toward the viewer. The quadruped fits compensate with a view yaw (`quadruped.fit.yaw`,
posefit `--fix-view`). `--view-yaw <deg>` turns the sprite camera about world up by that yaw in the fitters'
convention (Blender `Rz(yaw)` on the SpriteCam forward, glTF `ry(+yaw)`), so the sprite row shows the pose from the
DEF's side. The rest calibration no longer applies, so each clip uses its own frame-0 similarity fit, and size is
normalised (`board.json` records `viewYawDeg`). Measured 2026-10-07: for the griffin line, yaw -40 puts the body
19 deg toward the viewer (the DEF's front-3/4), yaw -60 is pure profile, and yaw -100 (the line's config and earlier
fit yaw) points the body 40 deg away from the viewer, a behind-3/4 view that mirrors the depth of every fitted pose.

## Device, parity, performance

- **Shared code:** `raster.py` runs the same code on both devices. It does morphs (sparse active targets) plus linear-blend skinning, then a pair-enumerating z-buffer rasteriser (`scatter_reduce` amin on depth bits and triangle id), then perspective-correct textured Lambert shading.
- **CPU-only work:** animation sampling and the joint hierarchy run on the CPU in float64. That work is a sequential parent walk that takes milliseconds.
- **No silent fallback:** `--device cuda` without a GPU raises.
- **Parity test:** `test_board.py` compares the two devices on h3_pikeman (idle 0 and an attack frame, all three cameras). On 2026-10-07, coverage differed on 0 px, the mean RGB difference was 1e-6 and the position difference was 2.4e-7.
- **No cuBLAS:** the kernels avoid matmul, because the cuBLAS handle alone added about 350 MB of host RSS.

Measured on 2026-10-07 with `tools/homm3_glb_patch/resmeter.py` on an RTX 5070 Ti, all clips:

| unit | wall (resmeter) | peak RSS | torch VRAM reserved |
|---|---|---|---|
| h3_pikeman (7 clips, 1008x870 DEF) | 19.0 s | 1428 MB | 438 MB |
| h3_gargoyle (9 clips) | 19.3 s | 1394 MB | 126 MB |
| h3_griffin (9 clips) | 14.1 s | 1379 MB | 150 MB |

About 1.1 GB of the RSS is torch plus lazily loaded CUDA kernel modules; the same board on `--device cpu` peaks
near 0.7 GB. The CUDA context adds roughly 0.3-0.5 GB of VRAM outside the torch allocator.

## Proof tier

The boards are generated artifacts: offline renders of the GLB. They do not prove the in-game look. Preview framing
in particular is approximate.

## Before/after reel

`reel.py <unit> --before <boards_dir> --after <boards_dir>` cuts the DEF, sprite and battle panels back out of each
`clip_<clip>.gif` (via the `clip_<clip>.gif.json` panel sidecar board.py writes) and plays every clip in game order as
one GIF: DEF | before | after on top, before | after battle view below. Posted to the user when a unit finishes.

## Joint coverage (`joint_coverage.py`, rubric 3a)

```
python tools/homm3_authenticity/joint_coverage.py <unit> [--glb <path>] [--out <json>] [--clips Idle,Move]
```

Lists joints that bend in the DEF's linked-master capture but stay still (or do not exist) in our GLB. For each clip
there is one table with these columns: capture joint, mapped bone(s), reference range (deg), our range (deg) at the
board's DEF frame times, and a flag. The flags are `STATIC` (ours < 25% of the reference), `WEAK` (< 50%) and
`MISSING` (no bone, or a subtree with no skin weight). A flag needs a reference of at least 15 deg (20 deg for a
swing, 25 deg for the short foot, toe, hand and clavicle segments) and a shortfall of at least 15 deg. Both floors sit
above the capture's jitter. The script prints only the non-OK rows. It writes
`V:/olden_port_work/authenticity/<labSid>/joint_coverage.json`, which also lists animated bones with no skin weight
and the ranges of rig bones the capture has no counterpart for (wing digits, tails, horse necks).

- **Measures.** Hinge joints use the angle between the incoming and outgoing segments. Limb-root ball joints (UpLeg,
  Arm, Shoulder) use the outgoing direction in the pelvis or chest frame. The script uses joint directions only: it
  ignores `pred_rot6d` and bone lengths.
- **Mapping.** Joints map by Mixamo name. Mounted units (castle_mount `HFL/HFR/HHL/HHR`) use a proxy: the capture's
  `<side>UpLeg/Leg/Foot` maps to every same-side horse chain bone `0/1/2`, and ours is the one that moves most. On
  quadruped configs the human capture limbs are only a proxy for the creature's legs. The script does not cover what
  the capture lacks, such as wing digits, tails, jaws and ears. Judge those on the board.
- **Capture noise floor.** DEF frames whose sprites are near-identical (< 0.5% of sprite pixels differ by more than
  8/255, matched across all clips) form static groups. A joint's noise is the largest range the capture shows inside
  one group, and the joint's reference minimum is raised to noise + 15 deg. On the royal griffin the capture moves the
  forearm up to 93 deg and the head/neck 22 deg across frames pixel-identical to idle f0; those rows no longer flag.
  The JSON lists the groups and the per-joint noise under `captureNoise`.
- **DEF keypoint reference (`ref def`).** When `keypoints/<labSid>.json` exists (see the next section), every chain
  joint with 2D points in the clip gets its own row. The DEF side is the signed 2D bend angle at the joint over the
  clip (circular range). Its noise is 2 x 1 px of marking error over the median segment length, and the reference
  minimum is max(15 deg, 2 x noise). Ours projects the mapped bone points through the DEF-matched sprite camera
  (`spritecam.py`, `--view-yaw`, default the file's `view.yawDeg`) at the board's DEF frame times. 2D bend angles do
  not depend on the board's similarity fit, so `--align` is only recorded. The flags are the same as for capture rows,
  plus `MISSING` when a chain point has no bone (a rig defect) or all three points ride one rigid bone, and `TIMING`
  when our peak excursion lands more than 1 DEF frame from the DEF's peak (cyclic on loops). The DEF reference wins:
  a capture row whose bone is a measured DEF joint stays in the JSON as `supersededBy: "def"` but is not printed.
  Capture rows still report the joints the keypoints do not cover. Both kinds share one table, with the source in the
  `ref` column.
- **Silhouette evidence: not implemented.** Region frame-difference energy cannot tell bent knees from a rigid leg
  that rotates with the body.
- **Performance and placement.** CPU numpy, with no torch. Measured 2026-10-07: 0.2-0.33 s and 210-300 MB peak RSS
  per unit.
- **2026-10-07 results.** h3_pikeman: 3 rows. h3_royal_griffin: 33 rows, including talons in Idle, Mouseover and
  Defence and the hind feet. h3_champion shipped: 48 rows. Every horse knee and fetlock is `STATIC` (0 deg) in Hitted,
  Defence, AttackFront and Death, and nearly still in MoveStart and MoveEnd. Candidate `cand_b31`: 40 rows; its knees
  bend 17-25 deg against a reference of 60-100 deg.

## DEF keypoint tracks (`keypoints.py`, reference for rubric 3a)

```
python tools/homm3_authenticity/keypoints.py [--kp <file>] <unit> sheet     [--clips g02_idle] [--frames 0,3] [--box x0,y0,x1,y1] [--scale 6]
python tools/homm3_authenticity/keypoints.py [--kp <file>] <unit> set       <marks.txt|marks.json|->
python tools/homm3_authenticity/keypoints.py [--kp <file>] <unit> propagate [--clips ...] [--matcher ncc|dino] [--device cuda|cpu]
python tools/homm3_authenticity/keypoints.py [--kp <file>] <unit> eval      [--clips ...] [--matcher ncc|dino] [--device cuda|cpu]
python tools/homm3_authenticity/keypoints.py [--kp <file>] <unit> review    [--clips ...] [--glb <path>] [--view-yaw D] [--align clip|idle]
python tools/homm3_authenticity/keypoints.py [--kp <file>] <unit> status
```

The capture has no joint for tails, jaws, ears, talons, wing digits or a lance, and its limbs on creatures are a human
proxy. Keypoint tracks give every articulating part a reference taken from the DEF sprite itself.

- **File.** `keypoints/<labSid>.json` (tracked, small; schema `homm3.authenticity.def_keypoints.v1`). `view` holds the
  DEF view used to project our GLB (`yawDeg`, `align`, as board.py). `chains` are named 2D polylines; each point maps
  to a GLB bone spec: `Bone` (head), `Bone@tip` (+Y to the 95th percentile of the bone's dominated vertices),
  `Bone@far` (the farthest 2% of them), `Bone@+x|-x|+y|-y|+z|-z` (axis extreme), `Bone@0.6` (a fraction of the tip),
  or `null` = **MISSING**, a body part the DEF moves and our rig has no bone for. `clips.<clipKey>.frames.<i>` hold
  `pts` (DEF canvas px, pixel i spans [i, i+1)) and `src` per chain, one character per point: `m` marked, `t`
  tracked, `h` hidden, `-` unknown.
- **Marking.** `sheet` renders enlarged frames with a labelled 1/5/10 px grid (`--box` zooms a region). `set` takes
  `clip <clipKey> <frames>` lines followed by `<chain> x,y x,y ...` (`-` hidden, `?` unknown) or `<chain>.<point> x,y`.
  `review` draws the chains (filled = marked, ring = tracked) and, with `--glb`, our projected bone points dashed.
  Images go to `V:/olden_port_work/authenticity/<labSid>/keypoints/`. `--kp` points every command at a copy, so
  several markers can work in parallel and merge with `set`.
- **Tracker (`propagate`).** GPU first, `--device cpu` is the reference. Frames pixel-identical to a marked frame (in
  any clip) copy its marks first. Every mark is tracked forward and backward (wrapping on loops) to the next mark:
  Gaussian-weighted NCC minus SSD on premultiplied RGBA 9x9 patches, scored against both the previous frame and the
  keyframe, +-12 px search, a displacement prior, a penalty for leaving the alpha mask, and a parabolic sub-pixel fit.
  `--matcher dino` adds DINOv3 ViT-S/16 dense features (`facebook/dinov3-vits16-pretrain-lvd1689m`, local cache only)
  at 4x upscale. Where the two directions disagree by more than 3 px the nearer keyframe wins and the frame is listed
  as a conflict; otherwise they blend by distance.
- **Accuracy (`eval`).** Leave-one-frame-out over the marked frames: each held-out mark is re-tracked from the others
  and compared. Writes `eval_<matcher>.json`.
- **Parity.** `test_keypoints.py` runs propagate on CPU and CUDA (NCC, and DINO when cached) over the champion's idle
  and attack clips, odd frames re-tracked from the even marks: 98% of 301 points identical, median 0.00 px, max
  0.98 px (sub-pixel fit on flat score peaks). CPU 1.7 s (NCC) and 7.7 s (DINO); CUDA under 1 s each.
- **Pilot, 2026-10-07.** h3_champion: 10 chains, 44 points, every DEF frame marked (68 frames). h3_royal_griffin:
  14 chains, 62 points; 43 distinct frames marked, the other 26 copied from pixel-identical frames. Leave-one-frame-out
  accuracy (a hard case: the held-out frame is tracked from its marked neighbours across the whole motion): champion
  median 1.4 px, 57% within 2 px, p90 11 px; griffin median 4.0 px, 34% within 2 px, p90 24 px (wings, flips between
  spread and folded). NCC and DINO score within 0.2 px of each other, so marks, not tracking, carry the pilot. Runtime:
  propagate 4-5 s and 0.7-1.1 GB RSS; eval NCC 6-10 s and under 0.5 GB VRAM, DINO 27-29 s and 1.2-1.9 GB VRAM (16-frame
  feature cache); joint_coverage with keypoints 0.9-1.7 s, 215-305 MB RSS.
