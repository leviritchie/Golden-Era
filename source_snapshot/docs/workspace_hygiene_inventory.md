# Workspace Hygiene Inventory (2026-09-19)

Untracked-file triage from the stale-docs/dead-code/code-smell remediation, Phase 5.
Mesh/animation pipeline scope is excluded from remediation and stays untracked.

## Tracked by this phase (were untracked, are compile- or gate-required)

| Path | Why |
| --- | --- |
| `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3SkinnedStrideLocomotion.cs` | Referenced by `Homm3ImportVisuals.cs` / `Homm3ImportReleaseBattleVisualHook.cs`; build-required |
| `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3OwnedSkinnedMapFogProbe.cs` | Referenced by `Homm3ImportVisuals.cs` / `Homm3MapSquadVisualControllerHook.cs`; build-required |
| `tools/validate_homm3_ui_scale_contract.py` | UI-scale gate (Castle Strategem reference pattern) |
| `tools/validate_raw_translation_entrance_occupancy_contract.py` | Entrance-occupancy gate; imports the two files below |
| `experiments/campaign_port_poc/raw_translation/entrance_occupancy.py` | Gate subject (raw gate occupancy policy) |
| `experiments/campaign_port_poc/raw_translation/test_entrance_occupancy.py` | Gate subject test |

## Keep untracked (excluded mesh/animation scope, ~440 files)

| Group | Count | Verdict |
| --- | --- | --- |
| `experiments/homm3_mocap_v2/` | 285 | Keep; out of remediation scope |
| `tools/homm3_silhouette_pose_fit/` | 131 | Keep; out of remediation scope |
| `tools/homm3_import/`, `tools/homm3_meshy_frame_pose/`, `tools/homm3_mocap_cleanup/`, `tools/homm3_map_building_meshes/` | 11 | Keep; out of remediation scope |
| `docs/homm3_mocap_*.md`, `docs/homm3_shipped_rigid_rebind_experiment.md`, `docs/plans/homm3_authored_donor_decisions.md`, `docs/surfaces/homm2_styleblit_preview.md` | 5 | Keep; mesh-lane docs |
| `diagnostics/*.png` | 4 | Keep; mesh-fit preview artifacts |
| Root `tmp_*.py` probes (pin sweep, IoU, silhouette, beak, flyer, ccd, rest pose, mark audit, roc, diff dir, gen pin, snap marks, w2cv, bind geom) | 17 | Keep; mesh-lane scratch owned by active experiments |

## Keep as-is (separate project)

| Path | Why |
| --- | --- |
| `golden_era_mod_helper/` | Nested git repo (own `.git`, public clone `leviritchie/golden-era-mod-helper`); teaching kit, not this repo's content. Added to `.gitignore` so status stays clean. |

## Proposed removals (need owner approval; NOT deleted)

| Path | Why candidate |
| --- | --- |
| `bash.exe.stackdump` | Crash artifact, no provenance value |
| `_inspect_rtb.csx` | One-off C# scratch script at root |

No other deletions proposed. Nothing in this inventory was deleted by the remediation.
