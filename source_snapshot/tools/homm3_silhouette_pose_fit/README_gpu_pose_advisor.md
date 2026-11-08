# GPU Pose Advisor

The advisor is the proposal lane carried back from the V2 experiment into the
original chromatic notebook. It is not a renderer and it is not a scoring
authority.

At initialization it loads the selected Meshy smart-rig GLB once on CUDA,
keeps sampled skinned surface points resident, and prepares the alpha-shadow-
culled target silhouettes as signed-distance fields. For a candidate pose it
does differentiable FK/LBS and orthographic projection without Blender. The
result is used only to suggest:

- a gradient direction, its opposite, and bounded escape directions for a
  single-bone rotation-vector search;
- a small, diverse Sobol shortlist for the motion-root rotation/translation
  search.

Every proposal is still sent through the original Blender worker and the
original chromatic/depth/DINO/SigLIP objective before it can be accepted or
shown in a preview. The original notebook therefore remains the quality
baseline, while the advisor reduces blind probe work and helps escape poor
root local minima.

The proposal breadth is sensitivity-aware. High projected sensitivity gets
the full escape set, medium sensitivity gets only the direct gradient pair,
and low sensitivity skips the arbitrary coarse vector shell so the existing
multi-bone and near-refinement passes can handle it later. Set
`gpu_pose_advisor_enabled=False` to return to the original search proposals
without changing the exact scorer.

The advisor requires CUDA and fails closed when enabled. It does not import or
invoke nvdiffrast, Eevee, compositor nodes, PNG output, or the V2 optimizer.
