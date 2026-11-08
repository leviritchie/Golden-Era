# Wood elf mesh and bow repair

## Reproduce

```powershell
py -3 tools/homm3_meshy_frame_pose/fit_mesh_rest_pipeline.py --manifest tools/homm3_meshy_frame_pose/wood_elf_rest_fit_pilot.json --review
py -3 tools/homm3_meshy_frame_pose/fit_mesh_rest_pipeline.py --manifest tools/homm3_meshy_frame_pose/wood_elf_rest_fit_pilot.json --preview
```

Outputs: `artifacts/meshy_downloads/meshy71_repair_candidates/h3_wood_elf/mesh-fitted-v2/`.
The body-only comparison is `mesh-fitted-v1/`; the original source inspection is `source_review.png`.
The original source, generated candidate, and saved mocap remain unchanged.

## What changed

The original mesh was an idle-pose biped with a fused held bow. This pilot uses one selective
Meshy 7.1 T-pose candidate (task `01a0be99-7f38-7259-84d9-144672b5aa60`, 8,000 target polygons,
texture/PBR/remesh enabled, no vendor rig). Its source hash is pinned in
`tools/homm3_meshy_frame_pose/wood_elf_prop_attachment.json`.

The shared geometry fitter places the rest skeleton inside this new mesh. The source motion is
the existing 79-frame linked-master capture, using its explicit `linked_master_remaining_scale`
registration. No new mocap or per-frame edits were introduced.

The generated bow lay horizontally behind the waist. Visible-surface points from
`inspect_prop_recipe.py` located both limbs, the grip, and string. A seeded local cut extracts
480 faces, separates 25 contact vertices, rotates the bow into a held orientation, and assigns
it rigidly to `LeftHand`. All 8,203 original faces and their UVs remain. The quiver and clothing
stay on the body. Textured prop-only, body-only, rest-overlay, and animated keyframe views were
inspected, not just the numerical extraction report.

The new inspection tool provides fixed-size textured orthographic views, pixel rulers, exact
visible triangle picking, and prop/body isolation from one command. Its camera centers the
projected bounds, not the vertex mean, so dense heads/props cannot push feet out of the frame.
This is reusable across units and replaces ad hoc coordinate-probe scripts.

## Verification and remaining work

59 focused tests passed, including depth-correct pixel picking, bounds framing, source face/UV
preservation, an exported geometry/normal/texture comparison, and rigid hand-relative bow motion
through all 79 saved frames. The combined still review measured 7.04 seconds, including 0.62
seconds through fitting, repair, and export before rendering. The 79-frame full reel measured
66.03 seconds including 0.66 seconds through export. These are local pilot measurements.

This is a generated candidate, not a deployed game asset. The extracted bow has two connected
components because the generated string was fused through the quiver; a short gap remains in
the string, with small contact remnants near the grip. The mesh has not been rebuilt to invent
that missing string segment. Finger closure, string draw, and draw-hand contact are also not
solved by rigid attachment. Both wooden limbs and the grip move together without skin stretch;
that is the improvement demonstrated here, not a claim of finished weapon animation.
