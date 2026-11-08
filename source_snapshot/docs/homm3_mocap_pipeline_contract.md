# HoMM3 Mocap Pipeline Contract

This is the production-shaped pipeline for unit animation candidates. It is
not the same thing as the legacy silhouette/fused-push experiment.

## Authority

The animation authority is the captured vendor joint-position sequence. The
capture is frozen before skin fitting, and every clip uses one asset-wide
calibrated idle reference. We reconstruct fixed-length local rotations from
those positions only to make the target mesh playable; we do not invent a new
trajectory from the rendered silhouette. A separately hash-pinned orientation
completion may change orientation only while preserving every captured joint
position.

Camera registration is an idle-only operation. The current registrar searches
the full azimuth rather than assuming a Meshy front, keeps alpha as the primary
objective, and uses overlapping normalized color as a front/back parity
tie-break. If the two parities remain texture-ambiguous, retain both as
explicit orientation candidates for review; never resolve the ambiguity by
changing the mocap trajectory.

The current provenance contract is
`experiments/homm3_mocap_v2/pipeline_contract.py` and the fast validator is
`tools/validate_homm3_mocap_pipeline_contract.py`.

Historical corpora that predate `motionRepresentation` are accepted only by
the validator's explicit legacy mode (the default for readback of the frozen
Stronghold selection). New corpus producers and new lane gates should pass
`--require-explicit-corpus`; this fails closed until the capture representation
is declared. Likewise, a legacy attachment-refit report with no
`motionOwner` is deliverable only when its parent fit report is present and
proves an allowed captured-mocap owner.

## Stage Ownership

1. **Source and profile**: select the original SmartRig/T2 surface, the
   structured anatomy profile, the frozen primary donor package, and the
   source-frame corpus. Hashes are checked before GPU work.
2. **Capture**: use the existing per-clip captured corpus when it exists. The
   optional linked-master path (`run_linked_master_pipeline.py`) is an
   acquisition path for a new one-pass capture, not an excuse to replace an
   existing capture with silhouette search. It remains generated-artifact only
   until separately accepted.
3. **Bind and motion reconstruction**: use the accepted prepared bind and the
   shared idle calibration. Keep bone lengths and the captured motion fixed;
   do not use learned `pred_rot6d` as a motion interface. Ordinary units use
   `capture_positions_v1`; mounted units may use the explicitly checked
   `fixed_composed_fk_v1` representation.
4. **Skin fit**: `run_skin_mesh_pilot.py` may redistribute weights against all
   captured frames. New Castle work starts in `weights_only` mode so the
   SmartRig rest surface cannot be silently warped. Bounded rest-mesh
   adaptation is an explicit, separately reviewed option, not a recovery path.
5. **Repair**: topology/attachment repair and a post-separation skin refit are
   opt-in and provenance-pinned. They may not change the captured joint
   trajectory. Hand authoring is allowed here when an attachment or fused
   component cannot be represented by the automatic support, but the result
   must be a separate hash-pinned candidate and never overwrite the raw fit.
6. **Raw export**: `export_ingame_candidates.py` copies baseline clips or
   serializes saved refits. It performs parity checks and must not retarget,
   smooth, optimize, retime, or add keys.
7. **Presentation**: derive a separate `approved-oe-v1` GLB. The current
   Stronghold policy preserves raw motion, applies the approved Move/Attack
   articulation gain (`2.20`, +120), slows Idle by `2.5x`, and leaves other
   clip timing unchanged. Lighting uses the existing soft matte
   `approved-oe-v1` bake. Raw clips remain the authority.
8. **Delivery**: assemble orientation/material/lifecycle metadata, import in
   the Unity lab, probe the loaded bundles at raw key times and midpoints, build
   the explicit selection, then deploy only after payload and hash readback.

## Forbidden Shortcuts

- `fused_push`, GPU cascade silhouette pose search, or continuous-tracker
  outputs are diagnostic evidence only and are not delivery inputs.
- Image IoU/chroma/DINO scores may evaluate a skin candidate, but may not
  redefine the mocap trajectory, bind pose, or cycle keys.
- Do not add physics smoothing, contact repair, hidden retiming, or invented
  transition poses under the approved style profile.
- Do not replace a bad mesh with a different unit's geometry or silently fall
  back to a placeholder. Stop or produce a clearly marked candidate.
- Do not claim runtime or gameplay proof from a generated GIF, a static report,
  or a successful Unity import alone.

## Castle Starting Point

The six currently materialized Castle corpora (`Archer`, `Marksman`,
`Pikeman`, `Crusader`, `Monk`, and `Swordsman`) already have captured corpora,
profiles, and prepared registrations. They should be rerun through the
current-mocap fitter, starting with weights-only and the standard Stronghold
presentation profile. `run_castle_mocap_pipeline.py` keeps historical corpus
readback explicit by default; pass `--require-explicit-corpus` for a new or
refreshed corpus and it will fail closed until `motionRepresentation` is
declared. The stopped Pikeman fused-push batch is retained as a diagnostic
artifact and must not be promoted.
