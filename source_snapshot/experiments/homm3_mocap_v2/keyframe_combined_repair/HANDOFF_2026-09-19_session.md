# Session Handoff — 2026-09-19 (keyframe repair → skinning → refit)

## Where things stand
The wood-elf neck warp is fixed and the fix is measured on every axis at once
(component stretch 13.1 → 1.0, seam gap 0.005, hand-to-hip bleed 0.22 → 0.0).
The standing pipeline is: cut → pin the separated part rigid → trace the body
with articulation enforcement. The joint refit exists as a tested cross-unit
module but is HELD OUT of the pipeline (opens the seam). No GLB was written
at any point; everything below is experiment + measurement + committed code.

## Commits this session (all in `experiments/homm3_mocap_v2/`)
- `aa27704ee8` — post-cut bind-weight reassignment (`reassign_cut_boundary_weights`)
- `41608ca516` — position-field trial verdict (negative, kept as experiment)
- `aee1e2b110` — hand-binds-to-hip diagnosis (bleed is deployed-first)
- `1d21cd12b0` — topology-traced skinning + optional articulation enforcement
- `e6d7826627` — rigid cut part over traced body (Toy Story combination)
- `3d3783ebd6` + `61d0655cfe` — worst-frames reel note, misalignment diagnosis
- `771b21f62f` — cross-unit joint-proxy refit + build validator (new files
  `joint_refit.py`, `test_joint_refit.py`)
- Prior baseline `faa596b33c` — texture-guided neck-cut selector, 10/10 green

Suites green: 29/29 attachment+runner, 7/7 refit (36/36 combined).

## Numbers that matter (Death clip unless noted, 61 frames)
- Neck component max stretch: deployed 13.1 → pinned+traced+articulated 1.0.
- Seam gap: 0.005 unrefitted (0.16 ring-reassign era); 0.61 max with refit.
- Hand→hip mass on 207 hand verts: deployed 0.22, field 0.025, traced 0.22,
  traced+articulated 0.0.
- Global edge stretch: traced+articulated bulk 3x better than deployed
  (p50 0.0115 vs 0.038) but contact tears at extremes (p99 7.2, max 95x).
- Refit fit quality (identical params): elf median joint-to-flesh 0.102→0.014,
  goblin 0.114→0.029, validator green on both.

## Reels (review artifacts, under `artifacts/homm3_mocap_v2/keyframe_combined_repair_woodelf_v1/h3_wood_elf/`)
- `h3_wood_elf_neckcut_worstframes.gif` — THE one to watch: face 4752 at
  13.5x/13.1x/9.9x before, 1.00x after, tight registered zoom. Start here.
- `..._pinned_tracked.gif` / `..._pinned.gif` — full 61f reels (neck barely
  moves per frame; most visible churn is reskinned body, not the neck).
- `..._closeup.gif`, `..._reassign.gif`, `..._field.gif`, `..._traced.gif` —
  superseded rungs, kept for comparison.

## Scratch (not committed, still on disk)
- `/tmp/stage{2,3,4,5,6,7,9}_*.py`, `/tmp/diag_*.py`, `/tmp/reel_*.py`,
  `/tmp/check_*.py` — measurement/reel/diagnostic scripts.
- `C:\tmp\stage{2,3,4,5,6,7,9}_result.json`, `C:\tmp\woodelf_neck_proposal.json` —
  result payloads and the reviewed cut proposal.

## Open questions (need explicit go-ahead)
1. GLB writes / delivery application — nothing applied to delivery assets.
2. Rigid-collar variant: pin seam sources rigid too, to close the refit seam.
3. Thigh contact tear (95x) under articulation enforcement.
4. Wiring `validate_refit_proxies` into the delivery selection gate.
5. `mixamorig:Hips` owning the neck cut smells like a mislabeled joint upstream.

## Standing constraints (do not break)
- Never `read_file` a PNG/GIF (base64 kills the session); diagnose numerically.
- Keep off C drive; motion/bind/topology/UV/albedo unchanged for delivery.
- Generated artifacts only; no GLB writes or repair reruns without go-ahead.
- One problem, one solution; no silent fallbacks; contracts ship with validators.
