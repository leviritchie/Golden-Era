# Town bench: fast edit / test / examine loop for the full-3D town scenes

`tools/homm3_town_scene_meshes/town_bench/` lets an agent find a town scene's defects, fix one, and prove the fix,
in seconds or minutes instead of the old cycle of building, bundling and discovering the next problem. It is a
workbench on top of the zero-streak recipe (`town_full3d_recipe.py`), not a second build path. A bench fix is an
op file. The recipe applies op files as its step 5b ("edits"), so `build` reproduces the fix from the seed, and the
same certificate (`town_full3d_zero_streak` / `town_gpu_kernels.CertifyEngine`) judges it.

## Quick start: from "here is a town" to "cluster N fixed and checked"

```sh
cd tools/homm3_town_scene_meshes/town_bench
# 1. one GPU session per candidate (≈5 s load; serves every agent over http://127.0.0.1:8765)
python town_bench.py serve fortress zs_v2 &
# 2. the defect atlas: every reachable pose x every build state (cached; --tier quick = start/full/anim)
python town_bench.py sweep --tier final
#    -> V:/olden_port_work/town_bench/atlas/fortress/zs_v2/{atlas.json, contact_sheet.png, cNNN_<class>.png}
# 3. look at a cluster's worst pose
python town_bench.py render defects --pose free_catmullRom_lookAt_left --state full
python town_bench.py render game --pose free_catmullRom_lookAt_left --frame game
python town_bench.py pick 434 320 --pose free_catmullRom_lookAt_left       # piece, face, texel, layer, classes
# 4. fix it with an op (applied hot; only the touched buffers are re-uploaded)
python town_bench.py edit new for-c1-drop --cluster 1 --kind drop --note "behind-streak sliver on dwelling body"
# 5. re-check: incremental sweep (only the (state, pose) pairs the edit can change re-run), then diff
python town_bench.py sweep --tier final --out V:/olden_port_work/town_bench/atlas/fortress/zs_v2_after
python town_bench.py diff  .../zs_v2/atlas.json .../zs_v2_after/atlas.json      # gone / kept / new clusters
python town_bench.py edit undo                     # if it made things worse
# 6. bake: a new candidate + its recipe (no bundle, no install)
python town_bench.py bake zs_v2b1
```

Install still goes through the coordinator as a packet. Bundling stays the existing Unity queue step
(`stronghold_full3d_scene.py bundle`).

## Pieces

| Module | What it does |
|---|---|
| `bench_scene.py` | Loads the candidate: the recipe Stage of every build state's prefabs, the 31 build states from the tree, `final`'s 157 poses (`reachable_cams_full`, loop 36), the runtime framing (catalog `referenceCamera.framing`: zoom, aim rotation, panScale re-run through the pan code) and the Hex/Lit lights. |
| `bench_gl.py` | moderngl views. `game`: Hex/Lit diffuse (city trilight, catalog key and fill, Cull Back), the sky panorama and drift bins unlit, Fx meshes tinted and translucent, particle discs. `ids` / `faces`: piece and face ids. |
| `bench_defects.py` | Per-pose analysis. It is the certificate's own engine (a `CertifyEngine` subclass that only remembers its raster and streak mask), so a bench row equals the certificate row. It adds the bench's own extra classes and connected components. |
| `bench_sweep.py` | Worker processes (one engine per state), the cache, the exact incremental planner, clustering and the atlas. |
| `bench_edits.py` | Op files, merge with conflict refusal, apply (shared with the recipe), and undo snapshots. |
| `bench_bake.py` | Copy-on-write candidate, recipe step 5b, catalog, gate, `validate_town_scene3d_contract --catalog`. |
| `bench_issues.py` | Issue registry `issues/<faction>.json`: a regression set every sweep re-checks. |
| `bench_fidelity.py` | Game view vs a Unity editor render through `tools/unity_queue`. |
| `town_bench.py` | CLI, HTTP server, client. |

### Defect classes

The certificate's classes are the ones `final` gates:
- `behind`: visible behind-streak components.
- `unseen`: unseen-face stretch.
- `ground`: ground holes after the restSky refinement.

The extra classes are reported, not gated:
- `skygap`: nothing drawn and no sky either, so the clear colour shows.
- `periphery`: a `Mesh_Outer*` px whose surface the rest camera sees inside the painted rect.
- `sliver`: a needle face, longest projected edge 24 px or more and height 0.75 px or less.
- `stretch`: streaked, not revealed, on a face the rest frame does show.
- `floating`: environment pieces failing `town_full3d_ground_contact.contact_gate`.

The `heat` view shows texture stretch, in screen px per texel.

### Clusters

Components are tokenized:
- face classes by (bin, local face);
- `ground` by 2 m floor cells;
- `skygap` by 1° sky cells.

Components that share a token in the same class join one cluster, across poses and states. A cluster's owners are
its bins by px; for holes, the owners are the bins on the hole's 1-px ring. Severity = class weight × worst px ×
log2(1 + poses).

`atlas.json` lists, per cluster:
- class, severity, poses and states, top pieces;
- worst (state, pose, px, bbox), and a thumbnail;
- every token, in `tokens.npz`, which `edit new --cluster` turns into faces.

It also holds:
- `gate`: the per-state values the recipe gate reads (`maxVisibleBehindPx`, `maxUnseenFacePx`,
  `groundHoleGrowthPx`);
- the issue results.

### Incremental sweeps are exact

The cache keeps, per (state, pose): the result, the bins it drew, and its rest footprint, meaning the rest-frame
cells its revealed / ground / periphery lookups read. After an edit, the planner works out the changed triangles
(added and removed, compared as float32 world vertices) and their rest-frame region. A pose re-runs if any of these
holds:
- it drew a changed bin;
- an added triangle projects into its frame;
- its footprint meets the region;
- it drew a bin whose rest-projected box meets the region, so a drawn face's rest px count could change.

For every other pose, the raster, every rest lookup and every rest count are unchanged, so the cached result is
exact. `test_town_bench.py` re-analyzes the kept poses after a real edit and compares the results.

### Ops

Op files live in `edits/<faction>/<id>.json` (schema `town_bench_edit.v1`; see the `bench_edits.py` docstring). Ops:
- `drop`, `card`, `planar`: the recipe's own repair rules, on named faces pinned by `facesSha`;
- `transform`: move, rotate or scale a piece, about its centroid;
- `seat`: the anchor rule's `piece_scale`;
- `hide`: per state. It is a bench what-if; bake accepts it only when it covers every state that builds the bin;
- `backstop`: a quad, uv from the bin's rest px → uv chart map. It is wound like the bin's own faces: the `game` view
  and Unity cull back faces but the ids view does not, so a quad wound the wrong way picks fine yet never draws;
- `reray`: scale vertex groups' distance from the rest camera (`groups [[k, [verts]], ..]`, pinned by `vertsSha`).
  Each vertex slides along its own rest ray, so the rest frame keeps every px. This is the tool for re-seating depth
  (for example a Meshy building's residual onto its body) without touching the painting view;
- `retexture`: copy, or `quilt_fill`.
- `twoside`: give named faces (pinned by `facesSha`) a back copy: their own vertices, flipped winding and normals,
  same uv. Use it for faces a reachable pose sees from behind, which the `game` view and Unity cull into clear-colour
  holes while the ids view still picks them.
  `"normals": "keep"` keeps the copy's normals unflipped. Use it for painted sheets and lighting-only sheets
  (`Mesh_Backstop`, decals): there a flipped copy lights from behind and draws as a black chip.

Faces are picked with `--cluster N`, or with `--rect x0,y0,x1,y1 --pose P` (the ids view at that pose), optionally
filtered with `--bins`.

## Measured (Fortress zs_v2, 2026-10-02, GPU shared with the Conflux lane)

Fortress zs_v2 has 138 bins, 31 build states and 157 poses, so a full sweep is 4867 analyses.

| Step | Time | Memory | Target |
|---|---|---|---|
| server load (`serve`) | 5.0 s (scene 2.2 + GL 2.8) | about 3 to 5.7 GB private RAM (5.7 GB once analyzers are cached), about 0.4 GB VRAM | |
| `render game` | 0.01 s on the GPU (+0.15 s PNG write; about 0.6 s CLI round trip) | | under 1 s: met |
| `render ids` / `render defects` | 0.13 s / 0.36 s warm (1.7 s cold, while it builds the state engine) | | under 1 s: met |
| `pick` | interactive (one ids render + ray/triangle) | | |
| full sweep, `--tier final --full` | **676 s**, 2 workers (7.2 analyses/s), + 16 s ground contact on the first run (then cached) | 3.4 to 4.4 GB private RAM per worker | about 3 min: **missed** |
| incremental sweep after one op | **80 s**, 1 worker (314 of 4867 analyses re-run; the rest read from cache) | one worker | 30 s or less: **missed** |
| fully cached re-sweep | 0.06 s | | |
| apply an op (hot, incl. GPU re-upload) | 0.013 s apply, 0.05 s total | | |
| bake (copy-on-write + 5b + catalog + recipe gate + scene3d contract) | 185 s (copy about 4 s, edits 0.3 s, catalog 2.7 s, gate 148 s, contract 29 s) | the recipe gate's own footprint | |
| `town_full3d_recipe.py verify` on the bake | 10 s | | |
| `test_town_bench.py --quick` | 52 s, 0 failed | torch max 791 MB | |
| `validate_town_bench_contract.py` (FullValidation) | 0.3 s | under 50 MB, no GPU | |

Why the sweep targets were missed:
- The kernels are the certificate's own. Each analysis costs 0.17 to 0.24 s of GPU time, and that is the floor
  unless the certificate itself gets faster.
- Throughput scales with workers, but each worker holds the whole scene plus one state engine, about 4 GB of RAM.
  With the Conflux lane taking priority, this PC fits two.
- About 3 minutes for a full sweep needs about 6 workers, so per-worker RAM has to come down first. Two ways: share
  the scene arrays read-only between workers (shared memory), or run several state engines in one process.
- The incremental re-run set is already small (6% of analyses). Its time is mostly the per-state engine builds
  (about 4 s each) plus the re-run poses. With 2 workers it would be about 40 s.
- In the meantime, iterate with `--tier quick` (start / full / anim, 471 analyses, about 1 min on 2 workers) or
  with `--poses`. Run `final` once before a bake.

Bundling was not run: the brief is "do not install", and a bundle job goes through the Unity queue. Recent
`town_full3d` queue jobs took 99 to 161 s of wall time, so bundling would be roughly half of bake → bundle. The
copy-on-write candidate keeps the base's Unity `Library/` (copied, never linked), so a bundle import should
re-import only the touched `.bytes` files. That is an incremental bundle by construction. If it turns out to
re-import everything, the next step is to hardlink `Library/` and copy-on-write only the touched assets' import
results.

### Pilot: Fortress zs_v2 → zs_v2b1

Full sweep:
- 248 clusters: 125 sliver, 73 behind, 25 unseen, 18 stretch, 7 periphery. No ground or skygap clusters, and no
  floating pieces.
- Every state fails `final`: max visible-behind is 745 to 1078 px. In `full`, 112 of 157 poses show visible-behind;
  the check queue's last `final` reported 109 of 157.

Fix:
1. Target: cluster 5, behind, 143 px worst, 70 poses in `full` and `min_tbfrdw_2_2`, all on
   `tbfrdw_2_2/Mesh_Body_resid_tbfrdw_2_2`. It is also the behind part of issues for-4 / for-5.
2. `edit new for-c5-drop --cluster 5 --kind drop` dropped 434 faces.
3. The incremental sweep showed c5 gone but one new cluster: the residual faces that the dropped layer had
   covered (onion peel).
4. `edit new for-c5-peel2 --cluster 8,80 --kind drop` dropped those 141 faces.
5. The second incremental sweep and its diff against the base atlas: **gone [c5], new []**, 247 kept.
   - `full`: poses with visible-behind 112 → 80.
   - `min_tbfrdw_2_2`: 106 → 82.
   - for-4: behind 248 → 108 px.
6. `bake zs_v2b1`: the recipe gate passes in all 31 states. `validate_town_scene3d_contract --catalog` is OK.
   `verify` is OK. The recipe is `recipes/fortress_zs_v2b1.json`, with `edits.base` = `fortress_zs_v2.json`.
   Not bundled, not installed.

### Fidelity (bench `game` vs Unity editor)

Command:
```sh
town_bench.py fidelity --faction fortress --candidate zs_v2 --pose default,sweep_left,sweep_high --state full --submit
```
It submits one `Homm3TownScene3dBundleBuild.RenderStates` job through `tools/unity_queue`: 12 s in Unity, 19 s
wall.

| Pose | Mean abs err (0-255) | p95 | Channel ratio bench/Unity (R, G, B) | Gradient corr |
|---|---|---|---|---|
| default | 8.9 | 48 | 1.03 / 1.00 / 0.93 | 0.85 |
| sweep_left | 8.3 | 47 | 1.03 / 1.01 / 0.96 | 0.83 |
| sweep_high | 8.3 | 50 | 1.05 / 1.03 / 0.98 | 0.86 |

Overall the geometry and the shading match. The gaps, largest first:

1. **`Mesh_Body_resid_*` bins render partly black in the Unity editor; the bench draws them textured.** At
   sweep_high, 8 900 px are black in Unity and textured in the bench, on these bins:
   - tbfrcstl_3: 6.1k px;
   - tbfrdw_2_2: 1.9k px;
   - tbfrmage_3, tbfrdw_4_2, tbfrdock: the rest.

   In the staged files, those faces face the camera, their vertex normals agree with the face normals, and their
   albedo is ordinary. Their import `.meta` files equal the body bins' apart from the guid. So the cause is on the
   Unity side and is still open. It is probably a real in-game defect: check-queue issue for-1, the "sky gap" at
   sweep_high, sits where the tbfrcstl_3 patch is. Until the bench replicates it, defects on residual bins can be
   under-reported in the `game` view; the certificate classes are unaffected.
2. Water: Unity's SSR/specular water is brighter and reflective; the bench draws it diffuse.
3. Fx glows (the hut fire, the crystal sprites) are stronger in the bench: tinted, translucent, unlit, with discs for
   particles.
4. No shadows and no post effects.
5. The editor harness renders native-fov pan poses, so the comparison is made in the certificate frame. The runtime
   framing is the same catalog numbers applied identically to every view.

The `unityClearPx` count (1178 px at sweep_high) is a magenta flower texture, not clear colour: the bench draws the
same colour there.

### Env weld: terrain slits at orbit (`make_env_weld.py`, 2026-10-03)

`python make_env_weld.py <faction> <candidate> --stack <edits> [--allow-appended]` writes `edits/<faction>/env-weld.json`.
It re-seats the back-layer copies of `town_full3d_ldi`'s smear-slope cuts onto `Mesh_Terrain` (`reray`), and drops the
back faces that then coincide with live sheet faces (`drop`). Ridge (ratio) cut vertices are never moved, so ridges stay
layered. The module docstring has the rule, the guards and a measured alternative that was rejected.

`--allow-appended` is off by default. It accepts a sheet that a later repair grew past the LDI record, checking the
recorded prefix ray by ray. Castle, Factory, Fortress, Stronghold, Bulwark and Inferno need it.

Cost: 4 to 6 s with no GL. Generating, applying and rendering 8 views takes 6 to 33 s per town.

Backdrop-hole px (env_gaps `survey2` method, state `full`; the sum over sweep_left, sweep_right and sweep_high):

| Town | Before | After |
|---|---|---|
| Tower | 28.9k | 0.27k |
| Castle | 21.3k | 1.2k |
| Cove | 73.8k | 2.2k |
| Factory | 21.2k | 3.3k |
| Fortress | 23.9k | 2.4k |
| Stronghold | 5.7k | 0.3k |
| Rampart | 1.2k | 0.66k |
| Bulwark | 16.5k | 3.2k |
| Inferno | 13.5k | 17.8k\* |
| Necropolis | 1.5k | 0.02k |
| Dungeon | 26.2k | 2.3k |

\* Inferno's sweep_high count rises because a dark sky region left of the demon starts being classed as enclosed. The
pixels there are unchanged, and the other two sweeps drop.

The rest (`default`) view is unchanged by eye; its mean abs diff is 0.003 to 0.3. Contact sheets are in
`V:/olden_port_work/town_bench/env_weld/<faction>/`.

### Footing: re-seat floating buildings (`make_footing.py`, `make_twoside.py`, 2026-10-15)

`python make_footing.py <faction> <candidate> <layer..> [--relief R] [--margin M] [--rounds N]` writes a `reray`
edit that sets a building back down on the ground it is painted on. The stage's rest-order scale
(`buildingDepth.restOrder`) pulled some buildings toward the eye to win paint order (Cove's tavern ×0.56). The rest
frame cannot tell, but every sweep pose shows the building hovering, swimming against the shore and opening the
ground behind it.

- Per rest-px column of the layer's body (`--col` px), the foot is the lowest body vertex and the ground is the
  nearest `Mesh_Terrain` / `Mesh_TerrainNear_*` ray distance within `--probe` px below it. Both are smoothed across
  columns.
- Every vertex of every piece of the layer slides along its rest ray to `ground + (d - foot) × relief`. The rest frame
  keeps every px; only occlusion order can change.
- An order pass then checks the rest frame in every state that builds a listed layer. A face that wins a px it did
  not win before slides back behind that px's original owner (+ `--margin` m); repeat for `--rounds`. Ownership is by
  bin, not face: Meshy T2 bodies are double-sided, so twin faces swap without a real conflict.

`python make_twoside.py <faction> <candidate> --edits <pre>` renders every state × every pose, culled and not
culled, and writes a `twoside` edit for each face that leaves a clear-colour hole only when culled.

Cove `kk_v2` (layers tavern, hall ×3, pir2, smrk; relief 0.5, margin 0.6, 16 rounds):

| Layer | Shift m (min / median / max) |
|---|---|
| tbcvtave | 33.8 / 36.8 / 50.9 |
| tbcvpir2 | 13.4 / 27.6 / 33.5 |
| tbcvhall / hal2 / hal3 | 5.1 / 10.2 / 22.5; 0.0 / 8.2 / 34.5; 1.7 / 6.3 / 30.7 |
| tbcvsmrk | 8.3 / 8.6 / 9.3 |

- Order conflicts fell from 401k px to 9.4k px over 31 states. The rest view differs by about 10–12.7k scattered
  speck px.
- Culled magenta holes at the sweeps went from 900–2700 px to 0 (most faces were on `Mesh_Backstop`).
- Far floaters (cas3, gmg4, nix2: shifts of up to 250 m) are left out because they cut dark slats near the castle at
  the sweeps. The market (tbcvmark) still smears at loop poses; it floats only 4.6 m, so it has a different cause.

### Footing v2, relief and floor (Cove `kk_v3`, 2026-10-15)

- `make_footing.py ... --field`: one smooth ray-shift field per layer on a `--cell` px grid, instead of one rigid k,
  plus order rounds that pull the field forward wherever another bin would win a rest px. Check the result for
  self-stretch. Where the ground probe below a far building finds far terrain but the painted background right
  behind it is near, the rounds hold the bottom near and push the top back. Cove's cas3 went from 27 m to 229 m deep
  along its rays, and sor1, sor2 and gmg4 by 3–5x. The contract's building-depth streak gate caught it on the
  decals. The rigid mode (default) on those layers gave k ≤ 1.03: they were already seated against what the rest
  frame shows behind them. Leave such layers out of the field run.
- `make_relief.py <faction> <cand> all --after <footing> [--sigma 12] [--relief 0.35] [--layer L=R:foot]`: low-passes
  each building's rest depth along its rays (normalized gaussian in screen space, its own mask), then compresses what
  is left toward the layer's fit plane (or its foot). This removes the Meshy surface noise the painting never had,
  which shreds a building into shards at its own wrong depths at sweeps. Rest-invariant. Hidden parts keep their
  offset behind the new sheet.
  Check the streak gate too: a layer whose rest depth spans far along its rays (Cove's say1, 238 m) gets a tilted
  plane that stretches its decal. `--skip` it.
- `make_floor.py <faction> <cand> --after ..`: folds `Mesh_Backstop` down onto the water plane fitted to the SSR
  water pieces' vertices (Cove: residual median 0.15 m), `--drop` 0.3 m under it. It applies only where a backstop
  vertex's rest ray meets the plane in front of it, and never in front of the rest frame's front-most surface along
  that ray (any state, grey-dilated 7 px, + `--rel` 0.5% + `--margin` 0.5 m). A sweep that opens a terrain gap then
  shows water at the right depth, not a plate 50–100 m behind the lagoon sliding against it. Rest check: 0 px off by
  more than 24 levels. `--flatten` (terrain water onto the plane) changed the rest frame through LDI back-layer
  occlusion for little gain; it is not used. The fold creates new back-facing backstop faces, so run `make_twoside`
  again after it.
- `make_tear.py --pieces` picks the bin prefixes (default `Mesh_Body_,Mesh_Decal_`; environment pieces work too).
- Stack order (Cove `kk_v3`): `footing2-cove` → `relief-cove` → `twoside2-cove` (normals keep) → `floor-cove` →
  `twoside3-cove` (normals keep). Bake by applying them in order with `bench_edits.apply_file` and quantizing the
  touched bins after each file, as the bench Session does. Later files pin `facesSha` on quantized vertices, so
  without that the bake refuses.

## Live preview and fly camera

`python tools/homm3_town_scene_meshes/town_bench/preview.py [--port 8770] [--open]` serves a page with the `game` and
`defects` views side by side. It re-renders whenever the session's edit stack changes, and follows the focus an agent
sets with `preview.py focus --pose P --state S [--yaw D --pitch D --move r,u,f --zoom Z] --note "..."`. In the page:
drag turns, double-click centres on a point, the wheel zooms, WASD moves, Q/E go down/up, shift moves x5 and R resets.
The page renders through the bench server.

Any render or pick takes a fly camera. Send `{"fly": {"base": pose, "frame": "cert"|"game", "yaw", "pitch",
"move": [right, up, fwd] scene-root metres, "zoom"}}`; the server then registers the pose `fly` for `pick`.

## Running parallel fix agents on one town

The building blocks are already in place:
- op files carry `after`;
- `merge` refuses two op files that touch the same bin unless one is an ancestor of the other;
- the sweep cache is keyed by bin hashes, so any process can reuse another's analyses.

Proposed protocol (not yet exercised with live agents):

1. **One coordinator sweep.** The coordinator sweeps the candidate once (`sweep --tier final`) and splits the atlas
   into *lanes by bin ownership*. Every cluster's owning bins go to exactly one lane, and clusters that share a bin
   go to the same lane, using union-find over `pieces`. On Fortress zs_v2 the natural lanes are:
   - `environment/Mesh_Outer*` (periphery and behind);
   - each dwelling's `Mesh_Body_resid_*`;
   - `tbfrcstl_*`;
   - `tbfrhrd2`;
   - `Mesh_Terrain` (stretch).
2. **Its own server per agent.** Each agent runs its own server on its own `--port`, with `TOWN_BENCH_URL` set.
   - A server is about 5 s to load, about 3 GB RAM and about 0.4 GB VRAM.
   - The agent edits only its lane's bins, writes `edits/<faction>/<lane>-<n>.json`, and checks with incremental
     sweeps.
   - Incremental sweeps re-run only the poses that see that lane's bins, and the shared cache keeps every other
     pose. One worker is about 4.5 GB RAM; size workers with `wait_for_memory`.
3. **Merging.** Lanes touch disjoint bins, so their op files merge with no `after` links between lanes.
   - If a lane needs a bin owned by another lane, it hands that cluster to the owner instead of editing it: merge
     would refuse it anyway.
   - The coordinator starts one server with every lane's ops (`serve --edits a,b,c`). It runs one incremental sweep
     (the union of the lanes' re-run sets) and diffs against the base atlas, so a fix that pushed a defect into
     another lane shows up as `new`.
   - Then it runs `bake`. The recipe's `edits.ops` lists every lane's files in merge order. `build` and `verify`
     reproduce the result, and `validate_town_bench_contract.py` pins each file's sha256.
4. **Budget.** On this PC, with the Conflux lane sharing the GPU, two or three agents fit at once: 3 GB server plus
   4.5 GB per sweep worker each. More agents need the per-worker scene memory cut first (see "Why the sweep targets
   were missed").

## Gotchas

- `edit new --cluster` refuses an atlas swept on other geometry (`binsHash`). An edit renumbers its bin's faces, so
  re-sweep, or pass `--force` only when the op is chained `after` the edit the atlas was swept with.
- `diff` compares face tokens only on bins whose geometry is the same in both atlases (`binHashes`). On changed bins
  it falls back to class + top piece + worst (state, pose) + overlapping box.
- A drop that removes an outer layer can expose the next layer: check the diff's `new` list and peel again with an
  `after`-chained op, as the pilot did.
- `bake` writes the recipe to `recipes/` while its gate runs (the result records the recipe path and sha). A failed
  bake moves it into the bake folder under `V:/olden_port_work/town_bench/bakes/` and leaves the candidate folder
  for inspection.
- The sweep needs `wait_for_memory.py <4.5 x workers>`; the server needs about 4 GB.
