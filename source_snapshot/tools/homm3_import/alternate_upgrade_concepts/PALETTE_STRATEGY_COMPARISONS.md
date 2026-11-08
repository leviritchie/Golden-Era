# Per-unit palette strategy comparisons

`cluster_ramp` is not assumed globally. Run:

```bat
python tools/homm3_import/compare_hota_alt_palette_grain_strategies.py --profile <attack_profile.json>
```

Then open that profile’s `grain_strategy_comparison/index.html` and pick a strategy before baking `paletteStrategy` into the proof profile.

## Latest auto-rank (metric-only; confirm visually)

| Unit | Comparison HTML | Metric-recommended | Notes |
| --- | --- | --- | --- |
| Halfling Firebug | `factory__t1__h3_halfling/animation_proof_cluster_ramp/grain_strategy_comparison/index.html` | `soft_blend` | `cluster_ramp` ranked worst on grain |
| Marshal | `factory__t6__h3_gunslinger/animation_proof_marshal_cluster_ramp/grain_strategy_comparison/index.html` | `hue_shift_shell` | `cluster_ramp` mid-pack |
| Aurora Ram | `bulwark__t2__h3_mountain_ram/animation_proof_aurora_cluster_ramp/grain_strategy_comparison/index.html` | `linked_consensus` | `cluster_ramp` worst (grainRatio ~2.6) |
| Plated Armadillo | `factory__t3__h3_armadillo/animation_proof/grain_strategy_comparison/index.html` | `cluster_ramp` | Still best visible-remap tradeoff here |

Evidence: generated strategy comparison only. Ranking prefers visible remap (`meanOpaqueRgbL1 >= 20`) then lower grain.
