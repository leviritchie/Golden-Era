# Roc Per-Frame Skinned-Mesh Selection Trial

This trial runs the existing Roc animation replay against two independently bound
surfaces:

- the flight-shaped `roc_move_bind_t2_v1` candidate;
- the standing/idle `roc_linked_master_idle_bind_v1` candidate.

Both candidates receive the same captured joint motion for every frame in the current
corpus. Each rendered frame is compared with its source sprite using three reported
signals: silhouette IoU, luma-normalized chroma quality, and normalized DINOv2 cosine
quality. The composite is the equal mean of those three values. The higher-scoring
surface is selected into the fourth column of the preview, but only after two
source-conditioned compatibility gates. The first limits relative error in the
projected wing-span-to-torso-width ratio to 25%. The second applies to upright
silhouettes and checks alpha support in source-derived head, breast, and feet
regions; it prevents a compact candidate from being accepted when it hides those
landmarks inside a broad wing shell. This is a regional occupancy compatibility
heuristic, not semantic landmark or occlusion proof. A frame for which neither
candidate passes is reported as `unresolved` rather than being forced to a mesh.

The current run covers 91 frames across all 15 corpus entries, including the two entries
marked unused in the corpus. The idle candidate receives one fixed 180-degree world-Y
facing correction after camera-basis transfer so its breast/beak side is compared with
the source-facing side; this is not a per-frame camera fit. The selector also rejects a
candidate when its robust posed-to-bind edge-strain cost is more than 5% worse than the
alternate candidate, or when its projected height/width aspect differs from the source
by more than 50%, in addition to the earlier limits. It then chose the move surface for
20 frames, the idle surface for 47 frames, and left 24 frames unresolved.
Results are in:

`artifacts/homm3_mocap_v2/roc_mesh_selection_v13/roc_per_frame_mesh_selection.gif`

and the compact contact sheet is:

`artifacts/homm3_mocap_v2/roc_mesh_selection_v13/roc_per_frame_mesh_selection_contact.png`

A 210-degree exploratory yaw was rendered separately as `roc_mesh_selection_v8`, but
was rejected: it improved some beak profiles while causing horizontal flight frames to
select an upright idle surface. The script default remains the accepted 180-degree
correction.

The v13 gate improves rejection behavior for horizontal frames, but it does not prove
that the remaining compact idle winners match the source pose. Those winners still need
a fixed idle-candidate pose correction or a better idle-bind surface before delivery.

## Terminology

The Unity concept is not usually called mesh warping. For different topologies like
these, the accurate term is a **runtime skinned-mesh swap** or **renderer mesh
replacement**: the active `SkinnedMeshRenderer` changes its mesh while the animation
continues. A true blend shape or vertex warp is only available when the topology and
vertex correspondence are compatible. This trial uses hard per-frame selection in a
preview; it does not claim a Unity implementation. In a production Unity setup the
selected surface would be swapped on the `SkinnedMeshRenderer` (with matching bind
pose/skeleton state), not geometrically warped between unrelated topologies.

## Proof boundary

This is generated-candidate visual evidence only. The saved move registration is
rescaled from its recorded renderer resolution to the requested square output, and the
idle candidate is orientation-transferred into the move camera basis so the two scores
are comparable. Candidate joint positions are name-permuted and checked for parity
before replay; each clip still uses the established clip-local hip re-anchor at frame 0.
The report records SHA-256 hashes for the corpus, source frames, captures, both bind
meshes, weight sidecars, and camera registrations. Rendering and DINO encoding both
honor the shared GPU cascade lock. No candidate has been promoted to delivery, and the
score winner is not a substitute for visual continuity review at a swap boundary. The
anatomy gate is an image-space heuristic and is intentionally treated as a diagnostic
guard, not semantic landmark or occlusion proof.
