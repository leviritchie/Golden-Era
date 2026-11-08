# Surface: HoMM3 depth billboard (Video Depth Anything)

## Intent

Take an existing HoMM3 **billboard** animation (the crusader move clip is the pilot) and put those same sprite pixels into 3D using the matching **Video Depth Anything** depth map. The unit stays a camera-facing billboard. This is **not** a Meshy/skinned character mesh (not a character mesh) and **not** the [skinned-mesh battle lane](custom_unit_skinned_mesh.md).

Player-visible idea: from the authored camera the sprite still reads as the original 2D frame. If the camera yaws, the sword/shield/body separate along the billboard normal because each opaque pixel has a Z from VDA (near=bright).

## Ownership preference

1. **Offline clip** — authentic DEF / shadow-culled frames plus a whole-clip VDA-S cache from `tools/homm3_silhouette_pose_fit/run_vda_movement_depth.py`. Unlabelled depth folders and Depth Anything V2 leftovers are refused.
2. **Point billboard** — `tools/homm3_depth_billboard/` places unordered opaque pixels in billboard space (X right, Y up, +Z toward camera). No triangle connectivity, no OBJ, no skinned GLB.
3. **Unity quad (optional, flag-gated)** — `OldenEra/Homm3/BillboardArrayDepth` tessellates the existing `billboard/quad` and displaces it on the authored normal. It reuses `Homm3BattleArrayBillboard` frame indexing. It does **not** replace `battlePresentationLane: skinned_mesh`.

Do not invent a second combat visual owner. Product 3D creatures stay on the skinned-mesh card. This surface is a 2.5D billboard experiment.

## Touch points

| Kind | Path |
| --- | --- |
| VDA cache | `tools/homm3_silhouette_pose_fit/run_vda_movement_depth.py` (`Video-Depth-Anything-Small`, `frames_ground_truth_depth_vda`) |
| 3D billboard points | `tools/homm3_depth_billboard/geometry.py` |
| Gap close + depth smooth | `tools/homm3_depth_billboard/fill.py` (default radius 1 before point extraction) |
| Software orbit proof | `tools/homm3_depth_billboard/run_depth_billboard.py` |
| Authentic CCRUSD move extract | `tools/homm3_depth_billboard/extract_ccrusd_move.py` (group 0 native 8 from the Golden Era crusader bundle) |
| One-shot CCRUSD move preview | `tools/homm3_depth_billboard/build_ccrusd_move_preview.py` (default: `sprites_raw` → `alpha_shadow_cull` → VDA on `sprites_shadow_culled`) |
| Continuous CCRUSD all-anims preview | `tools/homm3_depth_billboard/build_ccrusd_continuous_preview.py` (move → idle → hitted → idle → death → idle → attack_front; one VDA clip) |
| Geometry fixture only | `tools/homm3_depth_billboard/synthetic_crusader.py` — colored rectangles for z-buffer tests. **Not** HoMM3 / CCRUSD art. |
| Gate | `python tools/homm3_depth_billboard/test_depth_billboard.py` |
| Volume mesh extract (experimental) | `tools/homm3_depth_billboard/extract_depth_volume_mesh.py` → `front_shell` (default) or `voxel` marching cubes OBJ |
| Shader | `tools/homm3_import/unity_shaders/Homm3BillboardArrayDepth.shader` |
| Shader bundle | `tools/homm3_import/build_homm3_array_depth_shader_bundle.cmd` → `homm3_array_depth_billboard_shader` |
| Runtime opt-in | `Homm3ArrayDepthBillboardSupport` + `homm3_array_depth_billboard.flag` |
| Frame driver | `Homm3BattleArrayBillboard` (copies `_DepthTexArray*` when present) |
| Product 3D lane (do not mix) | [custom_unit_skinned_mesh.md](custom_unit_skinned_mesh.md) |

## Pitfalls

- **This is not the skinned-mesh ship.** `ship_crusader_pose_to_battle_billboard.py`, Meshy GLBs, and `battlePresentationLane: skinned_mesh` are a different owner. Do not retarget crusader bone clips onto this quad.
- VDA relative depth is **near=bright**. Do not invert it a second time. Outside-alpha is zero. The GPU solver already refuses DAV2 leftovers; this lane uses the same manifest.
- Real clips must point at a VDA pipeline cache (`assert_vda_pipeline_cache`). A folder of anonymous depth PNGs is a failed input, not a default.
- **Do not demo the crusader move with `synthetic_crusader.py`.** That fixture is rectangles. The HoMM3 move clip is `CCRUSD.def` group 0 (8 native plates; the shipped bundle RIFE's them to 40). Extract with `extract_ccrusd_move.py`.
- Official VDA-S inference still **refuses CPU** unless `--allow-cpu` is set. CPU uses the same Video-Depth-Anything-Small weights; it is not Depth Anything V2 and not a painted depth map.
- Geometry is **pixels**, not a mesh. Profile views show a thin relief, not a modeled back. Filling that with a displaced grid OBJ is the town-backdrop experiment (`build_depth_project_mesh.py`), not this surface.
- **Volume mesh lane (experimental):** `extract_depth_volume_mesh.py` builds either a **front_shell** mesh (full-res VDA depth surface + silhouette skirt/back cap) or a coarse **voxel** marching-cubes prototype. Exports OBJ + UV + normals for Unity lighting experiments. Not ship quality: front-painted UV only, back is inferred volume not authored anatomy.
- **Pinholes:** default `gap_close_radius=1` closes 1-pixel alpha gaps; `depth_smooth_radius=1` box-smooths VDA depth inside the silhouette; orbit previews use `splat_radius>=2`. Orthographic front uses `solid_front` (filled sprite composite). Unity shader uses a 5-tap depth smooth on the tessellated quad.
- **VDA bowing:** monocular depth pushes silhouette edges and vertical extremities farther than the torso. Sprite-path correction in `fill.py`: interior row detrend (`depth_bow_vertical_strength`) plus local max-filter edge lift (`depth_bow_edge_strength`). Diagnose with `diagnose_depth_bow.py`. Mesh lane inherits the same `prepare_billboard_frame` knobs once sprite tuning is accepted.
- Unity apply is fail-closed: the flag without `_DepthTexArray` on the material logs and **leaves the flat BillboardArray shader**. That is not proof that 3D is on. Do not sample a missing depth map as 0 and call it a billboard.
- Depth and upscale shader flags must not both drive the same renderer. Depth flag, when set, is the only array-shader swap on `Homm3BattleArrayBillboard`.
- In-combat look is **unproven**. Offline front-view reconstruction and orbit GIFs are generated-artifact only.

## Open unknowns

- Packed `Texture2DArray` depth chunks in the crusader battle bundle (16-bit R, same slice order as color) are not built yet. The shader will not apply until those arrays exist on the material.
- Whether battle camera yaw is large enough for the relief to read in actual Olden Era combat (the authored camera is nearly profile-on already).
- Foot-plant vs median-depth pivot for units whose VDA map includes the ground blob after a bad shadow cull.

## Proof

| Claim | Label |
| --- | --- |
| Front orthographic render matches the source sprite occupancy and color | generated (`test_depth_billboard.py`) |
| Near VDA pixels sit in front of far pixels; profile view separates them | generated (`test_depth_billboard.py`) |
| Real clips refuse unlabelled / DAV2 depth | generated (VDA cache contract + this lane’s loader) |
| Offline orbit uses authentic CCRUSD group-0 pixels (not rectangles) | generated (`extract_ccrusd_move.py` + walkthrough GIFs) |
| Player sees a 3D-ified crusader billboard in combat | **user-visible gameplay** — not claimed |

Hub: [../agent_surface_guide.md](../agent_surface_guide.md).
