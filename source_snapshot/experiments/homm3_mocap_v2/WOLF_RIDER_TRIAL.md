# Wolf Rider mounted trial

Status: generated diagnostic candidate, quality rejected. No game deployment.
User-visible evaluation is not inferred from export parity or rest identity.

## Structured authoring boundary

`wolf_rider_authored.py` owns source anatomy, missing rider torso/head landmarks,
regional vertex ownership, seat attachment, and rigid sword ownership. It is a
versioned preparation recipe, not a per-clip correction script. The original
Meshy GLB is SHA-pinned and untouched. Its dark texture remains unchanged.

`mounted_capture.py` encodes the authentic plates once and runs two complete,
unmodified vendor graphs: Coyote mount and Mixamo rider. Both see the full plate;
actor segmentation is NOT implemented. All 80 DEF frames and authored temporal
context are retained, including one-frame movement transitions.

`compose_mounted_corpus.py` adapts each actor against its single shared idle
reference, attaches the rider to the mount spine, and computes composite FK.
Rider root and leg rotations are explicitly held in the authored seated rest.
This contact policy also applies to death and cannot represent dismounting.
It is a limitation to evaluate, not an inferred property of every mounted clip.

`prepare_mounted_skin_asset.py` assigns regional capsule-distance weights with
at most eight influences and a single rigid sword owner. Initial rest vertices,
triangles, UVs, and texture are preserved. `corpus_motion.py` validates frozen
FK before fitting/export and consumes the composed matrices directly, avoiding
a lossy second reconstruction from positions. Existing position-capture assets
retain their original path. The ordinary preview also uses this motion contract.

## Proven checks and observed deficiencies

- Generated initial rest identity error: 4.44e-16 maximum coordinate error.
- All 15 composed clips pass frozen-bind FK validation.
- All 15 exported animated GLBs pass frame-by-frame mesh parity.
- Final rest-shape and depth-visibility gates pass.
- Idle appearance fails: alpha mean absolute difference 0.01847476 vs 0.005 cap.
- Animated surface quality fails. Off-axis attack views reveal stretched patches
  around the rider arm/body boundary; source-view approval alone is insufficient.
- Source-view attack inspection shows a recognizable windup but inaccurate
  sword direction at impact. Mesh fitting does not correct fixed motion errors.
- The initial actor split, current regional masks, and seated-contact policy
  are NOT validated as robust onboarding for another mounted unit.

## Artifacts and timing

Artifacts: `artifacts/homm3_mocap_v2/skin_mesh_pilot/wolf_rider/`.
`all_def_v1` contains all 15 comparison GIFs, GLBs, and the failed quality report.
`offaxis_v1` contains five independent-view diagnostic GIFs and contact sheets.
`registration_v1` compares original rest mesh against the known source idle.
`authoring_v1` pins the authored recipe and composite preparation arrays.
`composed_v2` is the used corpus; v1 retained an actor-only manifest without
original DEF group metadata and was rejected during registration.

Measured two-actor capture including shared encoding: 89.681 seconds.
Measured full-corpus fit, GIF generation, and export parity: 101.679 seconds.
These total 191.360 seconds, NOT end-to-end onboarding time. The ledger
`onboarding.json` records the longer elapsed session plus separately measured
stages. Architecture, authoring, review, debugging, and communication are not
free and must not be represented as GPU time. Model dollar cost is unavailable.

## Repeatable stages

Use `artifacts/homm3_mocap_v2/venv/Scripts/python.exe`. Each command's `--help`
describes inputs. Outputs refuse existing destinations; do not silently reuse
an old candidate after changing authoring. Execute in order:

1. `prepare_skin_corpus.py`: full DEF and known-idle canvas preparation.
2. `mounted_capture.py`: one encoding, both unmodified actor packages.
3. `wolf_rider_authored.py`: pinned authored manifest and composition preparation.
4. `prepare_mounted_skin_asset.py`: owned skin and central preparation freeze.
5. `compose_mounted_corpus.py`: aligned actor corpora plus original source manifest.
6. `register_skin_corpus_asset.py`: one common idle and source camera.
7. `run_skin_mesh_pilot.py`: immutable motion, shared skin and bounded rest mesh.
8. `preview_skin_mesh_corpus.py`: off-axis inspection without another fit.

The next useful experiment is actor-isolated rider capture and a visual ownership
audit before optimization, with the existing full-plate result as the explicit
control. Do not add per-clip bone offsets to hide either failure. Structured
AI preparation remains a viable product direction; this trial does not yet
establish its per-unit authoring cost or mounted-unit robustness.
