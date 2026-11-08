"""Tests for early-step profile symmetry helpers."""

from __future__ import annotations

from cascade_early_symmetry import (
    build_bilateral_index_pairs,
    central_bone_indices,
    filter_joint_directions,
    mirror_bone_raw,
    secondary_group_names,
    symmetry_catalog_defaults,
)


def test_symmetry_catalog_defaults_reads_pairs() -> None:
    catalog = {
        "symmetry": {
            "bilateralGroupPairs": [["wing_a", "wing_b"]],
            "centralGroups": ["trunk"],
            "centralJointAxes": ["x", "y"],
        }
    }
    defaults = symmetry_catalog_defaults(catalog)
    assert defaults["bilateral_group_pairs"] == (("wing_a", "wing_b"),)
    assert defaults["central_groups"] == ("trunk",)
    assert defaults["central_joint_axes"] == ("x", "y")


def test_build_bilateral_index_pairs() -> None:
    spans = (
        ("wing_a", (1, 2, 3)),
        ("wing_b", (4, 5, 6)),
    )
    pairs = build_bilateral_index_pairs(spans, (("wing_a", "wing_b"),))
    assert pairs[1] == 4
    assert pairs[4] == 1
    assert pairs[3] == 6
    assert pairs[6] == 3


def test_filter_joint_directions_keeps_profile_axes() -> None:
    directions = [(1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0)]
    filtered = filter_joint_directions(directions, allowed_axes=("x", "y"))
    assert filtered == [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]


def test_mirror_bone_raw_copies_partner() -> None:
    import torch

    raw = torch.zeros((2, 5, 3))
    raw[:, 2, :] = torch.tensor([0.1, 0.2, 0.3])
    mirror_bone_raw(raw, 2, 4)
    assert torch.allclose(raw[:, 4, :], raw[:, 2, :])


def test_secondary_group_names() -> None:
    assert secondary_group_names((("wing_a", "wing_b"), ("leg_a", "leg_b"))) == frozenset(
        {"wing_b", "leg_b"}
    )


def test_central_bone_indices() -> None:
    spans = (("trunk", (0, 1)), ("wing_a", (2, 3)))
    central = central_bone_indices(spans, ("trunk",))
    assert central == frozenset({0, 1})


if __name__ == "__main__":
    test_symmetry_catalog_defaults_reads_pairs()
    test_build_bilateral_index_pairs()
    test_filter_joint_directions_keeps_profile_axes()
    test_mirror_bone_raw_copies_partner()
    test_secondary_group_names()
    test_central_bone_indices()
    print("ok")
