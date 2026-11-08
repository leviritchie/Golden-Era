# Town full-3D: conditioning the img2img background depth for the one-sheet terrain (experiment rx_cond)

Status (2026-09-30): generated-artifact proof only (offline raster metrics, offline previews, Unity editor renders for
two finalists). Nothing installed; no runtime or in-game proof.

## Question

The 2026-09-30 image-to-image background depth (`depth/img2img_bg.npy`, `town_full3d_bg_depth.py`) is sharper than
Depth Anything (`depth/da_large.npy`). Swapped in like-for-like (`bgd_v1` = `props_v1` + the new depth) streaking rises
at every sweep in every town, because the terrain is one continuous screen-space sheet and every real depth step is
stretched into a curtain. Can the one sheet be kept, using the new map, by conditioning the depth that drives it?

## Method (`tools/homm3_town_scene_meshes/town_full3d_depth_cond.py`)

Opt-in per candidate: the pin `<candidate>/work/background_depth.json` gains a `conditioning` object; a pin without it
(and every unpinned candidate) is byte-identical. Hooks: `stronghold_full3d_terrain.background_disparity` (raw map ops),
`rect_depth` (calibrated inverse-depth ops), `stronghold_full3d_ground.frame_depth` (whole-frame ops before the seam
smooth). The conditioning is recorded in `stage_report.terrain.backgroundDepth.conditioning`.

Ops that shipped in the finalists:

- `oldlow {sigma}` (inverse depth): `inv * G(old) / G(inv)`, a NaN-aware Gaussian of sigma px; the old map's coarse
  layering with the new map's detail (the "hybrid" idea, done after calibration).
- `monotone {ratioMax}` (inverse depth): grounded-surface prior. Seen from above the ground, nothing is nearer than
  every surface below it in its own column unless it overhangs. Violations up to `ratioMax` in inverse depth are
  pushed back to the running minimum below (a floating relief pop); larger ones are real overhangs and kept.
- `envelope {slope}` (frame): step-limiting compression, the Lipschitz max envelope
  `inv'(p) = max_q inv(q) - g |p - q|_1`, `g = slope x` the floor plane's own vertical inverse-depth gradient per px.
  The occluder is never moved; the far side next to it is pulled forward into a ramp, so no step is steeper than `g`.
  Every vertex stays on its own rest ray, so the rest frame is unchanged by construction (except where layers placed
  on the old surface, such as props, now meet a different terrain depth).

Also tried, not shipped: `guided` (guided filter, painting guide), `jbf` (joint bilateral), `snap` (colour-guided
edge alignment), `hybrid` (raw-disparity hybrid), the envelope on the rect only. Per-triangle texture fill was not
built: `docs/homm3_town_curtain_reuv.md` already measured that lane negative, and after the envelope no terrain
triangle passes the streak threshold.

Iteration: `artifacts/homm3_rx_cond/harness.py` rebuilds the terrain sheet in memory for a spec and rasterises it with
the seed's other staged layers (no staging, private raymarch cache). It reproduces `bgd_v1`'s per-bin streak exactly.
Finalists are staged for real (`artifacts/homm3_rx_cond/stage_cand.sh`: copy of `bgd_v1`,
`stage --parts terrain,sky,periphery,nearfield`, `town_t2_streak_map.py`, `stronghold_full3d_scene.py cull`).

## Results (staged candidates, `town_t2_streak_map.py` streak px, all bins)

| town | candidate | sweep_left | sweep_right | sweep_high |
|---|---|---|---|---|
| rampart | props_v1 (old depth) | 2035 | 1906 | 2112 |
| rampart | bgd_v1 (new depth) | 67208 | 14906 | 16064 |
| rampart | **rx_cond_mono_env** | 3057 | 1932 | 2235 |
| necropolis | props_v1 | 5680 | 14948 | 12925 |
| necropolis | bgd_v1 | 23323 | 37900 | 18842 |
| necropolis | rx_cond_mono_env (deleted) | 5335 | 4919 | 3642 |
| necropolis | **rx_cond_oldlow_mono_env** | 5274 | 2818 | 1031 |
| dungeon | props_v1 | 36723 | 39069 | 24852 |
| dungeon | bgd_v1 | 89567 | 125208 | 80223 |
| dungeon | **rx_cond_mono_env** | 1051 | 1356 | 1414 |
| tower | props_v1 | 14335 | 20920 | 10720 |
| tower | bgd_v1 | 27312 | 60349 | 33498 |
| tower | **rx_cond_oldlow_mono_env** | 836 | 1788 | 996 |

`Mesh_Terrain` streak is 0 to a few dozen px at every sweep in every finalist; what remains is building bodies
(identical to the seeds) and the periphery rings (`Mesh_OuterL2/R2/C2`, rebuilt from the terrain). Rampart's
`Mesh_OuterL2` rises at the default and cursor_left poses (582 -> 1442 / 531 -> 1892 px); it is the left periphery,
not the curtain.

See-through gate (`stronghold_full3d_scene.py cull`): every finalist passes (no pose worse than baseline). Undrawn px
(no lit geometry: sky or hole) against bgd_v1 at sweep_left / right / high: Rampart +3.7k / +13.0k / +4.3k, all of it sky
along the skyline where the curtain used to hang (inspected per pixel); Tower and Necropolis fall back to props_v1 levels;
Dungeon (a cavern: undrawn is a hole there) +1.8k / 0 / -233. No hole below a terrain silhouette was found.

### Tower calibration / ordering fault (reported separately)

On Tower the new map's floor calibration puts the cliffs and mountains as near as the houses, so at rest the terrain
covers the castle, library and temples. Monotone ordering does not fix it (the mountains are not floating, they are
mis-scaled). `oldlow` (sigma 40) restores the old map's coarse layering: building px visible at rest (offline raster)
props_v1-layout 384k, bgd_v1 187k, oldlow 378k; the rest preview matches props_v1 (castle, library, temples visible).
`oldlow` also helps Necropolis (building px at rest 431k -> 472k = props level). It is harmful on Dungeon, where the
old map itself opens holes at the sweeps (undrawn 45k -> 95k at sweep_left), so it is chosen per town.

## Visual verdict (offline previews; Unity renders under each finalist's `renders/`)

Rampart: the right-hand curtain beside the cliff is gone (sky shows above the meadow, as on props_v1), and the meadow
behind the big house no longer smears. The rock ledge right of the house still reads somewhat stretched (mild, below
the metric's threshold). Tower: the rest frame is back to props_v1's layout and the sweep curtains are gone.

Unity editor renders (unitylock, full3d_full + pan sweeps + orbits) exist for Rampart `rx_cond_mono_env` and Tower
`rx_cond_oldlow_mono_env`. Animation spec: the rx bundles carry group A's fixed build_spec (new animation tuning); the
props_v1 / bgd_v1 renders compared against were made before that fix (old tuning). Only static terrain is compared.

- Rampart: the big right-hand curtain at sweep_left is mostly gone, but a smaller dark grey smear stays just right of
  the cliff; sweep_high is clean against bgd_v1; the rock ledge right of the house is mildly stretched. Close to
  props_v1 overall, not identical.
- Tower: full3d_full matches props_v1 (castle, library and temples visible; bgd_v1 hides them behind the mountains).
  At the sweeps the mountain faces still show some smearing near the castle spires, about as much as props_v1 and far
  less than bgd_v1.
- Dungeon: the pre-existing frame-corner hole of bgd_v1 (about 45k px at sweep_left) shifts slightly; a small negative,
  not a new hole.

## Costs and open points

- The envelope ramps far ground into the occluder: at the sweeps far ground near a silhouette moves a little with it.
- Props, buildings and FX keep their props_v1 placement; where the terrain moved (monotone pushes floating relief back)
  their contact with the ground can change.
- Per-town recipe (oldlow or not) is a choice, not a rule; Castle, Inferno and the other towns are untested.
- **The recipe on da_large instead of img2img** (tower `rx_cond_dalarge_dfix`, 2026-10-01). `oldlow` is the identity
  there, because its "old" map is da_large itself: `inv * G(inv) / G(inv)`. So it is dropped, and
  `stronghold_full3d_terrain.background_disparity` refuses it in a `da_large` pin. `monotone` (ratioMax 1.6) and
  `envelope` (slope 3) apply as pinned: `{"source": "da_large", "conditioning": {...}}` in
  `work/background_depth.json`. The terrain/sky stage needs `TOWN_FULL3D_EXTSRC` =
  `.../tower/tex_seam/extsrc_blend0`, the folder whose sky-only control stage matches exactly. Building depth and
  results are in `docs/homm3_town_building_contact_depth.md`.
