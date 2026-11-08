# Aurora Ram Attack Pipeline Proof

This proof applies one profile-defined global palette rewrite to the native indexed DEF for Argali (hota_bulwark_argali), then re-extracts runtime clip 14.Attack group 12.

- Contract: 8 frames, 450x400 RGBA, 12 FPS.
- Stability mechanism: the DEF body is byte-identical; only its single global palette changes.
- Geometry proof: every output alpha plane and bounding box is byte-identical to its matching source frame.
- Palette authoring: soot, crimson, copper, ember drive the Aurora Ram material treatment.
- Scope: palette/material propagation only; it does not prove arbitrary geometry transfer or new equipment silhouettes.
- Attack contract scope: shooter-front group 15 or melee-front group 12 with runtime clip 14.Attack (profile attackFamily: shoot|melee|auto).
- Palette strategy: cluster_ramp.
- Palette taxonomy: the classifier uses fixed soot, crimson, copper, and ember material classes; a different class vocabulary requires a mapper extension.
- Evidence boundary: generated artifact validated. This has not been built into an Olden Era bundle or runtime-tested.

Rebuild and validate:

```powershell
python tools/homm3_import/build_hota_alt_attack_palette_proof.py --profile tools/homm3_import/alternate_upgrade_concepts/bulwark__t2__h3_mountain_ram/animation_proof_aurora_cluster_ramp/aurora_ram_cluster_ramp_profile.json
```

Run the same fail-closed checks without rebuilding:

```powershell
python tools/homm3_import/build_hota_alt_attack_palette_proof.py --profile tools/homm3_import/alternate_upgrade_concepts/bulwark__t2__h3_mountain_ram/animation_proof_aurora_cluster_ramp/aurora_ram_cluster_ramp_profile.json --validate-only
```
