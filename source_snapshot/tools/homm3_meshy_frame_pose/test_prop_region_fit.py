"""Prop-region plate fit: whether a weighting repair can work at all, against known truth.

The fixture reuses `test_exact_reference_bind`'s synthetic unit and its known-answer reference: a
closed body, six joints, and plates rasterised from the true rigid deformation of a swinging arm.  A
prop box is added outside the body and is carried by the same swing, so the ground truth is
constructed rather than estimated:

* a prop the reference draws where a swinging bone reaches is reported bindable, and to that bone;
* the same prop drawn out of reach of every bone is reported unbindable, which is the measurement that
  says a weighting repair cannot work and the fault is in the geometry;
* a prop that the *shipped* field already places inside every plate is reported as no defect, so a
  region that needs no repair is not "repaired";
* a body with no prop yields no prop regions at all, and a nonsensical call is refused.

The prop's vertices are named directly (`regions=`) rather than detected, because a *compact* blob
cannot be detected as "far from every bone" on this fixture: a leaf bone's tail extends to its farthest
labelled vertex, so a small isolated box gets absorbed into the bone that owns it.  That is a property
of the detector, and it is measured on the real unit; here the point is the verdict, so the region is
given and the answer is known.
"""

from __future__ import annotations

import dataclasses
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_exact_reference_bind as fixture  # noqa: E402

from owned_rerig.exact_bind import (  # noqa: E402
    PROP_RIGID_SCHEMA,
    ExactBindParams,
    bind_from_exact_reference,
    fit_reference_scale,
    own_props_rigidly,
)
from owned_rerig.prop_fit import (  # noqa: E402
    PROP_FIT_SCHEMA,
    VERDICT_BINDABLE,
    VERDICT_INSIDE,
    VERDICT_SEAM,
    VERDICT_UNBINDABLE,
    PropFitParams,
    boundary_seam,
    measure_prop_region_fit,
    prop_regions,
)
from owned_rerig.tpose import _undirected_edges  # noqa: E402

BODY = fixture.BODY
# Inside the fixture's 64x64 sprite, clear of the body, and short enough that the arm swing keeps it on
# canvas at the largest angle.
PROP = ((0.45, 0.05, -0.05), (0.75, 0.35, 0.05))
# The fixture's swing rotates Shoulder and Hand about the spine root, so those bones' own rigid
# transform reproduces the prop's true motion exactly.
ARM_NAME_PARTS = ("Shoulder", "Hand")
TEST_PARAMS = PropFitParams(far_frac=0.2, link_frac=0.2, min_vertices=6, max_fraction=0.9)
# Detection on this fixture needs a wider grouping radius than a real unit's surface does, because the
# prop is a coarse box: its vertices sit 0.05-0.15 apart, so a radius below that groups nothing.  The far
# threshold stays at the library default, which is the point - a bone runs into the prop's inner face, so
# only the part of it the skeleton does not reach is a region, and the tests below assert on what changed
# rather than on the whole box.
DETECT_PARAMS = PropFitParams(far_frac=0.08, link_frac=0.2, min_vertices=6, max_fraction=0.9)
ANGLES = [0.0, 8.0, 16.0]


def _grid_box(
    low, high, steps: int, shared: tuple[list, dict] | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """A triangulated surface grid, so the prop is a real patch rather than eight loose corners.

    ``shared`` is a ``(vertices, points)`` registry.  Two boxes built into the same registry that touch
    on a grid point *share* that vertex, which is how these tests build a prop welded to a body: the
    weld is what the ownership verdict has to reason about, and it cannot be faked with extra triangles.
    """
    lo = np.asarray(low, dtype=np.float64)
    hi = np.asarray(high, dtype=np.float64)
    axis = [np.linspace(lo[dim], hi[dim], steps + 1) for dim in range(3)]
    if shared is None:
        shared = ([], {})
    vertices, points = shared

    def index(point) -> int:
        key = tuple(round(float(value), 9) for value in point)
        if key not in points:
            points[key] = len(vertices)
            vertices.append([float(value) for value in point])
        return points[key]

    added = len(vertices)

    triangles: list[tuple[int, int, int]] = []
    for dim in range(3):
        others = [other for other in range(3) if other != dim]
        for bound in (lo[dim], hi[dim]):
            for i in range(steps):
                for j in range(steps):
                    quad = []
                    for di, dj in ((0, 0), (1, 0), (1, 1), (0, 1)):
                        point = [0.0, 0.0, 0.0]
                        point[dim] = bound
                        point[others[0]] = axis[others[0]][i + di]
                        point[others[1]] = axis[others[1]][j + dj]
                        quad.append(index(point))
                    triangles.append((quad[0], quad[1], quad[2]))
                    triangles.append((quad[0], quad[2], quad[3]))
    return (
        np.asarray(vertices[added:], dtype=np.float64),
        np.asarray(triangles, dtype=np.int64).reshape(-1),
    )


def _mesh() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    body_v, body_t = _grid_box(*BODY, steps=2)
    prop_v, prop_t = _grid_box(*PROP, steps=2)
    vertices = np.vstack([body_v, prop_v])
    indices = np.concatenate([body_t, prop_t + len(body_v)])
    prop_rows = np.arange(len(body_v), len(vertices), dtype=np.int64)
    return vertices, indices, prop_rows


# A prop welded to the body's own surface: the two boxes share the grid points where they touch, so the
# prop's shell and the body's shell are one surface joined by real edges.  This is what a generator does
# when it fuses a bow into a hip, and it is the case the containment test alone cannot decide.
WELD_PROP = ((0.30, 0.00, -0.10), (0.40, 0.10, 0.00))


def _welded_mesh() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    shared: tuple[list, dict] = ([], {})
    body_v, body_t = _grid_box(*BODY, steps=2, shared=shared)
    prop_v, prop_t = _grid_box(*WELD_PROP, steps=1, shared=shared)
    vertices = np.asarray(shared[0], dtype=np.float64)
    body_rows = len(body_v)
    prop_rows = np.arange(body_rows, len(vertices), dtype=np.int64)
    # The prop is built second, so its triangle indices are already global and must not be offset.
    indices = np.concatenate([body_t, prop_t])
    return vertices, indices, prop_rows


class PropRegionFitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.vertices, self.indices, self.prop_rows = _mesh()
        self.body_rows = np.setdiff1d(np.arange(len(self.vertices)), self.prop_rows)
        self.params = ExactBindParams()

    def _solved(self, angles=None, mesh=None, prop_rows=None):
        mesh = mesh or (self.vertices, self.indices, self.prop_rows)
        prop_rows = self.prop_rows if prop_rows is None else prop_rows
        angles = ANGLES if angles is None else angles
        pose = fixture._pose_source(angles=angles, mesh=mesh)
        result = bind_from_exact_reference(
            pose=pose, mesh_positions=self.vertices, mesh_indices=self.indices
        )
        similarity, _scale = fit_reference_scale(
            pose=pose,
            mesh_positions=self.vertices,
            mesh_indices=self.indices,
            params=self.params,
        )
        return pose, result, similarity

    def _measured(self, pose, result, similarity, regions, mesh=None):
        mesh = mesh or (self.vertices, self.indices, self.prop_rows)
        return measure_prop_region_fit(
            pose=pose,
            similarity=similarity,
            mesh_positions=mesh[0],
            mesh_indices=mesh[1],
            parents=result["parents"],
            bone_names=result["boneNames"],
            heads=result["heads"],
            joints=result["joints"],
            weights=result["weights"],
            params=TEST_PARAMS,
            regions=regions,
        )

    def test_a_prop_a_bone_can_reach_is_reported_bindable_and_to_that_bone(self) -> None:
        pose, result, similarity = self._solved()
        measured = self._measured(pose, result, similarity, [self.prop_rows])
        self.assertEqual(measured["schema"], PROP_FIT_SCHEMA)
        self.assertEqual(measured["regionCount"], 1)
        region = measured["regions"][0]
        self.assertEqual(region["vertices"], int(self.prop_rows.size))
        self.assertNotEqual(
            region["verdict"],
            VERDICT_UNBINDABLE,
            "the reference draws this prop exactly where the arm swing carries it",
        )
        if region["verdict"] == VERDICT_BINDABLE:
            # The plates were rasterised from the prop rotating about the spine root, which is exactly
            # what those two bones' own rigid transform does; any other bone has to miss it.
            self.assertTrue(
                any(part in region["bestRigid"]["bone"] for part in ARM_NAME_PARTS),
                region["bestRigid"]["bone"],
            )
            self.assertEqual(region["bestRigid"]["worstPxOutside"], 0.0)

    def test_a_prop_the_reference_draws_out_of_reach_cannot_be_placed_by_any_bone(self) -> None:
        pose, result, similarity = self._solved()
        # Draw the prop somewhere else in every frame - a translation no bone's rigid transform can
        # produce, which is what a generator does when it fuses a prop to the wrong part.
        stray = self.vertices.copy()
        stray[self.prop_rows] += np.array([0.0, -1.6, 0.0])
        pose = dataclasses.replace(
            pose,
            alpha=np.stack(
                [
                    (fixture._raster(self.indices, stray, pose.camera) * 255).astype(np.uint8)
                    for _ in pose.frames
                ],
                axis=0,
            ),
        )
        measured = self._measured(pose, result, similarity, [self.prop_rows])
        region = measured["regions"][0]
        self.assertEqual(region["verdict"], VERDICT_UNBINDABLE)
        self.assertGreater(region["bestRigid"]["worstPxOutside"], 0.0)
        self.assertEqual(measured["unbindableVertices"], int(self.prop_rows.size))
        self.assertTrue(measured["reviewNotes"])
        self.assertIn("mesh-side", " ".join(measured["reviewNotes"]))

    def test_a_prop_the_shipped_field_already_places_inside_is_not_a_defect(self) -> None:
        pose, result, similarity = self._solved()
        arm = next(
            index
            for index, name in enumerate(result["boneNames"])
            if "Hand" in name
        )
        # Drive the prop rigidly, exactly as the reference draws it: the field path must then report
        # the region as already inside, not as something to repair.
        joints = result["joints"].copy()
        weights = result["weights"].copy()
        joints[self.prop_rows, :] = arm
        weights[self.prop_rows, :] = 0.0
        weights[self.prop_rows, 0] = 1.0
        measured = measure_prop_region_fit(
            pose=pose,
            similarity=similarity,
            mesh_positions=self.vertices,
            mesh_indices=self.indices,
            parents=result["parents"],
            bone_names=result["boneNames"],
            heads=result["heads"],
            joints=joints,
            weights=weights,
            params=TEST_PARAMS,
            regions=[self.prop_rows],
        )
        region = measured["regions"][0]
        self.assertEqual(region["verdict"], VERDICT_INSIDE)
        self.assertEqual(region["field"]["worstPxOutside"], 0.0)
        self.assertEqual(measured["unbindableVertices"], 0)
        self.assertTrue(any("not defects" in note for note in measured["reviewNotes"]))

    def test_detection_runs_end_to_end_and_a_unit_with_no_prop_finds_nothing(self) -> None:
        # The prop box is named, so detection is only checked for shape here; what it must never do is
        # invent a prop on a body that has none.
        body_v, body_t = _grid_box(*BODY, steps=2)
        pose = fixture._pose_source(angles=[0.0, 15.0], mesh=(body_v, body_t, np.zeros(0, np.int64)))
        result = bind_from_exact_reference(
            pose=pose, mesh_positions=body_v, mesh_indices=body_t
        )
        similarity, _scale = fit_reference_scale(
            pose=pose, mesh_positions=body_v, mesh_indices=body_t, params=self.params
        )
        measured = measure_prop_region_fit(
            pose=pose,
            similarity=similarity,
            mesh_positions=body_v,
            mesh_indices=body_t,
            parents=result["parents"],
            bone_names=result["boneNames"],
            heads=result["heads"],
            joints=result["joints"],
            weights=result["weights"],
            params=TEST_PARAMS,
        )
        self.assertEqual(measured["schema"], PROP_FIT_SCHEMA)
        self.assertEqual(measured["unbindableVertices"], 0)
        self.assertEqual(
            [row for row in measured["regions"] if row["verdict"] == VERDICT_UNBINDABLE], []
        )
        # And the detector's own contract on this fixture's geometry: a body-only mesh has no region
        # that no bone is near, because every vertex is within 0.2 of some bone line.
        self.assertEqual(
            prop_regions(
                positions=body_v,
                heads=result["heads"],
                parents=result["parents"],
                bone_names=result["boneNames"],
                params=TEST_PARAMS,
            ),
            [],
        )

    def test_fail_closed_on_a_mismatched_bind_a_bad_region_and_a_nonsense_sampling(self) -> None:
        pose, result, similarity = self._solved()
        with self.assertRaises(ValueError):
            measure_prop_region_fit(
                pose=pose,
                similarity=similarity,
                mesh_positions=self.vertices,
                mesh_indices=self.indices,
                parents=result["parents"],
                bone_names=result["boneNames"],
                heads=result["heads"],
                joints=result["joints"][:-3],
                weights=result["weights"][:-3],
                params=TEST_PARAMS,
            )
        with self.assertRaises(ValueError):
            self._measured(pose, result, similarity, [np.array([], dtype=np.int64)])
        with self.assertRaises(ValueError):
            self._measured(
                pose, result, similarity, [np.array([len(self.vertices) + 5], dtype=np.int64)]
            )
        for bad in (0.0, 1.0, -0.2):
            with self.assertRaises(ValueError):
                PropFitParams(far_frac=bad)
        with self.assertRaises(ValueError):
            PropFitParams(min_vertices=2)

    def _owned(
        self,
        *,
        prop_params=DETECT_PARAMS,
        angles=None,
        sharp="platefit",
        joints=None,
        weights=None,
        regions="detect",
    ):
        pose, result, similarity = self._solved(angles=angles)
        params = ExactBindParams()
        params.prop_rigid = sharp
        owned = own_props_rigidly(
            pose=pose,
            similarity=similarity,
            vertices=self.vertices,
            indices=self.indices,
            parents=result["parents"],
            bone_names=result["boneNames"],
            heads=result["heads"],
            joints=result["joints"] if joints is None else joints,
            weights=result["weights"] if weights is None else weights,
            params=params,
            prop_params=prop_params,
            regions=None if regions == "detect" else regions,
        )
        return pose, result, similarity, owned

    # The fixture's body box has corners further from its six-bone chain than the prop's own inner face,
    # so the default search returns one region mixing both (measured: 15 prop vertices and 2 body
    # vertices).  That is why the tests below that need the prop *on its own* name it, which is the same
    # escape ``measure_prop_region_fit`` offers a lane with its own definition of a prop.
    def test_platefit_ownership_hands_the_prop_to_the_bone_the_plates_name(self) -> None:
        _pose, result, _similarity, owned = self._owned(regions=[self.prop_rows])
        self.assertEqual(owned["schema"], PROP_RIGID_SCHEMA)
        self.assertEqual(owned["rule"], "platefit")
        self.assertEqual(owned["regionsFound"], 1)
        region = owned["regions"][0]
        self.assertTrue(region["owned"])
        self.assertEqual(region["verdict"], VERDICT_BINDABLE)
        self.assertEqual(region["vertices"], int(self.prop_rows.size))
        self.assertTrue(
            any(part in region["bestRigidBone"] for part in ARM_NAME_PARTS),
            region["bestRigidBone"],
        )
        # The verdict is honoured exactly: every vertex the rule touched lands on that one bone at 1.0,
        # which is what stops a rigid object from being stretched between two.
        bone = result["boneNames"].index(region["bestRigidBone"])
        changed = np.flatnonzero(
            np.any(owned["weights"] != result["weights"], axis=1)
            | np.any(owned["joints"] != result["joints"], axis=1)
        )
        self.assertEqual(changed.size, owned["verticesOwnedRigidly"])
        self.assertEqual(changed.size, int(self.prop_rows.size))
        self.assertTrue(np.array_equal(changed, self.prop_rows))
        self.assertTrue(np.all(owned["joints"][changed, 0] == bone))
        self.assertTrue(np.all(owned["weights"][changed, 0] == 1.0))
        self.assertTrue(np.all(owned["weights"][changed, 1:].sum(axis=1) == 0.0))
        # And nothing the skeleton does reach moves: a rule that also re-owned the body would be a
        # different bind, not a prop repair.
        self.assertTrue(np.array_equal(owned["joints"][self.body_rows], result["joints"][self.body_rows]))
        self.assertTrue(
            np.array_equal(owned["weights"][self.body_rows], result["weights"][self.body_rows])
        )

    def test_platefit_ownership_leaves_a_prop_the_field_already_places_alone(self) -> None:
        # Drive the prop rigidly with the bone the plates name, as the correct answer already would: the
        # region is then not a defect, and a rule that 'repairs' it anyway would act on no evidence.
        pose, result, similarity = self._solved()
        arm = next(index for index, name in enumerate(result["boneNames"]) if "Hand" in name)
        joints = result["joints"].copy()
        weights = result["weights"].copy()
        joints[self.prop_rows, :] = arm
        weights[self.prop_rows, :] = 0.0
        weights[self.prop_rows, 0] = 1.0
        _pose, _result, _similarity, owned = self._owned(
            joints=joints, weights=weights, regions=[self.prop_rows]
        )
        self.assertEqual(owned["regionsFound"], 1)
        self.assertEqual(owned["regions"][0]["verdict"], VERDICT_INSIDE)
        self.assertEqual(owned["regionsOwnedRigidly"], 0)
        self.assertEqual(owned["verticesOwnedRigidly"], 0)
        self.assertTrue(np.array_equal(owned["weights"], weights))

    def test_platefit_ownership_refuses_a_prop_no_bone_can_place(self) -> None:
        # The same stray prop the fit reports unbindable: rigidifying it would move the fault from a
        # stretch to a tear, so the rule must decline rather than pick the least bad bone.
        pose, result, similarity = self._solved()
        stray = self.vertices.copy()
        stray[self.prop_rows] += np.array([0.0, -1.6, 0.0])
        stray_pose = dataclasses.replace(
            pose,
            alpha=np.stack(
                [
                    (fixture._raster(self.indices, stray, pose.camera) * 255).astype(np.uint8)
                    for _ in pose.frames
                ],
                axis=0,
            ),
        )
        params = ExactBindParams()
        params.prop_rigid = "platefit"
        owned = own_props_rigidly(
            pose=stray_pose,
            similarity=similarity,
            vertices=self.vertices,
            indices=self.indices,
            parents=result["parents"],
            bone_names=result["boneNames"],
            heads=result["heads"],
            joints=result["joints"],
            weights=result["weights"],
            params=params,
            prop_params=DETECT_PARAMS,
            regions=[self.prop_rows],
        )
        self.assertEqual(owned["regionsFound"], 1)
        self.assertEqual(owned["regions"][0]["verdict"], VERDICT_UNBINDABLE)
        self.assertEqual(owned["verticesOwnedRigidly"], 0)
        self.assertTrue(np.array_equal(owned["weights"], result["weights"]))
        self.assertIn("mesh-side", " ".join(owned["reviewNotes"]))

    def test_a_detected_region_mixing_prop_and_body_is_refused_rather_than_owned(self) -> None:
        # The search groups by proximity, so it can put prop vertices and flesh the skeleton does reach
        # into one region.  No single bone drives such a mixed region, so the rule must decline it - the
        # alternative, owning it anyway, would tear the flesh at the region's edge.
        _pose, result, _similarity, owned = self._owned()
        self.assertEqual(owned["regionsSearched"], 1)
        region = owned["regions"][0]
        self.assertEqual(region["verdict"], VERDICT_UNBINDABLE)
        self.assertEqual(owned["regionsOwnedRigidly"], 0)
        self.assertEqual(owned["verticesOwnedRigidly"], 0)
        self.assertTrue(np.array_equal(owned["weights"], result["weights"]))

    def test_off_is_the_default_and_changes_nothing_while_an_unknown_rule_is_refused(self) -> None:
        pose, result, similarity = self._solved()
        params = ExactBindParams()
        self.assertEqual(params.prop_rigid, "off")
        # Through the solver: off must not even search, and the returned skin must say so.
        off = bind_from_exact_reference(
            pose=pose, mesh_positions=self.vertices, mesh_indices=self.indices, params=params
        )
        self.assertIsNone(off["skin"]["propRigid"])
        self.assertTrue(np.array_equal(off["weights"], result["weights"]))
        # A rule nobody implemented is refused rather than silently treated as off.
        broken = ExactBindParams()
        broken.prop_rigid = "nearest"
        with self.assertRaises(ValueError) as caught:
            own_props_rigidly(
                pose=pose,
                similarity=similarity,
                vertices=self.vertices,
                indices=self.indices,
                parents=result["parents"],
                bone_names=result["boneNames"],
                heads=result["heads"],
                joints=result["joints"],
                weights=result["weights"],
                params=broken,
                prop_params=TEST_PARAMS,
            )
        self.assertIn("prop_rigid must be one of", str(caught.exception))

    def test_platefit_on_the_solver_leaves_a_bind_it_cannot_help_exactly_as_it_was(self) -> None:
        # This fixture's prop is coarser than a real unit's surface, so the default region search - whose
        # radius is a fraction of subject height - finds nothing on it.  That is the honest end-to-end
        # contract to pin here: a rule that finds no prop must return the field untouched, not reshuffle
        # weights to look busy.
        pose, result, _similarity = self._solved()
        params = ExactBindParams()
        params.prop_rigid = "platefit"
        solved = bind_from_exact_reference(
            pose=pose, mesh_positions=self.vertices, mesh_indices=self.indices, params=params
        )
        reported = solved["skin"]["propRigid"]
        self.assertIsNotNone(reported)
        self.assertEqual(reported["regionsFound"], 0)
        self.assertEqual(reported["regionsOwnedRigidly"], 0)
        self.assertEqual(reported["verticesOwnedRigidly"], 0)
        self.assertTrue(np.array_equal(solved["weights"], result["weights"]))
        self.assertTrue(np.array_equal(solved["joints"], result["joints"]))

    def test_a_prop_welded_to_the_body_is_refused_because_owning_it_would_tear(self) -> None:
        # Welded to the body's own surface, the prop is the case containment alone cannot decide: the
        # plates say one bone places it perfectly, and that same bone is the one the surrounding surface
        # cannot follow.  Measured here so the rule has to answer with the seam, not with the plate.
        vertices, indices, prop_rows = _welded_mesh()
        pose = fixture._pose_source(angles=ANGLES, mesh=(vertices, indices, prop_rows))
        result = bind_from_exact_reference(
            pose=pose, mesh_positions=vertices, mesh_indices=indices
        )
        similarity, _scale = fit_reference_scale(
            pose=pose, mesh_positions=vertices, mesh_indices=indices, params=self.params
        )
        measured = measure_prop_region_fit(
            pose=pose,
            similarity=similarity,
            mesh_positions=vertices,
            mesh_indices=indices,
            parents=result["parents"],
            bone_names=result["boneNames"],
            heads=result["heads"],
            joints=result["joints"],
            weights=result["weights"],
            params=TEST_PARAMS,
            regions=[prop_rows],
        )
        region = measured["regions"][0]
        # The two halves of the case, both asserted: a bone can place it, the field cannot.
        self.assertEqual(region["bestRigid"]["worstPxOutside"], 0.0)
        self.assertGreater(region["field"]["worstPxOutside"], 0.0)
        self.assertEqual(region["verdict"], VERDICT_SEAM)
        seam = region["seam"]
        self.assertGreater(seam["boundaryEdges"], 0)
        self.assertFalse(seam["withinBudget"])
        self.assertGreater(seam["ownedWorstGrowth"], seam["budget"])
        self.assertIn("the fault is the weld", " ".join(measured["reviewNotes"]))

        params = ExactBindParams()
        params.prop_rigid = "platefit"
        owned = own_props_rigidly(
            pose=pose,
            similarity=similarity,
            vertices=vertices,
            indices=indices,
            parents=result["parents"],
            bone_names=result["boneNames"],
            heads=result["heads"],
            joints=result["joints"],
            weights=result["weights"],
            params=params,
            prop_params=TEST_PARAMS,
            regions=[prop_rows],
        )
        self.assertEqual(owned["regions"][0]["verdict"], VERDICT_SEAM)
        self.assertEqual(owned["regionsOwnedRigidly"], 0)
        self.assertEqual(owned["verticesOwnedRigidly"], 0)
        self.assertTrue(np.array_equal(owned["weights"], result["weights"]))
        self.assertTrue(np.array_equal(owned["joints"], result["joints"]))

    def test_a_separate_shell_is_the_case_rigid_ownership_exists_for(self) -> None:
        # The fixture's floating prop shares no vertex with the body, so there is no edge to shear: the
        # seam is empty, it costs nothing, and the same verdict that refuses a welded prop must accept it.
        pose, result, similarity = self._solved()
        measured = measure_prop_region_fit(
            pose=pose,
            similarity=similarity,
            mesh_positions=self.vertices,
            mesh_indices=self.indices,
            parents=result["parents"],
            bone_names=result["boneNames"],
            heads=result["heads"],
            joints=result["joints"],
            weights=result["weights"],
            params=TEST_PARAMS,
            regions=[self.prop_rows],
        )
        region = measured["regions"][0]
        self.assertEqual(region["verdict"], VERDICT_BINDABLE)
        self.assertEqual(region["seam"]["boundaryEdges"], 0)
        self.assertTrue(region["seam"]["withinBudget"])
        self.assertIn("separate", region["seam"]["note"])


class BoundarySeamTests(unittest.TestCase):
    """The seam arithmetic on its own, with no solver, no plates and no fixture."""

    QUAD = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]])
    QUAD_TRIANGLES = np.array([0, 1, 2, 0, 2, 3], dtype=np.int64)

    def _edges(self) -> np.ndarray:
        return _undirected_edges(self.QUAD_TRIANGLES)

    def test_a_translated_region_shears_by_however_far_it_moves(self) -> None:
        # The region's two top vertices move 0.5 up while their neighbours stay.  The edges that leave the
        # region are then the only ones that change, and the worst of them is (0,0,0)->(1,1.5,0):
        # sqrt(1 + 2.25) = 1.8028 against its rest length of sqrt(2) = 1.4142, i.e. 0.3886 of growth.
        members = np.array([1, 2], dtype=np.int64)
        rest = self.QUAD
        moved = rest.copy()
        moved[members] += np.array([0.0, 0.5, 0.0])
        seam = boundary_seam(
            edges=self._edges(),
            members=members,
            positions=rest,
            field_frames=[rest],
            rigid_frames=[moved],
            budget=0.3886,
        )
        self.assertEqual(seam["boundaryEdges"], 3)
        self.assertEqual(seam["fieldWorstGrowth"], 0.0)
        self.assertAlmostEqual(seam["ownedWorstGrowth"], 0.3886, places=3)
        self.assertIsNone(seam["grownOverTheField"])  # the field seam is exactly zero: no ratio exists
        self.assertTrue(seam["withinBudget"])
        self.assertFalse(
            boundary_seam(
                edges=self._edges(),
                members=members,
                positions=rest,
                field_frames=[rest],
                rigid_frames=[moved],
                budget=0.3885,
            )["withinBudget"]
        )

    def test_the_worst_frame_and_the_frame_it_is_compared_at_are_reported(self) -> None:
        members = np.array([1, 2], dtype=np.int64)
        mild = self.QUAD.copy()
        mild[members] += np.array([0.0, 0.1, 0.0])
        sharp = self.QUAD.copy()
        sharp[members] += np.array([0.0, 0.5, 0.0])
        seam = boundary_seam(
            edges=self._edges(),
            members=members,
            positions=self.QUAD,
            field_frames=[self.QUAD, self.QUAD],
            rigid_frames=[mild, sharp],
            budget=10.0,
        )
        self.assertEqual(seam["ownedWorstFrame"], 1)
        self.assertGreater(seam["ownedWorstGrowth"], seam["fieldWorstGrowth"])

    def test_a_region_that_shares_no_edge_is_a_separate_shell_and_costs_nothing(self) -> None:
        # Vertices 4 and 5 are a second component: no edge leaves them, so nothing can be sheared.
        positions = np.vstack([self.QUAD, [[5.0, 0.0, 0.0], [6.0, 1.0, 0.0]]])
        indices = np.concatenate([self.QUAD_TRIANGLES, [4, 5, 4]])
        moved = positions.copy()
        moved[[4, 5]] += 100.0
        seam = boundary_seam(
            edges=_undirected_edges(indices),
            members=np.array([4, 5], dtype=np.int64),
            positions=positions,
            field_frames=[positions],
            rigid_frames=[moved],
            budget=0.0,
        )
        self.assertEqual(seam["boundaryEdges"], 0)
        self.assertEqual(seam["ownedWorstGrowth"], 0.0)
        self.assertTrue(seam["withinBudget"])
        self.assertIn("separate", seam["note"])

    def test_an_edge_is_the_same_edge_whichever_triangle_names_it(self) -> None:
        # Two triangles sharing the edge 1-2 name it in opposite directions; the boundary is a set of
        # undirected edges, so the shared edge is interior and cannot be counted twice.
        indices = np.array([0, 1, 2, 2, 1, 3], dtype=np.int64)
        seam = boundary_seam(
            edges=_undirected_edges(indices),
            members=np.array([1, 2], dtype=np.int64),
            positions=self.QUAD,
            field_frames=[self.QUAD],
            rigid_frames=[self.QUAD],
            budget=0.0,
        )
        self.assertEqual(seam["boundaryEdges"], 4)  # 0-1, 0-2, 1-3, 2-3
        self.assertEqual(seam["ownedWorstGrowth"], 0.0)

    def test_fail_closed_on_a_bad_seam_request(self) -> None:
        edges = self._edges()
        members = np.array([1, 2], dtype=np.int64)
        with self.assertRaises(ValueError):  # one frame measured against two
            boundary_seam(
                edges=edges, members=members, positions=self.QUAD,
                field_frames=[self.QUAD], rigid_frames=[self.QUAD, self.QUAD], budget=1.0,
            )
        with self.assertRaises(ValueError):  # no frames at all
            boundary_seam(
                edges=edges, members=members, positions=self.QUAD,
                field_frames=[], rigid_frames=[], budget=1.0,
            )
        with self.assertRaises(ValueError):  # an empty region is not a region
            boundary_seam(
                edges=edges, members=np.array([], dtype=np.int64), positions=self.QUAD,
                field_frames=[self.QUAD], rigid_frames=[self.QUAD], budget=1.0,
            )
        with self.assertRaises(ValueError):  # flat triangle indices are not an edge list
            boundary_seam(
                edges=self.QUAD_TRIANGLES, members=members, positions=self.QUAD,
                field_frames=[self.QUAD], rigid_frames=[self.QUAD], budget=1.0,
            )


if __name__ == "__main__":
    unittest.main()
