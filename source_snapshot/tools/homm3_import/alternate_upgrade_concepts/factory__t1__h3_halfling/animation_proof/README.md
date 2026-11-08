# Halfling Firebug Attack Pipeline Proof

This proof applies one profile-defined global palette rewrite to the native indexed DEF for Grenadier (hota_factory_halfling_grenadier), then re-extracts runtime clip 14.Attack group 15.

- Contract: 24 frames, 450x400 RGBA, 12 FPS.
- Stability mechanism: the DEF body is byte-identical; only its single global palette changes.
- Geometry proof: every output alpha plane and bounding box is byte-identical to its matching source frame.
- Palette authoring: soot, crimson, copper, ember drive the Firebug material treatment.
- Scope: palette/material propagation only; it does not prove arbitrary geometry transfer or new equipment silhouettes.
- Attack contract scope: the current validator accepts shooter-front group 15 with runtime clip 14.Attack; melee and other attack families are intentionally outside this proof.
- Palette taxonomy: the classifier uses fixed soot, crimson, copper, and ember material classes; a different class vocabulary requires a mapper extension.
- Evidence boundary: generated artifact validated. This has not been built into an Olden Era bundle or runtime-tested.

Rebuild and validate:

```powershell
python tools/homm3_import/build_hota_alt_attack_palette_proof.py --profile tools/homm3_import/alternate_upgrade_concepts/factory__t1__h3_halfling/animation_proof/firebug_attack_profile.json
```

Run the same fail-closed checks without rebuilding:

```powershell
python tools/homm3_import/build_hota_alt_attack_palette_proof.py --profile tools/homm3_import/alternate_upgrade_concepts/factory__t1__h3_halfling/animation_proof/firebug_attack_profile.json --validate-only
```
