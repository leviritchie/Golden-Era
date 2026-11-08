# Town full-3D: mirrored-back closure of terrain masses (experiment, 2026-09-29)

**Proof tier:** generated artifact / offline moderngl render only. Candidate `fa_v8_mirror` (Factory, seeded from
`fa_v5_ldi`) is staged. There is no catalog, no bundle, no Unity build and no install.

## Idea

This is the user's trick from an earlier depth experiment: assume the hidden half of a depth-mapped mass mirrors its
visible half. For example, a seen hemisphere becomes a full sphere, and its back shows the front's texture mirrored.
It is meant for landscape masses that are not regenerated with Meshy, such as ridges, ledges and spurs.

## Method (`tools/homm3_town_scene_meshes/town_full3d_mirror.py`)

The pass runs on top of the layered-depth fill (`docs/homm3_town_layered_depth_backfill.md`). That fill cuts the
curtains and continues the far ground under each ridge. This pass adds a `Mesh_Back_<piece>_Mirror` sheet between the
two: the ridge's back half.

1. **Crest depth.** The crests are the near ends of the LDI's cut triangles. Each rest ray takes the nearest crest's
   depth, smoothed in inverse depth (24 px).
2. **Mirrored copy.** Every front vertex of the ridge within the LDI band gets a copy at `2*crest - z` on its own rest
   ray. It never goes past the continued far ground, and it always stays at least 2% behind its front copy. The copy
   keeps its screen position and UV, so the back face shows the ridge's own texels mirrored about the crest, with no
   texture synthesis. Its texture is a verbatim copy of the piece's albedo.
3. **Dropped triangles.** Triangles that lie wholly on the far ground, triangles over the validator's 1.25
   depth-ratio cap (none on Factory), and the curtain cells themselves are dropped.
4. **Lighting.** The normal is the front vertex's own. v1 reflected the normal across the rest ray's plane
   (`--normals reflect`). That relit already-shaded texels a second time and drew a dark saw-tooth rim along every
   crest at the sweeps.

## Factory result

On `Mesh_Terrain` the pass produced 26 318 mirror triangles, with a median back depth 5.4% behind the front (p95 24%).
The two near pieces have no cuts at the reachable poses, so they get no mirror.

| Measure | Pose | fa_v4 (installed) | fa_v5_ldi | fa_v8_mirror |
|---|---|---|---|---|
| Terrain streak px | sweep_left | 73 077 | 39 229 | 36 791 |
| Terrain streak px | sweep_right | 133 893 | 64 028 | 59 319 |
| Terrain streak px | sweep_high | 117 524 | 51 032 | 47 124 |
| Revealed + streak px | sweep_left | 38 693 | 27 272 | 24 898 |
| Revealed + streak px | sweep_right | 75 337 | 46 453 | 41 879 |
| Revealed + streak px | sweep_high | 65 656 | 36 562 | 32 821 |
| Empty px | any reachable pose | 0 | 0 | 0 |

- **Rest frame:** identical to `fa_v5_ldi` (0 px differ). Against `fa_v4`, the 2 391 px over 8 levels are the LDI's
  own 1-px silhouette lines, and this pass adds none.
- **Sheets:**
  - `artifacts/claude_takeover_20260927/review/factory_mirror_vs_ldi.png`
  - `artifacts/claude_takeover_20260927/review/factory_mirror_vs_installed.png`

**Visual verdict:** a modest, real gain over the layered fill alone. Behind the mid ledges (sweep_high, sweep_right
zooms), pale quilted far-ground smear becomes mirrored rock strata, which reads as the back of the ledge. The other
change is 6-10% fewer streak px. The large remaining stripes in those zooms are building slabs (old depth buildings),
which the Meshy T2 buildings replace. Terrain curtains that face the sky (arches, skyline ridges) are unchanged.
