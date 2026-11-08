# Town full-3D: LLM-reviewed stretch snip (cheap experiment)

**Proof tier:** generated artifact / offline moderngl render only. Candidate `fa_v6_snip` (Factory, seeded from `fa_v4`)
has its staged bins rewritten. No catalog, bundle, Unity build or install was made. The `<piece>_SnipFade` pieces are
new `rows.json` rows. Whether the stage/bundle path and the Hex/Lit rebind accept them is **unproven**.

## Method (`tools/homm3_town_scene_meshes/town_full3d_snip.py`)

A reviewer looks at renders of the reachable camera extremes (`sweep_left` / `sweep_right` / `sweep_high`) and marks
the regions that read badly. The reviewer can be an LLM that views images, or a person. Each mark becomes a rule in a
selection file (`snip_selections/<faction>.json`, schema `town_full3d_snip.v1`). A rule records:

- the pose and a region (a pose-pixel box or `all`);
- the groups it applies to;
- the filters, as below;
- the action;
- the reviewer's note.

`select` id-renders `(piece, triangle)` per pixel at the rule's pose. It takes the visible triangles in the region that
pass all the filters:

- **`minAniso`:** the texel footprint's s1/s2 at the pose. A face whose three vertices share one texel counts as
  infinite.
- **`minRestRatio`:** the rest forward-depth ratio.
- **`maxRestCos`:** how close the face is to edge-on at rest.
- **`maxRestPx`:** the number of pixels the face owns in the rest frame.

The pass then writes the triangle ids of the seed's original bins into `resolved`. Rounds run in order, each on the
state the earlier rounds left, so a removal that reveals the next wall layer is caught by the next round.

`apply` rewrites the touched bins from the originals kept in `work/snip/orig/`. It never compounds, and a re-apply is
bit-identical. The actions are:

- **remove:** drop the triangles.
- **fade:** move the triangles into `<piece>_SnipFade`, which uses the piece's albedo blurred by 12 texels. The
  piece's own texture is never touched.
- **clamp:** move duplicated vertices along their rest rays to at most 1.05 x the nearest depth.

`render --round N` writes the review images to `work/snip/round_N/`: the plain render, a 100-px grid copy, and a
streak overlay.

Measured choices on Factory:

- **Terrain curtains:**
  - **remove / clamp:** these open sky holes in the canyon floor. Clamp measured 23k-46k terrain->sky px, plus 78-3027
    empty px. Rejected.
  - **fade:** turns hard streaks into soft haze. Kept.
- **Building side walls (`tbfaholy` lattice tower, domed building, mid-right factory):**
  - **fade:** keeps the stripes, because each face shows one texel.
  - **clamp:** still a slab.
  - **Remove every face within `maxRestCos` 0.15 of edge-on, over 3 rounds:** leaves the building's own front faces.
    This is the only one that removed the slab.
- **Rest identity:** fading the slivers that own rest pixels costs softened 1-px rim lines. The count of rest px
  more than 8 levels off moves with `maxRestPx`:

  | `maxRestPx` | rest px > 8 levels |
  |---|---|
  | 0 | 283 |
  | 1 | 447 |
  | 4 | 10 266 |
  | 16 | 17 313 |

  At 16 the lines are visible at 2x. 1 was kept. A terrain sliver's UV footprint is exactly its rest-visible texels,
  so fading a sliver can never be rest-exact.

## Factory result (fa_v4 -> fa_v6_snip)

Summary image: `artifacts/claude_takeover_20260927/review/factory_stretch_snip.png`. It uses the LDI v2 format, plus
four building zoom rows. Selection: 14 514 triangles, 10 986 removed and 3 528 faded, in 24 pieces.

- **Rest frame:** mean 0.0048 levels. 472 px differ by more than 8 levels (LDI v2: 2 391). All of them are 1-px
  silhouette lines. There are no empty px at any pose.
- **Building bridging tris (>1.25/>1.5):** 1853/75 -> 128/11. The terrain bridging tris are unchanged (2814/1208/149):
  the terrain curtains are faded, not removed.

Building streak px:

| pose | fa_v4 | fa_v6_snip |
|---|---|---|
| sweep_left | 49 692 | 27 455 |
| sweep_right | 48 628 | 32 717 |
| sweep_high | 29 600 | 16 874 |

Building revealed+streak px:

| pose | fa_v4 | fa_v6_snip |
|---|---|---|
| sweep_right | 25 584 | 10 193 |
| sweep_high | 17 942 | 6 459 |
| sweep_left | 9 982 | 9 548 |

**Terrain streak metric:** it goes up slightly (sweep_right 133 893 -> 141 067). The metric measures texel
stretch, and a faded curtain is still stretched. The blur is invisible to it. The removed walls also reveal terrain.

**Sky:** anyToSky rises to 2 510 / 695 / 45 px at sweep_left / right / high, where the lattice and domed building now
show sky through them.

**Visual verdict:** clearly better on buildings. The opaque striped slabs of the lattice tower and the domed building
are gone at all three sweeps. The tower now reads as a sheared lattice, with some thin dark wisps. The terrain is
mildly better: the fully edge-on curtains are hazy instead of streaky. The rim streaks that are owned by rest-visible
slivers remain. The magnified blurry foreground sand is untouched.

Costs:
- The removed buildings lose side-wall silhouette: the relief becomes thinner/card-like at the sweeps.
- A few hundred to 2.5k px of sky show through.
- No popping is expected, because the geometry is static and the snipped faces are edge-on at rest. This is unproven
  in motion.

## Rollout to the other towns

The tool is faction-agnostic: it takes `--faction` plus `TOWN_FULL3D_CANDIDATE`. Per town:

- seed a candidate;
- render round 0;
- have an LLM review the 3 sweep images and write the rules;
- run 2-3 select/render/look rounds;
- run the review.

Rendering takes about 10 s and each select about 1-2 min. The main cost is the review: about 30-60 min of reviewer
time per town. The terrain curtain-fade rule is generic and can be copied as-is. The building regions are
per-town marks.

Still open before any install:
- a bundle build proving `_SnipFade` pieces;
- catalog / validator acceptance;
- an in-game look.
