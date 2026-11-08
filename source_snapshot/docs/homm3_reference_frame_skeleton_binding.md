# Owned bind from an exact animation reference

Status: generated-artifact. The lane is validated for one unit on one clip (`h3_wood_elf`'s
`g00_move`); it now also *runs* end to end on a second unit of a different body plan - a quadruped -
where no clip passes its own audit yet. Not installed, not runtime, not user-visible gameplay.

Owning the bind of an AI-generated mesh used to be pose-blind. `owned_rerig/bind.py` places
joints at AABB fractions of a hand-authored species template, and
`homm3_sprite_motion_track/blender_map_articulation_parts.py` puts hinges on the silhouette
surface and rotates about the camera axis. Neither reads the pose, and both were judged by a
rendered-image score, which is how the Roc reached `incompatible_bind_pose` while every
automated number looked acceptable (`homm3_static_bind_registration.md`).

This lane removes the guesswork where the animation has been *captured* into per-frame 3D
joints and registered onto the mesh, i.e. where the animation is known exactly.

## The exact reference

Three artifacts state the animation, each with its own provenance:

| artifact | states |
| --- | --- |
| `raw_capture.npz` (`pred_position`, `joint_names`, `parents`) | the 3D joint configuration of every frame |
| `idle0_registration.json` (`static_bind_registration.py`) | the capture -> mesh similarity and the source-view camera |
| `master_sequence.json` | which authored DEF plate each capture frame was observed from |

Together they say that for frame `f` the joints are at known 3D positions, that those positions
project to known DEF pixels, and that the DEF alpha is the silhouette those positions produced.
`sanctioned motion interface` is `pred_position`; the vendor's `pred_rot6d` is diagnosis-only.

Two consequences drive the whole design:

* every joint's rest position **in the image plane** is ground truth, so the only free quantity is
  depth - the one axis an orthographic plate cannot observe;
* the acceptance question stops being a score. A wrong joint or a wrongly owned vertex is a
  measurable pixel or silhouette violation.

## What the solver decides

`owned_rerig/exact_bind.py`, one decision per stage, none of them authored per unit:

1. **Reference scale, from the mesh's own extent.** The registration's similarity is consumed but
   its *scale* is re-derived: the reference pose must exactly span the mesh it was generated
   from. A crouched or reclining bind pose is refused, and a fitted scale outside a bounded band
   around the registered one is refused. This is deliberately one equation in one unknown -
   a mean-distance objective was tried and discarded because it is minimised by collapsing the
   whole skeleton into the body core. The identity is a statement about a **biped**, and the second
   unit below is where that stops being an abstraction: a quadruped mesh is legitimately longer than
   it is tall, so for those units the identity cannot choose a scale at all. `scale_source` therefore
   has a second, explicit value, `registered`, which takes the registration's own scale verbatim -
   nothing fitted, no distance searched - and records the extents it did not use and a `scaleCaveat`
   beside the fit. The default stays `extent`, and a pose the identity refuses is still refused
   unless the caller asks for the registered scale by name.
2. **Joint placement on the reference rays.** A joint keeps its exact reference pixel and keeps
   its reference depth unless that depth is not in the flesh; only then does it slide along the
   view axis. Shifts are then reverted, deepest first, until no bone's rest length drifts past
   the bound, because a shifted ancestor can break a descendant's length without the descendant
   moving. A joint that still cannot be made both contained and rigid is reported, never moved
   somewhere plausible.
3. **Skin weights as a function of position.** A vertex's weights are decided by where the vertex
   is - inverse squared-distance to the flesh bones, strongest four - and never by which connected
   patch it belongs to. No partition rule list participates, and no per-unit authored rule either;
   markers (`marker_tokens`) are not candidates, because the capture extrapolates them past the
   surface.

## What acceptance means

For every authored frame the reference joints drive the bind through position-anchored rigid
skinning (each bone's head is anchored on its observed joint; orientation is the minimal swing,
since joint positions do not determine axial twist - `pose_rotation_fk.TWIST_POLICY` is
`minimum_change_prior_not_captured_evidence`). The measured quantities are:

* **`maxOutsideExcess`** - of the vertices the bare mesh already holds inside the bind plate,
  how many the replay pushes out of *this* frame's plate. The null is exactly zero. The budget is
  not a tuned per-clip number: it is raised to the reference's own measured rigidity, because a
  rigid skeleton cannot reproduce joint tracks whose bone lengths move.
* **`referenceRigidity`** - per-bone length excursion across the clip, median and worst. This is
  the floor on any exactness claim, and it gates: a reference whose median excursion exceeds
  `max_reference_median_length_excursion` is refused as not a rigid skeleton.
* **`maxBoneLengthDrift`** - the bind's rest lengths against the reference, i.e. the rigid
  invariant. Zero means the bind can reproduce the animation.
* **joint flesh clearance** - exact point-to-triangle distance from each pivot to the surface,
  not a nearest-vertex sample (a joint in the middle of a coarse mesh is far from any vertex and
  barely off the surface; the repository already records vertex sampling as not
  acceptance-grade).
* **reference joint plate coverage** - a flesh pivot must project onto the silhouette of the plate
  it was captured from, to within the dilation budget. A joint whose capture and plate disagree is
  named, and the bind for that bone is reported unvalidated.
* **rest identity** - the driver must reproduce the bind rest surface exactly, or the bind would
  deform its own rest pose.
* **`tearing` / `cohesion`** - review evidence, not gates. How far the driven surface stretches its
  own edges, and how far it pulls apart vertex pairs that touch at rest. Both are needed: a rule that
  freezes each patch onto one bone lowers the first and raises the second, and measuring only the
  first is how a hole gets shipped as an improvement.

`ok` is `not issues`. The audit also reports `containmentProof`, which is
`open_mesh_proximity_heuristic_unproven` whenever the mesh has boundary edges: a Meshy mesh is
usually not watertight, so containment is surface proximity, not a parity proof.

## Weights are a function of position

The mesh this lane binds is not a surface. `h3_wood_elf` is 7207 vertices in **585 connected
patches** (the largest is 74 vertices) with 5567 boundary edges - and that is an artifact of the
index buffer, not of the geometry. The 7207 vertices stand at **3796 distinct positions**: 5562 of
them (77%, largest group 8) are bit-identical duplicates of another vertex, because the exporter
splits a vertex wherever the UV or the normal changes. Merging the duplicates collapses the 585
patches to **one** patch with 47 boundary edges and loses zero triangles. It is one sheet of flesh,
written down 585 times.

That merge is not the repair and must not be applied. All 2151 coincident groups hold vertices that
differ in *both* UV and normal, so welding would destroy every texture seam and hard edge in the
asset. The repair is in the weights instead, and it is the same fact read the other way round: what
identifies a piece of flesh is not the patch and not the vertex, it is **the position**. So
`skin_by_position_field` computes a vertex's weights as a function of where the vertex is -
inverse squared-distance to the flesh bones, strongest four - and two vertices at one point then
carry the same weights by construction. Measured, the worst gap between coincident vertices is
**0.000 mm on all three clips**, against 168 mm, 83 mm and 873 mm for the label-keyed rules below.

Two earlier rules failed here, and in neither case was the failure the mesh:

* **Per-vertex nearest-bone labels** (`890d12ec6d`). A vertex's candidate set jumped with its nearest
  bone, and a card sitting where two limbs meet had one vertex nearest the left hand and its
  neighbour nearest the right hand; those bones share no articulating bone, so the card was stretched
  between the hands like a rubber band. Measured on the walk: 4111% edge stretch, 91 edges past 10x.
* **One patch, one piece of flesh** (`5fdeb9f84d`). Forcing each connected patch onto a single bone
  did freeze the stretch inside a patch (128 edges past their own length against 934) and opened a
  hole at every seam the label rule had created: 648 seams pulled apart, the worst by 513 mm. Reading
  an exporter's UV splits as topology is what put the holes there - the flesh it pulled apart was
  never disconnected.

Markers are not flesh. `HeadTop_End` and `Toe_End` are Mixamo's terminal markers
(`marker_tokens`), and the capture extrapolates them past the surface, so their tracks carry the
lift's own error (68% bone-length excursion on this unit's right toe). The ownership repair used to
hand a vertex to `RightToe_End` to satisfy "every bone must own flesh", and that vertex was then
dragged by a marker while its neighbours followed the foot: the toes tore at 15x their edge length.
Markers are now excluded as field candidates and exempted from the ownership requirement, which is
what the audit already did for flesh clearance.

Sharpness is the field's one knob, and a sharp falloff is what tears: neighbouring vertices get very
different weights, and the difference between them is the distortion. Measured on the walk, at the
shipped marker exclusion:

| field power | edges past their own length | past 10x | worst stretch | seams opened past 5.1 mm | `maxOutsideExcess` (budget 15.2%) |
| --- | --- | --- | --- | --- | --- |
| 2 (shipped) | **540** | **0** | **910%** | **0** | **4.36%** |
| 3 | 582 | 0 | 828% | 4 | 4.40% |
| 4 | 744 | 0 | 748% | 4 | 4.51% |
| 6 | 1078 | 0 | 692% | 4 | 4.66% |
| 8 | 1262 | 0 | 702% | 4 | 4.90% |

All three candidate artifacts, measured the same way on the same clips:

| clip | artifact | edges >100% | edges >1000% | worst stretch | worst edge growth | seams opened past 5.1 mm | worst gap between coincident vertices |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `g00_move` | per-vertex labels | 934 | 91 | 4111% | 485 mm | 0 | 168 mm |
| `g00_move` | patch collapse | 128 | 5 | 1496% | 170 mm | 15 | 513 mm |
| `g00_move` | **position field** | 540 | **0** | **910%** | **108 mm** | **0** | **0.000 mm** |
| `g02_idle` | per-vertex labels | 133 | 0 | 704% | 77 mm | 0 | 30 mm |
| `g02_idle` | patch collapse | 3 | 0 | 229% | 27 mm | 8 | 83 mm |
| `g02_idle` | **position field** | **0** | **0** | **98%** | **19 mm** | **0** | **0.000 mm** |
| `g15_shoot_front` | per-vertex labels | 1302 | 270 | 7915% | 861 mm | 4 | 104 mm |
| `g15_shoot_front` | patch collapse | 484 | 0 | 855% | 262 mm | 26 | 873 mm |
| `g15_shoot_front` | **position field** | 1657 | 8 | 1713% | 285 mm | **0** | **0.000 mm** |

The honest reading: the field is the only artifact that never opens a seam, and the only one with no
1000%-plus tear on the walk and the idle. On the shoot's large rotations it stretches more edges
mildly than the collapse does, and a few harder. What it trades is stated: median edge stretch rises
from 5.4% to 11.4% on the walk, because flesh now deforms smoothly across every joint instead of
being rigid inside each patch.

Sharpening is not a free correction for the head's detail slip. On the shoot, moving the field from
power 2 to power 4 raises the head region's own share from 0.516 to 0.666 and cuts its slip from 14.2%
to 10.3% of the head radius - and costs 1657 -> 2199 edges past their own length, 8 -> 6 edges past
ten times that, and 748 -> 952 escaped vertices. Neither setting is wrong; they are two points on the
same trade, which is why the delivered artifacts exist in both (`h3_wood_elf_positionfield/` and
`h3_wood_elf_power4/`) instead of one being declared the answer. The gate's budget is unchanged by
this: sharpening does not move `maxOutsideExcess` past it on any clip (4.36% -> 4.51% on the walk,
6.74% -> 9.24% on the shoot, budget 15.6%).

Because tearing alone cannot see a hole, the audit measures the surface too: `audit.cohesion`
(`surface_cohesion.v1`) tracks every vertex pair that touches at rest and reports how far each pair
is pulled apart, with the pairs, the radius and the dominant bones named. That is the measurement
whose absence let the patch collapse ship: freezing a patch onto one bone lowers the stretch of the
edges inside it and opens the seam instead.

Treating the field's smooth blend as a defect is the other way to get this wrong. The head loses 3%
of its own radius on the shoot, which reads as squish, and the field is what causes it: at the
shipped sharpness the 913-vertex head region carries `Head` 0.516, `Neck` 0.215, `LeftShoulder`
0.123, `Spine2` 0.113, `LeftHand` 0.020, so 48% of the head is driven by bones that are not the head
and the region lags its own bone. That is the trade tabulated above, not a fault, and the honest
measure of it is first-order, not radial: `diag_head_slip.py` reports the mean distance from each
head vertex to where the `Head` bone's own rigid transform would put it, as a fraction of the head's
radius. Radial contraction cannot see the difference (0.9696 at power 2 against 0.9659 at power 4 on
the shoot, i.e. no movement at all) while the slip does (14.2% against 10.3%), because a blob of
slightly different rotations contracts only to second order.

## Detecting geometry attached to the wrong part

The question a prop raises is not "is the bind wrong somewhere" - the escape fraction answers that -
but "which geometry is wrong, and what is it attached to". Two measurements answer it, and both are
reported rather than gated: the acceptance null stays exact and unchanged.

**Plate violations, grouped** - `audit.escaping` (`escape_regions.v1`). Acceptance counts escaped
vertices over the whole surface, which is the right null and the wrong diagnostic: a prop fused to
the wrong limb escapes in a small region while the body stays inside, and one number over 7207
vertices hides exactly that. So the vertices that ever leave their own frame's plate are grouped
spatially (union-find, radius `escape_region_radius_frac` x subject height, default 2%), and each
group of at least three vertices reports how many vertices and patches and frames it covers, where it
is in the frame (`centroidPlatePixel`, `bboxPlatePixels`), the bones that drive it, the reference
joint nearest its centroid, and how far outside the plate its vertices sit. What makes it readable is
the pair of fields `drivingBones` and `referenceJointNearestCentroid`: "93 vertices driven by
`RightHand`, where the plate has `RightUpLeg` 0.133 away" is a defect stated as a place and an
ownership conflict, not as a count. Measured on `g15_shoot_front` at the shipped sharpness, 748 of
7207 vertices escape at least once, in 45 regions. The report keeps every region and orders them by
how far outside the plate they reach; the eight largest by vertex count are:

| vertices | patches | frames | centroid plate px | median / max px outside | driving bones | plate has |
| --- | --- | --- | --- | --- | --- | --- |
| 93 | 9 | 9 | 183,225 | 1.0 / 4.5 | `RightHand` (79), `RightForeArm` (12), `RightUpLeg` (2) | `RightUpLeg` 0.133 |
| 71 | 7 | 11 | 181,216 | 2.8 / 5.1 | `RightArm` (63), `RightForeArm` (8) | `RightArm` 0.227 |
| 62 | 12 | 7 | 207,213 | 1.0 / 2.8 | `LeftHand` (62) | `LeftForeArm` 0.366 |
| 55 | 9 | 11 | 212,230 | 5.4 / 7.3 | `LeftArm` (55) | `LeftUpLeg` 0.370 |
| 50 | 5 | 10 | 200,191 | 1.0 / 2.2 | `LeftHand` (50) | `LeftHand` 0.263 |
| 35 | 5 | 6 | 207,232 | 3.0 / 4.1 | `LeftUpLeg` (35) | `LeftLeg` 0.295 |
| 28 | 4 | 6 | 196,191 | 1.0 / 2.0 | `LeftHand` (17), `Head` (11) | `HeadTop_End` 0.251 |
| 28 | 6 | 7 | 200,200 | 0.0 / 0.0 | `LeftHand` (28) | `LeftHand` 0.165 |

**Fusion, measured on the rest mesh** - `diag_bow_ownership.py`. The plate test says where the surface
leaves the art; this one says why, and it reads no weights to do it. Geometry that no bone is near is
clustered (the signature of a prop), and each cluster reports which bones claim it, how many of its
rest edges leave the cluster, how many of those bridge to flesh whose nearest bone is not an
articulation neighbour of the cluster's own, and how far the clip stretches the cluster's own edges.
A prop that is genuinely its own object leaves along **no** edge. Measured on `g15_shoot_front`, the
prop-scale cluster (72 vertices, 10 patches, centroid 0.31 units to the left of the body axis at
chest height, median 0.319 units from the nearest bone) is claimed by `LeftArm` (66) and
`LeftForeArm` (6) and is **fused**: 21 of its edges leave the cluster and 9 of those cross bones the
animation moves apart. Its own edges then stretch up to **431%**, because the arm chain spans it.
That is the bow - and the number is the answer to "is this a weight problem": those 9 edges cannot be
satisfied by any weighting, since a rule that follows one end tears at the other. Its two
alternatives are the two the audit already refuses to choose between: tear, or smear.

What does **not** detect this, each measured so a future agent does not revive it:

* **patch identity** - the mesh has no bow patch; the largest connected patch spans 0.35 units of a
  1.7-unit body, and the bow is ~315 small cards. Keying on the exporter's patch split is also what
  opened 648 seams (`5fdeb9f84d`) and is now forbidden by the contract validator.
* **touching pairs** - only 8 of 5884 vertex pairs that touch at 0.004 x height straddle two labels, so
  a "contact between differently-owned geometry" test is blind to exactly this defect: a small prop
  gets all its vertices claimed at once and reads as rigid.
* **distance to the nearest bone alone** - 46% of this mesh is more than 0.08 x height from every
  bone, because marker extrapolation pushes flesh out, so "far from the skeleton" does not isolate
  the prop; it is only the input to the clustering above.
* **a per-bone envelope radius** - the trial that fed a bone's reach from its own envelope made the
  toe bones claim 16% of the head, 3340 torn edges against 540, and opened seams.
* **sharpness** - the prop regions are not a softness artifact and sharpening makes them worse:
  power 4 lifts the escaped population from 748 to 952 vertices on the shoot and from 830 to 945 on
  the walk, and tearing from 1657 to 2199 edges past their own length.

The boxed overlay draws it: each panel is that frame's own plate at 2x dim with the driven mesh
vertices as dots (green inside the plate, red escaped), the reference joints as cyan dots, and each
escaped region in a yellow box labelled with its vertex/patch count, its driving bones and the joint
the plate has there. `artifacts/homm3_owned_bind/escape_overlay/g15_shoot_front_escapes_sheet.png`
and `g00_move_escapes_sheet.png` (and the matching `.gif`s). The plate-space pixel numbers above are
small by construction: the DEF subject is a 39x77 px sprite, so "5 px outside" is "a fifth of the
subject's own width", not a rounding error.

**Whether a weighting repair can work at all** - `owned_rerig/prop_fit.py`, reported by
`tools/homm3_meshy_frame_pose/prop_region_fit.py` (`prop_region_fit.v1`, run on a delivered bind with
`--bind-dir` so a whole unit set can be swept without re-solving). Knowing *where* a prop is
wrong does not say whether any weighting can put it back, and the cheap way to find out is to try every
flesh bone: each one's own rigid transform against every frame's own plate, which needs no replay audit
and does not weigh the other 7000 vertices. Each region then gets one of three verdicts:

| verdict | meaning | action |
| --- | --- | --- |
| `already_inside_under_the_field` | the shipped field already places it inside every plate | none - it is not a defect |
| `bindable_to_one_bone` | some bone's rigid transform places it inside every plate | bind it rigid to that bone |
| `no_bone_fits_the_plates` | no bone does | nothing weightable; the geometry disagrees with the art |

Two ways to get this wrong are ruled out by the implementation because both were measured. Selecting
the bone by the **global** escaped count moved 2 of 748 vertices while making the region itself reach
*further* outside its plate (7.28 px to 8.49 px), so a 72-vertex region is scored alone. And **far from
every bone is not a defect**: of the two regions the detector found on the shoot, the 40-vertex one is a
prop-sized cluster that the shipped field already keeps inside all 12 plates, so it is reported as no
defect rather than "fixed".

On this unit the verdict for the bow is `no_bone_fits_the_plates`, and that is what makes the rest of
this section decidable: the best of all 22 flesh bones (`RightFoot`) still leaves those 72 vertices
5.0 px outside a plate only 39 px wide, inside on 5 of 12 frames, against the field's 9.22 px. Three
repairs were built and measured against the same audit, and none of them is worth shipping:

| repair | global effect (shoot) |
| --- | --- |
| rigid ownership of the two prop regions | 748 -> 746 escaped vertices, 1657 -> 1655 torn edges |
| cut the 16 triangles that bridge prop and flesh across non-articulating bones | 748 escaped (unchanged), 1657 -> 1635 torn |
| remove the 7 patches no bone can place (70 vertices, 72 triangles) | 748 escaped (unchanged), 1657 -> 1626 torn |
| cut and then bind rigid (the two halves together) | 748 -> 746 escaped, 1657 -> 1620 torn |

Each does what it claims locally - rigid ownership takes the bow region's own worst edge from 5.3x its
rest length to 1.0x by construction, and rigid ownership's *best* choice (by that global count) is what
made the region reach 8.49 px outside - but the worst stretch in every variant stays at 1713%, because
that edge lives in the far-from-bone flesh, not in the prop. The honest reading: the visible artefacts
on this unit are not prop ownership, and the mesh is what has to change. The instrument above is what
decides that per region and per unit, so a re-generated mesh only has to clear the verdicts rather than
be inspected by hand.

**Part-restricted ownership, tested and rejected** - aggressive separation plus strategic weld. The
proposal is to separate the surface into parts, weld back the joints so no hole is left, and let the
parts say which joints a piece of geometry must not be weighted to. It was built on the welded view
(7207 delivered vertices are 3796 nodes), cutting *every* edge between two nearest-bone regions - 675 of
11539 node edges, not only the 5.8% that are spurious - then welding back a boundary when the two sides
share enough of the smaller side's perimeter to be one surface, and then spending the map two ways.

What it found, and why it is not the repair:

* **the weld decision is the whole game, and a permissive weld undoes the separation.** A few welds at a
  small shared-perimeter fraction merge the parts back toward one, and the result returns to the field's
  silhouette - which is to say, to its faults. The Toy Story sweep below measures this across the whole
  fraction rather than at two points, and its numbers supersede the two-point figures quoted here before
  it: at 5% shared perimeter 13 parts survive and the shoot still tears 840 edges past their own length,
  against the shipped field's 1657. At the coarser fractions the only parts that stay separate are the
  hand/prop clusters: 103 vertices allowed only `LeftHand` (the bow), 94 and 47 allowed only `RightHand`.
  That is the same geometry the prop instrument flags, found from the other direction - and binding those
  parts rigidly to the hand tears more, because no bone places them inside their plates either.
* **the head result is real.** The bleed is what makes the head lag: forbidding a bone more than one
  skeleton step from a vertex's own nearest bone cuts its departure from its own bone from 12.1% to
  6.1% (walk) and 14.2% to 8.0% (shoot) of the head radius. Applied as a graded decay
  `exp(-alpha * (steps - 1))` instead of a mask, alpha 0.75 keeps a third of the win (7.6% and 9.5%) at
  the lowest tearing cost.
* **and it is paid for at the joints.** Replacing a smooth blend with near-rigid ownership makes the
  stretch distribution worse at its tail while making it better in the middle: on the shoot, edges past
  their own length *fall* 1657 -> 1052 while edges past ten times theirs rise 8 -> 192 and the worst
  edge goes 17x -> 66x. By the frames' own plates the shipped field still wins (excess 6.74% -> 8.27%),
  and on the walk, where the shipped field is the only variant the audit accepts, restricting ownership
  also drops the per-bone ownership repair (the field is rebuilt per node, so a bone can end up owning
  no flesh).

So the map answers "which elements should not be given weights for certain joints" - the head should
not be driven by a hand, and the bow should not be driven by itself - but spending the answer as
ownership is a trade the plates do not endorse. It is recorded here so it is not rebuilt: the durable
outcome is that **the gentle lever already documented for the head is the better one** (sharpening to
power 4: 14.2% -> 10.3% slip with no new tears, against 9.5% with 192 new 10x tears). Motion A/B for
that judgement: `artifacts/homm3_owned_bind/graded_by_steps/comparison/graded_steps_<clip>.gif` (top
panel graded alpha 0.75, bottom panel shipped), from `artifacts/homm3_owned_bind/emit_graded_variant.py`
+ `exp_part_ownership.py`.

One trap worth naming for anyone working on the welded view: `position_groups` returns the
group representative **per vertex**, so a node-indexed array (a label per node, a position per node)
must be gathered by node id, not indexed through that array. A first run of this experiment mis-indexed
it and produced labels belonging to unrelated vertices, which looked like a catastrophic result rather
than a bug. The corrected run is what is tabulated above.

Proof tier: **generated-artifact**. The detector localises a defect in an exported bind; it does not
prove the bind plays in the game, and it is review evidence, not an acceptance gate.

What is left is not a weight problem. The vertices in the field's worst 100 edges sit a median
**0.257 mesh units from the nearest bone** - 15% of the subject height, against 0.145 for the mesh as a
whole - and their strongest weight is a near-uniform 0.316 spread over four bones, the signature of
geometry that is nowhere near the skeleton at all. Those are stray cards the generator left in the
empty space between limbs, in patches of 4 to 28 vertices; `diag_stray_geometry.py` measures the
separation. Removing or re-generating that geometry is mesh repair, not binding, and it is the
remaining lever on the visible artefacts.

**The rigid-part test, and the weld sweep** - `artifacts/homm3_owned_bind/exp_toy_story.py`. This takes
weights out of the argument entirely: every vertex is driven by exactly one bone at weight 1
(`oneBonePerVertex`), and every vertex of a separated part shares that part's bone. A part is made by
cutting every edge whose two ends are nearest different bones, then welding a boundary back when the two
sides share enough of the smaller side's perimeter to be one surface, so the weld fraction spans "the
whole body is one rigid part" (0.00) through "almost nothing is welded back" (1.00). Walk / shoot:

| weld | parts | escaped | torn edges | past 10x | worst stretch | head slip |
| --- | --- | --- | --- | --- | --- | --- |
| shipped (position field, power 2) | - | 830 / 748 | 540 / 1657 | 0 / 8 | 9.1x / 17.1x | 12.1% / 14.2% |
| rigid parts, weld 0.00 | 1 | 1834 / 2253 | 0 / 0 | 0 / 0 | 0.0x / 0.0x | **181% / 149%** |
| rigid parts, weld 0.05 | 13 | 1222 / 1081 | 864 / 840 | 50 / 164 | 20.8x / 40.8x | 0.16% / 0.12% |
| rigid parts, weld 0.15 | 29 | 1194 / 1193 | 1590 / 1718 | 134 / 318 | 38.8x / 77.9x | 0.16% / 0.12% |
| rigid parts, weld 0.30 | 36 | 1163 / 1195 | 1732 / 1878 | 158 / 356 | 42.2x / 77.9x | 0.16% / 0.12% |
| rigid parts, weld 0.50 | 49 | 1163 / 1193 | 1772 / 1974 | 166 / 360 | 42.2x / 77.9x | 0.00% / 0.00% |
| rigid parts, weld 1.00 | 59 | 1169 / 1189 | 1888 / 2076 | 184 / 386 | 42.2x / 77.9x | 0.00% / 0.00% |

Two findings, and they point in opposite directions.

* **The head squish is a weight problem, not a geometry one.** The head region is 913 vertices with 2181
  internal edges. Under the shipped field its own mean `Head` share is **0.516**; at every rigid rung it
  is **1.000** (0.9956 at the two coarsest weld fractions), and the region then follows its own bone
  exactly: `headSlipMeanOfRadius` falls from 12.05% / 14.19% to **0.00-0.16%**, and
  `headEdgeStretch.sameBone.max` falls from 9.10x / 11.42x to **0.00**, i.e. every head edge keeps its
  exact rest length. So the lag is the field blending 48% of the head onto `Neck`, `LeftShoulder` and
  `Spine2` - the trade tabulated earlier in this document - and no property of the head's own geometry
  forces it.
* **Everything rigid parts fail at is geometric, and finer separation makes it worse rather than
  better.** As one rigid body (weld 0.00) the escaped population nearly doubles (830 -> 1834 walk,
  748 -> 2253 shoot) and containment excess rises to 10.9% / 17.2%, past the shoot's 15.6% budget,
  while tearing goes exactly to zero - nothing stretches because the mesh moves on one bone. Welding
  back at 5% partly restores the field's silhouette and also restores its faults, and tearing then
  *rises* monotonically with separation (864 -> 1888 walk, 840 -> 2076 shoot, 164 -> 386 past ten times
  their rest length): the residual 1169-1195 escaped vertices are the same stray and fused geometry the
  escape regions already name, and a cut edge with a different bone on each side is exactly what
  produces the 42x / 78x worst edge.

Motion A/B for this pass, absolute paths:

* `V:\Games\Olden Era Playtest Tweak\artifacts\homm3_owned_bind\toy_story\comparison\toy_story_vs_shipped_g00_move.gif`
* `V:\Games\Olden Era Playtest Tweak\artifacts\homm3_owned_bind\toy_story\comparison\toy_story_vs_shipped_g15_shoot_front.gif`
* head strips beside them: `head_strip_g00_move_frame4.png`, `head_strip_g15_shoot_front_frame9.png`

Panels per gif: `labels_thr100`, `labels_thr030`, `csr_thr100`, shipped, each audit line read out of its
own rung report rather than typed in.

**Can a wrong weld be detected at all?** - `owned_rerig/weld_topology.py`, run against this mesh and
tested by `tools/homm3_meshy_frame_pose/test_weld_topology.py` on hand-built sheets whose ground truth is
known. The measurement needs no weights, no reference and no threshold: a real seam leaves exactly two
triangles on the shared welded edge and one connected triangle fan around the shared node, while a
coincidence leaves the node carrying two or more fans that meet only at the point (a bowtie), or the
shared edge carrying four triangles (a line contact). The pieces a part rule sees are then counted two
ways - through every welded edge, and through clean edges only - and equality is the threshold-free test
of whether a coincidence changes what a piece *is*.

On `h3_wood_elf` the answer is unambiguous: **one** welded piece; **3789 of 3796** nodes carry exactly one
triangle fan; **0** edges carry more than two triangles; **7** bowtie nodes (22 vertices, extents <= 0.03
units); and joining only across clean two-triangle edges still gives one piece. The 585 index patches are
exporter seams in a single continuous surface, correctly re-welded. (An earlier reading of `patches > 1`
as "multiple surfaces" was wrong and is not repeated here: 51 of the 59 label parts have more than one
patch and it means nothing.)

The consequence is the scope in the module's own docstring: **this can prove a weld bad, never prove one
good.** Where the generator fused two objects into one continuous surface - this unit's bow is part of
the body's own skin - no topology rule can find the weld, because there is no weld to find; only the
reference's own plates can say those vertices must come apart.

**The containment cut, measured** - the same lane, mode `csr`. Every piece no single bone places inside
every frame's plate is cut recursively (tolerance 2.0 px, bone candidates limited to the piece's own
three nearest, the same restriction the per-part plate test applies), those cuts are never welded back,
and each piece then keeps its label bone if that bone places it and otherwise takes the best of its own
nearest bones. Measured: 59 label parts become 70 pieces on the walk with 1891 cut edges, 69 on the shoot
with 1782; **17 pieces / 1204 nodes** are rerouted on the walk and **13 / 1375** on the shoot, while 53
and 56 pieces keep the bone their label gave them.

It does buy silhouette: escaped 830 -> **622** (-25%) and 748 -> **516** (-31%), escape regions 44 -> 44
and 45 -> 33, containment excess 0.0436 -> **0.0291** and 0.0674 -> **0.0352**, head slip 12.05% -> 11.0%
(walk) and 14.19% -> 0.0% (shoot). It also localises the plate-violating population: the per-part plate
test flags 7 parts / 2894 vertices beyond the reference's own 2.5 px slack on the walk and 6 / 2627 on the
shoot, and over the cut pieces that becomes **5 parts / 88 vertices** and **6 / 125**. The large blocks
stay unplaceable either way (`LeftHand` 1029 vertices, `LeftUpLeg` 570, `LeftLeg` 410 on the walk).

And it is paid for in anatomy, which is why it is a lever and not a repair:

| clip | piece rerouted | label bone | to | nodes |
| --- | --- | --- | --- | --- |
| walk | 47 | `Head` | `Neck` | 225 |
| walk | 53 | `LeftShoulder` | `Head` | 269 |
| walk | 45 | `LeftHand` | `Neck` | 65 |
| walk | 61 | `LeftUpLeg` | `LeftForeArm` | 24 |
| shoot | 65 | `LeftHand` | `LeftArm` | 516 |
| shoot | 61 | `LeftUpLeg` | `Hips` | 296 |
| shoot | 68 | `LeftArm` | `LeftUpLeg` | 35 |
| shoot | 46 | `LeftHand` | `Head` | 65 |

Whole-unit containment cannot tell a head from a neck, so a rule that reroutes by silhouette alone
produces exactly these: a `LeftShoulder` piece handed to `Head`, a `LeftHand` piece to `Neck`, a
`LeftArm` piece to `LeftUpLeg`. Bones owning no flesh grows rather than shrinks (`LeftArm` owns no vertex
on the walk once the cut reroutes), and the tearing rises with it - 540 -> 1632 edges past their own
length on the walk, 0 -> 158 past ten times theirs, worst 9.1x -> 48.9x; 1657 -> 1960 and 8 -> 386,
worst 17.1x -> 77.9x on the shoot. Only the rerouted pieces change motion at all - the other 53 and 56
replay exactly as the label region did - so the audit difference above is the reroute, not the cut.

### Part identification: where the owner comes from

Every rule above decides ownership from *geometry*: the nearest bone, or the nearest piece. Both were then
replaced by stronger constructions and measured against the same audit, because "the parts are still not
identified adequately" is a hypothesis with a number attached to it.

**Distance along the surface instead of through the air** - `artifacts/homm3_owned_bind/exp_geodesic_field.py`.
The shipped field measures a straight line from the vertex to each bone segment, and on a body whose arms
hang against it that line crosses air the surface never crosses. Measured: the two rules disagree about
**585 of 3796 nodes (15%)** in one pass. For those nodes the straight line to the bone they left is a median
0.222 units while the *surface path* to that same bone is 0.203 - the straight line was winning by cutting
through air, exactly as suspected. The field is then the shipped inverse-power / strongest-four / trim rule
applied to that surface distance, per welded node and broadcast, so coincident vertices still share one
weight vector (asserted fail-closed). Three passes of core reseeding were also run and are **not** the
honest configuration: the pass feeds its own labels back in as cores and the relabelled count drifts
monotonically (585 -> 795 -> 1020), so the one-pass row is the one to read.

| variant | escaped | regions | torn | past 10x | worst | seams | excess | head slip |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| shipped (walk / shoot) | 830 / 748 | 44 / 45 | 540 / 1657 | 0 / 8 | 9.1x / 17.1x | 0 / 0 | 4.36% / 6.74% | 12.1% / 14.2% |
| surface geodesic, one pass (walk / shoot) | 944 / 1024 | 42 / 46 | 536 / 1592 | 0 / 2 | 8.0x / 10.8x | **2 / 10** | 4.72% / 10.61% | **8.2% / 10.8%** |
| surface harmonic, three-pass cores (walk / shoot) | 930 / 1121 | 46 / 46 | 1548 / 2351 | 44 / 142 | 24.1x / 46.6x | 21 / 48 | 4.63% / 11.24% | 13.3% / 16.6% |

**What this settles.** Fixing the measuring stick does not fix the faults it was blamed for: escapes and
containment excess get *worse*, and the one property the position-keyed design exists to guarantee - the
surface never opens - is lost (2 and 10 seam pairs where the shipped field opens none). It does buy the
stretch tail (worst edge 17.1x -> 10.8x on the shoot) and the head's lag (14.2% -> 10.8%), which says the
air-shortcut mis-assignments were real and were part of what reads as deformation. The reason it cannot win
outright is stated by its own worst relabels: a torso node joined to `RightHand` and a `LeftShoulder` node
joined to `LeftHand`, because when two surfaces *touch*, the path along the surface between them is short
too. Distance, along the surface or through the air, cannot tell "against" from "part of".

**The harmonic (diffusion) family** - the same file. Pinning each bone's own core and solving for the
harmonic function across the welded graph is the smoother, more standard "automatic skinning" field, and it
was measured with the same machinery: it is strictly worse than both the shipped field and the nearest-core
surface rule on every axis (worst edge 24.1x / 46.6x, 44 / 142 edges past ten times their rest length, 21 /
48 seams, and the head's own share of its flesh falls to 0.416 so its lag *rises* to 13.3% / 16.6%).
Softness is not the missing ingredient either: it is the same trade this document already tabulates.

**Ownership from the reference's own motion** - `artifacts/homm3_owned_bind/exp_plate_informed_field.py`.
If geometry cannot decide ownership, the reference can, and the measurement already exists: drive a node
with one bone's own rigid transform in one frame and ask how far outside *that frame's own plate* it lands.
That is `prop_fit`'s prop-region question asked per welded node (3796 x 22 nodes x bones, 8 and 12 frames;
60 059 and 64 383 of the 83 512 node-bone pairs are inside every frame). The shipped field's shape is kept
and each bone's share is multiplied by `1 / (1 + (worstOutsidePx / tolerance)^2)`, so a bone the reference
refutes loses its share to its neighbours *smoothly and per node*, instead of the containment cut's hard
reroute of a whole piece onto a bone the anatomy disagrees with.

| veto tolerance | escaped | regions | torn | past 10x | worst | seams | excess | head slip |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| shipped (walk / shoot) | 830 / 748 | 44 / 45 | 540 / 1657 | 0 / 8 | 9.1x / 17.1x | 0 / 0 | 4.36% / 6.74% | 12.1% / 14.2% |
| 1 px (walk / shoot) | **378 / 385** | 27 / 28 | 1315 / 2641 | 2 / 60 | 11.9x / 37.5x | 5 / 19 | **1.79% / 3.77%** | 11.5% / 12.0% |
| 2 px (walk / shoot) | 529 / 513 | 37 / 34 | 807 / 2066 | 2 / 20 | 11.9x / 30.9x | 3 / 19 | 2.75% / 4.90% | 11.3% / 12.0% |
| 4 px (walk / shoot) | 679 / 598 | 43 / 38 | 598 / 1801 | 2 / 8 | 11.9x / 17.1x | 3 / 8 | 3.14% / 6.04% | 11.5% / 12.0% |

This is the first weighting change in this document that reduces the escape population and the containment
excess at once - 830 -> 378 and 4.36% -> 1.79% on the walk at 1 px, better than the containment cut's
622 / 2.91% - and it does it without the cut's wrong-anatomy reroutes. Two costs are measured rather than
assumed. Tearing rises as the veto tightens (540 -> 1315 walk, 1657 -> 2641 shoot at 1 px), because the
share a vetoed bone gives up is share that used to bridge two bones smoothly. And the surface opens in 3-19
pairs: the agreement factor is read through an integer pixel lookup of the plate distance transform, so two
vertices a tenth of a pixel apart can land in different pixels and get different factors, which is an
artifact of the lookup rather than of the principle - the fix is to smooth the factor over the node graph
(or to sample the transform continuously) before this can be judged on cohesion. The shoot's own veto is
also much the bluntest (`vetoFractionOfShares` 0.30-0.48 against the walk's 0.0002-0.0006), because the
reference itself is inconsistent there: the audit already refuses that clip for putting a forearm off its
own plate, so the veto is refuting bones on the strength of a reference that is partly wrong.

Motion A/B, absolute paths (top panel vetoed at 1 px, middle at 2 px, bottom shipped):
`V:\Games\Olden Era Playtest Tweak\artifacts\homm3_owned_bind\plate_informed\comparison\shipped_vs_reference_vetoed_g00_move.gif`
and `..._g15_shoot_front.gif`; the surface-distance families are beside them under
`artifacts\homm3_owned_bind\geodesic\comparison\straight_line_vs_surface_distance_<clip>.gif`.

**How detailed the mesh is, and how the classification was being drawn** -
`artifacts/homm3_owned_bind/probe_mesh_detail.py`. The colour sheets above read as rough, patchy and
pointy, and that needs separating from whether the owners are right. The mesh's own numbers: 7207
delivered vertices, 7677 triangles, **3796 welded nodes** (3411 duplicates, so one surface arrived as 585
index patches of median 8 triangles), 11 539 node edges against 14 299 raw-vertex edges, and a median
triangle edge of 0.0317 mesh units - **1.44 px of the DEF plate it was generated from**, p90 3.09 px, on a
member 77 px tall. The mesh is finer than the art it came from, so coarse is not what it is. What it is is
*hard-edged*: 2151 of 3796 welded nodes carry more than one authored normal, worst-angle median 36 degrees
with 377 past 90, so the surface is delivered as a segmented shell and will facet even when correctly
shaded. Two real contributors to a rough reading are 545 needle triangles under a quarter of the median
area and 125 patches of fewer than four triangles.

The pictures were the larger contributor, and that is counted rather than asserted. The first sheets filled
each triangle with one flat colour and computed their Lambert term from *projected* coordinates with the
depth axis pinned to zero, which collapses the term to a constant per winding - no shading of form at all.
Across the four classification panels that is **1744-1831 distinct colours over 91 000 painted pixels**
(about 22 bones times two winding tints), and **8** across the entire disagreement panel. They are now drawn
by a z-buffer rasterizer (`artifacts/homm3_owned_bind/shaded_raster.py` + `plot_part_coloring.py`) that
interpolates the region colour and the mesh's own authored normal per pixel, lights the result from two
directions and strokes each label boundary; the same four panels then carry **21 853-24 425 distinct colours
over 89 000 painted pixels**. At the panel's own 7.7x plate magnification one triangle is about 11 px wide,
so an unshaded panel shows the triangulation before it shows the labels.

Sheets, absolute paths. Shaded at the fitted framing:
`V:\Games\Olden Era Playtest Tweak\artifacts\homm3_owned_bind\part_coloring\part_coloring_shaded_front.png`
and `..._side.png`. The same at 2x plate resolution, 3x nearest upscale, without bone labels:
`V:\Games\Olden Era Playtest Tweak\artifacts\homm3_owned_bind\part_coloring\part_coloring_x2plate_front.png`
and `..._side.png`. The unshaded pair they replace is kept beside them as `part_coloring_front.png` and
`_side.png`. Which owners are right is the reader's eye's question; the renderer's job was only to stop
answering it with the triangulation.

### Part identification from appearance, with the surface as a hard constraint

Everything above infers ownership from 3D proximity, and that is the shared reason all of it stalls: a
surface that touches another surface is near it, so no distance - straight, along the surface, or
diffused - can separate "against" from "part of". Two further facts close the geometric family. The
welded graph is a single piece (one triangle fan covers 3789 of 3796 nodes), so there are no authored
parts to recover. And the reference's own plates are silhouettes: they can refute a node driven to the
wrong *place*, but not a node driven to the wrong *limb inside* the silhouette. What is left is
appearance, read by a model that has seen archers, bow limbs and elbows before.

**The method.** Three signals, each doing a job the others cannot:

* **Appearance, lifted from a 2D foundation model.** The textured mesh is rendered from 64 directions
twice - lit, and as flat albedo, because the baked sheet already carries the original render's lighting
and a lit pass invites a model to read lighting as material - at 896x896, and DINOv2-large's patch
tokens are sampled at each vertex's own projected pixel in every view where the surface actually shows
it, weighted by how square-on it faces the camera and averaged over views. 3781 of 3796 welded nodes are
assigned this way; 15 are completed from a neighbour along the mesh graph and none is left with no
evidence. Median 22 of 64 views see a vertex. 29 vertices are visible from *no* direction - the fused
interior - and are named as such rather than folded into the average.
* **The reference's own motion**, as a per-node, per-bone signature: drive the node with that bone's rigid
transform and measure how far outside *that frame's* plate it lands, softened to
`1/(1+(px/tolerance)^2)`. This is the quantity a rigid-part bind is optimised for, and it is the part of
the evidence this project uniquely owns.
* **The surface, as a hard constraint on the clustering.** Agglomerative clustering is constrained by the
welded node graph, so a cluster can only form from pieces that touch. This is what makes the output
"parts" rather than the feature-space blobs the earlier colour clustering produced - the sub-agent found
its 10-means colour clusters each spanning the whole body with 43-232 pieces.

**Contiguity and prop concentration, appearance only** (`artifacts/homm3_owned_bind/appearance_parts.py`).
At 24 parts: **24 of 24 are one connected surface piece**, cutting 9.5% of the 11 539 node edges. The prop
regions the connectivity probe had found are used as *unseen* test regions and concentrate cleanly, all
with `partsTouched: 1`:

| region | nodes | recall into its dominant part | that part's precision |
| --- | --- | --- | --- |
| `bowLowerLimb` | 50 | **1.00** | 0.909 |
| `bowUpperLimb` | 104 | **1.00** | 0.727 |
| `backLeftHipObject` | 32 | **1.00** | 0.727 |
| `backOfHeadObject` | 100 | **1.00** | 0.370 |

Agreement with an independent second opinion - the reference's own best-fit bone per node - is purity
0.726 at 12 parts, 0.754 at 24 and 0.766 at 32. Adding the motion block at weight 1.0 raises purity to
0.771 and 0.805, and it costs something real: the bow's upper limb goes from recall 1.00 to 0.71 at 24
parts and 0.375 at 48, because that clip's reference is itself partly wrong and pulls the bow apart. The
trade is recorded, not settled.

**Does a one-bone-per-part bind beat the shipped field?** This is the number that decides it, and it is
reported held out, because choosing each part's best bone on the frames one then scores on is an
in-sample fit and not evidence (`artifacts/homm3_owned_bind/validate_parts.py`: fit the part bones on half
the walk frames, score on the other half, both directions, same nodes throughout).

| split | rigid part, fitted | rigid part, **held out** | shipped field | per-node oracle |
| --- | --- | --- | --- | --- |
| even frames -> odd | 3.77 | **3.71** | 7.38 | 3.46 |
| odd frames -> even | 3.65 | **3.92** | 8.49 | 3.65 |

Mean plate violation in pixels, lower is better. A 24-part rigid bind is **2.0-2.2x better than the
shipped field** on frames it was not fitted to, and sits within 7-8% of the per-node oracle that no bind
can reach. The fitted-to-held-out gap is small (3.77 -> 3.71 and 3.65 -> 3.92), so the parts are not
overfitting four frames. Whole-clip figures for reference: shipped straight-line 8.56 px, per-node best
bone 3.80 px, rigid part 3.92 px.

**What is not established.** These are plate-violation numbers, not the acceptance audit: escapes,
containment excess, tearing and opened seams have **not** been run on this decomposition, so nothing here
says the rigid part bind is a better bind - only that it fits the reference's plates much better. Three of
the 24 parts have no bone that holds them within 16 px of the plates on the frames they were fitted to, so
a rigid decomposition this coarse still misplaces some surface. The shipped field's number is read as its
dominant bone per node, which is a proxy for a smooth field rather than an exact counterpart. And the
`g15_shoot_front` reference is refused by the clip audit for putting a forearm off its own plate, so a
split whose frames are mostly shoot frames is scoring against a reference that is itself partly wrong.

Sheets, absolute paths, appearance-only at 24 parts beside the shipped straight-line labels:
`V:\Games\Olden Era Playtest Tweak\artifacts\homm3_owned_bind\appearance_parts\parts_vs_shipped_front_896_64v_k24_mw0.png`
and `..._side_896_64v_k24_mw0.png`; what the model's own feature space separates, as PCA colour, is
`...\feature_pca_896_64v.png`; and the multi-view renders it was read from are in
`...\views_shaded_48v_contactsheet.png`. The lane lives in gitignored `artifacts/` and is a measurement,
not a delivery.

**Correction to the held-out plate-fit numbers above, found by using the parts.** The 3.71 and 3.92 px
rows were fitted with ``argmin`` over the bones, i.e. each part took the outright best-scoring bone. That
is not a neutral choice and the toy-story run below measures what it costs: it moves 23 of 48 parts off
their own flesh, including an upper-leg part onto ``LeftForeArm`` and four of the head's own parts onto
``Neck``. So those numbers remain a valid measurement of *what a rigid part can fit*, and they are **not**
evidence of a correct bind - part of that plate fit was bought with wrong anatomy, which is the same
failure this document already records against the containment cut.

### The parts in the rigid-part (Toy Story) bind, and the trade that lives in the bone choice

`artifacts/homm3_owned_bind/exp_toy_story.py` gained an `appearance` separation (via
`--appearance-labels`) that cuts every edge crossing a part boundary and makes each cut weldable, so the
existing weld sweep now walks from one bone for the whole body to the appearance parts, and a
`--bone-source platefit` rule for choosing each part's bone. One bone per vertex, one bone per part,
`g00_move`:

| rung | parts | bone rule | escaped | torn | worst stretch | excess | head slip | head rigid | seams | bones owning nothing |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| shipped | - | smooth field, power 2 | 830 | 540 | 9.10x | 4.36% | 0.1205 | 0% | 0 | 0 |
| geometric rigid parts | 59 | majority | 1169 | 1888 | - | 5.94% | **0.0000** | 100% | - | - |
| appearance rigid parts | 24 | platefit:argmin | **411** | 984 | 21.79x | **1.87%** | 0.1029 | 60% | 0 | 9 |
| appearance rigid parts | 24 | platefit:veto | 1214 | 1109 | 21.79x | 6.67% | **0.0170** | 94% | 0 | 6 |

**What the appearance parts fixed.** At full separation the *geometric* rigid rule was strictly worse than
the shipped field on both axes that matter - 1169 against 830 escaping vertices and 5.94% against 4.36%
excess - and that was the negative this lane had recorded. With the appearance parts and the same rigid
rule, escapes fall to 411 and excess to 1.87%, better than the shipped field on both. Contiguity was never
the problem and is now measured: 24 of 24 parts are one connected surface piece.

**What did not get fixed, and is not a bug.** Head rigidity and plate coverage trade against each other on
this asset. Using the reference to *choose* the bone fits the plates best and gives the head up; using it
to *veto* keeps the head nearly rigid and loses plate coverage to worse than the shipped field. That is the
same attribution this document already reached from the geometric side - the head is a weight problem and
what is left under it is geometry - now reproduced with a decomposition that is anatomically coherent, so
it is not an artefact of bad parts.

**More parts is not the fix.** Sweeping the part count with the plate fit driving the bones:

| parts | escaped | torn | worst stretch | excess | head slip | seams | bones owning nothing |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 24 | 411 | 984 | 21.79x | 1.87% | 0.1029 | 0 | 9 |
| 32 | 413 | 988 | 21.79x | 2.23% | 0.1105 | 0 | 6 |
| 48 | 444 | 1280 | 28.23x | 2.28% | 0.1147 | 4 | 4 |

More parts buys bone coverage (9 bones owning nothing falls to 4) and pays for it on every other measured
axis, including opening 4 seams. So the bones that own nothing at 24 parts genuinely own nothing under a
rigid-part rule, and the earlier open question - coarse parts, or a mesh that does not need 22 bones - is
answered in favour of the parts being the constraint worth keeping.

Motion A/B, absolute paths, four rungs stacked per frame with each caption read from its own artifact's
audit: `V:\Games\Olden Era Playtest Tweak\artifacts\homm3_owned_bind\appearance_parts\comparison\appearance_parts_vs_shipped_g00_move.gif`
and the upper-body still at `...\comparison\upper_body_strip_g00_move_frame4.png`.

Proof tier: **generated-artifact**. Both appearance rungs fail their own audit (`ok: false`): the escape
budget is met by the argmin rung but its tearing tail is 21.8x and `ownershipBeyondReviewLimit` lists
bones the audit thinks reach past plausibility, and the veto rung fails on escapes. Neither is a delivery,
and runtime or user-visible gameplay remains unproven.

Proof tier: **generated-artifact**, and the three lanes above live in the gitignored `artifacts/` experiment
directory - they are measurements that decide a design question, not deliveries. Acceptance is unchanged and
still the frame's own plate coverage, so the veto's better numbers are not evidence of a better scheme
until its own tear and cohesion costs are settled.

### Part identification from texture chroma, and the local normalisation that made it worse

The appearance lane above was brought in to replace geometry as the source of part identity, and its parts
were judged still not good enough, so the simpler rule it was standing in for was built and measured:
`artifacts/homm3_owned_bind/chroma_parts.py`.  No foundation model, no lift, no clustering in a learned
space - only the colour the asset's own baked sheet carries, cut into contiguous regions of the welded
graph.  Four things in it are measured choices rather than preferences, and each is reported by
`probe_chroma.py`:

* **Chroma, not colour.**  The bake is a *shaded* render: its CIELAB L* runs p5 10.6 / median 24.8 / p95
  70.8, so most of the luminance difference between two adjacent nodes is where the light fell, not what
  the surface is made of.  The signal is the (a*, b*) chroma plane.
* **A median per welded node.**  3411 of the mesh's 7207 vertices are UV-seam duplicates, so one welded
  node can be sampled at two different texels.  Of 2151 such nodes, **507 disagree by more than 5 Lab
  units** and the worst by 35.7.  A colour rule cannot classify a node whose own two samples are far
  apart, so the node takes the median and the disagreement is reported instead of hidden.
* **Evidence from a wider ring than the boundary.**  Each node's divisor is the robust spread of chroma
  over its 2-ring, and an edge's weight is the chroma step across it over the quadrature sum of the two
  endpoints' spreads - the noise-model form, not the larger of the two.  The normalisation is also run
  *off* (raw Lab step) so the lane can say whether it earned its place; it did not.
* **Contiguity by construction, and one scale knob.**  Chunks grow by Felzenszwalb-Huttenlocher graph
  segmentation: edges in ascending weight, two components merging only when the edge is no larger than
  each side's own internal variation plus a size term `k / |C|`.  That is exactly "similar colour, judged
  against how much the colour varies there", it cannot emit a disconnected part, and components under 8
  nodes are then absorbed into their cheapest neighbour.

Graded on the same welded graph, the same live bones and the same per-node plate test as the appearance
lane, so the rows are comparable (the shipped straight-line baseline is 8.56 px and the per-node oracle
3.80 px on this clip):

| part rule | parts | cut edges | purity vs reference-best bone | one-bone-per-part plate fit | bones used | largest part |
| --- | --- | --- | --- | --- | --- | --- |
| appearance (DINOv2 lifted tokens), k24 | 24 | 9.5% | 0.754 | **3.92 px** | 10 | - |
| chroma, local-scale normalised, k8 | 24 | 9.4% | 0.703 | 4.12 px | 10 | **1700 nodes** |
| chroma, local-scale normalised, k20 | 17 | 4.7% | 0.618 | 4.54 px | 9 | 2897 nodes |
| chroma, raw Lab step, k8 | 113 | 27.4% | 0.768 | 3.95 px | 15 | 264 nodes |
| chroma, raw Lab step, k48 | 58 | 19.8% | 0.736 | 3.96 px | 12 | 323 nodes |

and end to end in the same rigid-part bind, `g00_move`, one bone per vertex and one bone per part:

| rung | parts | bone rule | escaped | torn | worst stretch | excess | head slip | head rigid | seams | bones owning nothing |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| shipped | - | smooth field, power 2 | 830 | 540 | 9.10x | 4.36% | 0.1205 | 0% | 0 | 0 |
| chroma, normalised | 24 | platefit:argmin | 630 | 1238 | 34.73x | 4.15% | **0.2214** | 8% | 7 | 9 |
| chroma, normalised | 24 | platefit:veto | 1014 | 1506 | 69.50x | 6.31% | **0.2876** | 8% | 7 | 7 |
| chroma, raw Lab step | 58 | platefit:argmin | 431 | 2196 | 92.48x | 2.97% | 0.1271 | 39% | 15 | 4 |
| appearance | 24 | platefit:argmin | **411** | **984** | **21.79x** | **1.87%** | **0.1029** | **60%** | **0** | 9 |
| appearance | 24 | platefit:veto | 1214 | 1109 | 21.79x | 6.67% | 0.0170 | 94% | 0 | 6 |

**The requested normalisation is the wrong normaliser for this asset, and the mechanism is visible.**
Dividing by the local spread discounts a boundary exactly where the texture is busy and inflates it where
the texture is flat, but on this mesh the local variation *is* the anatomy - it is where the surface
changes material and where the silhouette turns - not noise laid over it.  The consequence is measured:
at 24 parts the normalised rule puts 45% (1700 nodes) and 22% (846 nodes) of the mesh into its two largest
parts, and the head's own region sits inside the 1700-node blob.  So its head recall of 0.92 is paired
with a precision of **0.22** and a head slip of **0.2214** - worse than the shipped field's 0.1205, which
is the one axis this whole lane exists to improve.  Switching the normalisation off does not rescue it
either: raw chroma is better on escapes (431) and purity (0.768) and never reaches 24 parts at any scale
(it bottoms out at 58), while tearing 2.2x the appearance parts and opening 15 seams against their 0.

**What the chroma rule does do.** Prop isolation is as good as the appearance lane's - bow lower limb,
bow upper limb, `backOfHeadObject` and `backLeftHipObject` all reach recall 1.00 at the 24-part rung, and
all 24 parts are one connected surface piece.  The failure is in the body's own structure, not in finding
objects that differ in colour from the flesh.  One caveat is inherent and is not a bug: at that rung 507
seam-disagreeing nodes touch 22 of the 24 parts and **220 cut edges sit at a node whose own two UV samples
differ by more than 5 Lab units**, so some of the boundary is the bake's discontinuity rather than the
model's anatomy.

A note for whoever next edits this lane: the first version of the size cleanup seeded its union-find one
node per component instead of one component per segmentation label, which silently replaced the
segmentation with the cleanup and made the part count non-monotonic in `k` (0.25 -> 19 parts, 1.0 -> 158).
The sweep being monotone in `k` is the check that the cleanup is only cleaning.

Motion A/B, absolute paths, four rungs stacked per frame with each caption read from its own artifact's
audit: `V:\Games\Olden Era Playtest Tweak\artifacts\homm3_owned_bind\chroma_parts\comparison\chroma_vs_appearance_vs_shipped_g00_move.gif`
and the upper-body still at `...\comparison\upper_body_strip_g00_move_frame4.png`.  Per-rung previews sit at
`...\toy_story\chroma_platefit_argmin_thr100\g00_move\g00_move.gif`, `...\chroma_platefit_veto_thr100\...`
and `...\chromaraw_platefit_argmin_thr100\...`; the part-colouring sheets against the appearance parts and
the shipped nearest-bone regions are
`...\chroma_parts\chroma_vs_appearance_vs_shipped_front_local_k8.png` and `..._side_...`.

#### The raw-chroma rung across the whole reel

The 58-part raw-chroma decomposition is the best-behaved of the four rules in motion, so it was run over
the entire master reel: every clip whose bind was emitted has its own bone assignment, re-derived by the
same plate fit against *that clip's* frames, which is the favourable case for the rule - the parts are
fixed and only the assignment is per clip.  Each clip's numbers are its own audit, over the native
segment (the idle bookends are one frame each and are audited inside ``g02_idle``):

| clip | frames | escaped | torn | excess of budget | head slip |
| --- | --- | --- | --- | --- | --- |
| `g02_idle` | 8 | 11 | 550 | 0.00% of 4.36% | 0.0333 |
| `g20_move_start` | 2 | 23 | 1784 | -0.51% of 3.22% | 0.0607 |
| `g00_move` | 8 | 431 | 2196 | 2.97% of 15.18% | 0.1271 |
| `g21_move_end` | 2 | 275 | 1628 | **3.07% of 2.64%** | 0.2435 |
| `g01_mouseover` | 11 | 212 | 1864 | 1.90% of 12.20% | 0.0077 |
| `g03_hitted` | 6 | 1456 | 2324 | 6.41% of 18.85% | 0.0916 |
| `g04_defence` | 11 | 1786 | 2046 | 15.32% of 20.92% | 0.2169 |
| `g12_attack_front` | 8 | 4480 | 2204 | **56.04% of 20.40%** | 0.0680 |
| `g15_shoot_front` | 12 | 433 | 2206 | 3.55% of 15.57% | 0.0382 |
| `g05_death` | 5 | 3147 | 2670 | 30.90% of 34.52% | 0.2565 |

**What that says, stated precisely.**  Eight of the ten clips meet their own escape budget and two do not -
`g12_attack_front` at 56.0% against 20.4%, and `g21_move_end` at 3.07% against a 2.64% budget that is tight
because a two-frame move-end is nearly still, so a small excursion is a large fraction of it.  The attack is
the one clip where the rule genuinely fails: 2860 vertices in 307 patches leave the frame's own plate over
7 of its 8 frames, driven by `Head`, `Neck` and `Spine1`, i.e. the torso bends and the rigid parts do not
follow it.  Every clip nonetheless reports `ok: false`, and the reason matters: the issues are dominated by
"bone X owns no mesh vertex" - the expected measurement for a rigid-part rule, already tabulated above as 9
of 22 bones at the 24-part rung - and by the *reference's* own defect where it puts the hand or forearm off
its plate.  Neither is a clip-specific failure.  Tearing is the axis that does not recover: 550 edges past
the review limit on the idle, rising to 2670 on the death, with the worst edge reaching 150x its rest
length on the shoot.  That is the rigid rule's price, not a chroma-specific one, and it is the same tail the
appearance parts pay at 21.8x.

One emit-side fix was needed to run a clip at all and is worth recording, because it is a contract detail
rather than a convenience.  ``emit_variant`` used to take its report template from `h3_wood_elf_positionfield`
**for the clip being rendered**, and a shipped delivery exists only for the three clips that were delivered,
so any other clip failed; inheriting the template's `reference.frameCount` would also have captioned a
12-frame render with an 8-frame report, which the preview refuses by design.  The template now comes from the
clip that contains the **bind frame**, derived from the master sequence's own segment ranges, and
`frameCount`, `bindFrame` and `jointCount` are written from the run itself.  Re-emitting `g00_move` after the
change produced a byte-identical report, so the three existing rungs are unaffected.

Motion reel, absolute path - the master's own 79-frame composition, rebuilt frame by frame from the ten
per-clip previews so the idle bookends land where the native reel puts them (joint names are not drawn;
`--labels 0`):
`V:\Games\Olden Era Playtest Tweak\artifacts\homm3_owned_bind\chroma_parts\reel\chromaraw_reel_g02_idle_to_g05_death.gif`,
with a per-clip still at `...\reel\chromaraw_reel_clip_sheet.png` (start / middle / end of each clip) and
the ten single-clip previews under
`...\toy_story\chromaraw_platefit_argmin_thr100\<clip>\<clip>.gif`.

Proof tier: **generated-artifact**.  Every chroma rung fails its own audit (`ok: false`), the 24-part rungs
on head slip and tearing, the raw rung on tearing and cohesion.  This is a measurement lane in gitignored
`artifacts/`, not a delivery, and runtime or user-visible gameplay remains unproven.

### Rigidization by distance to the skeleton, and the constraint that actually helped

The rule asked for was: the further a vertex sits from *any* bone, the fewer bones it may share, and
the more likely it is to inherit one bone from a mesh-connected neighbour - while vertices close to
a bone keep the field's freedom to blend.  `artifacts/homm3_owned_bind/exp_bone_distance_rigidize.py`
builds exactly that, with the allowed set fed into the lane's existing
`weights_from_allowed`/`exp_part_ownership` producer, so nothing about part identity, colour or a
learned model participates.  It has two separable halves, and they measured in opposite directions.

**The scale has to come from the mesh, not from the anatomy.**  Node-to-nearest-bone distance as a
fraction of subject height runs p5 0.0201, median 0.0759, p95 0.158, max 0.2414 on `h3_wood_elf`, so
a height cut at 0.25 rigidizes **10 of 3796 nodes** - the bow is fused into the hip flesh and is
*close* to a bone, and the whole surface is within a quarter of the subject's height of the
skeleton.  The band is therefore taken from the mesh's own distance quantiles, which keeps the rule
identical and makes the knob mean the same fraction of a unit (58/86 parts from one `k` was the same
lesson in the chroma lane).

**`--min-bones 4 --mesh-trace off` reproduces the delivered field to the digit** - escaped 830, torn
542, worst stretch 9.10, median 0.0521, seams 0, excess 4.36% on `g00_move` - so this harness
measures what the field measures and every difference below is attributable.

**Half one, the count schedule, is a negative.**  Fewer allowed bones further out monotonically buys
head ownership and monotonically pays for it in tearing, at relative slack 8:

| allowed bones out at the rim | 1 | 2 | 3 | 4 (none) |
| --- | --- | --- | --- | --- |
| torn edges | 920 | 696 | 632 | **492** |
| head slip | **0.0789** | 0.0914 | 0.0952 | 0.1004 |

That is the same rigidity-versus-tearing curve the Toy Story lane and the appearance parts already
traced, reached by a different argument - and at the rigid end it costs more than it buys: on the
idle the same setting takes torn edges from **0 to 188** and worst stretch from 0.98 to 7.77, and on
the shoot from 1657 to 1995.  No point on this curve dominated the delivered field.

**Half two, routing the candidates through the mesh instead of through air, is the part that helped**
- on one of the two units.  Same four bones everywhere, no rigid cut, the only change being that a
node may use a bone only if that bone's own core is reachable within 0.16 of subject height *along
the surface*:

| clip | | escaped | torn | worst stretch | median stretch | seams | excess | head slip | audit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `g00_move` | delivered | 830 | 540 | 9.10 | 0.0521 | 0 | 4.36% | 0.1205 | clean |
| `g00_move` | traced | **810** | **456** | **7.24** | **0.0417** | 0 | **3.84%** | **0.1007** | clean |
| `g02_idle` | delivered | 40 | 0 | 0.98 | 0.0068 | 0 | 0.00% | - | refused |
| `g02_idle` | traced | 47 | 0 | 0.98 | **0.0053** | 0 | 0.07% | 0.0385 | refused |
| `g15_shoot_front` | delivered | 748 | 1657 | 17.13 | 0.0506 | 0 | 6.74% | - | refused |
| `g15_shoot_front` | traced | 800 | **1348** | 17.13 | **0.0404** | 0 | 8.33% | 0.1210 | refused |

On the walk it improves every axis at once with **zero seams opened**, which no part rule managed; on
the other two clips it improves tearing and median stretch and gives back a little on escapes and
excess.  **On the quadruped it goes the other way.**  `hota_factory_armadillo` `g02_idle` is the
cleanest bind in this document - escaped 130, torn 35, worst stretch 1.62 - and the same band makes
it 187 / 196 / 3.62, with the count schedule worse still at 514 torn.  Widening the band converges
back onto the delivered numbers exactly (a relative hop slack of 24 or 32, or `--mesh-trace off`, all
give 130 / 35 / 1.72), so the cut is **inert** there rather than harmful once it is wide enough - but
there is no single band that helps both units: the wood elf wants 0.16, the armadillo needs at least
0.32 to stop hurting and is never better.

Three smaller results are worth keeping:

* **A hop is not a fixed amount of surface.**  The useful absolute budget was 8 hops on the 3796-node
  wood elf and 24 on the 5475-node armadillo, because the same hop count spans far more surface on
  the coarser unit.  The distance-along-surface form (`--hop-rule geodesic`) is the portable
  statement; the *useful band* is still unit-specific, which is the honest limit of this result.
* **Inheriting from a neighbour is best done as a flood fill, not a race.**  Letting each rigid node
  take whichever bone's core is fewest mesh hops away is a global race and it is demonstrably wrong:
  diagnosing the worst edges showed nodes sitting on the spine - nearest bone `Spine` - handed
  `RightHand` and `LeftForeArm` at 6 to 9 hops, with the tiny edges between them stretching **48x**.
  Growing the confident region's ownership outward one mesh step at a time, voting and committing a
  level at a time, is the literal reading of "inherit the bone of a nearby neighbor" and measured
  best of the three: at the same band it tore 1532 edges with 5 seams against each node taking its own
  nearest bone (1758, 30 seams) and the hop race (1471, 13 seams), and its head slip was 0.0660
  against 0.0584 and 0.0713.
* **At equal head ownership, tracing halves the tearing.**  The same count schedule *without* the
  surface constraint gives 1165 torn edges at head slip 0.0908; with it, 696 at 0.0914.  That is the
  one clean attribution in this experiment.

**A diagnostic that failed, recorded so it is not tried again.**  The hypothesis was that the
constraint helps exactly where the delivered field reaches nodes with bones the surface barely
connects them to, which would turn "does this unit need the cut?" into a measurement.  It does not:
at the same band the armadillo's field is *more* long-range (41.5% of its weight mass beyond the band,
93% of its nodes) than the wood elf's (6.9%, 34%) and is nonetheless the cleaner of the two.  The
share of long-range influence is not a predictor of whether removing it helps.

Motion A/B/C, three panels on one camera and one registration so only the weights differ (shipped
field / mesh-traced four bones / distance-rigidized far field).  `artifacts/build_bone_distance_reel.py
<unit>` runs **every clip of that unit's own master sequence**, not just the delivered three, because a
rule judged only on `move` and `idle` is not judged: it builds the shipped field for any clip that has
no delivered bind (three for the wood elf, one for the armadillo) so panel one is always the *shipped
rule* rather than a mixture of a delivered artifact and a look-alike, emits and previews both rungs for
all ten clips, and composes per-clip reels plus the whole master sequence in the master's own order with
the idle bookends where the master puts them.  Every step is skipped when its output exists, so an
interrupted run resumes; `--force` re-renders.  Outputs:

* `V:\Games\Olden Era Playtest Tweak\artifacts\homm3_owned_bind\bone_distance_rigidize\wood_elf\master_reel_wood_elf.gif`
  - 79 frames, 1137x400, ten clips plus the idle bookends;
* `...\bone_distance_rigidize\armadillo\master_reel_armadillo.gif` - 101 frames, 2483x400, the same ten
  clip keys on the quadruped;
* `...\bone_distance_rigidize\<unit>\clip_<clip>.gif` and `_sheet.png` for each clip alone (start /
  middle / end as a still);
* the individual single-bind renders behind those: `...\<unit>\shipped_preview\<clip>.gif` and
  `...\<unit>\<rung>\preview_clean\<clip>.gif`.

Panels are **the mesh alone** - no joint labels, no skeleton, no audit caption, no DEF plate - because
all four are evidence about a single rendered bind and are noise when the question is how the surface
moves.  The audit state is still read from each artifact's own report and still refuses to render
without one, so a clean sheet cannot become a flattering one.  Each panel is framed by the same
turn camera direction and the same rest mesh; the panel *width* is that clip's own subject crop, and
since the crop is measured over the deformed frames it can differ by a few pixels between binds, so the
composite pastes every frame onto one fixed-width column per panel (a GIF whose frames differ in size
is mis-rendered by most viewers).

Proof tier: **generated-artifact**.  Every rung in this section happens to pass its own audit on the
wood elf's walk - the first rule in this document that does - but a passing audit here still means
plates and edges, not eyes, and nothing has been installed or seen in the game.  The count schedule
is a measured negative and should not be shipped; the surface constraint is a candidate whose benefit
is unit-dependent and whose predictor is still unknown.

### The canonical T-pose, and the fused prop it names

Every measurement above is pose-relative: the surface is compared to the plate the frame was
captured from, which is an exact null and is blind to a fault whose signature is the same in every
pose.  `owned_rerig/tpose.py` adds a pose where the correct answer is known in advance.  It builds a
canonical T-pose by forward kinematics from the reference's own rest joints **using the reference's
own bone lengths**, so it is a rigid reconfiguration of that skeleton rather than a second,
differently-scaled rig: measured `boneLengthDrift` 6.7e-16, and the driver then applies one swing per
bone, so any distortion it produces belongs to the weights or to the mesh, never to the target pose.
A T-pose is also the pose a bind is normally authored in, so measuring it is the precondition for
re-binding in it.

The direction table is per joint and holds the direction that joint's own **incoming** bone takes.
Mixamo's names are one bone later than the anatomy suggests - `LeftUpLeg` is the hip joint, so
`Hips -> LeftUpLeg` is the short lateral pelvis offset and the *thigh* is what ends at `LeftLeg` -
and reading the table anatomically instead rotates the pelvis 74 deg.  The table is authored, not
inferred: an unknown joint name is a hard error, because a silently half-posed skeleton would produce
a flattering picture of a rig it never tested.

Measured on the delivered wood-elf walk bind (`artifacts/homm3_owned_bind/exp_tpose.py reveal`), with
the shipped field and with a one-bone-per-welded-node control so the blend and the geometry can be
told apart:

| bake | edges past limit | past 10x | worst stretch | worst edge growth | worst as % of height | flipped triangles |
| --- | --- | --- | --- | --- | --- | --- |
| shipped blend | 1533 / 14299 | 26 | 26.5x | 0.459 | **27.0%** | 427 |
| one bone per welded node | 1439 / 14299 | 450 | 125.1x | 1.799 | **105.8%** | 603 |

Two things follow immediately.  The T-pose is a far stronger stress than any clip - median edge
stretch 0.163 against the walk's 0.052 - so it is a diagnostic, not a replacement for the clip audits.
And the blend is *mitigating*, not causing: the rigid rule tears 4x further in absolute terms, so "the
weights are too soft" is not the fault here.

**It names a place, and the place is a prop fused into the flesh.**  Grouping the failing surface by
rest proximity over the welded graph gives, in the shipped blend, two regions on the body's own
**front centre-line**, both driven by the left arm chain:

| region | nodes | vertices | patches | centroid | y | dominant bones | own-edge weight jump |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 146 | 311 | 52 | (0.023, 1.062, 0.072) | 0.95-1.17 | `LeftForeArm` `Spine` `LeftHand` `Spine1` | 0.28 |
| 2 | 317 | 648 | 94 | (0.030, 1.376, 0.033) | 1.16-1.69 | `LeftHand` `LeftShoulder` `LeftArm` `Neck` | 0.24 |

The spine is at `x = -0.10`, so both regions sit ~0.10 to the character's left in front of the torso,
spanning waist to above the shoulder - and the rest left hand is at `(0.252, 1.120, 0.078)`, the same
height and depth.  This is the bow: a structure that must travel with the hand, fused into the chest
and **blended** between the arm chain and the spine.  The `own-edge weight jump` column is what rules
out the obvious alternative reading - the stretch inside these regions is not concentrated on a hard
ownership boundary (0.24-0.28, well under the 0.5 the weight-jump test uses), so it is a smooth blend
between two bones the target pose moves ~90 deg apart.  Across the whole bake, edges that do straddle
a hard change stretch 1.08 mean against 0.40 elsewhere.

That is the answer to "is this a weight problem": **the ownership is wrong in a way no weighting can
repair, because the geometry is one surface.**  The rigid control makes it explicit - collapsing each
node onto its dominant bone takes the same region's worst edge from 0.459 to 1.799 units, because the
region's own nodes split between `LeftHand` and the torso and the tear simply moves to the new seam.
What is needed is for the prop to stop being part of the body.

**Two conventions a reader must not mix up.**  `edge_stretch.v1` here is keyed on *undirected* edges
(each edge one row, `edgeKeying: undirected_unique`), whereas `audit.tearing` stacks the three
directed pairs of every triangle and takes the unique rows, so it counts an interior edge twice, once
per winding.  `median`/`p99`/`max` are identical under both, but `edges` and `edgesPastReviewLimit`
are about doubled in the audit: the same surface is 14299 edges here against the audit's 23031, and
1533 past the limit against its 2441.  And ``position_groups`` returns a **per-vertex** representative
array, so indexing it by a welded-node id silently reads an unrelated vertex - the node's own position
comes from the vertices that share it.  The first version of this module made that mistake, which is
why its regions were reported at the wrong places and with the wrong driving bones while their
stretch numbers were correct.

Motion evidence: `artifacts/homm3_owned_bind/exp_tpose.py reveal` writes
`artifacts/homm3_owned_bind/tpose/tpose_reveal_wood_elf.png` - five rows (rest pose, T-pose, its
stretch map, the rigid control, its stretch map) at three angles on one camera framed on both poses
together - and `tpose_reveal_wood_elf.json` beside it.  The stretch ramp is 0 / 0.1 / 0.3 / 1 / 3x.

Proof tier: **generated-artifact**.  A posed bind and its measurement, not gameplay, not an install.

### Re-binding in the T-pose, and why it is the wrong trade here

The obvious repair the reveal suggests is to re-pose the mesh into the T-pose and author the bind
there, so the field can never hand the bow chest flesh: in a T-pose the hand is ~0.6 units from the
chest instead of lying against it.  `exp_tpose.py rebind` does exactly that - bake the pose in
(rigidizing, triangle-wise, wherever the blend cannot carry it), re-skin with the same
`skin_by_position_field`, and drive all ten clips - and it is a **measured negative**.  Worst absolute
edge growth per clip, in units of a 1.700-unit subject:

| clip | shipped | rebound, repair on | rebound, repair off |
| --- | --- | --- | --- |
| `g02_idle` | 0.98x / 0.019 | 22.04x / 0.281 | 22.04x / 0.281 |
| `g20_move_start` | 5.20x / 0.082 | 26.33x / 0.336 | 26.33x / 0.336 |
| `g00_move` | 9.10x / 0.108 | 25.88x / 0.316 | 25.88x / 0.316 |
| `g01_mouseover` | 15.50x / 0.211 | 21.68x / 0.277 | 21.68x / 0.277 |
| `g03_hitted` | 17.21x / 0.267 | 39.23x / 0.509 | 39.23x / 0.509 |
| `g05_death` | 15.95x / 0.288 | 36.26x / 0.470 | 36.26x / 0.602 |
| `g15_shoot_front` | 17.13x / 0.285 | 20.33x / 0.257 | 20.33x / 0.284 |

The rest of the ten are the same story, and one number settles it: **at the bind frame itself** - the
pose the shipped bind reproduces exactly, stretch 0.0000 - the rebound stretches **21.2x**.  The
emitted artifact is sound (its own rest identity is 7e-8, float32 round-trip included), so this is not
a broken export; it is the cost of the pose.  The mesh's rest pose *is* the DEF frame the mesh was
generated from, and every clip in this unit's set lives near that idle, so a T-pose rest moves the
mesh 60 to 90 degrees of arm rotation away from every frame and each replay now drives a large swing
through the blend.  The shipped bind has nothing to do at the idle - 0.98x - and the rebound has a
whole pose to travel.

**The repair pass is not the cause, and the ablation shows it.**  With the rigidize pass switched off
entirely (`--repair-limit 1000`, rigid vertex fraction 0.000 against 0.498), the worst stretch and the
worst absolute growth are **identical on all ten clips**; only the *count* of edges past the review
limit moves (146 against 259 on the idle, 556 against 920 on the death, 128 against 300 on the walk).
So the worst edge is a place where the blend spans bones the clip moves apart, and rigidizing cannot
touch it, while what rigidizing does buy is a roughly halved torn-edge count - at the price of a bake
that is 5x worse on its own terms (26.5x and 27% of height becomes 125.1x and 105.8%), because
`--repair-limit` defaults to the *review* threshold and 1.0 rigidizes half the mesh (0.498).  The
review limit is a reporting threshold; it is not a repair threshold.

**A check that is confounded, recorded so it is not quoted.**  The mechanism test compares hand-chain
weight share on the vertices the blended bake flings.  It reads 0.429 shipped against 0.485 rebound
and says nothing either way, because the mask is indexed by vertex and the bake *moves those very
indices*: after re-posing, those indices are the bow in its new, correct place at the hand, so a high
hand share is the expected answer rather than a failure.  A weight comparison across a geometry change
has to be keyed on something that survives it.

The conclusion is narrower than "T-pose before binding is good practice".  It is good practice when
the animation set is authored *for* the T-pose, which is the usual case and is not this one.  Here the
generator emitted the mesh in the pose of the sprite it was made from, the clip set is the same idle
and its neighbours, and the bind that matches that pose is the one with the least work to do.  What
the reveal justifies is **separating the fused bow**, not re-posing the whole mesh.

**The motion evidence, and how it was checked.**  Two GIF families sit under
`artifacts/homm3_owned_bind/tpose/`, emitted by `exp_tpose_gifs.py`: `sweep/tpose_sweep_yaw{000,040}.gif`
and `replay/replay_<clip>.gif` plus `replay/replay_master_wood_elf.gif`.  They are local review artifacts,
not deliverables - `artifacts/` is gitignored - so a reader who needs them re-runs the driver.  Both are
mesh-only (no joint labels, no skeleton, no DEF plate), which is what the review asked for.

The sweep drives the reference from its own rest pose to the canonical T-pose and back, 21 steps
ping-ponged to 40 frames, three panels: the shipped blend, the one-bone-per-welded-node control, and the
shipped blend coloured by local edge stretch.  Intermediate poses interpolate each bone's *direction*
with its rest length held, so the rig is rigid at every step and any distortion in the picture belongs to
the mesh rather than to the interpolation.

The replay drives all ten cycle clips through the shipped bind and through the rebound, two panels per
frame, in the master sequence's own order - 79 frames including the idle bookends - plus one GIF per clip.
The left panel is always the shipped blend and the right always the rebound, whose regression the table
above measures; what the replay adds is that the regression is *visible at rest*, before any clip has done
work.

Because these were accepted without a viewer, the acceptance is numeric and re-runnable
(`verify_tpose_gifs.py`): 13 GIFs, every frame rasterising to one canvas size (a GIF whose frames differ
in size is mis-rendered by most viewers), no two consecutive frames byte-identical, no blank panel (ink
0.097-0.159 per replay panel, 0.15-0.29 per sweep panel), and the two replay panels differing by 2.5-4.2
mean levels, so two different binds are actually being drawn.  The shipped panel moves in every clip
(median consecutive-frame difference 0.89 on the idle to 2.91 on the hitted), which is the claim the
replay exists to support.  Frame counts match the master manifest exactly, per clip and in total.

Proof tier: **generated-artifact**.  Replays of an emitted bind, not gameplay and not an install.

### Regenerating the mesh in a T-pose, instead of re-posing it

Re-posing the existing mesh is a negative because the mesh's rest pose *is* the pose it was generated in.
The way around that is not to re-pose the mesh but to ask the generator for a different one: meshy-7
image-to-3D from the unit's own still with ``pose_mode="t-pose"``, everything else in the missing-mesh
recipe unchanged (standard topology, adaptive-medium remesh, 4K PBR, ``remove_lighting=false``).
`artifacts/homm3_owned_bind/tpose/gen_tpose_mesh.py` is that request and nothing else; the result is
21867 vertices / 14291 triangles, and its span over its own height is **1.002 against the shipped mesh's
0.449**, so the request changed the pose rather than being ignored.

Binding it needs no new solver, but three things are load-bearing:

- **The T-pose is built in the mesh frame, not the capture frame.** `CANONICAL_T_POSE` names directions in
  the character's own frame, and this capture is yawed ~45 deg and pitched ~15 deg relative to the glTF
  frame - the only frame where `up` is +Y. Built there and pulled back through the registration's own
  similarity, the pose is exact: bone lengths return unchanged to 7e-16, and the fitted T-posed skeleton
  spans 0.951 of its height against the mesh's 1.002, i.e. the arm span lands where the mesh's arms are.
- **The T-pose is appended as one extra capture row, and the bind frame points at it.** `bind_frame`
  indexes the whole capture while `frames` and `alpha` are the *selected segment*, so the appended row
  must sit past the capture's own length and `frames` must not be touched - and mutating the bind row in
  place instead would have replaced the first frame of the idle reel with a T-pose.
- **The scale is re-anchored by the same extent identity, and lands where the shipped bind's did.**
  Fitted 1.0629 against the registered 1.1983, which per unit of mesh height is **0.5594 against the
  shipped bind's 0.5618** - 0.4% apart, so the reference sits in the sprite exactly as before and every
  plate-based measure below stays comparable.

The fit is sound: mean joint-to-surface distance falls from 0.4872 to **0.0567** (3.0% of height) with the
worst joint `LeftHand` at 0.242 - that hand holds the bow - and the emitted bind reproduces its own rest
pose to 2.2e-16. The audit returns one issue, `the reference places a flesh pivot off the plate it was
captured from`, which the shipped bind's own idle audit reports identically: it belongs to the capture and
the sprite, not to this mesh. Its reviews are ordinary for an AI mesh (21243 boundary edges, 28.7% of the
bare mesh already outside the idle plate, which is what a T-posed silhouette does to an idle sprite) plus
8 escape regions reaching 2.8 px past a plate and 101 vertex pairs opening by 0.0609.

**Driving the same ten clips through both binds is a trade, not a repair.** The two panels are *not* the
same mesh: the shipped one is a browser SmartRig export and the regenerated one is a raw API output, and
those two pipelines do not split vertices alike. Across the inventory the SmartRig exports run ~0.9
vertices per triangle (wood elf 7207/7677, `h3_amalek` 6986/7692, `h3_arch_devil` 7216/7882) while the raw
API outputs run ~1.5-2.0 (this one 21867/14291, `h3_boar` 16237/11157, `h3_crystal_dragon` 24776/12622),
and their triangle counts differ here by 1.9x. Absolute edge growth and torn-edge *counts* both move with
triangulation - a shorter edge grows fewer units for the same strain - so the resolution-independent
number is the stretch **ratio**, and the torn count is only meaningful as a fraction of each mesh's own
edges (23031 / 42873).

| clip | shipped ratio | T-posed ratio | shipped growth | T-posed growth | shipped torn | T-posed torn |
| --- | --- | --- | --- | --- | --- | --- |
| `g02_idle` | 0.98x | 9.17x | 0.019 | 0.088 | 0 (0.00%) | 289 (0.67%) |
| `g20_move_start` | 5.20x | 9.39x | 0.082 | 0.112 | 67 (0.29%) | 332 (0.77%) |
| `g00_move` | 9.10x | 10.40x | 0.108 | 0.124 | 219 (0.95%) | 305 (0.71%) |
| `g21_move_end` | 5.41x | 9.35x | 0.083 | 0.106 | 72 (0.31%) | 345 (0.80%) |
| `g01_mouseover` | 15.50x | **12.21x** | 0.211 | **0.118** | 697 (3.03%) | **359 (0.84%)** |
| `g03_hitted` | 17.21x | **13.52x** | 0.268 | **0.181** | 964 (4.19%) | **634 (1.48%)** |
| `g04_defence` | 16.63x | **15.96x** | 0.248 | **0.169** | 898 (3.90%) | **546 (1.27%)** |
| `g12_attack_front` | 16.24x | **11.11x** | 0.174 | **0.143** | 582 (2.53%) | **648 (1.51%)** |
| `g15_shoot_front` | 17.13x | **12.02x** | 0.285 | **0.117** | 886 (3.85%) | **430 (1.00%)** |
| `g05_death` | 15.95x | 25.51x | 0.288 | 0.339 | 1109 (4.82%) | 1698 (3.96%) |

The pattern is structural, not incidental: **a clip improves exactly when its limbs are already away from
the body.** The five action clips gain - worst-case strain down from 15.5-17.2x to 11.1-16.0x, marginal on
`g04_defence` (16.63x to 15.96x) and largest on `g15_shoot_front` (17.13x to 12.02x) - and the torn-edge
fraction is roughly halved to quartered, because an extended-arm frame is *closer* to a T-posed rest than
to an idle one. The near-rest clips pay for it, and the idle pays most: 0.98x to 9.17x and 0 torn edges to
289, because every idle frame now carries the 60-90 deg of arm travel the T-pose moved away from it. The
death clip gains on the torn fraction (4.82% to 3.96%) and loses on both magnitudes.

**What this does not establish.** The gain is not yet attributable to the pose alone, because the two
panels differ in mesh instance as well as rest pose, and the confound runs in the direction of the result:
a finer triangulation is expected to reduce absolute edge growth on its own. The ratio column is the one
that survives that objection and it carries the same verdict on the five action clips, so the pose reading
is the better explanation available rather than a proven one. Settling it needs a **matched-pipeline
control**: the same request with `pose_mode` omitted, so the only difference from the right panel is the
pose. That is one more generation and it has not been run. The version is not the difference and cannot be
tested from the repository either way: the GLBs record only the Blender exporter (`Khronos glTF Blender I/O
v4.5.51` on the shipped SmartRig, `v4.4.55` on the API output), the browser-route doc names no model, and
meshy-7 is documented for the missing-mesh, city and map-building lanes rather than for the SmartRig batch.

So the regeneration is worth having for an animation set that lives away from rest, and it is the wrong
trade for this one, whose reels are built around an idle the mesh was generated in - the same conclusion
as the re-pose experiment, reached from the other side. What it does establish is that the reference is not
the constraint: its own arm chain is 0.398 / 0.366 of its height (an ordinary human proportion) and the
regenerated mesh's arm span agrees with it to 6.6% (extent ratio 0.934), so a unit can be bound from a
fresh generation of any pose as long as the pose is named before the field is solved.

Motion evidence: `artifacts/homm3_owned_bind/tpose/tpose_mesh/reel/yaw000` and `yaw040`, per clip and as a
79-frame master, left panel the shipped bind and right the T-posed mesh, each panel framed by its own
camera because the two generators normalise height independently (1.700 against 1.900). Checked without a
viewer, as before: every frame one canvas size, no two consecutive frames identical, no blank panel, and
the two panels differing by 3.2-5.3 mean levels.

Proof tier: **generated-artifact**. A bind emitted and replayed from both meshes, not gameplay.

### The mesh's own surface: what reassembling it does not buy

The suspicion this lane inherited was that its mesh was too broken to bind - 5567 boundary edges over 7677
triangles, read as a triangle soup whose patches could not be held together. Both halves of that reading are
now measured, and the first half is wrong.

**It is not a soup, and it is not holes.** 7207 delivered vertices become 3796 when vertices at one point are
merged, and the 5567 boundary edges become **47**. The splits are *normal* splits, not UV splits: not one of
the 7207 vertices carries two UVs, but 2151 of the 3796 welded nodes are hard-edged by their own authored
normals, and a glTF vertex is duplicated wherever a normal changes. So the surface was always one continuous
sheet delivered as 585 index patches (`artifacts/homm3_owned_bind/retopo/topology_shipped.json`, and
independently in Blender through the MCP, which is the only place bmesh can see it as the importer builds it).

**What the merged surface does say is where the geometry is fused.** Its Euler characteristic is **-66**, so it
carries about **34 independent handles** - tunnels through the solid. A hand-authored character has almost
none, and a handle is exactly what a wrong fusion looks like once it has been melted into one skin: the bow
that leans on the thigh and the thigh it leans on, joined by a neck of geometry. That is the detection rule
this lane had been missing, and it is cheap, threshold-free and needs no reference:
`weld_topology.weld_topology` already reports the two-count comparison that tells a real seam from a
coincidence, and it cannot see this - a *fused* junction leaves no topological trace at the junction. The
characteristic is what sees it, and it is a property of the whole surface rather than of any one edge.

**Separating a fusion is a scale measurement, not a rule.** Voxel remesh samples the mesh as a volume, so a
neck thinner than the grid does not survive it and comes back as two shells. Sweeping the grid
(`stage2_voxel_sweep.json`) separates the props without touching the body:

| voxel (fraction of height) | shells | boundary edges | χ | reading |
| --- | --- | --- | --- | --- |
| 0.020 (1.2%) | 4 | **0** | 4 | four genus-0 shells, watertight; the body plus three thin props |
| 0.015 (0.9%) | 7 | 0 | 6 | |
| 0.010 (0.6%) | 8 | 0 | 6 | ~5 handles survive; detail no longer lost |
| 0.008 (0.5%) | 10 | 0 | 6 | |
| 0.006 (0.4%) | 9 | 0 | -4 | |
| 0.004 (0.2%) | 2759 | 0 | 5510 | the grid is finer than the surface: the mesh shatters |

The 0.020 rung is the least aggressive one that separates anything, and what it peels off is three slivers -
84, 24 and 8 vertices, of 0.03 x 0.03 x 0.27 and thinner - sitting at chest height beside the body: the
bowstring and arrow shafts. That is the measurement the earlier part-segmentation attempts were reaching for
with colour and distance, and it is separable by a scalar.

**Binding it anyway changes nothing, and that is the result that matters.** The weight rule's own docstring
claims the splits cannot matter - weights are a function of *position*, with a fail-closed check that two
vertices at one point carry one set of weights (`coincidentWeightMismatch`). Measured, on the shipped mesh
against the same geometry with only its duplicated vertices merged (mean distance to the original surface
0.000000), each audited clip:

| clip | mesh | boundary | `tearing.max` | past limit | weight jumps | `poseExcursionPx` |
| --- | --- | --- | --- | --- | --- | --- |
| `g00_move` | shipped | 5567 | 9.095 | 540 | 2074 | 19.709 |
| `g00_move` | welded | 47 | **9.095** | **540** | **2074** | **19.709** |
| `g02_idle` | shipped | 5567 | 0.980 | 0 | 2074 | 2.125 |
| `g02_idle` | welded | 47 | **0.980** | **0** | **2074** | **2.125** |
| `g15_shoot_front` | shipped | 5567 | 17.128 | 1657 | 2074 | 28.334 |
| `g15_shoot_front` | welded | 47 | **17.128** | **1657** | **2074** | **28.334** |

Bit-identical strain on all three clips. The 3411 duplicated vertices - the whole of the "triangle soup"
accusation - contribute exactly nothing to the deformation, because no rule in this lane keys on patch
identity. `escaped` and `maxOutsideExcess` move only because the vertex *population* changed (7207 -> 3796),
so the same geometry is a different fraction; every reference-side field is unchanged, which is what makes the
comparison a control.

This is the same conclusion the crusader lane reached from a fit score and a shipped competitor
(`crusader_owned_bind_skinned_mesh_handoff.md`: the soup is fine, the weights were the problem, and Meshy's own
rig ships the same soup). What is new here is the instrument: an exact-reference audit says it to the last
digit instead of within noise, and it says it for a lane whose rule *cannot* be patch-keyed.

**Through the harness, the rebuilt surface does not improve the bind.** Two voxel rungs were carried all the
way (`stage3_retopo.json`, `build_retopo_glb.py`, `clip_matrix.json`); `r02` is the 0.020 rung, `r01` the
0.010 one at 43986 vertices:

| clip | audit | verts | boundary | contains | escaped | excess | stretch ratio | past limit | weight jumps |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `g00_move` | shipped | 7207 | 5567 | proximity, unproven | 4.97% | 4.36% | 9.095 | 540 | 2074 |
| `g00_move` | `r02` | 10090 | **0** | **parity available** | 7.53% | 6.77% | 11.409 | 1758 | 624 |
| `g00_move` | `r01` | 43986 | **0** | **parity available** | 7.14% | 6.40% | 18.937 | 7238 | 370 |
| `g02_idle` | shipped | 7207 | 5567 | proximity, unproven | 0.45% | 0.00% | 0.980 | 0 | 2074 |
| `g02_idle` | `r02` | 10090 | **0** | **parity available** | 0.99% | 0.64% | 4.058 | 14 | 624 |
| `g02_idle` | `r01` | 43986 | **0** | **parity available** | 0.85% | 0.58% | 5.191 | 484 | 370 |
| `g15_shoot_front` | shipped | 7207 | 5567 | proximity, unproven | 6.81% | 6.74% | 17.128 | 1657 | 2074 |
| `g15_shoot_front` | `r02` | 10090 | **0** | **parity available** | 10.24% | 10.12% | 41.951 | 4200 | 624 |
| `g15_shoot_front` | `r01` | 43986 | **0** | **parity available** | 9.73% | 9.62% | 39.891 | 15236 | 370 |

Three things to read, and one not to.

*The improvement is a label, not a proof.* `containmentProof` flips from
`open_mesh_proximity_heuristic_unproven` to `closed_mesh_ray_parity_available`, because a watertight mesh
makes a parity proof *possible* - which is what the source's own review note asks for ("remesh before
treating containment as proven"). Nothing consumes the flag yet: the audit still measures surface proximity,
so a rebuilt mesh is a prerequisite for that proof, not the proof.

*The ratio column is a resolution artifact and must not be quoted across meshes.* `tearing.max` is
`|posed/rest - 1|` per edge, so halving the edges roughly doubles what the worst one can do, and the three
rungs show it monotonically on the same shape: 0.980 (3796 nodes), 4.058 (10090), 5.191 (43986) on the idle,
where the welded control at the shipped resolution reproduces the shipped number exactly. `edgesPastReviewLimit`
scales with triangle count for the same reason. Absolute growth is the comparable column, and on it the
rebuilt surface is better on 8 of 10 clips, level on `g00_move` (6.56% of height against 6.35%) and worse on
`g05_death` (23.4% against 16.9%) - see `reel/r02_comparison.json`. The one thing the rebuild genuinely buys
is weight *continuity*: edges straddling a weight jump of more than half fall from 9.0% of the mesh to 1.0%
(`r02`) and 0.14% (`r01`), which is the axis a uniformly sampled surface should improve and nothing else.

*The fault is not in the surface.* The escaping population is the same geometry on all four meshes (the worst
frame's regions are driven by `LeftLeg` and `LeftFoot`), and the reference-side refusals are identical to the
pixel: `g02_idle` and `g15_shoot_front` still refuse on the reference's own hand, `RightHand` at 3.4 px off the
plate it was captured from, on every mesh. A restful clip's audit remains clean (`g00_move`, no issues).

Motion evidence: `artifacts/homm3_owned_bind/retopo/reel/yaw040`, per clip and as a 79-frame master, left panel
the shipped bind and right `r02`, each driven at its own audited similarity and framed by its own camera.
Verified without a viewer: one canvas size per file, no two consecutive frames identical, both panels inked
and moving, the panels differing by 3.1-4.7 mean levels, and the two silhouettes covering 13.5% against 13.0%
of their panels. The rebuilt panel is ~17% darker at the median while carrying the same texture (verified
byte-identical base-colour image) and the same mean Lambert term (0.234 against 0.252): voxel remesh is a
smoother surface, so the fine relief that catches light on the original is gone, and the panel differs the way
a lower LOD does. The bow still stretches in both panels.

Commands, in order: `blender_stage1.py` .. `blender_stage4.py` through `tools/blender_mcp/probe.py code`,
then `build_retopo_glb.py`, then `bind_from_exact_reference.py --mesh <rung> --clip <clip>`, then
`reel_retopo.py --rung r02`, then `verify_tpose_gifs.py --dir <reel>`.

Proof tier: **generated-artifact**. Meshes built, bound, audited and replayed; not installed, not runtime.

## Measured: `h3_wood_elf`

Reference: `artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs/h3_wood_elf`, mesh
`artifacts/meshy_downloads/h3_wood_elf_smartrigged.glb` (7207 vertices, 7677 triangles, 5567
boundary edges).

Two independent checks locate the registration's scale error. The published registration places
the 25-joint skeleton with `scale = 1.1983`, spanning 2.133 mesh units on a mesh that is 1.700
tall; its own `skeletonPlacement.reason` is `null` and it was accepted. The extent identity needs
`scale = 0.9550` (`correctionFactor 0.7970`), which is also where the mean exact surface distance
from the reference joints to the mesh has its minimum, and it lifts joint plate coverage from
11/25 to 22/25. Every report records the registered and fitted scales so the correction is visible.

| clip | frames | issues | `maxOutsideExcess` | budget | reference rigidity (median) | `maxBoneLengthDrift` |
| --- | --- | --- | --- | --- | --- | --- |
| `g00_move` | 8 | none | 4.36% | 15.2% | 15.2% | 0% |
| `g02_idle` | 8 | `RightHand` 3.4 px off plate (budget 2.5) | 0.00% | 4.4% | 4.4% | 0% |
| `g15_shoot_front` | 12 | `RightForeArm` 3.9 px off plate (budget 2.5) | 6.74% | 15.6% | 15.6% | 0% |

Read this as: the solver is doing its job - 25 bones taken from the animation's own joint tree,
rigid invariants exact, rest pose exact, and a locomotion replay that stays inside the plates -
and the remaining blockers are upstream, in the reference itself:

* the capture's hand and forearm joints leave the silhouette of the very plate they were captured
  from on the clips where the arm is held against the body (measured against a binary plate, so
  it is not an alpha-threshold artifact);
* the reference's bone lengths move by 15% at the median on moving clips and up to 92% on one
  forearm, so no rigid skeleton can reproduce those tracks exactly. The audit reports this as the
  budget it uses rather than hiding it behind a tolerance.

Neither is a bind defect, and neither is fixable inside the bind solver: a capture/plate
disagreement cannot be resolved without another observation. The correct behaviour is the one
implemented - name the joint, name the number, refuse.

## Measured: `hota_factory_armadillo`

The second unit was picked to attack this lane's own authoring assumptions rather than to add clip
count, so it is not a biped: the `hota_factory` quadruped, mesh
`artifacts/meshy_downloads/hota_factory_armadillo_smartrigged.glb` (8376 vertices, 10956 triangles,
5156 boundary edges, 5475 welded nodes, one 4096x4096 baked sheet). Its reference
(`artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs/hota_factory_armadillo`) is the **same
25-joint mixamo capture** as the wood elf - same joint names, same ten clips - registered at scale
2.2626, bound at frame 0, over 101 master frames at 83.33 ms. Holding the capture fixed is what makes
this a test of the body plan and the mesh rather than of the capture.

### The upright identity is a biped statement

`fit_reference_scale` re-derives the scale from "an upright bind pose spans the mesh it was generated
from", and on this unit it **hard-refused**: the reference's own extents at the registered scale are
`x=1.9889 y=1.3259 z=2.0866`, so the vertical axis is not the dominant one, while the mesh is
`x=1.8929 y=1.7000 z=3.0450` - genuinely longer than it is tall. A quadruped is not a crouched or
mis-scaled biped, and no rescaling makes its bind pose upright; refusing was the correct answer to
give.

`ExactBindParams.scale_source` is the explicit second option, and `extent` remains the default.
`registered` takes the registration's own scale verbatim - `fittedScale` equals `registeredScale`,
`correctionFactor` 1.0, `anchorAxis` null, nothing fitted and no distance searched - and writes into
`scaleFit` the extents it did *not* use (`extentRatios` here: x 0.9517, y 1.2822, z 1.4593) and a
`scaleCaveat`, so any containment number built on that similarity carries the mismatch in its own
report rather than in a reader's memory.

**That the registered scale was the right one here is measured, not assumed.** The shipped
position-field bind built on it comes out mild: `g02_idle` escapes 130 vertices, worst 2.2 px outside,
excess 0.88% of an 8.48% budget, 35 edges past the tearing review limit, worst stretch 1.6176 - and
**21 of the 25 reference joints sit fully on their own plate**, with 22 bones owning flesh. On the
wood elf the same artifact reported 11 of 25 joints on plate *before* the extent identity corrected a
20% scale error (1.1983 registered against 0.9550 needed). The two units disagree in the informative
direction: the elf's registration was wrong and the identity caught it; this quadruped's registration
is right and needs no identity. `test_exact_reference_bind.py` pins the distinction - the same
non-upright pose is refused under `extent` and accepted, verbatim and caveated, under `registered`.

What no scale choice fixes is the reference itself. On all ten clips the same nine joints are reported
not to be flesh pivots - `Hips` 0.3213 from the surface, `RightToeBase` 0.4144, `RightHand` 0.2771 and
six more, against a 0.1989 limit - because a biped mixamo tree does not sit inside a quadruped's body.
The shipped field reports those identical issues, so they are the floor under every bind on this unit
rather than a property of any weighting.

### The chroma rule on a quadruped

The rule needed nothing new for this unit: the welded graph is built from the mesh's own triangles
when no edge file is given, so a mesh the appearance lane never saw still segments. (The DINOv2
appearance lane itself was **not** run here, so this section compares the chroma rung against the
shipped field and against the wood elf, nothing else.)

At the rung the reel used (raw Lab step, `k=48`) this mesh yields **86 parts of 5475 nodes**, each one
connected surface piece, with a one-bone-per-part plate fit of **1.63 px** against a per-node oracle's
1.41 px and the shipped straight-line baseline's 12.25 px. Four things carry over from the wood elf
and one does not:

* The same knob is not the same partition: `k=48` gives 58 parts on the elf and 86 here, so
  `--target-parts` is the portable control and `k` is not.
* The head is again the worst-owned region: 82 head nodes at recall 0.4024 and precision **0.0244**,
  sitting inside a 1354-node dominant part.
* About seven parts in ten straddle the reference's own nearest-bone regions on *both* units - 59 of 86
  parts here, 41 of 58 on the wood elf - which is the same statement as "these are colour regions, not
  anatomical units".
* The 24-part rung is a giant blob here too (`local_k16` gives 23 parts with one holding 5208 of 5475
  nodes, purity 0.30), so that failure belongs to the rule rather than to the unit.
* The sweep **is** monotone in `k` on this mesh, at both normalisations (255 -> 45 parts over `k` 4 ->
  96; 261 -> 3 over `k` 0.5 -> 32), so the size cleanup was inert here. It is still not inert in
  general: the wood elf's own label set is not monotone (`local_k12` 16 parts, rising to 17 at `k16`,
  then collapsing to 4 at `k24`), which is the cleanup pass the note above describes.

No prop regions were configured for this unit, so the prop-recall column is not measured on a
quadruped at all - and a quadruped is where the fused-weapon problem this lane cannot yet detect would
next be looked for.

### The reel, and what it costs

Every clip of the master reel was emitted with its own bone assignment - the parts are fixed and the
assignment is re-derived per clip by the same plate fit against *that clip's* frames - then previewed
and chained into the master's own 101-frame composition. Each clip's numbers are its own audit over
its native segment (the one-frame idle bookends are audited inside `g02_idle`):

| clip | frames | escaped | torn | excess of budget | head slip | head rigid | bones owning nothing |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `g02_idle` | 12 | 112 | 3279 | 0.74% of 8.48% | 0.3045 | 0.28 | 2 |
| `g20_move_start` | 2 | 265 | 3186 | 2.34% of 3.09% | 0.6052 | 0.28 | 1 |
| `g00_move` | 8 | 726 | 4600 | 4.97% of 11.94% | 0.4203 | 0.44 | 2 |
| `g21_move_end` | 2 | 235 | 3126 | 1.92% of 3.42% | 0.6573 | 0.28 | 1 |
| `g01_mouseover` | 17 | 612 | 4666 | 3.18% of 17.27% | 0.5799 | 0.28 | 2 |
| `g03_hitted` | 7 | 523 | 3974 | 4.21% of 8.94% | 1.0250 | 0.44 | 3 |
| `g04_defence` | 9 | 531 | 4008 | 4.69% of 12.42% | 0.5855 | 0.44 | 2 |
| `g12_attack_front` | 10 | 1459 | 5126 | 5.61% of 26.17% | 0.6450 | 0.44 | 1 |
| `g15_shoot_front` | 17 | 5039 | 5360 | 31.16% of 147.66% | 2.0088 | 0.49 | 7 |
| `g05_death` | 11 | 1663 | 4738 | 9.62% of 32.24% | 0.9269 | 0.28 | 2 |

**Ten of ten clips are inside their own escape budget** - the first time this rule has managed that -
but read the budget column before the excess column. On seven clips the budget is 3.1% to 17.3%, which
is the reference's own measured non-rigidity and therefore a tight bar, and the excesses there run
0.74% to 4.97% of it. On `g12_attack_front`, `g05_death` and `g15_shoot_front` the reference's own bone
lengths move 26.2%, 32.2% and 147.7% at the median, so the budget is dilated to nearly the motion
itself and "inside budget" is weak evidence on those three.

Tearing is where this unit's answer differs from the wood elf's, and it is the axis the rigid rule does
not survive. Against the shipped position field on the *same* clip and the same reference - 35 torn
edges, worst stretch 1.6176 - the rigid rule tears every clip past the review limit (3126 to 5360
edges) and pushes 4522 of them past ten times rest length on the shoot, with the worst edge at 203x
rest length, while leaving 1 to 7 of the 25 bones owning no flesh where the field leaves none. The
escapes are a different *shape* too. The armadillo's 1459 escaped vertices on the attack sit in 147
listed regions - groups of three or more escaping vertices within one region radius, 2% of subject
height; smaller specks are not listed - with the largest only 18 vertices, driven by `LeftForeArm`, and
the shoot's 5039 sit in 524 regions; the worst violations are 7-9 px. That is spread along arm and toe
boundaries, not the wood elf's single 2860-vertex region driven by `Head`, `Neck` and `Spine1`. The
shipped field's escapes are smaller still: 130 vertices in 11 listed regions, none longer than 3
vertices, reaching 2.2 px at worst.

Every clip still reports `ok: false`, and for three reasons that are not clip-specific failures of the
rule: the nine biped-reference joints that are not flesh pivots on this mesh, the bones a rigid-part
rule leaves unowned, and on three clips the reference's own non-rigidity past the 25% gate.

**So on this unit the rigid rule is not the better bind, and it must not be reported as one.** It edges
the shipped field on escapes and excess (112 against 130, 0.74% against 0.88% on the idle) and loses
decisively on tearing, worst stretch and bone coverage (3279 against 35; 12.07 against 1.6176; two
bones unowned against none). The wood elf's rigid rungs at least bought silhouette for that price; on
the one clip where both bindings can be compared against the same reference here, the field is simply
cleaner. What this unit contributes is the scale finding above and a second body plan showing the lane
runs - not a recommendation. The shipped field's own head slip is not in the artifact at hand, so the
head columns above are the rigid rule's numbers rather than a comparison.

Motion reel, absolute path - the master's own 101-frame composition at 80 ms, joint names not drawn:
`V:\Games\Olden Era Playtest Tweak\artifacts\homm3_owned_bind\chroma_parts_armadillo\reel\chromaraw_platefit_argmin_thr100_reel_g02_idle_to_g05_death.gif`
(1272x418, 18 MB), with a half-scale companion `..._small.gif` (763x251, 8.4 MB) and a per-clip still
at `...\reel\chromaraw_platefit_argmin_thr100_reel_clip_sheet.png`. Single-clip previews are under
`...\artifacts\homm3_owned_bind\toy_story_armadillo\chromaraw_platefit_argmin_thr100\<clip>\<clip>.gif`.

Proof tier: **generated-artifact**. The reel is an experiment rather than a delivery, every clip fails
its own audit, and runtime or user-visible gameplay remains unproven.

## Usage

```
py -3 tools/homm3_meshy_frame_pose/bind_from_exact_reference.py \
  --run-dir "artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs/h3_wood_elf" \
  --out-dir "artifacts/homm3_owned_bind/h3_wood_elf/g00_move" \
  --clip g00_move
```

`--power` sets the sharpness of the position field (default 2; the sweep and the head trade are
tabulated above, and the script refuses a non-positive value). Everything else in the report is
independent of it, so the two delivered lanes differ only in the weights they export.

`--scale-source` decides where the scale anchor comes from. `extent` (the default) is the identity
above, and it refuses a bind pose that is not an upright stance. `registered` takes the registration's
own scale verbatim, for units whose bind pose is legitimately not upright, and writes the
`extentRatios` and the `scaleCaveat` that go with it. It must be passed to the preview as well as to
the bind build, or the preview re-derives a different scale and refuses the artifact.

The scope is one clip **segment**, not a DEF group. A linked-master reel repeats the idle plate as
a bookend around every other clip and the capture assigns those repeats different poses (measured
7.2 px apart on identical pixels), so a group filter would hand the audit several mutually
inconsistent references for one plate. The loader refuses duplicate plates outright. Exit code is
`0` only when the audit is clean.

The Meshy armature inside the source mesh is never consumed: the solver reads positions and
indices only, and the report records `meshHadVendorSkin` / `ignoredVendorSkin`. The mesh is bound
in its own frame; reorienting it would silently invalidate both the registration and the camera,
so the camera carries an explicit `world_frame` and a mismatch is refused.

## Seeing the bind play

```
py -3 tools/homm3_meshy_frame_pose/preview_exact_reference_bind.py \
  --run-dir "artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs/h3_wood_elf" \
  --bind-glb "artifacts/homm3_owned_bind/h3_wood_elf/g00_move/owned_bind.glb" \
  --out-dir "artifacts/homm3_owned_bind/h3_wood_elf/preview" --clip g00_move
```

It writes `<clip>.gif` and `<clip>_sheet.png`. Each frame is two views of one deformation: the
plate camera (frame N's own authored DEF plate behind the driven mesh and its skeleton), and a
fixed three-quarter turn framed once on the rest mesh so the motion reads as motion.

Four flags change what is drawn without changing what is *checked*, and each defaults to the evidence
view above:

| flag | `0` omits | why |
|---|---|---|
| `--caption 0` | the per-frame audit caption | the caption is drawn *over* the render (a bottom rectangle, `CAPTION_H` per line), so it cannot be cropped off; the verdict is still read from the report and a bind with no report still refuses to render |
| `--skeleton 0` | both skeleton overlays, and the joint labels with them | `face_labels` requires `args.skeleton`, so `--skeleton 0` removes the labels whether or not `--labels` is set |
| `--plate 0` | the left plate panel, the `GUTTER`, and the `pixel_outside` entry | renders only the turned mesh view, which is what a comparison sheet wants; the plate panel is this tool's own evidence that the mesh lands on the art, not a presentation view |
| `--labels 0` | the joint names (with `--skeleton 1`) | - |

The three drawing flags are verified by counting their exact colours in the lossless `_sheet.png`: with
the flag off the sheet holds **0** pixels of `CAPTION_H`-fill `(16,16,20)` and **0** of the skeleton's
`(255,235,60)` / `(255,90,40)`, against 104,920 / 19,227 / 3,846 for the wood elf and 132,865 / 57,409 /
6,300 for the armadillo with them on; `--plate 0` halves the canvas (236x400 against 478x400, i.e. one
panel instead of one panel plus a 6 px gutter plus a second).  Note that a frame whose subject does not
reach the bottom edge also ends in a uniform dark band, so "a dark band at the bottom" is not by itself
evidence of a caption - comparing render to render is.

Surfaces are textured per pixel from the mesh's own baked 4096x4096 base colour, with the authored
normals rotated by the driver's own bone transforms. Two earlier mistakes are worth naming because
each produced a misleading picture:

* shading a face with one flat colour read off the DEF plate. The plate is a 39x77 px sprite, so the
  whole body resolved to a few thousand texels and everything read as blocky - that was the render,
  not the asset;
* the exported bind GLB dropped `NORMAL` (and the texture `sampler`). The source mesh carries
  authored normals across 7207 vertices of which only 3796 are distinct positions, so 77% of its
  vertices share a position with another vertex holding a different normal. A consumer that has to
  invent normals cannot recover those hard edges, and on a 585-patch mesh there is nothing to
  average across a patch seam either. The writer now carries `NORMAL` and the samplers, and the
  contract validator pins both.

The source mesh is genuinely hard-edged - that is the Meshy bake, not a rendering fault - so some
faceted edges survive an honest render.

The plate panel is cropped to the subject because the DEF figure is a 39x77 px sprite inside a
450x400 canvas; the crop is a pure orthographic crop of the registration's own camera, so the mesh
still lands on exactly the pixels the audit measured.  The plate drawn behind frame N is frame N's
own plate, not the bind plate: showing the bind plate behind a walking frame would imply
containment against art that frame was never measured against.

The preview refuses rather than flatters:

* the delivered `owned_bind.glb` is read back and its node graph must reproduce the fitted reference
  rest pose (measured `2.8e-17`), so a stale or foreign skeleton cannot be drawn;
* the sibling `owned_bind_report.json` must name the same capture, registration, mesh, bind frame,
  frame count, vertex count and fitted scale, so the caption's verdict belongs to this artifact;
* a view that rasterises no surface, or a mesh that lands mostly off the drawn DEF art, is an error
  rather than a quietly blank picture.

The caption's audit state is read from that report, never guessed from the clip name.  The idle and
shoot binds are captioned `refused-by-audit` because they are: their audit names a hand or forearm
pivot outside its own plate.  That is the honest state of those clips, not a rendering fault.

| clip | frames | audit | max joint travel | moving frame pairs | mesh pixels off the drawn plate |
|---|---|---|---|---|---|
| `g00_move` | 8 | clean (excess 4.36% of 15.18%) | 0.540 (RightToe_End) | 7/7 | 14.1% |
| `g02_idle` | 8 | refused: RightHand 3.4px off plate | 0.070 (HeadTop_End) | 7/7 | 9.1% |
| `g15_shoot_front` | 12 | refused: RightForeArm 3.9px off plate | 0.626 (RightHand) | 11/11 | 18.8% |

Travel is in mesh world units against a 1.700-unit subject.  The last column is a coarse
screen-space companion to the audit's exact point-to-triangle test (a blended coarse mesh over
pixel-art alpha is not a parity proof); it is reported to catch a framing error, not to accept a
bind, and its alarm threshold is 50%.

Proof tier: **generated-artifact**.  A preview is a picture of an exported bind driven by its
reference; it is not gameplay, not an install, and not evidence that the unit animates in the game.

## Open items

* The T-pose reveal names the fused bow (two regions on the body's front centre-line between the waist
  and the shoulder, driven by the left arm chain, with no hard weight jump inside them). **Separating
  that prop from the torso is the open repair** - the reveal says the geometry is one surface, so it is
  a geometry change and not a weighting one. Re-posing the whole mesh into the T-pose and re-binding
  there is measured as a **negative** and should not be retried: see the re-binding subsection above.
* Re-capture, or exclude as markers, the hand and forearm joints that leave their plates; until
  then the idle and shoot binds for this unit are reported unvalidated.
* The reference's non-rigidity is the dominant limit on replay fidelity. A rigid re-fit of the
  capture, or a per-frame rigid projection, would tighten the budget and make the moving-clip
  test far sharper.
* Twist remains unresolved by construction. Driving with the capture's own rotations would test
  it, but that lane is diagnosis-only and would change what the acceptance measures.
* The mesh has 5567 boundary edges in 585 patches, so containment is proximity, not proof. A weld
  would let the parity path run, but it cannot be applied to the delivered asset without destroying
  its texture seams and hard edges (all 2151 coincident groups differ in both UV and normal) - the
  bind no longer needs it, because position-keyed weights need no connectivity. What is still needed
  is a re-generated mesh at a higher plate resolution.
* The field's remaining stretched edges are stray cards that sit far from every bone
  (`diag_stray_geometry.py`: median 0.257 units against 0.145 for the mesh). Repairing or re-generating
  that geometry is the next lever on the visible artefacts; a weight rule cannot fix geometry that
  belongs to no limb.
* The prop defect is now localised, and what to do about it is decided by measurement rather than by
taste. The bow region is fused into the flesh by 21 rest edges, 9 of them across bones the animation
moves apart, and its own worst edge reaches 5.3x its rest length because the arm chain spans it
(`diag_bow_ownership.py`). No
weighting can repair it: of all 22 flesh bones the best still leaves it 5.0 px outside its own plate in
7 of 12 frames, and the three repairs that follow from that idea (rigid ownership, cutting the bridging
triangles, removing the patches) move 2 escaped vertices of 748 and at most 31 torn edges of 1657. The
fix is mesh-side, and `prop_region_fit.py` is the accept instrument for it: a re-generated bow has to
come back `bindable_to_one_bone` or `already_inside_under_the_field`.
* Per-object rigidity is the rule this lane cannot write yet. "One connected patch, one bone" is
  forbidden because it reads the exporter's UV split as topology, and it would not fix the bow anyway -
  the bow is 10 patches, so per-patch rigidity leaves it shearing card to card. What a rigid prop needs
  is object identity that the mesh does not carry, and `weld_topology.py` shows why topology cannot
  supply it here: the unit is one welded piece with one triangle fan at 3789 of 3796 nodes, so a fused
  prop leaves no trace at all. The containment cut is the reference-side substitute for that identity,
  and its measured cost is tabulated above.
* Median edge stretch is higher under the field (11.4% against 5.4% on the walk) because flesh now
  deforms across every joint instead of being rigid inside a patch. If that reads as too soft, the
  field's sharpness is the knob and its effect is tabulated above.
* Part identity is still the open problem this lane has not solved, and every rule tried so far is a
  negative on this asset. Geometric rigidity is strictly worse than the shipped field; DINOv2 appearance
  parts are better than the shipped field but not clean at joints; texture chroma finds props as well as
  the appearance lane does and fails on the body's own structure, and the local-variation normalisation
  asked for makes it worse, not better; and rigidizing by distance to the skeleton is a negative whose
  rigid end costs more tearing than the head ownership it buys. What is left untried is a rule that uses
  the *reference* to decide part identity - a piece no single bone places is not one part - which is what
  the containment cut approximates and what its measured cost, tabulated above, says must be done more
  cheaply.
* The distance experiment's one positive is not about parts at all: constraining a node's candidate
  bones to those the *surface* connects it to improved the wood elf's walk on every axis with zero seams
  while keeping all four influences, and it needs no part identity, no colour and no model. Its problem is
  that it is inert-to-harmful on the quadruped and no predictor of which unit it helps has been found
  (the long-range-influence share was tested and does not discriminate). Pulling that thread - a
  per-unit criterion for whether the cut will help - is the cheapest open lead in this document.
* The lane has now run on two units of different body plans, but only *run*. The armadillo adds a
  quadruped's mesh and the failure of the extent identity; it does not add a third body plan, and it
  reuses the wood elf's own 25-joint capture, so the reference-side defects are shared rather than
  independently varied. The appearance (DINOv2) part lane and the prop-region fit instrument have
  both still only ever run on `h3_wood_elf`. Nothing in this lane has been installed or seen in the
  game.

## Gates

* `tools/homm3_meshy_frame_pose/preview_exact_reference_bind.py` - renders a delivered bind playing
  its reference clip (manual visual aid; not a gate, and not an acceptance path).
* `tools/homm3_meshy_frame_pose/prop_region_fit.py` - per prop region, whether the shipped field
  already places it inside the plates and whether any single bone can (`prop_region_fit.v1`). Source is
  `owned_rerig/prop_fit.py`, tests are `tools/homm3_meshy_frame_pose/test_prop_region_fit.py`; the
  module's public names and its two measured traps are pinned by the source contract below.
* `tools/validate_homm3_reference_frame_bind_contract.py` - source contract; wired into the
  `OfflineUnlockMod` build as `ValidateHomm3ReferenceFrameBindContract`.
* `tools/homm3_meshy_frame_pose/test_weld_topology.py` - whether the welded node graph is a surface and
  whether a coincidence is load-bearing, on fixtures whose ground truth is constructed: a seam-split sheet
  that must stay one piece, a point contact and a crossed line contact that must not, sheets apart, a
  wall-seamed corner, and fail-closed on malformed input. Source is `owned_rerig/weld_topology.py`
  (`weld_topology.v1`), whose scope - it can prove a weld bad, never prove one good - and its two verdict
  strings are pinned by the source contract above.
* `tools/homm3_meshy_frame_pose/test_exact_reference_bind.py` - 25 tests against a synthetic unit
  whose ground truth is constructed, not estimated: scale recovery, the two scale sources (a
  non-upright pose refused under `extent`, accepted verbatim and caveated under `registered`, and an
  unknown value refused), rigid replay, acceptance on a consistent reference, coincident vertices
  sharing one weight vector, markers owning no flesh, the cohesion measurement, an escape region
  named as a place with its driving bone and the joint the plate has there (and the escape list
  reported untruncated), and fail-closed on a corrupted reference, a drifted bone length, a joint
  outside the flesh, a reference that is not single-valued, and a rejected registration.

## Status summary (moved from AGENTS.md, 2026-10-01)

This is the index-level summary that used to sit in root `AGENTS.md`, kept verbatim. The sections above are the authority.

Owned bind for AI-generated meshes from an *exact* animation reference (registered mocap capture + DEF plates) is owned by `tools/homm3_meshy_frame_pose/owned_rerig/exact_bind.py` + `pose_source.py`, driven by `tools/homm3_meshy_frame_pose/bind_from_exact_reference.py`, and documented in `docs/homm3_reference_frame_skeleton_binding.md`. Acceptance is the frame's own DEF coverage, never an image score; weighted by an inverse-distance field over position, never by the exporter's patch split, and marker bones own no flesh; the audit reports tearing, `surface_cohesion.v1` (seams opening) and `escape_regions.v1` (plate-violation groups naming the bone that drives each region and the reference joint the frame's plate actually has there) beside containment. Field sharpness is `--power`, and the head/tearing trade it buys is tabulated in the doc rather than settled. Whether a prop region can be bound at all is decided per region by `tools/homm3_meshy_frame_pose/prop_region_fit.py` (`owned_rerig/prop_fit.py`), which tries every flesh bone's rigid transform against every frame's own plate and reports `already_inside_under_the_field` / `bindable_to_one_bone` / `no_bone_fits_the_plates`. Part/label-based ownership restriction (aggressive separation + strategic weld, hard mask or skeleton-step decay) was built and measured too: it halves the head's lag but multiplies extreme joint tears, so it is recorded as a negative in the doc rather than shipped. The rigid-part ("Toy Story") pass settles the attribution behind that negative: one bone per vertex removes the head's lag entirely (head slip 12.1% / 14.2% -> 0.00-0.16%, head edges back to their exact rest length) while separating parts raises escaped vertices and tearing monotonically, so the head is a weight problem and the residue is geometry. Whether a weld is wrong is only ever provable *bad*: `owned_rerig/weld_topology.py` (`weld_topology.v1`, test `tools/homm3_meshy_frame_pose/test_weld_topology.py`) measures this unit as one welded piece with one triangle fan at 3789 of 3796 nodes and no edge carrying more than two triangles, so the bow fused into the skin leaves no topological trace. The containment cut (cut wherever no single bone places a piece inside every frame's plate, then reroute that piece) buys silhouette - escaped 830 -> 622 walk and 748 -> 516 shoot, excess 0.0436 -> 0.0291 / 0.0674 -> 0.0352 - by handing `LeftShoulder` flesh to `Head` and tripling tearing, so it is a lever, not a repair. Part identification was then attacked directly and the geometry-only family is closed: distance measured *along* the surface relabels 585 of 3796 nodes but raises escapes (830 -> 944 walk, 748 -> 1024 shoot) and opens seams, and a core-pinned harmonic diffusion is worse on every axis, so neither is a delivery. Ownership that does work comes from the reference's own motion instead - multiply the shipped field's shares by `1/(1+(worstPlatePxOutside/tolerance)^2)` per node and per bone - which cuts escapes to 378 / 385 and excess to 1.79% / 3.77% at a 1 px tolerance, at the cost of more tearing and of seams opened by an integer-pixel lookup artifact that must be smoothed before it ships. **Appearance-and-graph part segmentation** (`artifacts/homm3_owned_bind/lift_appearance.py`, `appearance_parts.py`, `validate_parts.py`, `mv_render.py`): DINOv2-large patch tokens lifted per node from 64 lit + 64 flat-albedo textured views (median 22 of 64 views see a vertex; 3781/3796 nodes assigned, 15 graph-completed, 29 fused-interior vertices visible from no direction), clustered by agglomerative clustering **constrained by the welded mesh graph** so every part is one connected surface piece (24/24 at K=24, cutting 9.5% of edges) - the shape-geometry lanes never achieved that, and the props concentrate unseen (bow lower/upper limb recall 1.00). One bone per part, held out (fit on half the walk frames, score on the other): **3.71 and 3.92 px** mean plate violation against the shipped field's 7.38 and 8.49 and a per-node oracle's 3.46 and 3.65 - but that fit used `argmin` over the bones, and the toy-story run shows what it costs: 23 of 48 parts move off their own flesh, including a leg part onto `LeftForeArm`, so it is a valid measure of what a rigid part can fit and **not** evidence of a correct bind. Feeding the same 24 parts into the existing rigid-part harness (`exp_toy_story.py --appearance-labels`, `--bone-source platefit`) at full separation: escaped **411**, excess **1.87%**, head slip 0.1029, 984 torn, 9 of 22 bones owning nothing - against the *geometric* rigid rule's 1169 / 5.94% and the shipped field's 830 / 4.36%, so the appearance parts fix the rigid lane's own negative. Using the reference to *veto* the bone instead of choosing it (`--platefit-rule veto`) gives head slip **0.0170** at 94% head-rigid but escapes 1214: head rigidity and plate coverage trade against each other, and more parts (24 -> 48) buys bone coverage at the cost of every other axis. Neither rung passes its own audit. The mesh itself is finer than the art it came from (7207 vertices / 7677 triangles / 3796 welded nodes, median triangle edge 1.44 px of the 39x77 px plate) but hard-edged by its own authored normals at 2151 of 3796 nodes; the colour sheets that read as rough and pointy were drawn by a flat per-triangle fill whose Lambert term collapses to a winding tint (1744-1831 distinct colours per panel, 8 on the disagreement panel), so never judge an ownership classification from an unshaded panel - the shaded z-buffer sheets (`plot_part_coloring.py` + `shaded_raster.py`) carry 21853-24425. **Texture-chroma part segmentation** (`artifacts/homm3_owned_bind/chroma_parts.py`, probed by `probe_chroma.py`) is the simpler rule the appearance lane was standing in for, and it is a negative on this asset: the bake is shaded (CIELAB L* p5 10.6 / median 24.8 / p95 70.8) so L* is lighting rather than material and the signal is (a*,b*) only, sampled as a median per welded node because 507 of 2151 seam-duplicated nodes disagree between their own two texels by more than 5 Lab units and the worst by 35.7. Chunks grow by Felzenszwalb-Huttenlocher graph segmentation on the welded graph (edges ascending, merge only where the edge is no larger than each side's own internal variation plus `k/|C|`), so contiguity is by construction and 24/24 parts are one surface piece at the 24-part rung. Normalising each edge's chroma step by the local 2-ring spread - the rule that was asked for - is the **wrong normaliser here**: on this mesh the local colour variation *is* the anatomy, not noise over it, so the 24-part normalised rule puts 45% (1700 nodes) and 22% (846) of the mesh into its two largest parts, the head's region sits inside the 1700-node blob (recall 0.92 at precision **0.22**), and the bind's head slip is **0.2214, worse than the shipped field's 0.1205** - the one axis the lane exists to improve - with veto 0.2876. Turning the normalisation off does not rescue it (raw Lab step: escaped 431, purity 0.768, but torn 2196 against the appearance parts' 984 and 15 seams opened against 0, and it never reaches 24 parts at any scale, bottoming out at 58). Prop isolation is as good as the appearance lane's (bow lower/upper limb and both back objects recall 1.00), so the failure is in the body's own structure. Run across the master reel's ten clips - each with its own plate-fit bone assignment, the favourable case - 8 of 10 meet their own escape budget and `g12_attack_front` does not (56.0% against 20.4%, 2860 vertices in 307 patches driven by `Head`/`Neck`/`Spine1`: the torso bends and the rigid parts do not follow), while tearing does not recover on any clip (550 edges past the review limit on the idle rising to 2670 on the death, worst edge 150x on the shoot). All ten report `ok:false`, dominated by bones-owning-nothing and by the *reference's* own off-plate hand - expected measurements, not clip failures. Gates: `tools/validate_homm3_reference_frame_bind_contract.py` (wired into the OfflineUnlockMod build) and `tools/homm3_meshy_frame_pose/test_exact_reference_bind.py`. Generated-artifact only; `h3_wood_elf` locomotion passes and its idle/shoot clips are refused because the reference puts the hand or forearm off their own plate. A second unit of a different body plan is now exercised on the *same* 25-joint capture - the `hota_factory` quadruped `hota_factory_armadillo` - and what it adds is that **the extent identity is a biped statement**: a quadruped's mesh is legitimately longer than it is tall, so the anchor hard-refused (`x=1.9889 y=1.3259 z=2.0866` reference against a `x=1.8929 y=1.7000 z=3.0450` mesh) and `ExactBindParams.scale_source` gained an explicit second value `registered` (default unchanged at `extent`) that takes the registration's own scale verbatim, fits nothing, and records the `extentRatios` and `scaleCaveat` it did not use. Taking it was right for that unit (21 of 25 joints sit fully on plate; the shipped field built on it is mild at 130 escaped / 35 torn / 1.6176x) where the wood elf's registration had needed a 20% correction, and the contract now pins the default and the unit test. The lane runs end to end there (86 chroma parts, all ten clips inside their own escape budget) but **the rigid part rule is not the better bind on it**: 3279 torn edges against the shipped field's 35 and 12.07x against 1.6176x worst stretch on the same clip and reference, so the armadillo is recorded as a scale finding and a second body plan, not a recommendation. The `animation_bind.py` articulation lane remains the no-capture fallback and must not be a silent substitute. The distance-to-skeleton experiment (`artifacts/homm3_owned_bind/exp_bone_distance_rigidize.py`) is recorded as a measured **negative** for its stated form and a positive for one half of it: fewer bones the further a node is from any bone buys head ownership and pays for it monotonically in tearing (torn 492 -> 920 as the rim floor goes 4 -> 1, and 0 -> 188 torn on the idle, which is the whole reason it is not a delivery), whereas restricting a node's candidates to bones its own *surface* connects it to - four influences kept, no part identity, no colour, no model - improves the wood elf's walk on every axis with zero seams and a clean audit (escaped 810/830, torn 456/540, worst stretch 7.24/9.10, head slip 0.1007/0.1205) and is inert-to-harmful on the armadillo, with no predictor of which unit it helps (the long-range-influence share was tested and does not discriminate). A rigid node's bone inherits by flood fill from the confident region, never by a global hop race, which hands spine geometry to `RightHand`.
