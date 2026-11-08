#!/usr/bin/env python3
"""Fail-closed source contract for the exact-reference owned bind lane.

Pins the static shape of the bind solved from an *exact* animation reference (a
registered mocap capture + the authored DEF plates) rather than from the vendor
smart-rig armature that ships inside an AI-generated mesh:

* the reference must be single-valued (one pose per authored frame) and the bind
  plate must be carried independently of the audited segment;
* the scale must come from an extent identity, not a distance score search, and the only
  alternative is the registration's own scale taken verbatim by explicit request - never a
  silent fallback for a bind pose the identity refused;
* the rigid invariant must be gated and the replay acceptance must be reported;
* acceptance must be an exact reference-frame measurement (silhouette coverage of
  the frame the joints actually produced), never an image-similarity score;
* axial twist is declared unobservable instead of silently assumed.

Source/static only: the solver is not executed and no generated artifact is read, so
a pass here is source-static evidence, not generated-artifact, runtime, or
user-visible gameplay proof.  Used by the OfflineUnlockMod build via
``ValidateHomm3ReferenceFrameBindContract``.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import tokenize
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "homm3.reference_frame_bind_contract.v1"

MESH_DIR = Path("tools") / "homm3_meshy_frame_pose"
OWNED_RERIG_DIR = MESH_DIR / "owned_rerig"

POSE_SOURCE = OWNED_RERIG_DIR / "pose_source.py"
EXACT_BIND = OWNED_RERIG_DIR / "exact_bind.py"
ANIMATION_BIND = OWNED_RERIG_DIR / "animation_bind.py"
RUNNER = MESH_DIR / "bind_from_exact_reference.py"
OWNED_RERIG_INIT = OWNED_RERIG_DIR / "__init__.py"
UNIT_TEST = MESH_DIR / "test_exact_reference_bind.py"
PROP_FIT = OWNED_RERIG_DIR / "prop_fit.py"
PROP_FIT_RUNNER = MESH_DIR / "prop_region_fit.py"
PROP_FIT_TEST = MESH_DIR / "test_prop_region_fit.py"
WELD_TOPOLOGY = OWNED_RERIG_DIR / "weld_topology.py"
WELD_TOPOLOGY_TEST = MESH_DIR / "test_weld_topology.py"

GLB_IO = OWNED_RERIG_DIR / "glb_io.py"
GLB_IO_TEST = MESH_DIR / "test_glb_io_surface_attributes.py"
PROP_ATTACHMENT = OWNED_RERIG_DIR / "prop_attachment.py"
PROP_BRIDGE_TEST = MESH_DIR / "test_prop_bridges.py"

REQUIRED_FILES = (
    POSE_SOURCE,
    EXACT_BIND,
    ANIMATION_BIND,
    RUNNER,
    PROP_FIT,
    PROP_FIT_RUNNER,
    WELD_TOPOLOGY,
    PROP_ATTACHMENT,
    PROP_BRIDGE_TEST,
)

PROP_FIT_PUBLIC_NAMES = (
    "measure_prop_region_fit",
    "prop_regions",
    "score_prop_region",
    "PropFitParams",
)

# No topology rule can prove a weld *good*: a generator that fuses two objects into one continuous
# surface leaves no trace, which is this unit's bow fused to its own skin.  The measurement therefore
# only proves whether a *shown* coincidence is load-bearing, and the distinction it must keep is that a
# seam (two triangles on the shared edge, one fan at the node) is not a coincidence, a bowtie or a
# four-triangle edge is, and only a coincidence that raises the piece count above the welded component
# count is a wrong weld.
WELD_TOPOLOGY_PUBLIC_NAMES = ("weld_topology",)
WELD_TOPOLOGY_REPORT = (
    "weld_topology.v1",
    "every_weld_is_a_surface_continuation",
    "a_coincidence_joins_two_pieces",
    "bowtieNodes",
    "edgesWithMoreThanTwoTriangles",
    "piecesJoinedAcrossCleanEdges",
    "weldedComponents",
)
WELD_TOPOLOGY_GUARDS = (
    "can prove a weld bad, never prove one good",
    "fail-closed",
)

EXACT_BIND_PUBLIC_NAMES = (
    "bind_from_exact_reference",
    "audit_exact_bind",
    "fit_reference_scale",
    "rescale_to_extent",
    "replay_deformed_vertices",
    "bone_names_from_capture",
    "skin_by_position_field",
    "position_groups",
    "nearby_vertex_pairs",
    "place_joints",
    "ExactBindParams",
)

POSE_SOURCE_PUBLIC_NAMES = (
    "load_registered_pose_source",
    "load_capture",
    "load_capture_similarity",
    "load_registration_camera_fit",
    "yaw_pitch_basis_rows",
    "CaptureToWorld",
    "PoseSource",
    "SpriteCameraFit",
    "ReferenceInconsistentError",
)

OWNED_RERIG_ALL_NAMES = (
    "bind_from_exact_reference",
    "audit_exact_bind",
    "load_registered_pose_source",
    "load_reference_frames",
    "ExactBindParams",
    "ReferenceInconsistentError",
    "PropFitParams",
    "measure_prop_region_fit",
    "weld_topology",
)

# The vendor/smart-rig armature is stripped, never consumed as bind authority: the exact
# solver must not read source skin data at all.  Attribute names only - a bare "JOINTS_0"
# is inexpressible as a check because it can only appear inside a string literal, which the
# code scan below deliberately ignores.
VENDOR_SKIN_FORBIDDEN = ("skin_joints", "inverse_bind")

# Acceptance is the authored frame's DEF coverage, not a rendered-image score.  The code scan
# proves no such score is computed; the prose assertion below proves the prohibition is stated
# rather than merely absent by accident.
IMAGE_SIMILARITY_FORBIDDEN = ("iou", "chroma", "dinov", "silhouette_iou", "ssim", "lpips")
IMAGE_SIMILARITY_DECLARED = "not within an IoU tolerance"

RIGID_INVARIANTS = ("max_bone_length_drift", "restIdentityMaxError")
REPLAY_ACCEPTANCE = ("maxOutsideExcess", "outsideExcessBudget", "poseExcursionPx")
# A Meshy mesh is delivered with a vertex duplicated wherever the UV or the normal changes, so one
# sheet of flesh arrives as hundreds of patches that share no indices: 5562 of this unit's 7207
# vertices are bit-identical duplicates of another, and welding them at 0.1 mm gives one patch with
# zero triangles lost.  The weld must not be applied (all 2151 coincident groups differ in both UV and
# normal, so it would destroy every texture seam), and the flesh unit is therefore neither the patch
# nor the vertex: it is the position.  A rule keyed on patch identity drives two vertices at one point
# with different transforms and opens the seam into a hole (measured 648 seams, worst 513 mm); a rule
# keyed on the nearest bone tears a card that straddles two limbs (measured 4111%).  Position-keyed
# weights can do neither, and that property is what these names and this rule text must keep.
POSITION_FIELD_NAMES = (
    "position_groups",
    "skin_by_position_field",
    "nearby_vertex_pairs",
)
POSITION_FIELD_RULE = (
    "The weights are a function of *where the vertex is*",
    "same point, same weights, same transform",
)
POSITION_FIELD_GUARDS = (
    "vertices at the same position carry different weights",
    "inverse_distance_to_flesh_bones_strongest_four",
)
# Markers are not flesh.  Mixamo's terminal markers sit past the surface by construction, so the
# capture extrapolates them and their tracks carry the lift's own error (68% bone-length excursion on
# this unit's right toe).  Flesh driven by one is dragged by that error: handing a vertex to
# RightToe_End to satisfy "every bone must own flesh" tore this unit's toes at 15x an edge length.
MARKER_EXCLUSION_NAMES = ("markerBonesExcluded", "is_marker")
# The flesh unit is reported rather than enforced: enforcing the strict articulation relation is what
# traded tearing for holes.  The count of vertices that blend outside it must stay visible.
ARTICULATION_REPORT = (
    "articulation_neighbourhoods",
    "mesh_components",
    "Reported, not enforced",
    "groupsBlendingUnarticulatedBones",
)
TEARING_REPORT = ("edge_stretch.v1", "max_edge_stretch_review", "edgesPastTenTimesReviewLimit")
# Tearing alone cannot see a hole: freezing each patch onto one bone lowers the stretch of the edges
# inside it and pulls the flesh apart at the seam instead (648 seams, worst 513 mm).  The surface
# itself must therefore be measured on rest-adjacent vertex pairs, which is exact where the field is
# position-keyed.
COHESION_REPORT = (
    "surface_cohesion.v1",
    "cohesion_radius_frac",
    "pairsOpenedPastRadius",
    "the surface is opening",
)
# A global escape fraction says the bind is wrong somewhere, not which geometry is wrong: a prop fused
# to the wrong limb is a small region that leaves the frame's own plate while the body stays inside,
# and one number over 7207 vertices hides exactly that.  The escaping vertices must be grouped and
# named - with the bone driving each group and the reference joint the plate has there - so a mesh
# defect is reported as a place, not as a count.
ESCAPE_REGIONS_REPORT = (
    "escape_regions.v1",
    "escape_region_radius_frac",
    "verticesEscapingAtLeastOnce",
    "regionCount",
    "centroidPlatePixel",
    "drivingBones",
    "referenceJointNearestCentroid",
    "geometry attached to the wrong part",
)
# A prop fused to the wrong part is reported as a place by the escape regions, but that does not say
# whether any weighting can put it back: the frames' own plates are the ground truth for where the unit
# is, so every flesh bone's rigid transform is tried against every frame's plate.  The two ways to get
# this wrong are named in the source and pinned here, because both were measured: selecting by the
# *global* escaped count (which moved 2 of 748 vertices while the region itself reached further out),
# and treating "far from every bone" as a defect (a region can be far from every bone and already
# inside every plate, and must then not be repaired).
PROP_FIT_REPORT = (
    "prop_region_fit.v1",
    "no_bone_fits_the_plates",
    "bindable_to_one_bone",
    "already_inside_under_the_field",
    "bestRigid",
    "worstPxOutside",
)
PROP_FIT_GUARDS = (
    "every flesh bone's own rigid transform",
    "fail-closed",
)
# The exporter must carry the authored normals and the texture samplers.  Without normals a consumer
# has to invent them, and on a mesh of hundreds of disconnected patches there is nothing to average
# across a patch seam, so the surface reads as faceted.
SURFACE_ATTRIBUTES_CARRIED = ("NORMAL", "TEXCOORD_0", "samplers_out")
# A *rebuilt* surface - a remesh, a retopology, a decimation - authors its own vertices, so the source's
# per-vertex attributes are the wrong length for it.  The writer takes replacements, and a replacement that
# does not name every vertex is a corrupt accessor rather than a mesh with missing UVs, so it is refused.
SURFACE_ATTRIBUTE_REPLACEMENTS = (
    "normals must name every vertex",
    "uvs must name every vertex",
    "uvs must be (N,2)",
)
SURFACE_ATTRIBUTE_TEST_NEEDLE = "test_replacements_are_written_and_the_sources_attributes_are_not"
BIND_PLATE_CARRIERS = ("bind_alpha", "bind_coverage")
DUPLICATE_PLATE_GUARD = "not single-valued"
SCALE_EXTENT_IDENTITY = (
    "reference_pose_must_span_the_mesh_it_was_generated_from",
    "rescale_to_extent",
)
SCALE_DISTANCE_SEARCH = "scale_search_samples"
# The extent identity is a statement about a biped: a quadruped's mesh is legitimately longer than it
# is tall, so for such a unit the identity cannot choose a scale at all and refuses.  The second
# option, added for exactly that case, takes the registration's own scale *verbatim* - nothing fitted,
# no distance searched - and must record the extents it did not use and the caveat that goes with
# them, so the mismatch travels with every containment number built on that similarity.  What must not
# come back: a default that rescales silently, `registered` used as the fallback for a pose the
# identity refused, or a third value that guesses.
SCALE_SOURCE_DEFAULT = 'scale_source: str = "extent"'
SCALE_SOURCE_CHOICES = '("extent", "registered")'
SCALE_SOURCE_GUARD = 'params.scale_source == "extent"'
SCALE_REGISTERED_REPORT = (
    "registration_scale_taken_verbatim",
    "scaleCaveat",
    "extentRatios",
)
SCALE_SOURCE_TEST_NEEDLE = "scale_source"
TWIST_DECLARATION = "twist"

# Anti-regression: a weight rule keyed on which connected patch a vertex belongs to must not come
# back.  It reads the exporter's UV/normal vertex splits as topology and drives two vertices at one
# point with different transforms, which is what opened 648 seams (worst 513 mm) on this unit.
PATCH_KEYED_WEIGHTING_FORBIDDEN = ("patch_coherent_labels", "patchCoherence", "patch_coherent")

_ALL_BLOCK = re.compile(r"^__all__\s*=\s*\[(?P<body>.*?)\]", re.DOTALL | re.MULTILINE)
_STRING_LITERAL = re.compile(r"""["']([^"']+)["']""")
_MODULE_DEF = re.compile(
    r"^(?:async\s+)?def\s+(?P<func>[A-Za-z_]\w*)|^class\s+(?P<cls>[A-Za-z_]\w*)",
    re.MULTILINE,
)
_MODULE_ALIAS = re.compile(r"^(?P<name>[A-Za-z_]\w*)\s*=\s*[A-Za-z_][\w.]*\s*$", re.MULTILINE)


def _display(repo: Path, path: Path) -> str:
    try:
        return path.relative_to(repo).as_posix()
    except ValueError:
        return path.as_posix()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _matching_line(text: str, needle: str, case_insensitive: bool) -> int | None:
    target = needle.casefold() if case_insensitive else needle
    for number, line in enumerate(text.splitlines(), start=1):
        haystack = line.casefold() if case_insensitive else line
        if target in haystack:
            return number
    return None


def _code_only(text: str) -> str:
    """Strip comments and string literals so a scan sees executable code only.

    Prose that documents a prohibition, and diagnostic messages that merely name a format,
    are not violations; an actual computation or attribute read is.  If the file cannot be
    tokenized the full text is returned, so the check fails closed rather than open.
    """
    pieces: list[str] = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        for token in tokens:
            if token.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            pieces.append(token.string)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return text
    return "\n".join(pieces)


def _module_level_names(text: str) -> set[str]:
    names = {match.group("func") for match in _MODULE_DEF.finditer(text) if match.group("func")}
    names |= {match.group("cls") for match in _MODULE_DEF.finditer(text) if match.group("cls")}
    names |= {match.group("name") for match in _MODULE_ALIAS.finditer(text)}
    return names


def _declared_all(text: str) -> set[str]:
    match = _ALL_BLOCK.search(text)
    if match is None:
        return set()
    return set(_STRING_LITERAL.findall(match.group("body")))


def _require_contains(repo: Path, path: Path, needle: str, errors: list[str]) -> None:
    if not path.is_file():
        errors.append(f"missing file: {_display(repo, path)}")
        return
    if needle not in _read(path):
        errors.append(f"{_display(repo, path)}: missing contract text {needle!r}")


def _require_absent(
    repo: Path,
    path: Path,
    needle: str,
    errors: list[str],
    *,
    label: str,
    case_insensitive: bool = False,
    code_only: bool = True,
) -> None:
    if not path.is_file():
        errors.append(f"missing file: {_display(repo, path)}")
        return
    text = _read(path)
    line = _matching_line(_code_only(text) if code_only else text, needle, case_insensitive)
    if line is not None:
        suffix = " (case-insensitive)" if case_insensitive else ""
        scope = " in executable code" if code_only else ""
        errors.append(
            f"{_display(repo, path)}: {label} text {needle!r}{suffix}{scope}"
        )


def _require_exported(repo: Path, path: Path, names: tuple[str, ...], errors: list[str]) -> None:
    if not path.is_file():
        errors.append(f"missing file: {_display(repo, path)}")
        return
    text = _read(path)
    exported = _module_level_names(text) | _declared_all(text)
    for name in names:
        if name not in exported:
            errors.append(f"{_display(repo, path)}: does not define or export {name!r}")


def _require_in_all(repo: Path, path: Path, names: tuple[str, ...], errors: list[str]) -> None:
    if not path.is_file():
        errors.append(f"missing file: {_display(repo, path)}")
        return
    declared = _declared_all(_read(path))
    for name in names:
        if name not in declared:
            errors.append(f"{_display(repo, path)}: __all__ is missing {name!r}")


def _check_unit_test(repo: Path, errors: list[str]) -> bool:
    if not (repo / UNIT_TEST).is_file():
        errors.append(
            f"missing file: {_display(repo, UNIT_TEST)} "
            "(unit test for the exact-reference bind; must exercise replay_deformed_vertices)"
        )
        return False
    text = _read(repo / UNIT_TEST)
    for needle in ("test_", "replay_deformed_vertices"):
        if needle not in text:
            errors.append(f"{_display(repo, UNIT_TEST)}: missing contract text {needle!r}")
    return True


def validate(repo: Path, errors: list[str]) -> dict[str, Any]:
    pose_source = repo / POSE_SOURCE
    exact_bind = repo / EXACT_BIND
    runner = repo / RUNNER

    missing = [relative.as_posix() for relative in REQUIRED_FILES if not (repo / relative).is_file()]
    for relative in missing:
        errors.append(f"missing file: {relative}")
    unit_test_present = _check_unit_test(repo, errors)
    if missing:
        return {"unitTestPresent": unit_test_present, "contentChecksSkipped": True}

    _require_exported(repo, exact_bind, EXACT_BIND_PUBLIC_NAMES, errors)
    # Lightweight build gate; behavior and source preservation are exercised by the tests.
    for needle in ('get("shaftBridges", [])', 'trimesh.creation.cylinder',
                   '"sourceMeshSha256"', '"uvSourceFace"', 'np.full(count, -1)',
                   'np.full(count, number)', '"generatedFaces"', '"preservedTexturedFaces"'):
        _require_contains(repo, repo / PROP_ATTACHMENT, needle, errors)
    for needle in ('test_original_faces_and_attributes_preserved_and_counts_exclude_generated',
                   'test_invalid_recipe_values_fail_closed', 'test_bridge_recipe_remains_source_hash_pinned'):
        _require_contains(repo, repo / PROP_BRIDGE_TEST, needle, errors)
    _require_exported(repo, pose_source, POSE_SOURCE_PUBLIC_NAMES, errors)
    _require_exported(repo, repo / PROP_FIT, PROP_FIT_PUBLIC_NAMES, errors)
    _require_in_all(repo, repo / OWNED_RERIG_INIT, OWNED_RERIG_ALL_NAMES, errors)
    for _needle in PROP_FIT_REPORT:
        _require_contains(repo, repo / PROP_FIT, _needle, errors)
    for _needle in PROP_FIT_GUARDS:
        _require_contains(repo, repo / PROP_FIT, _needle, errors)
    if not (repo / PROP_FIT_TEST).is_file():
        errors.append(f"missing file: {_display(repo, PROP_FIT_TEST)}")

    _require_exported(repo, repo / WELD_TOPOLOGY, WELD_TOPOLOGY_PUBLIC_NAMES, errors)
    for _needle in WELD_TOPOLOGY_REPORT:
        _require_contains(repo, repo / WELD_TOPOLOGY, _needle, errors)
    for _needle in WELD_TOPOLOGY_GUARDS:
        _require_contains(repo, repo / WELD_TOPOLOGY, _needle, errors)
    if not (repo / WELD_TOPOLOGY_TEST).is_file():
        errors.append(f"missing file: {_display(repo, WELD_TOPOLOGY_TEST)}")

    _require_contains(repo, runner, "ignoredVendorSkin", errors)
    for needle in VENDOR_SKIN_FORBIDDEN:
        _require_absent(
            repo,
            exact_bind,
            needle,
            errors,
            label="forbidden source-skin consumption",
        )

    for needle in IMAGE_SIMILARITY_FORBIDDEN:
        _require_absent(
            repo,
            exact_bind,
            needle,
            errors,
            label="forbidden image-similarity acceptance",
            case_insensitive=True,
        )
    _require_contains(repo, exact_bind, IMAGE_SIMILARITY_DECLARED, errors)

    for needle in RIGID_INVARIANTS:
        _require_contains(repo, exact_bind, needle, errors)

    for needle in REPLAY_ACCEPTANCE:
        _require_contains(repo, exact_bind, needle, errors)

    # Weights are a function of position, and that is what keeps a split surface closed.
    for needle in POSITION_FIELD_NAMES:
        _require_contains(repo, exact_bind, needle, errors)
    for needle in POSITION_FIELD_RULE:
        _require_contains(repo, exact_bind, needle, errors)
    for needle in POSITION_FIELD_GUARDS:
        _require_contains(repo, exact_bind, needle, errors)
    for needle in MARKER_EXCLUSION_NAMES:
        _require_contains(repo, exact_bind, needle, errors)
    for needle in ARTICULATION_REPORT:
        _require_contains(repo, exact_bind, needle, errors)
    for needle in TEARING_REPORT:
        _require_contains(repo, exact_bind, needle, errors)
    for needle in COHESION_REPORT:
        _require_contains(repo, exact_bind, needle, errors)
    for needle in ESCAPE_REGIONS_REPORT:
        _require_contains(repo, exact_bind, needle, errors)
    _require_exported(repo, exact_bind, POSITION_FIELD_NAMES, errors)

    for needle in SURFACE_ATTRIBUTES_CARRIED:
        _require_contains(repo, repo / GLB_IO, needle, errors)
    for needle in SURFACE_ATTRIBUTE_REPLACEMENTS:
        _require_contains(repo, repo / GLB_IO, needle, errors)
    if not (repo / GLB_IO_TEST).is_file():
        errors.append(f"missing file: {_display(repo, GLB_IO_TEST)}")
    _require_contains(repo, repo / GLB_IO_TEST, SURFACE_ATTRIBUTE_TEST_NEEDLE, errors)

    for needle in BIND_PLATE_CARRIERS:
        _require_contains(repo, pose_source, needle, errors)

    _require_contains(repo, pose_source, DUPLICATE_PLATE_GUARD, errors)

    for needle in SCALE_EXTENT_IDENTITY:
        _require_contains(repo, exact_bind, needle, errors)
    # The scale anchor: the extent identity stays the default and the only fitted option, the second
    # source is explicit and verbatim, and the unit test must exercise it.
    _require_contains(repo, exact_bind, SCALE_SOURCE_DEFAULT, errors)
    _require_contains(repo, exact_bind, SCALE_SOURCE_CHOICES, errors)
    _require_contains(repo, exact_bind, SCALE_SOURCE_GUARD, errors)
    for needle in SCALE_REGISTERED_REPORT:
        _require_contains(repo, exact_bind, needle, errors)
    _require_contains(repo, repo / UNIT_TEST, SCALE_SOURCE_TEST_NEEDLE, errors)
    _require_absent(
        repo,
        exact_bind,
        SCALE_DISTANCE_SEARCH,
        errors,
        label="forbidden distance-score scale search",
    )
    for needle in PATCH_KEYED_WEIGHTING_FORBIDDEN:
        _require_absent(
            repo,
            exact_bind,
            needle,
            errors,
            label="forbidden patch-keyed weight rule",
        )

    _require_contains(repo, exact_bind, TWIST_DECLARATION, errors)

    return {
        "unitTestPresent": unit_test_present,
        "contentChecksSkipped": False,
        "checkedFiles": [
            POSE_SOURCE.as_posix(),
            EXACT_BIND.as_posix(),
            ANIMATION_BIND.as_posix(),
            RUNNER.as_posix(),
            OWNED_RERIG_INIT.as_posix(),
            PROP_FIT.as_posix(),
            PROP_FIT_RUNNER.as_posix(),
            PROP_FIT_TEST.as_posix(),
            WELD_TOPOLOGY.as_posix(),
            WELD_TOPOLOGY_TEST.as_posix(),
            GLB_IO.as_posix(),
            GLB_IO_TEST.as_posix(),
            PROP_ATTACHMENT.as_posix(),
            PROP_BRIDGE_TEST.as_posix(),
        ],
        "exactBindPublicNames": list(EXACT_BIND_PUBLIC_NAMES),
        "poseSourcePublicNames": list(POSE_SOURCE_PUBLIC_NAMES),
        "ownedRerigAllNames": list(OWNED_RERIG_ALL_NAMES),
        "propFitPublicNames": list(PROP_FIT_PUBLIC_NAMES),
        "weldTopologyPublicNames": list(WELD_TOPOLOGY_PUBLIC_NAMES),
        "scaleSourceChoices": ["extent", "registered"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    args = parser.parse_args()
    repo = args.repo_root.resolve()

    errors: list[str] = []
    checks = validate(repo, errors)
    print(
        json.dumps(
            {
                "ok": not errors,
                "schema": SCHEMA,
                "validator": "validate_homm3_reference_frame_bind_contract",
                "repoRoot": str(repo),
                "errorCount": len(errors),
                "errors": errors,
                "checks": checks,
                "proofBoundary": (
                    "source-static only: pins the exact-reference owned bind source contract; "
                    "does not run the solver, read generated artifacts, or prove runtime or "
                    "user-visible gameplay behavior"
                ),
            },
            indent=2,
        )
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
