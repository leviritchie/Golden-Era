# Town full-3D: Kokon back-fill (Cove trial `kk_v1`, 2026-10-15)

Kokon is the local Qwen-Image 2.1 editor (`reference_kokon`: API on `127.0.0.1:39151`, models on V:). This trial
asked whether its outpaint, inpaint and upscale can replace the hand-made extension, the `quilt_fill` guesses
and the LANCZOS painting texels of an installed town scene. It ran overnight on Cove, seeded from the installed
`zs_v2_bo_wf2`.

Tool: [`tools/homm3_town_scene_meshes/town_full3d_kokon_backfill.py`](../tools/homm3_town_scene_meshes/town_full3d_kokon_backfill.py).
Scratch, Kokon outputs and sheets: `V:/olden_port_work/kokon/cove_trial/`.

## Method

The tool works only on textures. It writes no vertex, uv or triangle, so the seed's geometric gates still hold:
the zero-streak certificate, the contract, and the LDI npz. For `kk_v1` the `.bytes` hash list is identical to
the seed's.

Every edit starts the same way. moderngl rasterises each piece in its own UV space, giving a per-texel prefab
position and normal. The rest-frame px comes from projection. The colour is de-lit with the lane's own Hex/Lit
irradiance (`conflux_full3d_env.light`, the scene's rig and sun), exactly as `Baker` and `bake_piece` do.

**Method check.** Re-creating the seed's in-rect `Mesh_Terrain` texels as painting divided by our irradiance gives
a mean abs error of 3.35/255 (p90 8.2).

| Subcommand | What it does |
|---|---|
| `rebake --extsrc` | Repaints the environment outside the painted rect from a `town_full3d_extsrc.v1` canvas. On frame-affine terrain pieces, texels outside the rect take the canvas and in-rect texels stay byte-identical. On `Mesh_Outer*`, texels whose rest ray lands on the canvas outside the frame take it, feathered over 60 px from the canvas border (the periphery's own rule). LDI back-layer texels that are shown or protected follow their main piece. |
| `backfill --plate` | Replaces the LDI back layers' guessed texels with a frame-registered plate. The mask is `synth_back_texture`'s own: hidden minus the `PROTECT_TEXELS` ring, and all hidden texels on `_Far`. The quilt stays wherever no plate covers a texel. It refuses to write if any non-fill texel changes, so the rest frame is unchanged. |
| `detail --upscaled` | Adds detail to in-rect texels that the lane copied verbatim from the painting: `new = old + rec(upscaled) - rec(native LANCZOS)`, in linear light. Texels the lane synthesised (reconstruction off by more than 12/255) are left alone. This step deliberately changes the rest frame: the painting gets sharper. |

Why not re-run the lane's bake with a new `TOWN_FULL3D_EXTSRC`? Cove's profile has `EXT_SKYLINE`, which fits the
terrain geometry to the canvas skyline, so a new canvas would move the geometry. The seed's canvas
(`artifacts/claude_takeover_20260927/.../extsrc_bridge_blend`) is also gone from the worktree.

## The Cove inputs

- **Extension canvas.** I first tried a straight `/outpaint`: it cloned the mountain and the shipwreck across 3
  seeds. Inpaint `replace` into a grey-padded canvas with a mask works well.
  - Right band: seed 33. Left band: seed 43.
  - Bottom: three overlapping 1150 px tiles (seeds 53/61/71), each drift-corrected to its known context.
  - Kokon `/upscale` x4 in tiles brings it to k=4. The rect itself is the native painting, LANCZOS x7.2.
- **Behind-object plate.** The mask is where the LDI fill texels land in the frame, dilated 4 px. Kokon inpaint
  `remove` ran in two ~1 MP windows. I picked seeds A81 and B91 by eye: open water without new boulders, and the
  wreck kept in place.
  - Kokon redraws outside the mask too, so only masked px are composited.
  - Where the quilt actually shows at the sweeps, it is thin slivers behind the near rocks, the wreck, the
    right-hand headland and the reeds. I checked this with a magenta/cyan fill-texel render.
- **Upscale.** Kokon `/upscale` (4x NMKD Superscale ESRGAN) on the native 800x374 painting. It invents no content.

## Results (offline bench, review poses, `full` and `start`)

| Step | Verdict |
|---|---|
| Near band and periphery (`rebake`) | **Large win.** The smeared, stretched reeds, water and blotchy rocks below the painting become mossy boulders, agaves, ferns and reeds, with the lagoon running to the camera. The right edge is now a headland with an open sea horizon instead of a blurred mountain copy. The left-edge periphery intrusion is gone. Holds at every sweep, loop and free pose. |
| Behind-object plate (`backfill`) | **Modest win.** The slivers revealed at the sweeps read as dark water and reeds instead of a reddish quilt smear. Rest is unchanged. |
| Upscale (`detail`) | **Small win.** Cliff rock and palms are slightly crisper at game distance. Hard to see at 1x. |
| Painted reflections | **Not done.** The reflections under the tavern, stilt houses and ship are inside the HotA building sprites, so they live on the building meshes, not on the terrain. Removing them would repaint building textures and change the rest frame. That is a separate lane and needs an SSR-water look. |
| `TEXSRC` option in `town_full3d_texsrc.py` | **Not added.** `TEXSRC` needs a full restage, which is blocked: the restage moves `EXT_SKYLINE` geometry, and the seed's canvas is gone. The `detail` subcommand covers the same use for staged candidates. |

Unchanged: the magenta geometry holes near the lower-middle dock at the sweeps are pre-existing (no geometry
there), and the 43-pose certificate was not re-run because the geometry is byte-identical.

**Risk to check in game:** the foreground plants are large. They are the most detailed thing in the frame,
which is what the brief asked for, but they are a composition change compared with the painting.

Sheets: `V:/olden_port_work/kokon/cove_trial/sheets/before_after_{full,start}_{a,b}.jpg`, left = installed, right = kk_v1.

## Install

- Installed 2026-10-15 06:45 UTC: bundle `ac0df5a1`, catalog `5b1ba7ed`.
- Contract validator: OK.
- Rollback: `artifacts/town_scene_rollback/cove_20261015T064534Z`.
- In-game check row: `docs/ingame_check_queue.md`.

## `kk_v2`: footing re-seat (2026-10-15)

`kk_v1` repainted textures only, so the biggest source of mid-ground smear stayed: buildings the stage's paint-order
rescale had pulled toward the eye float in front of the ground they are painted on. Every sweep shows them swimming
and smearing the shore behind. `kk_v2` = `kk_v1` + two bench edits (geometry, rest frame kept):

- `edits/cove/footing-cove.json` (`make_footing.py`): the tavern, three halls, pir2 and smrk slide along their rest
  rays onto the ground under each px column (tavern 37 m median), then an order pass keeps their paint order.
- `edits/cove/twoside-cove.json` (`make_twoside.py`): back copies for the faces that sweeps saw from behind.
  Culled holes went from 900–2700 px per sweep to 0.

Details and numbers: [`docs/town_bench.md`](town_bench.md), section "Footing". The seed had no passing recipe, so
`bench_bake` could not run. Instead: `candidate-init --seed-from kk_v1`, apply both files with `bench_edits.apply_file`
on the kk_v2 Stage, verify the written bins against a quantised dry run on kk_v1 (39/39 equal, no other bin changed),
then `catalog --carry previous` (needs kk_v1's `terrain_streak.npz` / `building_depth.npz` copied in), `bundle`,
contract OK, install.

- Installed 2026-10-15 20:35 UTC: bundle `7c02b12b`, catalog `6cd11c33`. Rollback:
  `artifacts/town_scene_rollback/cove_20261015T203530Z` (restores kk_v1).
- Sheets: `V:/olden_port_work/kokon/cove_trial/diag/{ft_sweeps,ft_loops,fc_sweeps}.jpg` (base_* = kk_v1).
- Not done yet: Kokon plates for the ground the re-seat now reveals, the market smear, the far floaters
  (cas3, gmg4, nix2).

## `kk_v3`: depth, plates and sky (2026-10-15)

`kk_v2` fixed six floaters but left the three most visible defects: objects at the wrong depth (against each other,
the background or themselves), corrupt or warped space behind obstructions, and a sky that moved with the scene.
`kk_v3` = `kk_v1` stage + new textures + five bench edits. The trial tools live in
`V:/olden_port_work/kokon/cove_trial/tools` (outside the repo).

Depth (bench edits, all rest-invariant; see [`town_bench.md`](town_bench.md), "Footing v2, relief and floor"):
- `footing2-cove`: field footing for 22 layers. cas3, sor1, sor2 and gmg4 were left out because the field stretched
  them 3–9x along their rays. They were not floaters: rigidly they cannot move (k ≤ 1.03).
- `relief-cove`: depth low-pass for every building (relief 0.35; mark 0.2 and tavern 0.15 to their foot). say1 is
  skipped: its fit plane tilted along its 238 m ray span and stretched its decal to 62 m, failing the streak gate.
- `floor-cove`: the backstop folded onto the water plane. `twoside2-cove` and `twoside3-cove`: back copies, normals
  kept.

Behind obstructions (texture only, `piece_plate.py`):
- Mesh_Terrain, Mesh_Back_Terrain, Mesh_Back_Terrain_Far and Mesh_Backstop texels the rest frame never shows take
  the object-free plate (`plates/plate_kk_v1.png`) inside the painted rect and the outpaint canvas outside it, de-lit
  by each piece's normals.
- `--outside-canvas`: beyond the 1440x673 rect, the canvas wins even where a back layer shows at rest. Back layers
  there carried stale bytes, which drew as a slab at sweeps.
- Shown texels keep their bytes (asserted), with a 2-texel guard ring. Totals: 2.2M texels plated in frame, 4.9M
  from the canvas.

Sky (`sky_dome2.py`, `sky_masks3.py`):
- The dome texels that any of the 157 poses or the rest camera sees outside the painting get a harmonic fill.
  The fill is a Jacobi Laplace solve on CUDA, coarse to fine; it never overshoots its boundary, while push-pull
  dipped into a pale line.
- The window is widened to x 3080, which removes the dark block at the top right. Painted-edge columns are refilled
  (14 px left, 6 px right, 3 px top).
- The sky no longer carries projected buildings or cliffs.

Bake: apply the five files in order on the kk_v3 Stage, quantizing after each file. 82 bins; the dry run and the
reload are equal, and no other bin changed. Then copy the two npz files in, `catalog --carry previous`, `bundle`,
contract OK.
- The first bake failed the contract's building-depth streak gate (the cas3 and say1 decals). That gate led to the
  cas3/sor/gmg4 and say1 fixes above.
- The bundle needs 20 GB free on V: (launch guard).

- Installed 2026-10-15 23:28 UTC: bundle `eb8ad79a`, catalog `031d61aa`. Rollback (restores kk_v2):
  `artifacts/town_scene_rollback/cove_20261015T232809Z`.

Review: `V:/olden_port_work/kokon/cove_trial/diag/ab_v2_v3_{a,b}.jpg` (8 poses, left = kk_v2, right = kk_v3).
- Every sweep and loop: the market, halls and tavern stay whole and seated, and the shore and lagoon are continuous.
  No culled holes, no black chips.
- Leftovers:
  - A mild water jigsaw at far sweeps, from the terrain's own non-flat painted water.
  - Some grass and rock smear at sweep_right.
  - The far mountain base is dark (that is the canvas itself).
  - A soft glow line at the sky's left edge.

## Pipeline bug found and fixed

`candidate-init` copied the seed's `build_spec.json`, and its `outputPath` still pointed at the seed's `bundle/`.
The first `bundle` run of the fork therefore overwrote `zs_v2_bo_wf2/bundle/homm3_town_scene3d_cove`.

- The seed's bundle and build report were restored from the installed source copy (sha `ee6ab732…`, matching its
  catalog). The fork's bundle moved into the fork.
- The seed's Unity sidecars (`bundle`, `*.manifest`) are not installed files, so they now exist only in `kk_v1`.
- `candidate_init` now rewrites `outputPath` to the fork's own `bundle/`.

Proof tier: generated artifact, offline render (town bench), and installed payload (readback). Not yet seen in game.

## kk_v4: layered back-to-front (Cove pilot, 2026-10-16)

User rule (2026-10-15): build town scenes in layers and project back to front, so that a nearer object never affects the textures behind it. kk_v4 rebuilds the kk_v3 environment this way. The trial tools are in `V:/olden_port_work/kokon/cove_trial/tools`: `seg_layers.py`, `peel.py` and `build_v4.py`.

Segmentation sorts the rest frame (2x) into near foliage, standing objects (wreck, rocks, statue, reeds), the cliff, and everything else.

Peel, front to back, uses Kokon inpaint `remove`:
- P1 = P0 with the near foliage removed.
- P2 = P1 with the objects removed.
- P3 = P2 with the cliff removed.

Each layer's mask is dilated by 13-15 px. Water rows get low-frequency harmonization, and a membrane seam pass removes colour steps at the mask edges.

Geometry:
- **Base** (`Mesh_Terrain*`): the old depth outside the masks. Inside the masks, the lagoon's water plane (fitted to the SSR water), capped at the far depth.
  - A 48 px log-depth ramp joins the two.
  - `relax_floor` smooths small depth steps that would otherwise drop cells and crack the base open onto the dome.
  - Behind peeled layers above the horizon, the dome is painted with P3, except where rest already showed the dome.
- **Layers** (`Mesh_Back_Layer_{Cliff,Objects,Near}*`): each is clamped in front of the layer behind it.
  - Objects use a band around their own local depth, so masts and rails stay on the hull.
  - The cliff is relaxed into one surface.
  - The `Mesh_Back_` prefix makes them the phase-6b contract's back layers: `terrain_streak.npz` holds main = base, back = layers, and cut = base cells over the cap.

Textures:
- Where a layer is what rest shows, the texel is the rest albedo. Where an old LDI back layer drew the rest px, that is the old rest raster's albedo.
- Where a nearer layer covers the texel at rest, it is that layer's clean plate, de-lit.
- So the rest frame matches kk_v3: mean abs diff 1.5/255 at `start`.

SSR water is re-staged on the new base.

Result: at low poses near the wreck, the hull stays solid, with no smear onto the mountain or sky. Contract OK: streakMax 1.250, streakNeg 39, panVoid 0.

Known leftovers:
- The left-cliff palms are part of the cliff layer, so they ride flat on its face.
- Green slabs at the far-left frame edge at extreme yaw.

Installed 2026-10-16 02:29 UTC: bundle `df1692f1`, catalog `51a75e6d`. Rollback (restores kk_v3): `artifacts/town_scene_rollback/cove_20261016T022951Z`.

### kk_v4 rebuild (2026-10-16 03:15 UTC)

The first install showed two problems.
- **Water.** In game, objects in the water had a frame of static painted water. Each layer mesh covered its 13-15 px depth padding, which carried the painted background, and the SSR water renders behind the layers. The preview does not draw the SSR water, so it hid this. Now each layer mesh covers only its outline + 3 px (2x). The wide padding is kept for depth only (ramp, relax).
- **Texture rule.** A layer took the painting where rest showed it and a plate where a nearer layer hid it, which seams at that boundary. The user's rule: the emptier plate is ground truth. Each layer is now textured over its whole mesh from one image: the plate where it is frontmost (base P3, cliff P2, objects P1, near the painting P0), de-lit with the layer's own normals (`texture_from_plate`). The only texture boundary left is a nearer layer's silhouette.

Bundle `07c1d126`, catalog `c5af2e60`, contract OK. Rollbacks: `cove_20261016T031505Z` restores the first kk_v4 install; `cove_20261016T022951Z` restores kk_v3.

### kk_v4 rebuild 2 (2026-10-16 04:55 UTC)

In game, after rebuild 1, the skeleton rock, the wreck and the objects in the water had black outlines, and the skeleton rock and the waterfall stretched in depth.
- **Outlines.** The game's full-screen `Hidden/Hex/ContourLines` pass draws a dark line at every depth step. Back-to-front layers step in depth along every object's outline, so every painted object was inked. The preview has no such pass. The plugin (`Homm3TownScene3d.RebindLitPieceOrThrow`, commit 33d485855e) now sets `_ContourLinesOpacity` to 0 on full-3D town env and building pieces.
- **Upright objects.** `build_v4.py`: each object column stands on its own foot. The foot is the median rest depth of the label's lowest 12 px, with overhangs interpolated. It is limited to `FOOT_SLOPE` of sideways recession and drawn as a camera-facing vertical plane with clipped relief. Before this, the objects leaned back from their foot along the rest depth.
- **Base behind masks.** Log-depth push-pull fill from the ground outside the masks, never nearer than the water plane and never behind the backstop plate. The near and cliff layers are relaxed and then re-clamped.
- **Cliff behind the waterfall.** The cliff face stands up from its foot (`CLIFF_FACE_DEG`, a bottom-up envelope). Behind the falls (building `tbcvnmp1`, rasterized from its staged body) it sits at 1.04 times the falls' depth instead of about 85 m behind a 55 m stream. The pull fades out over 420 px; a 160 px fade streaked the rock beside the falls.

Bundle `d61d905b`, catalog `db918fb8`, contract OK. Rollback `cove_20261016T045543Z` restores rebuild 1. Waterfall A/B: `artifacts/homm3_cove_full3d/candidates/kk_v4/ab_waterfall_cliff.jpg`.
