# Town full-3D: re-UV the stretched curtains (texture fix instead of geometry) - measured negative

**Proof tier:** generated artifact / offline moderngl render only. Candidate `fa_v6_reuv` (Factory, seeded from the
installed `fa_v4`) is staged but **not bundled and not installed**. There is no Unity-editor render and no in-game check.
**Verdict: not recommended.** It trims the streak metric, but it adds visible new artefacts at the sweep poses and it
changes the rest frame.

## Question

The rubber-sheet bands at the reachable camera extremes (vanilla `sweep_left/right/high`) read badly because one
texel column is smeared across a stretched triangle. Can the texture coordinates be fixed without touching geometry
(the cheap alternative to `docs/homm3_town_layered_depth_backfill.md`)?

## Method (`tools/homm3_town_scene_meshes/town_full3d_reuv.py`)

**`apply`** works on the terrain, whose UVs are an affine map of the rest frame. The tool fails closed otherwise.
1. **Curtains.** The curtain triangles are those with rest depth ratio > 1.25 (`--rule ratio`). With
   `--rule ratio+smear`, the LDI's pose-smear step triangles are added as well.
2. **Unweld.** The curtains are unwelded, so they get their own vertex copies. Triangles shown at rest keep their UVs.
3. **Band length.** Each copied vertex gets a band coordinate `s`: its Dijkstra 3D distance over the curtain from an
   anchor, converted to rest px at that depth's painted density (`--density`). The anchor is the far foot for
   `--side far`, or the near lip for `--side near`.
4. **New UV.** The new UV is the rest texel at `pixel + s * dir`. `dir` is the smoothed rest log-depth gradient,
   pointing towards the sampled side and Laplacian-smoothed along the curtain.
5. **Staying on the sampled side.** The band is folded back (triangle wave, one period per curtain component) where
   it would leave that side's depth window (x1.03 .. x1.5). The anchor keeps its own UV, which makes that edge
   seamless.
6. **Textures** are never modified.

**`apply-buildings --layers <k>|all`** re-UVs a building piece's triangles whose UV is degenerate (3D->texel
anisotropy > 20, the extruded silhouette walls):
- The same unfolding runs in texture space, walked inward from the painted front's silhouette at the front's own texel
  density.
- The fold stays inside the front's texture coverage.

**Commands:**

    TOWN_FULL3D_CANDIDATE=fa_v6_reuv python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py --faction factory candidate-init --seed-from fa_v4
    TOWN_FULL3D_CANDIDATE=fa_v6_reuv python tools/homm3_town_scene_meshes/town_full3d_reuv.py --faction factory apply --rule ratio --side near
    TOWN_FULL3D_CANDIDATE=fa_v6_reuv python tools/homm3_town_scene_meshes/town_full3d_reuv.py --faction factory apply-buildings --layers tbfaholy
    python tools/homm3_town_scene_meshes/town_full3d_ldi_review.py --faction factory --before fa_v4 --after fa_v6_reuv \
        --out artifacts/homm3_factory_full3d/candidates/fa_v6_reuv/reuv_review \
        --summary artifacts/claude_takeover_20260927/review/factory_stretch_reuv.png \
        --label "curtain + tbfaholy wall re-UV (texture coords only, geometry unchanged)" --summary-poses sweep_left,sweep_right,sweep_high

The review tool gained `--label` and `--summary-poses`. Its defaults reproduce the LDI summary.

## Results (Factory, fa_v4 -> variant; reachable sweep poses)

The terrain streak columns are px of terrain with UV-footprint anisotropy > 6. **This metric falls partly by
construction**, because the method changes UV density.

| variant | rest px > 8 levels | terrain streak (sweep L / R / high) | terrain revealed+streak (L / R / high) |
|---|---|---|---|
| fa_v4 | 0 | 73 077 / 133 893 / 117 524 | 38 693 / 75 337 / 65 656 |
| ratio + smear, far | 62 404 | - | 33 749 / 60 142 / 52 005 |
| ratio, far (smoothed) | 5 862 | 70 599 / 120 065 / 99 197 | 37 111 / 68 548 / 56 866 |
| **ratio, near (= fa_v6_reuv, + tbfaholy walls)** | 8 754 (terrain 6 876, buildings 1 816) | 64 168 / 102 996 / 81 784 | 33 360 / 58 803 / 46 789 |
| ratio, near, density 0.4 | 6 929 | 63 202 / 106 425 / 84 180 | 32 353 / 59 803 / 46 810 |

**Other measurements:**
- **Buildings.** tbfaholy walls re-UV'd: 7 594 degenerate triangles. Building revealed+streak at the sweeps goes
  9 982 / 25 584 / 17 942 -> 9 408 / 25 913 / 18 127, which is no change.
- **Empty and sky-hole pixels** stay at 0 at every pose, because the geometry is unchanged.
- **Controls.** The cursor poses (pure rotations) gain about 2.5k terrain revealed+streak px. The re-UV'd cells are
  now minified bands at every pose, so the metric flags them.

## Why it does not work (visual verdict)

- **The curtains are not invisible at rest.** The terrain is a screen-uniform grid, and every triangle, edge-on or
  not, owns about 4.5 px² of the rest frame. The 2 814 ratio curtains own about 12.5k rest px. The smear triangles own
  about 91k rest px, so `ratio+smear` changes 3% of the frame and is ruled out.
- **Visible rest change even for ratio only.** The painted anti-aliased halo along silhouettes (for example the pale
  sky rim of the Factory arch) becomes a hard, stair-stepped dark rim, 1-3 px wide. The summary's red crop shows it.
  That is a recolouring of visible painting.
- **At the sweeps the texture reads as a collage, not a cliff face.**
  - *Far side:* the band samples distant haze and sky-blue texels, which appear as blue-grey patches on the horizon
    curtains.
  - *Near side:* the band samples the ridge's dark shaded face, which gives crisp dark jagged patches on the horizon,
    floating rock chips and mirrored strata where the band folds.
  - *Grid outline:* the grid's staircase outline, which the soft smear hid, is now drawn with contrasting texture.
  - *Where it works:* only the large near-field canyon walls (sweep_high right) plausibly read as a rock face.
  - *Overall:* the soft smear is less conspicuous than the new artefacts.
- **The elevator tower (tbfaholy) is a geometry problem.** Its rubber slab is relief filling the gaps of the lattice.
  Re-texturing the walls leaves a striped slab, so idea 3 does not help it.
- **Vertex-colour or alpha fade (idea 2) is not available.** The staged `.bytes` format carries no colour channel, and
  `Homm3TownLabHexLit.shader` reads no vertex colour. It would need a format, importer and shader change, which is
  outside this lane's allowed pipeline, so it was not attempted.

## Rollout cost (12 towns), if it were wanted

The tool is faction-agnostic and CPU/moderngl only: about 1 min apply plus about 15 s review per town. Each town then
needs a bundle build (unitylock, >= 20 GB free on V:). That is roughly 1-2 h of machine time for 12 towns, plus a
per-town visual review. It is **not recommended**, because the result is not better than fa_v4 to the eye.
