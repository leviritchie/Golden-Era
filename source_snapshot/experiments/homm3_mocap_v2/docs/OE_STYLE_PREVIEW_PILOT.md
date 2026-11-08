# OE Style Preview Pilot

`oe_motion_style_v2.py` is an offline, candidate-only motion preview tool for
already exported mocap GLBs. It does not modify the source GLBs, build Unity
bundles, deploy payloads, solve IK, infer contacts, or establish runtime proof.

## Run

From the repository root:

```powershell
& artifacts/homm3_mocap_v2/venv/Scripts/python.exe experiments/homm3_mocap_v2/oe_motion_style_v2.py `
  --manifest artifacts/homm3_mocap_v2/stronghold_ingame_test_v1/raw/manifest.json `
  --output artifacts/homm3_mocap_v2/oe_style_pilot_v2/motion `
  --units h3_goblin h3_roc h3_ogre h3_wolf_rider `
  --groups g00_move g12_attack_front `
  --gain 1.45
```

The tool requires the requested unit/group Cartesian product to be present. It
patches only float quaternion rotation accessor bytes. Rest geometry, UVs,
indices, skin joints/weights, bind poses, materials, textures, and JSON remain
byte-preserved. It rejects unsupported animation channels and malformed key
times rather than silently skipping them.

The v2 style uses shared WORLD-space quaternion references and converts the
styled result back to parent-relative local rotations. Attack clips use a
first/end boundary envelope. Move clips use a cyclic mean reference with a
short boundary blend. Root rotation/translation and leaf local rotations are
preserved. Gain `1.45` is a preview parameter, not an acceptance threshold.

The motion report explicitly records `accepted: false`, `noIkContacts`, and
`deformationStrainCheck: not_run_offline_pose_only`. The separate preview renderer
does measure added edge strain against the baseline at matching sample times.
This is a diagnostic, not an acceptance gate or automatic damping rule.

## Lighting And Preview

The initial matte/key-fill variant (v2, key x0.65 and fill x1.35) removed shine
but mostly darkened the mesh. The next candidate (v3) redistributes part of the
key into ambient fill. All four units use identical controls:

```text
key = 0.60 * original key
world RGB radiance = original world RGB radiance + 0.25 * 0.40 * original key RGB radiance
```

The 0.25 coefficient is a sphere-average cosine heuristic, not an exact Cycles
energy conservation claim. Both variants create a separate matte material before
baking (metallic 0, roughness 1, flat normal). COMBINED baking still includes the
dielectric BRDF; this is not a claim that every highlight or painted shadow has
been removed. Source albedo is retained, not delit.

```powershell
& artifacts/homm3_mocap_v2/venv/Scripts/python.exe experiments/homm3_mocap_v2/oe_lighting_style.py `
  --rollout artifacts/homm3_mocap_v2/stronghold_ingame_test_v1 `
  --units h3_goblin h3_roc h3_ogre h3_wolf_rider `
  --profile energy-redistributed `
  --output artifacts/homm3_mocap_v2/oe_style_pilot_v3

& artifacts/homm3_mocap_v2/venv/Scripts/python.exe experiments/homm3_mocap_v2/preview_oe_style.py `
  --unit h3_goblin --clip Unit_Move `
  --styled-glb artifacts/homm3_mocap_v2/oe_style_pilot_v2/motion/h3_goblin/g00_move.glb `
  --soft-texture artifacts/homm3_mocap_v2/oe_style_pilot_v3/lighting/h3_goblin/soft_baked_lit.png `
  --out artifacts/homm3_mocap_v2/oe_style_pilot_v3/previews/h3_goblin/Unit_Move
```

These are reproduction commands; lighting and preview outputs must be new
directories. Existing output is rejected. Move uses `g00_move` / `Unit_Move`;
attack uses `g12_attack_front` / `Unit_AttackFront`.

The four panels are current, stronger motion, softer bake, and both. They share
one camera and timing. Replay retains all eight influence slots. Rendering uses
the existing CUDA rasterizer under the shared GPU lock; bakes use CPU with eight
threads. Reports pin source/candidate hashes and GIF timing. These are textured
LBS previews, not the native OE shader, battle camera, or in-game lighting.

## Observed Result

User-approved visual profile, 2026-09-07: all four units rendered Move and
AttackFront comparisons, and the user approved the shared stronger-motion and v3
lighting result. This approves the presentation profile, not unreviewed units or
installed runtime behavior. No quantitative vanilla OE comparison was measured.
Motion gain increases range; attack clips show greater deformation,
and planted contacts/grips are not solved. The user explicitly prioritizes higher
articulation and is willing to accept increased deformation if necessary. Strain
is therefore a diagnostic tradeoff, not grounds for automatically rejecting or
damping a candidate. Visual review should distinguish tolerable distortion from
failures of action readability, grip, or rider attachment. Blanket delivery still
requires that review, not a zero-deformation requirement.
At matching times, the fraction of mesh edges changing length by over 25 percent
was 0.94 percent Goblin, 1.37 percent Ogre, 2.36 percent Roc, and 3.14 percent Wolf
Rider for attacks. These are diagnostic strain figures, not artifact acceptance
or visible-defect percentages.

The four v3 CPU bakes took about 190 seconds combined. Preview rendering and
engineering/review time are separate costs; this is not an end-to-end runtime
claim. The lighting bake is shared by all clips of a unit.

Focused tests:

```powershell
& artifacts/homm3_mocap_v2/venv/Scripts/python.exe -m unittest experiments.homm3_mocap_v2.test_oe_motion_style_v2 experiments.homm3_mocap_v2.test_oe_lighting_style experiments.homm3_mocap_v2.test_preview_oe_style
```

Thirteen pilot tests passed. Preserve the raw baseline alongside every candidate.
The subsequent explicit `approved-oe-v1` delivery integration is documented in
`docs/homm3_mocap_ingame_delivery.md` at the repository root. It includes the
user-requested 2.5x idle duration and build/deploy provenance validation. Other
durations remain unchanged. Idle comparison GIFs show five baseline cycles beside
two slowed cycles so both reset at the same GIF boundary. The initial pilot did
not modify the installed mod; subsequent build and installed proof must come from
the delivery stage reports, not this visual approval.
