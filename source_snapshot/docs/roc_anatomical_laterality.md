# Profile Anatomical Laterality

The anatomy-box scorer must not infer biological left/right from image-space X. A profile animation can put the biological left leg on the right side of the image, and the two legs can exchange screen positions during a walk. Matching boxes by X therefore creates false positives even when the detector is otherwise correct.

The current implementation uses the profile depth ordering instead:

- The target sprite uses its cached monocular depth map, with near surfaces encoded as bright values.
- The Blender candidate writes the same near-bright convention from its rendered depth pass.
- For two detections of the same lateral part, the nearer detection is assigned `near_side` and the farther detection the opposite biological side. This assignment survives a 2D crossing.
- For a lone detection, the scanner only assigns a side when its depth is outside the configurable subject-reference margin. Ambiguous detections remain unsided rather than being forced into a false match.
- The default Roc profile camera is `bird_right`, so `near_side="R"`. Units with a different authored profile contract must set `anatomical_laterality_near_side` explicitly.

Relevant configuration fields are `anatomical_laterality_enabled`, `anatomical_laterality_source` (`"depth"` or `"none"`), `anatomical_laterality_near_side`, and `anatomical_laterality_depth_margin`. `anatomical_laterality_center_margin_frac` remains only as a compatibility field for older notebook cells; it is not used to split boxes by X.

This is source-level and focused-test validated. A full GPU detector run over the current animation is still required before treating the resulting anatomy alignment as user-visible proof.
