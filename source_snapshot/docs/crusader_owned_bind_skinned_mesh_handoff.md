# Crusader pose pipeline → owned bind + skinned-mesh OE handoff

**Current ship (2026-08-17):** GPU-cascade poses on the Meshy smartrig mesh `artifacts/meshy_downloads/h3_crusader_smartrigged_rigidized.glb` (user override; owned-bind hard gate waived this iteration). Delivery tree: `artifacts/crusader_pose_pipeline/gpu_cascade_skinned/` (10 clips; DEF groups 7 and 8 skipped). Albedo is the smartrig 4096² `Baked_BaseColor` extracted into `crusader_owned_skinned_basecolor.jpg` (the previous owned-bind 8192² jpg scrambled this mesh). Lab/bundle/deploy: `custom_units_castle_h3_crusader` **150,520,613** bytes, SHA-256 `23A67B8D0405E6D2126810F869146278C2F9369920D3A8D991962444DCB40E63`. Offline probe: texture 4096×4096, `Crusader_Move` 1.167s, bones move, `Orientation` +90°. Surface card: `docs/surfaces/custom_unit_skinned_mesh.md`. **In-combat albedo/pose remain unproven** until a player combat smoke of this bundle.

**Status (historical through 2026-08-10):** owned rigid bind and authored combat-clip batch regenerated with audited semantic ownership rules; Unity skinned lab import, override-controller build, corrected lane-aware bundle, live bundle deployment, runtime source contract, and combat-load freeze fix (cached-only presentation donor) proven (2026-08-10). Combat smoke identified and addressed four follow-on failures: wrong facing (diagnosed as the vanilla +90° mesh-content convention and fixed structurally with an `Orientation` yaw bake in the master + all clip GLBs), non-looping/held clips, seam holes ("floating armor pieces"), and the facing-diag attach crash — see the 2026-08-10 session evidence below.
**Proof bar today:** generated-artifact validated for all 14 authored Crusader clips, owned GLB triangle ownership, owned-master `fixed_length_ik`, 180 ms GIF-timed lit previews, Unity lab import/prefab/clip mapping, corrected isolated bundle construction, live payload deployment, and the Golden Era interop compile. The first live-name candidate was intentionally superseded after material review; the current deployed bundle is 206,859,170 bytes with SHA-256 `B6FE9149E7CD7CAE740D78225453B09FAA78EC583CA33ECC8FA639A0A2710651` (the facing-fix rebuild, 2026-08-10 — GLB `Orientation` baked at −90° so Unity imports +90°, with clips at stock cadence), contains the owned-skinned prefab/material and map/sound assets, includes the base `StockEsquireBattle.controller` (previously missing, which left the AnimatorOverrideController without a state machine at runtime), and contains no battle billboard array or material. The first deployed material-fix DLL froze combat load (the release hook ResManager-loaded the presentation donor inside `ecd.Init` mid battle-load; fixed with a cache-only donor lookup — the validator fail-closes against the ResManager-loading getter on the release path). An offline bundle probe (`tools/homm3_import/unity_editor/ProbeOwnedSkinnedBundle.cs`) then found the white-clay/static causes: the basecolor jpg was never packed into the bundle (added as an explicit root asset), and the authored clips animated scene-relative paths rooted at the GLB armature node (`OwnedCrusader/Hips/...`) while Unity resolves clip paths relative to the Animator root — every binding missed, leaving bind pose. `CrusaderOwnedSkinnedLabBuild` now rebases clip paths (`RebaseClipPaths`, fail-closed) and the probe verifies bones move (`bones moved after animator.Update: True`) and the texture loads (2048x2048) from the rebuilt bundle. **In-combat gameplay remains unproven** (the fixed bundle is deployed but not yet combat-tested), and Golden Era passes the artifact preflight with 155 catalog entries, 20 chunk bundles, and a 155-asset manifest.

### Current evidence (2026-08-09)

- Active candidate: `artifacts/crusader_pose_pipeline/owned_bind/crusader_master_rigid_components.glb`.
- Triangle gate: `rigid_triangle_audit.json` reports 6,972 vertices, 8,349 triangles, zero unowned vertices, zero ambiguous vertices, and zero mixed-owner triangles.
- Mesh provenance: Meshy image-to-3D task `019fe2e0-9d90-7b94-b760-79334c63c5d9` and retexture task `019fe320-3db6-777c-a5e6-5b1d03233672` were redownloaded into `artifacts/crusader_pose_pipeline/redownload_verify/`; both redownloads are SHA-256 identical to the local source files. A fresh rigid audit of the redownloaded raw T2 GLB independently reports 386 disconnected components.
- Raw GLB structure: `tools/homm3_meshy_frame_pose/inspect_glb_structure.py` reads the GLB JSON chunk directly. Both redownloads contain one scene, one unnamed node, one mesh, one primitive, and only `POSITION`, `NORMAL`, and `TEXCOORD_0`; they contain no `COLOR_0`, node/mesh/material extras, or semantic part labels. The colored component view in Meshy is therefore a viewer-generated Smart Topology overlay, not scene-tree metadata.
- Semantic ownership: `tools/homm3_meshy_frame_pose/ownership_rules_h3_crusader.json` applies the reviewed `shield_side_boundary` correction to 22 components (`Hips -> LeftArm`) after geometric nearest-bone assignment. The generated skeleton records every application; overlapping rules and missing expected matches fail closed.
- Full batch gate: `tools/homm3_silhouette_pose_fit/validate_crusader_owned_clip_batch.py` passes with 14 authored groups and no errors. Every group has an owned-master fixed-length fit, one delivery GLB, fit report, and 180 ms lit-preview metadata.
- Current g12 preview means are 10.61 px Nose, 4.73 px WeaponTip, and 31.69 px body loss. These are generated-preview metrics only.
- Unity lab source: `oldenera_factions/Assets/Editor/CrusaderOwnedSkinnedLabBuild.cs`. It targets a separate `Assets/CustomUnits/homm3_lab/h3_crusader/OwnedSkinned/` lane and leaves the existing billboard `battle.prefab` untouched.
- Unity lab proof: `artifacts/crusader_pose_pipeline/unity_owned_skinned_build.log` ends with `Crusader owned skinned lab build passed.` and batchmode return code 0. The generated audit is `V:\homm3_unity_work\Assets\CustomUnits\homm3_lab\h3_crusader\OwnedSkinned\crusader_owned_skinned_audit.json`; it reports one `SkinnedMeshRenderer`, 14 imported clips, and all 27 stock-to-owned override mappings applied. The corrected material-only rebuild also restores the existing override controller after prefab regeneration. The final isolated build log is `artifacts/crusader_pose_pipeline/owned_skinned_bundle_live_name_material_fix_direct.log`; it reports 58 assets and a successful batchmode exit. This proves Unity import, lab prefab construction, corrected material/controller packaging, and isolated bundle construction; live deployment is complete and OE combat smoke remains outstanding.
- Bundle-builder correction: the candidate manifest now declares `battlePresentationLane: "skinned_mesh"`; `BuildCustomUnitBundles.cs` uses that lane to omit battle `Texture2DArray`, billboard materials, and billboard animation assets while retaining map assets, sounds, and owned prefab dependencies. The prior 49-asset candidate at `artifacts/crusader_pose_pipeline/owned_skinned_bundle_candidate/` remains an audit artifact only: its manifest includes `Generated/BillboardAnim/Array/*`, so it is superseded and must not be deployed.
- Runtime lane proof: `tools/validate_crusader_owned_skinned_runtime_contract.py --require-artifact` passes. The marker `__homm3_skinned_battle_lane__` is serialized into the owned prefab; its local rotation is the per-prefab forward-axis correction consumed by target-facing. `Homm3ImportVisuals`, pool/release helper attachment, and attack-facing resolution recognize that marker and bypass billboard-only helpers while retaining shared telemetry/audio. The compile-only Golden Era build passes with 0 errors when unrelated pre-existing validator drift is explicitly skipped; the normal build remains blocked earlier by unrelated raw-translation and Factory/Bulwark validator failures. This is source/build proof, not deployed or user-visible runtime proof.

### 2026-08-10 combat-smoke follow-on session (facing / clip flow / seam holes)

User-visible combat after the loop-fix deploy reported three failures; this session addressed each with measured evidence (all numbers from `tools/homm3_silhouette_pose_fit/inspect_glb_skinning.py` and `tools/homm3_silhouette_pose_fit/measure_rigid_gaps.py`):

1. **Facing diag attach crash fixed.** `Homm3SkinnedFacingDiag.TryAttach` used `instance.AddComponent<T>` on a mono type never registered with Il2Cpp → `MethodInfoStoreGeneric_AddComponent_Public_T_0\'1` TypeInitializationException crashed the release-hook postfix (log: `Homm3Import release battle visual postfix failed for unitSid='h3_swordsman_upg'`), so the facing diagnostic never ran. It now mirrors `Homm3BattleBillboardCameraFacing`: `ClassInjector.RegisterTypeInIl2Cpp<Homm3SkinnedFacingDiag>()` once + `IntPtr` ctor + per-attach try/catch. Rebuilt and deployed (`OfflineUnlockMod.dll` SHA-256 starts `bada5a4fef046ee6…`). The diag logs self/vanilla yaw samples under `homm3_battle_visual_diag.flag`; the live convention readout still needs one combat run.
2. **Clips never looped; states held the final pose.** Every owned `.anim` shipped `m_LoopTime: 0`; the base layer default state (`idle`) played `Crusader_Mouseover` once (0.33s) and froze, and Walk/Stance behaved the same. `CrusaderOwnedSkinnedLabBuild` (canonical copy now at `tools/homm3_import/unity_editor/CrusaderOwnedSkinnedLabBuild.cs`) sets `loopTime` for Move/Mouseover/Defence and repeats those open cycles twice with a one-frame DEF-authentic jump-cut (`RepeatCycle`), bringing Move/Mouseover to ~0.68s and Defence to ~0.93s so the stock controller's 0.1-0.3s crossfades no longer cover an entire cycle. Verified in the regenerated lab `.anim` files (loop flags + key counts).
3. **Seam holes are real and quantified; master GLB seam-blended.** The fit clips are drift-heavy: authored mouseover frame 7 is byte-identical to frame 0, but the fitted clip's first/last rotations differ up to 36° (LeftForeArm), and all clips open ~110° mean from the bind pose. Skin-sampled inter-island gaps at the idle pose: Head island opens +30cm, RightArm +21cm, neck +13cm vs rest (rest itself is dense: p99 22cm, user-accepted). New post-processor `tools/homm3_meshy_frame_pose/blend_rigid_seams.py` rewrites the delivery master `owned_bind/crusader_master_rigid_components.glb` in place (pure-rigid backup `…_purerigid_backup.glb`): every non-trunk island blends 0.06-0.25 toward its parent bone and expands 1.0-1.12× around its owner joint origin. Measured after: Head opening +30→+25cm, RightArm +21→+12.5cm, neck +13→+10cm, overall seam-opening p99 0.336→0.279 m. Skin math validated (rest skin error vs authored mesh = 0.0). Clips are rotation-only on the same bones, so no fit re-run was needed.
4. **Rebuilt + redeployed the whole chain** with the above: lab build → bundle `custom_units_castle_h3_crusader` 206,789,941 bytes / SHA-256 `639CC4D58EAFCEB56D7D3DD88E720A992491FD965DF1B6F0F702EB8DA3402A0F` (contract updated) → payload + audio validators pass → installed + repo copies refreshed. `validate_crusader_owned_skinned_runtime_contract.py --require-artifact` passes.

**Open items after this session:** in-combat re-verification of loop flow, seam density, and the facing diag numbers; the fitted-clip drift itself (per-frame bodyMean error ~28px; open-cycle DEF content with authentic jump-cuts) is the remaining quality ceiling and would need a fit-pipeline cycle-closure/constraint pass.

### 2026-08-10 facing-fix session (mirrored mesh root cause + deployment)

User reported the crusader faced exactly backwards in combat while all facing telemetry looked correct. Root cause, verified in `crusader_owned_skinned.prefab`: **the Unity glTF importer flips the sign of Y rotations** (GLB RH → Unity LH). The GLB +90° yaw `Orientation` node imported as −90° in Unity, so the mesh content effectively shipped at a −90 state facing; the Unity-side lane marker (+90) is why logs read correct while the screen showed the exact mirror.

Fix applied and deployed:

1. **Bake changed to −90° glTF yaw.** `tools/homm3_meshy_frame_pose/bake_orientation_group.py` now writes `ROTATION_MINUS_90_YAW = [0, -0.7071, 0, 0.7071]` and supports `--rewrite` for files that already have `Orientation` nodes. All 13 delivery GLBs (master + 12 clips) re-baked; the Unity lab import now reads `Orientation` as **+90°** (`y: 0.7071068` in the prefab).
2. **Clip cadence locked to vanilla pace.** Authored clips are rescaled to the stock Esquire etalon durations in `CrusaderOwnedSkinnedLabBuild` (`RescaleClipToDuration`, `TargetSecondsByContract`): Idle 5.33s, Walk 1.167s, Attack 2s, Damage 1.167s, Death 0.833s, Stance 1.2s, MoveStart 0.667s, MoveEnd 0.5s, Victory 2s; `RepeatCycle` 2× repeat removed. User confirmed in-combat speed now matches vanilla regardless of battle-speed setting.
3. **Rebuilt + redeployed.** Bundle `custom_units_castle_h3_crusader` 206,859,170 bytes / SHA-256 `B6FE9149E7CD7CAE740D78225453B09FAA78EC583CA33ECC8FA639A0A2710651` (contract updated) → payload + audio validators pass → installed + repo + `build_out` copies refreshed (all three SHA-verified) → offline probe passes (texture 2048x2048, `Crusader_Move` 1.167s, bones move, `Orientation` +90 in hierarchy). `validate_crusader_owned_skinned_runtime_contract.py --require-artifact` passes.

**Facing convention for future units (do not re-litigate):** `ApplySideFacing` skips the skinned lane on purpose; the mesh carries the ±90 convention. Vanilla points the ecz orientation root at `dir − 90` and expects mesh content at +90; the +90 is now a Unity-side factor via the −90 glTF bake. The `__homm3_skinned_battle_lane__` marker on the root is Unity-side forward (+90), consumed by `TryApplySkinnedBattleTargetFacing` / `MeasureSkinnedTargetFacingDelta`. If a skinned unit looks mirrored in OE, check the imported prefab's node rotation against the GLB (GLB expects +X, Unity imports are flipped) before touching dynamic flips. In-combat facing re-test remains outstanding.

### 2026-08-10 enhanced-mesh pilot (replace holey master)

User supplied `C:\Users\<user>\Downloads\crusader-enhanced.glb` (8,751 verts, single welded mesh, no armature) after the delivered master looked like floating armor pieces in combat. Owned bind rebuilt from it (`rig_frame0_shared_skeleton.py`, 24-bone skeleton, `owned_bind/crusader_enhanced_rigged.glb` + `crusader_enhanced_skeleton.json`; joint audit passes). Pilot walk fit (`configs/h3_crusader_move_g0_enhanced_pilot.json`, authored marks reused from `g00_move_authored`) succeeds with nose 6.3px / tip 1.6px vs old baseline 10.6 / 9.8. Gap evidence (`measure_rigid_gaps.py`, walk frame 0):

| Metric | Old master | Enhanced rigged |
|---|---|---|
| seamOpening p99 | 21.2 cm | **5.4 cm** |
| seamOpening p95 | 15.7 cm | **1.7 cm** |
| rest max island gap | 44.7 cm | **25.9 cm** |
| rest-skin error vs source | 0.54 m (blend artifact) | **0.0 m** |

Both meshes ~1.4 m tall in the same GLB units (feet on Y=0). Enhanced is a welded surface (only 2 verts with NN>5 cm) so seams cannot open like the old islanded mesh; old master's 0.54 m rest error is the seam-blend distortion itself. Artifacts under gitignored `artifacts/crusader_pose_pipeline/` (`owned_bind/crusader_enhanced_*`, `out_fit_enhanced/g00_move_pilot/` with lit previews + side-by-side GIF). Not yet: batch re-fit of all clips, Unity lab swap, bundle rebuild, deploy, combat re-test.

### 2026-08-10 rigid-with-flex-band skin (all-metal crusader)

User reframed: the crusader is **all plate armor** — the problem is not finding the few rigid parts (old island approach) nor smooth-blending everything (stretchy pilot); it is finding the few spots where armor must fold. New skin mode `rigid_with_joint_blend` in `rig_frame0_shared_skeleton.py`: every vertex gets exactly one bone (rigid metal), then narrow fold bands around the ~15 articulation points (neck, shoulders, elbows, wrists, hips, knees, ankles, torso) re-blend parent/child with a smoothstep so the welded mesh folds instead of tearing. Result (`crusader_enhanced_rigid.glb`): **91.1% single-bone verts**, 7.8% two-bone fold bands, 1.2% leftover 3+ (band overlaps).

Evidence (walk pose frame 0, `measure_pose_tears.py` + edge-distortion analysis): weld stays closed (tear delta p99≈0 for both skins); plate stretch is the real differentiator — same-owner triangles stretched >10%: **6.4% rigid vs 79.5% soft**; rigid same-owner median distortion 0.0%. Fit quality unchanged/better (nose 5.1 px rigid vs 6.3 px soft; tip 1.6 px both). `measure_rigid_gaps.py` different-owner "seam opening" is NOT comparable across skins — rigid patches inflate it (patch interior to any other owner is far); use geometric NN (`measure_pose_tears.py`) and edge-length distortion instead.

Pilot: `configs/h3_crusader_move_g0_enhanced_rigid.json` → `out_fit_enhanced_rigid/g00_move_pilot/` (lit GIF `move_g0_enhanced_rigid_lit_loop.gif`). Not yet: band-width tuning per joint if elbows/knees still read rubbery, batch re-fit, Unity swap, deploy.

### 2026-08-10 dual-quaternion skinning discovery (previews lied; Unity already DQS)

User judged the rigid+flex pilot and rejected it too ("different, but still bad; the fundamental look of the mesh is unpreserved"). Root cause: the ENTIRE pipeline skins with **linear blend skinning** (glTF's only mode) — all three weight strategies (soft k-nearest, rigid islands, rigid+flex) only changed the weight map, never the transform interpolation. LBS interpolates bone matrices linearly → candy-wrapper collapse/shear past ~30-40° of bend; no weight map fixes it (rigid dodges interpolation but pushes the failure into the fold seam).

**The game already uses dual quaternion skinning:** Unity's `SkinnedMeshRenderer` blends 2/4-bone weights with dual quaternions (SkinQuality Auto → Bone4; our hooks never touch `quality`). Blender's glTF import leaves LBS on (`use_deform_preserve_volume=False`), so every preview we rendered showed candy-wrapper stretch the game never produces. Verified: with an 80° forearm rotation, Blender DQS vs LBS differs up to 7.9 cm on this mesh.

Fix: `render_fixed_length_lit_60fps.py` + `render_fixed_length_preview.py` now set `mod.use_deform_preserve_volume = True` after glTF import so previews match Unity's math. Both pilots re-rendered as DQS previews (`out_fit_enhanced/g00_move_pilot/` and `out_fit_enhanced_rigid/g00_move_pilot/`). Note: edge-length distortion is NOT a valid DQS metric (bending changes edge lengths by design — volume preservation); judge by eye. A numpy DQS skinning experiment (`measure_dqs_skinning.py`) was deleted — the reconstruction kept disagreeing with theory and the metric was invalid for DQS anyway. Open: does the soft (multi-bone) skin finally read correct under DQS? user verdict needed; then batch re-fit on the winning skin.

### 2026-08-10 THE MESH WAS THE PROBLEM (triangle soup; watertight remesh fix)

User: "no meaningful improvement for either [DQS pilot]. Be certain the mesh isn't the problem." It WAS. Topology audit (Blender-side bmesh — in-memory, no export confound):

| Mesh | Components | Open rim edges | Largest patch |
|---|---|---|---|
| `crusader-enhanced.glb` (download) | **1,236** | **8,297** | 154 verts |
| old delivered master | 386 | 4,823 | 84 verts |
| original Meshy source | 386 | 4,823 | 84 verts |
| **voxel remesh (0.0125 m)** | **1** | **0** | 33,908 verts (in-memory) |

Every mesh in the pipeline was a triangle soup: 1,236 adjacent-but-unconnected patches that LOOK dense (verts within 1 mm) but share no triangles. No skinning method (LBS, rigid, rigid+flex, DQS) can preserve a surface that doesn't exist — that is why every attempt failed identically. The original Meshy export is also a soup (386 patches); the "enhanced" download improved point density, not topology.

Fix (canonical mesh-prep step): `tools/homm3_meshy_frame_pose/remesh_watertight.py` — Blender voxel remesh → single watertight manifold (in-memory 1 component / 0 boundary), UVs stripped (must be re-transferred later). Important audit caveat: the exported GLB still shows component/boundary splits — Blender's glTF exporter duplicates vertices at normal crease seams (voxel surface has 90° edges). Audit connectivity IN BLENDER (bmesh), not on the file. Re-rigged soft k-nearest on the watertight master (`crusader_enhanced_watertight_rigged.glb`), joint audit clean, walk fit with `highest_skinned_vert` crown site (`bone_roles_crusader_owned_watertight.json`; `farthest_skinned_vert` grabs helmet-back verts after remesh): nose 11.0px / tip 0.7px. Tear measurement (`measure_pose_tears.py`) on the watertight pilot: rest NN p99 0.9cm (soup was 2.2cm), pose NN p99 1.0cm, tear p99 0.4cm, **0 verts >5cm**. DQS lit preview: `out_fit_watertight/g00_move_pilot/preview_lit_60fps/move_g0_watertight_lit_loop.gif`.

Open: user verdict on the watertight DQS walk; then UV transfer onto the watertight mesh (voxel remesh regenerates UVs), batch re-fit, Unity swap, deploy.

### 2026-08-10 MESHY ANALYSIS — the soup is fine; the WEIGHTS were the problem

User supplied Meshy's own knight rig+animations (`C:/Users/<user>/Downloads/Meshy_AI_Azure_Knight_of_the_E_biped/`) and asked what Meshy did differently. Findings:

1. **Meshy's mesh is the SAME triangle soup** — 8,772 verts / 6,911 tris / 1,238 components / 8,301 boundary edges (Blender-side). Nearly identical to the "enhanced" download (8,751 / 6,911 / 1,236 / 8,297). The soup is NOT the failure; Meshy ships it and it works.
2. **Meshy's weight profile is the difference.** Strong dominant bone per vertex: dominant>0.9 on 37.7% of verts (ours soft k4p2: 3.9%), mean dominant 0.756 (ours 0.468), 27% single-bone verts, 81% of pieces fully single-bone coherent. Our flat 4-way weights fragment pieces → the "flails wildly in small parts" and lost look.
3. **Reproduced exactly** with `_nearest_bone_weights(k=4, power=10, trim=0.03)` (drop weights < trim, renormalize): dominant>0.9 36.4%, mean 0.740, full-coherent 73.1% — within noise of Meshy. Rig script now takes `--skin-k/--skin-power/--skin-trim`.
4. **Remesh verdict reversed:** the watertight remesh path (previous session) is NOT needed for the soup meshes and destroyed UVs/texture. Canonical prep is now: enhanced soup mesh + strong weights + DQS preview + texture preserved.

Strong master: `crusader_enhanced_rigged_strong.glb` (texture/UVs intact). Walk pilot `out_fit_strong/g00_move_pilot/` (nose 13.5px, tip 1.6px; DQS lit GIF `move_g0_strong_lit_loop.gif`), tear p99 0.4cm / 0 verts >5cm. `remesh_watertight.py` stays available for genuinely-broken meshes but is not the crusader path. Open: user verdict on the strong walk; then batch re-fit all clips, Unity swap, deploy.

### 2026-08-10 Meshy-walk A/B pilot (our mesh, Meshy's own Walking clip) — WORKING

`tools/homm3_silhouette_pose_fit/retarget_meshy_walk_pilot.py` drives **our** `crusader_enhanced_rigged_strong.glb` mesh with **Meshy's own `Walking` clip** (24 rotation channels, 32 keys, closed cycle) so the user can judge mesh+weights without our DEF-fit. Two bugs found and fixed in this session:

1. **Hips root translation units.** The pilot applied Meshy's Hips translation scaled by 1.4/1.9 (0.737) — but Meshy's translation track is in **cm** (mesh bbox 0–1.7 m; Hips y≈92 = 92 cm) while our rig is meters (bbox 0–1.4 m). That launched our Hips to y≈67 m, putting the whole character outside the camera frustum (all frames rendered bind-pose background, md5-differing only by EEVEE noise). Fix: key only **deltas from frame 0** × `0.01 * (1.4/1.7)` so our bind height is preserved. Host probe `artifacts/crusader_pose_pipeline/_dbg/tr_constant_probe.py` proved the other 23 translation channels are constant rig offsets (2 keys, zero deviation) — correctly ignored.
2. **Camera was hand-rolled at origin scale.** Replaced with the established `setup_pose_camera` (iso az 40 / el 30 / dist 3 / orthoScale 4.2, rootYaw 0 — same as the accepted strong-fit previews) + `_setup_lit_scene`. Silhouette bbox now centered and pose-varying (x 186–588, y 213–564 of 720).

Also confirmed a non-issue: bone names match 23/24 between Meshy's walk channels and our skin (only `headfront` Meshy-only, `RightWeaponTip` ours-only) — the old "all frames byte-identical" report predates the per-frame `bpy.context.view_layer.update()` in the render loop. Action `OwnedCrusaderAction` gets 95 fcurves (23×4 quat + 3 Hips loc); frame 31 returns exactly to frame 0 pose (closed cycle).

Deliverable: `artifacts/crusader_pose_pipeline/out_fit_meshywalk_pilot/meshywalk_loop.gif` + 12 lit PNGs + `diagnostics.json` (per-frame pose samples + md5s). **User verdict pending** — does our mesh now deform like Meshy's (rigid plates, no flail/stretch) under Meshy's own motion?

### 2026-08-10 reverse A/B — Meshy rig + our walk (world-space retarget) — CORRECT

User asked for the opposite direction to isolate mesh vs animation: drive **Meshy's rig** (`C:/Users/<user>/Downloads/Meshy_AI_Azure_Knight_of_the_E_biped/..._Merged_Animations.glb`) with **our walk** (`artifacts/crusader_pose_pipeline/out_fit_strong/g00_move_pilot/move_g0_strong_fixed_length_ik.glb`). The first runs produced "sideways and/or mirrored" garbage. Root cause: the rest poses differ massively between the two rigs (Hips rest differs ~124°, shoulders ~147–177°) — **naive local-quat transfer is meaningless**. The fix is a world-space retarget, and it uncovered three real bugs:

1. **Quaternion inverse missing conjugation (`_qinv`).** It returned `q/|q|²` instead of `(w,−x,−y,−z)/|q|²` — not a 180° flip but a completely wrong quaternion. This was the root cause of ALL the ~90–180° garbage in both A/Bs. Always test with `q * qinv == identity`.
2. **glTF node rotation channels ARE the local rotation** (no separate rest factor): `W_A(b,k) = W_A(parent,k) @ clip_q(b,k)`. Do NOT multiply by the rest-local quat first.
3. **Blender's glTF import reinterprets bone rest** (head/tail/roll) vs the raw GLB node TRS, so the solve must run against **Blender's `bone.matrix_local`** (not raw node TRS), and the chain accumulation must be **pure quaternion** — reading `parent.matrix` from the depsgraph during pose compute returned stale rest values.

Two scripts implement the corrected recipe:

- `tools/homm3_silhouette_pose_fit/retarget_our_clip_to_meshy.py` (host-side, `py -3`): parses both GLBs, computes our clip's world rotations per key (`W_A`), solves Meshy pose_locals to reproduce them, asserts `W_B == W_A` (<1e-3°), writes `retarget_pose_locals.json` (pose_locals + expected_worlds + times + shared). **PASSES (0.000°).**
- `tools/homm3_silhouette_pose_fit/drive_meshy_rig_with_our_clip.py` (Blender): imports ONLY Meshy's GLB, pass 1 computes pose_locals with pure-quaternion chain accumulation against `bone.matrix_local` (no depsgraph reads), pass 2 writes fcurve keyframe values **directly** (`fc.keyframe_points.insert(frame=..., value=...)` — `keyframe_insert()` snapshots whatever the depsgraph last evaluated and can record action-evaluated values), renders lit DQS frames, readbacks world vs expected_worlds. **Readback worst 0.148° (LeftShoulder, frame 7), most 0.000–0.1°** — the pose is correct to render resolution.

Deliverable: `artifacts/crusader_pose_pipeline/out_meshyrig_ourwalk/` — 12 lit frames `ourwalk_00..11.png`, `meshyrig_ourwalk_loop.gif` (composed via `compose_method_compare_gif.py`; frames staged as `frame_XX.png`), `retarget_pose_locals.json`, `diagnostics.json`. Camera: iso az 40 / el 30 / dist 3 / orthoScale 4.2 / lookAtZ 0.9 (Meshy's armature has object scale 0.01 — affects `matrix_world` only, not quaternions).

**Decision point:** does our walk look right on Meshy's rig?
- **Yes** → our animation data is fine; the earlier "worst one yet" (our mesh + Meshy's Walking clip) was just the broken retarget. Re-run that A/B (`out_fit_meshywalk_pilot`) with the corrected recipe, then proceed to batch re-fit + Unity swap + deploy on the winning mesh.
- **No** → our walk data itself is bad; revisit DEF-fit/authoring.

The other A/B's current `meshywalk_loop.gif` was rendered with the broken retarget and is garbage — do not judge mesh+weights from it; re-render with this recipe first.

## User intent (non-negotiable)

1. **Crusader must render as an animated skinned mesh** in OE combat — same class as vanilla swordsman/inquisitor (`SkinnedMeshRenderer` + bone `AnimationClip`s + root `Animator`).
2. **Do not** ship mesh-rendered poses as DEF/billboard PNGs fed into `billboard/quad` + `Texture2DArray` (`Homm3BillboardAnimatorBuild` lane). That path was explored and **rejected**.
3. **Every unit** in the HoMM3 pose program needs **owned bind + skin** (humanoid and non-humanoid). Meshy auto-rig is never delivery authority.

Operational contract: `.cursor/skills/homm3-pose-pipeline/SKILL.md` (also copied to `~/.cursor/skills/homm3-pose-pipeline/SKILL.md`).

---

## Identity

| Role | Value |
|------|--------|
| Lab SID | `h3_crusader` |
| Game SID | `h3_swordsman_upg` (Crusader) |
| Bundle | `custom_units_castle_h3_crusader` |
| Battle prefab (today) | `Assets/CustomUnits/homm3_lab/h3_crusader/battle.prefab` |
| Import row | `OfflineUnlockMod/homm3_import.json` (~1453–1466) |
| DEF | `CCRUSD.def` |
| Golden Era install | `V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era` |
| Deploy bundles | `-p:DeployHomm3Bundles=true` → `BepInEx/plugins/OfflineUnlockMod/homm3_bundles/` |

---

## What exists today

### Mesh sources

| Asset | Path | Role |
|-------|------|------|
| **Unrigged mesh (ship from here)** | `artifacts/crusader_pose_pipeline/out_meshy_t2_idle_f0/meshes/idle_f0_meshy6_retexture.glb` | Meshy T2 + meshy6 retexture, **no armature** — input for owned bind |
| Unrigged alt | `…/meshes/idle_f0.glb` | Earlier export; prefer meshy6 retexture |
| **Blocked transition master** | `…/rigged/idle_f0_rigged_meshy6_bridgefix_hand.glb` | 24-bone Meshy/Mixamo auto-rig + right-hand bridgefix — **do not use for delivery fits** |

### Sprite authorship (hard gate — **passed** for combat set)

All dirs under `artifacts/crusader_pose_pipeline/out_fit/*_authored/` with `human_eye_landmark_authoring` in `sprite_landmarks/keypoints.json`, including:

- `g00_move_authored`, `g01_mouseover_authored`, `g03_hitted_authored`, `g04_defence_authored`, `g05_death_authored`
- `g07_turn_left_authored`, `g08_turn_right_authored`, `g09_unused_a_authored`, `g10_unused_b_authored`
- `g11_attack_up_authored`, `g13_attack_down_authored`, `idle_attack_front_authored`
- `g20_move_start_authored`, `g21_move_end_authored`

Missing from authored set: idle-only g2 (separate from `idle_attack_front`), shoot groups 14–16 (crusader is melee).

### Fixed-length IK (owned rigid delivery batch)

`out_fit/*_fixed_length/` delivery batches exist for the groups above, all pointing at the owned rigid master via `bone_roles_crusader_owned.json`.

The delivery batch is regenerated from the active rigid master and passes the generated-artifact validator. Fit metrics are evidence for pose quality only; they do not substitute for Unity import or OE runtime proof.

- Upright-unwrap full batch (groups 0,1,3–5,7–13,20–21) completed with good Nose metrics on many clips.
- Crown-Nose site (`highest_skinned_vert` on Head) **worsened** some Nose errors vs unwrap-only; idle g12 re-fit with posed crown landed ~**7.5px** mean Nose (best recent idle metric).
- **Head still melts** on Mixamo bind even with Head eulers zeroed — see `_head_rest_test/`.

### Head melt evidence

`artifacts/crusader_pose_pipeline/def_billboard_ship/_head_rest_test/`:

- `head_eulers_zeroed.png`, `with_head_ccd.png` — helmet collapse with **no IK** on Head rotation → **bind/deformation ownership**, not sprite sticks or CCD alone.
- Root cause: Mixamo `Head` / `head_end` do not own helmet crown verts; retargeting `jointSites.Nose` to crown fixes IK targets, not LBS.

### Billboard ship artifacts (deprecated — do not continue)

- `tools/homm3_import/ship_crusader_pose_to_battle_billboard.py`
- `tools/homm3_silhouette_pose_fit/render_fitted_def_billboard_frames.py`
- `artifacts/crusader_pose_pipeline/def_billboard_ship/` — partial renders; **not** product path.

### OE bundle today

The live Crusader import row now points at the **owned-skinned lane** (`OwnedSkinned/crusader_owned_skinned.prefab`). The prefab has the serialized lane marker, explicit Etalon-compatible material, one visible `SkinnedMeshRenderer`, and the existing override controller. Runtime hooks recognize that marker, preserve the billboard path for existing rows, and skip billboard camera/array/disk helpers for the skinned path. The installed bundle has passed the scoped payload/audio/runtime-contract validators; in-combat smoke is still outstanding, but Golden Era main-menu payload preflight now passes.

### Owned-bind pilot result

Created `artifacts/crusader_pose_pipeline/owned_bind/crusader_master.glb` from the unrigged Meshy mesh. The hand-built armature is marked `hand_owned_mixamo_like`, strips the source vertex groups, places `Head` on the helmet crown, and adds `RightWeaponTip` on the raised blade end. The bind audit passes with no issues in `owned_bind/joint_audit/joint_audit_report.json`.

The first owned-master fit is `out_fit/g12_attack_front_owned_fixed_length/`. It uses authored sprite marks, the bone-owned weapon-tip site, rotate-only fixed-length IK, and a 180 ms GIF-timed lit preview. Fit means are 15.17 px Nose and 13.58 px WeaponTip. These are preview metrics, not OE gameplay proof.

### Rigid armor delivery candidate

The owned-bind tool supports `--skin-mode rigid_connected_components`. This strips all source groups, finds disconnected mesh components, assigns each component to one bone at weight 1.0, and applies explicit armor ownership rules. It is the current delivery policy: it prevents plate warping; any seam gaps are visible and auditable rather than hidden by soft deformation.

The Crusader delivery candidate is `owned_bind/crusader_master_rigid_components.glb`; its g12 fit and lit preview are under `out_fit/g12_attack_front_rigid_components_fixed_length/`. It uses the rigid connected-component bind plus the external `shield_side_boundary` rule, which keeps the ambiguous shield-side islands on `LeftArm` rather than the pelvis. The full authored batch has now been regenerated against this exact master. As of 2026-08-10 the delivery master is seam-blended (`tools/homm3_meshy_frame_pose/blend_rigid_seams.py`, pure-rigid backup kept) so rigid islands stay attached under the DEF poses — see the 2026-08-10 session section.

The rigid comparison also exposed and fixed a head-pivot issue: `Head` now starts just above the neck and ends at the helmet crown. The crown remains the owned Nose site, but the rigid head component no longer rotates around the crown and floats behind the body.

The invasive ownership audit is now `tools/homm3_meshy_frame_pose/audit_owned_skin_triangles.py`. On the current rigid master it reports **6,972 vertices**, **8,349 triangles**, **386 disconnected components**, zero unowned vertices, zero ambiguous vertices, and zero mixed-owner triangles. This proves rigid ownership purity; the separate generated skeleton ownership record proves which reviewed semantic rules were applied.

For visual semantic review, `tools/homm3_meshy_frame_pose/render_skin_owner_preview.py` produces `owned_bind/skin_owner_preview.png`, coloring each triangle by its rigid owner. Current review shows the head/crown on `Head`, shield-side armor on the shoulder chain, blade on the dedicated `RightWeaponTip` chain, and leg armor on the corresponding leg chains. The blade fix is an explicit semantic corridor from `RightHand` to the authored raised weapon tip; it prevents the main blade islands from remaining on `RightHand` while preserving the rigid hand/forearm pieces. The audit currently reports **13 weapon components / 200 triangles** and **62 owner-vs-nearest-bone exceptions**; the latter is a review signal, not a failure, because armor plates can intentionally be farther from their driving segment than a neighboring body surface. The adjacent torso/neck and hip/spine assignments remain the main review boundary because their rest-pose segments are close; they are now reported with nearest-bone distance margins rather than silently treated as proven.

The regenerated g12 lit preview is under `out_fit/g12_attack_front_rigid_components_fixed_length/preview_lit_60fps/attack_front_g12_fixed_length_lit_loop.gif` with the required 180 ms GIF timing. This is a generated animation preview and bind proof. Unity lab import, the corrected explicit Etalon-compatible material, and the isolated candidate bundle are proven. The candidate was deployed under the live bundle name with SHA-256 `639CC4D58EAFCEB56D7D3DD88E720A992491FD965DF1B6F0F702EB8DA3402A0F` (206,789,941 bytes); it now explicitly contains `OwnedSkinned/Reference/StockEsquireBattle.controller` as a root asset (override base, GUID `f543af776e3f31246926ef1dd671d426`) and `crusader_owned_skinned_basecolor.jpg` as a root asset (2048x2048 albedo; the material sheet itself stays garbage under InternalErrorShader, so the runtime loads the texture by bundle path and stamps it). The 2026-08-10 rebuild additionally carries the seam-blended master mesh and looped/repeated loop-state clips. The stale `custom_units_castle_h3_crusader.backup-before-owned-material-fix-20260809-185316` leftover was removed after the new bundle landed because the fail-closed payload validator flags uncontracted files. The material fix in the deployed DLL rebuilds the runtime sheet from a native Hex/Lit donor (white `_Color`) and loads `crusader_owned_skinned_basecolor.jpg` from the bundle by path; the active DLL SHA-256 is `bada5a4fef046ee6…` (2026-08-10 facing-diag fix build). Fresh startup logged `Homm3ArtifactMeshBundle: validated catalog (155 entries), 20 bundle file(s), and manifest (155 asset(s))`; in-combat runtime proof remains outstanding.

---

## What was tried and why it failed

| Approach | Result | Why insufficient |
|----------|--------|------------------|
| Meshy/Mixamo auto-rig as master | IK previews run | Wrong spine/neck/head; helmet not Head-skinned |
| Right-hand `bridgefix` | Weapon tip improved | Patch on foreign skeleton |
| Head unwrap / crown `jointSites` / posed Nose eval | Nose px metrics move | IK target tweak ≠ deformation ownership |
| `fixed_length_ik` on Mixamo | Lit previews | Transition debt only |
| DEF billboard PNG render → bundle | Renders exist | Wrong OE delivery paradigm |

---

## Next work (ordered)

### Phase A — Owned bind + skin (crusader pilot) — complete

**Delivery output:** `artifacts/crusader_pose_pipeline/owned_bind/crusader_master_rigid_components.glb` + `owned_bind/crusader_skeleton_rigid_components.json`

1. **Input mesh:** `meshes/idle_f0_meshy6_retexture.glb` (unrigged).
2. **Joint placement:** from authored idle f0 landmarks (`idle_attack_front_authored` frame 0 or dedicated idle g2 seed) + mesh AABB bands. Tooling pilot:
   - `tools/homm3_meshy_frame_pose/rig_frame0_shared_skeleton.py --unit-sid h3_crusader --skin-mode rigid_connected_components --ownership-rules tools/homm3_meshy_frame_pose/ownership_rules_h3_crusader.json` — hand-built owned hierarchy plus rigid topology ownership.
   - Optional cross-check: `artifacts/crusader_pose_pipeline/out_articulation/` (80-frame corpus).
3. **Head bone:** tail at **helmet crown** (highest head-region vert or authored Nose projected to mesh), not Mixamo `head_end`.
4. **Weapon:** ensure `RightHand` chain + optional dedicated tip bone owns blade verts (geometric reskin pattern in `reskin_meshy46_from_scratch.py`).
5. **Pauldron boundary:** hand-review weights at shoulder/head — automatic k-blend often bleeds torso into Head.
6. **Export** owned GLB; **strip all Meshy vertex groups** before export.

**Roles file:** `tools/homm3_silhouette_pose_fit/bone_roles_crusader_owned.json`
- `rigFamily`: `hand_owned_mixamo_like`  
- `masterGlb`: `artifacts/.../owned_bind/crusader_master_rigid_components.glb`
- Keep same OpenPose landmark names; `jointSites.Nose` → `highest_skinned_vert` on **our** `Head`.

### Phase B — Bind audit (fail-closed) — complete

```bash
py -3 tools/homm3_silhouette_pose_fit/run_joint_audit.py \
  --master artifacts/crusader_pose_pipeline/owned_bind/crusader_master_rigid_components.glb \
  --roles tools/homm3_silhouette_pose_fit/bone_roles_crusader_owned.json \
  --out artifacts/crusader_pose_pipeline/owned_bind/joint_audit
```

Gate: no collapsed landmarks, crown Nose site on helmet, weapon tip on blade chain. Re-render head rest pose (bind-only, no IK) and compare to `_head_rest_test` — helmet must stay volumetric.

### Phase C — Re-fit clips on owned master — generated-artifact complete

The authored combat set is regenerated against `owned_bind/crusader_master_rigid_components.glb`. The active g12 fit is `out_fit/g12_attack_front_rigid_components_fixed_length/`; all 14 delivery groups have owned-master fit reports, delivery GLBs, and 180 ms lit previews.

1. Duplicate or regenerate `configs/h3_crusader_*_fixed_length_ik.json` to point at `bone_roles_crusader_owned.json`.
2. Re-run **one clip first** (idle attack front g12), then batch:

```bash
py -3 tools/homm3_silhouette_pose_fit/batch_fixed_length_crusader.py --groups 12 --workers 1
```

3. Lit preview at GIF wall-clock (`PREVIEW_GIF_FRAME_MS=180`).

The generated clip gate is passed. Human visual review confirms the head pivot, blade ownership, and shield-side ownership; Unity lab import is proven, while Unity/OE delivery remains the outstanding proof tier.

### Phase D — OE skinned-mesh battle delivery (runtime implementation complete; lane-aware rebuild and deployment proof outstanding)

The runtime lane is now implemented behind an explicit prefab marker. The remaining work is controlled delivery and runtime proof:

1. **Blender → Unity clip baker:** `fixed_length` pose snapshots → `AnimationClip` assets named to stock override contract (`22.Idle`, `01.Walk`, `14.Attack`, `20.Damage`, `21.Damage`, … over `Reference/StockEsquireBattle.controller` or `inquisitor_upg` donor).
2. **Unity lab** (`oldenera_factions/Assets/CustomUnits/homm3_lab/h3_crusader/`): **import/prefab/clip mapping and isolated bundle build proven** by `CrusaderOwnedSkinnedLabBuild` and `BuildCustomUnitBundles`; the generated `OwnedSkinned/crusader_owned_skinned.prefab` has one visible `SkinnedMeshRenderer`, a root `Animator`, and an override controller over `_Battle_Unit_Anim_ctrl_v2`.
   - Remaining lab review: scale, foot placement, and material review against `ESQUIRE_STOCK_VISUAL_CONTRACT.md`; no runtime claim is implied by the isolated bundle.
3. **Runtime:** `Homm3ImportVisuals`, pool/release helper attachment, and attack-direction resolution now distinguish the marker lane from billboard instances. The existing billboard helpers remain untouched for the current live rows.
4. Build the candidate under the live bundle name `custom_units_castle_h3_crusader`, update the Crusader contract after the staged payload passes the bundle/audio contracts, and deploy only that bundle with a timestamped backup. **Complete:** deployed candidate hash is pinned in `custom_factions/contracts/homm3_bundle_payload_contract.json`.
5. **Proof:** battle smoke on Golden Era — Crusader visible as a skinned mesh, all mapped animations resolve, facing/attack direction is correct, and the existing billboard lane remains unaffected. **Startup prerequisite complete:** artifact catalog and chunk-bundle preflight now pass; combat smoke is the remaining proof tier.

---

## Tooling map (quick reference)

| Step | Tool |
|------|------|
| Skill contract | `.cursor/skills/homm3-pose-pipeline/SKILL.md` |
| Meshy mesh only | `generate_meshy_t2_unit_master.py --skip-rig` |
| Owned bind pilot | `rig_frame0_shared_skeleton.py` |
| Geometric reskin | `reskin_meshy46_from_scratch.py` (adapt per unit) |
| Joint audit | `run_joint_audit.py` |
| Fit | `run_fit.py` → `blender_fixed_length_ik.py` |
| Lit preview | `render_fixed_length_lit_60fps.py` |
| **Do not use for ship** | `ship_crusader_pose_to_battle_billboard.py` |

Blender: `V:/Games/actionmesh/tools/blender-3.5.1/blender.exe`  
Host Python: `py -3`

---

## Parallel track: lizardman

Same skill gates. Artifacts under `artifacts/lizardman_pose_pipeline/`. Partial authored clips; **no owned bind yet**. Do not route through billboard ship. Reuse crusader owned-bind script pattern after crusader pilot passes audit.

---

## Proof labels (use precisely)

| Claim | Required evidence |
|-------|-------------------|
| Authorship complete | `*_authored/` + `human_eye_landmark_authoring` |
| Owned bind complete | `owned_bind/crusader_master.glb` + joint audit pass + head rest visual |
| Clip fit complete | `fixed_length` on **owned** master + lit preview |
| Build target proven | Unity bundle builds + isolated candidate manifest/asset evidence |
| OE battle proven | Deploy + in-combat smoke (skinned mesh visible) |

---

## Anti-patterns (do not repeat)

- Batch `fixed_length_ik` on Mixamo and call the unit pipeline complete.
- Tune `jointSites` / head unwrap instead of replacing bind + skin.
- Render mesh to PNG → `Texture2DArray` billboard as “shipping crusader.”
- Launch game without bundle deploy and claim visual ship.
- Commit unless user asks (repo rule).

---

## Related docs

- `docs/crusader_pose_pipeline_first_test.md` — first Meshy/Mixamo pilot (historical; partly stale)
- `tools/homm3_silhouette_pose_fit/README.md` — pipeline goal statement
- `tools/custom_prefab_pipeline/ESQUIRE_STOCK_VISUAL_CONTRACT.md` — vanilla prefab / animator contract
- `docs/custom_town_scene_paradigm.md` — town mesh lane is separate; not battle ship
