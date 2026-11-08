"""Idle-leading DEF sequences: only groups that exist, idle always first."""
from __future__ import annotations

import tempfile
from pathlib import Path

from PIL import Image

from materialize_rife_source_frames import (
    def_sequence_animation_name,
    def_sequence_choice_id,
    ensure_def_nn_upscale_meta,
    idle_leading_def_sequences,
    inventory_authentic_def_groups,
    load_nn_upscale_contract,
    motion_core_def_groups,
    motion_only_def_sequences,
    resolve_nn_upscale_meta_for_source,
    pose_sequence_kind,
    require_authentic_def_pose_groups,
    require_idle_leading_pose_groups,
    require_idle_leading_source_manifest,
    require_motion_only_pose_groups,
)
from roc_semantic_hybrid_widgets import (
    _discover_lab_def_choices,
    homm3_lab_root,
    homm3_lab_roots,
    remap_isolated_choice_id_to_idle_leading,
)


def _png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (8, 6), (10, 0, 0, 255)).save(path)


def run() -> dict[str, object]:
    crusader = idle_leading_def_sequences({2: 8, 20: 2, 0: 8, 12: 8, 3: 6})
    assert (2,) in crusader, crusader
    assert (2, 20, 0) in crusader or any(groups[:3] == (2, 20, 0) for groups in crusader), crusader
    assert (2, 12) in crusader or any(12 in groups for groups in crusader), crusader
    assert (2, 3) in crusader or any(3 in groups for groups in crusader), crusader
    assert all(groups[0] == 2 for groups in crusader), crusader
    assert not any(13 in groups for groups in crusader), crusader
    assert def_sequence_animation_name((2, 20, 0)) == "idle_start_move"
    assert def_sequence_animation_name((2, 20, 0, 21, 2)) == "idle_start_move_end"
    assert def_sequence_animation_name((20, 0, 21)) == "start_move_end"
    assert motion_core_def_groups((2, 20, 0, 21, 2)) == (20, 0, 21)
    assert motion_core_def_groups((2, 12, 2)) == (12,)
    assert motion_core_def_groups((2,)) == ()
    assert pose_sequence_kind((2, 20, 0, 21, 2)) == "idle_leading"
    assert pose_sequence_kind((20, 0, 21)) == "motion_only"
    assert pose_sequence_kind((2,)) == "idle_only"
    motion = motion_only_def_sequences({2: 8, 20: 2, 0: 8, 21: 6, 12: 8, 5: 9})
    assert (20, 0, 21) in motion, motion
    assert (12,) in motion, motion
    assert (5,) in motion, motion
    assert all(2 not in groups for groups in motion), motion
    require_motion_only_pose_groups((20, 0, 21))
    require_authentic_def_pose_groups((20, 0, 21))
    require_authentic_def_pose_groups((2, 20, 0, 21, 2))
    try:
        require_motion_only_pose_groups((2, 20, 0))
        raise AssertionError("idle-leading groups must not count as motion-only")
    except ValueError as exc:
        assert "omit idle DEF group" in str(exc), str(exc)
    try:
        require_authentic_def_pose_groups((20, 2))
        raise AssertionError("trailing idle on a motion-only chain must fail closed")
    except ValueError as exc:
        assert "omit idle DEF group" in str(exc), str(exc)
    assert def_sequence_animation_name((2, 12, 2)) == "idle_attack_front"
    assert def_sequence_choice_id("h3_crusader", (2, 20, 0)) == "h3_crusader:g02-g20-g00"
    assert def_sequence_choice_id("h3_crusader", (2, 20, 0, 21, 2)) == "h3_crusader:g02-g20-g00-g21-g02"

    crusader_end = idle_leading_def_sequences({2: 8, 20: 2, 0: 8, 21: 6, 12: 8, 5: 9})
    assert (2, 20, 0, 21, 2) in crusader_end, crusader_end
    assert crusader_end[0] == (2,), crusader_end
    assert (2, 12, 2) in crusader_end, crusader_end
    assert (2, 5) in crusader_end, crusader_end
    assert (2,) in crusader_end, crusader_end
    assert (2, 21, 2) not in crusader_end, crusader_end

    cannon = idle_leading_def_sequences({2: 1, 3: 9, 4: 9, 5: 9, 14: 8, 15: 8, 16: 8})
    assert cannon[0][:2] == (2, 3), cannon[0]
    assert all(0 not in groups for groups in cannon), cannon
    assert any(groups[:2] == (2, 15) for groups in cannon), cannon

    teleport = idle_leading_def_sequences({2: 8, 0: 1, 20: 14, 11: 8})
    assert (2,) in teleport, teleport
    assert any(groups[:2] == (2, 0) for groups in teleport), teleport
    assert any(20 in groups for groups in teleport), teleport
    assert not any(groups[:3] == (2, 20, 0) for groups in teleport), teleport

    assert idle_leading_def_sequences({0: 8, 12: 8}) == ()

    require_idle_leading_pose_groups((2, 20, 0))
    require_idle_leading_pose_groups((2, 13))
    require_idle_leading_pose_groups((2,), allow_idle_only=True)
    try:
        require_idle_leading_pose_groups((0,))
        raise AssertionError("isolated walk must not count as an idle-leading pose sequence")
    except ValueError as exc:
        assert "idle DEF group 2" in str(exc), str(exc)
    try:
        require_idle_leading_pose_groups((20, 0))
        raise AssertionError("start+walk without idle must not count as an idle-leading pose sequence")
    except ValueError as exc:
        assert "idle DEF group 2" in str(exc), str(exc)
    try:
        require_idle_leading_pose_groups((2,))
        raise AssertionError("idle-only must not count as a motion sequence without allow_idle_only")
    except ValueError as exc:
        assert "idle-only" in str(exc), str(exc)

    crusader_ids = (
        "h3_crusader:g02",
        "h3_crusader:g02-g20-g00-g21-g02",
        "h3_crusader:g02-g12-g02",
    )
    assert (
        remap_isolated_choice_id_to_idle_leading("h3_crusader:move_g0", crusader_ids)
        == "h3_crusader:g02-g20-g00-g21-g02"
    )
    assert (
        remap_isolated_choice_id_to_idle_leading("h3_crusader:g0", crusader_ids)
        == "h3_crusader:g02-g20-g00-g21-g02"
    )
    assert (
        remap_isolated_choice_id_to_idle_leading("h3_crusader:attack_down_g13", crusader_ids)
        == "h3_crusader:g02-g12-g02"
    )
    assert (
        remap_isolated_choice_id_to_idle_leading("h3_crusader:g02-g20-g00", crusader_ids)
        == "h3_crusader:g02-g20-g00-g21-g02"
    )

    from roc_semantic_hybrid_experiment import RocHybridConfig, SETUP_SOURCE

    _, gpu_prep_rest = SETUP_SOURCE.split("\n\n# Predicted depth cache\n\n", 1)
    gpu_prep_depth, _ = gpu_prep_rest.split("\n\n# Bone range placeholders\n\n", 1)
    assert "from alpha_shadow_cull import" in gpu_prep_depth, gpu_prep_depth[:400]
    assert "cull_alpha_shadows" in gpu_prep_depth

    motion_config = RocHybridConfig(
        def_lab_frame_dir=Path("lab"),
        def_lab_group=(20, 0, 21),
        def_expected_count=(2, 8, 6),
        def_nn_upscale_meta=Path("meta.json"),
        target_frame_dir="frames_def12_nn_start_move_end",
        shadow_culled_frame_dir="frames_def12_nn_start_move_end_shadow_culled",
        target_depth_dir="frames_def12_nn_start_move_end_depth_vda",
    )
    assert tuple(motion_config.def_lab_group) == (20, 0, 21)
    try:
        RocHybridConfig(
            def_lab_frame_dir=Path("lab"),
            def_lab_group=(20, 2),
            def_expected_count=(2, 8),
            def_nn_upscale_meta=Path("meta.json"),
            target_frame_dir="frames_def12_nn_start_idle",
            shadow_culled_frame_dir="frames_def12_nn_start_idle_shadow_culled",
            target_depth_dir="frames_def12_nn_start_idle_depth_vda",
        )
        raise AssertionError("mixed idle on a motion-only chain must fail closed")
    except ValueError as exc:
        assert "omit idle DEF group" in str(exc), str(exc)

    with tempfile.TemporaryDirectory() as raw:
        lab = Path(raw) / "CCRUSD.dir"
        for index in range(3):
            _png(lab / f"02_{index:02d}.png")
        for index in range(2):
            _png(lab / f"00_{index:02d}.png")
        _png(lab / "20_00.png")
        inventory = inventory_authentic_def_groups(lab)
        assert set(inventory) == {0, 2, 20}, set(inventory)
        assert len(inventory[2]) == 3
        rife = Path(raw) / "rife.dir"
        _png(rife / "02_0000.png")
        try:
            inventory_authentic_def_groups(rife)
            raise AssertionError("RIFE four-digit plates must not count as authentic DEF")
        except RuntimeError as exc:
            assert "RIFE interpolated plates" in str(exc), str(exc)

        meta = Path(raw) / "nn_upscale" / "upscale_meta.json"
        first = ensure_def_nn_upscale_meta(lab, meta)
        second = ensure_def_nn_upscale_meta(lab, meta)
        assert first == second == meta.resolve()
        contract = load_nn_upscale_contract(meta)
        assert contract.scale >= 2
        assert contract.out_size[0] == contract.crop_size[0] * contract.scale

        # A valid contract from another extraction is historical evidence, not
        # a canvas for the current source. Keep it intact and choose a stable
        # source-specific replacement instead of failing every clip.
        stale_root = Path(raw) / "stale_root"
        stale_sid = "h3_archer"
        stale_source = stale_root / "old_lab" / "ARCHER.dir"
        current_source = stale_root / "new_lab" / "ARCHER.dir"
        _png(stale_source / "02_00.png")
        _png(current_source / "02_00.png")
        recorded_path = stale_root / "artifacts" / "pose_picker_runs" / stale_sid / "nn_upscale" / "upscale_meta.json"
        ensure_def_nn_upscale_meta(stale_source, recorded_path)
        replacement = resolve_nn_upscale_meta_for_source(
            stale_root,
            stale_sid,
            current_source,
            source_frames=(current_source / "02_00.png",),
        )
        assert replacement != recorded_path.resolve()
        assert replacement.name.startswith("upscale_meta_")
        ensure_def_nn_upscale_meta(current_source, replacement)
        current_contract = load_nn_upscale_contract(replacement)
        assert current_contract.source_size == (8, 6)
        assert recorded_path.is_file(), "stale contract must remain preserved"
        assert (
            resolve_nn_upscale_meta_for_source(
                stale_root,
                stale_sid,
                current_source,
                source_frames=(current_source / "02_00.png",),
            )
            == replacement
        )

        with tempfile.TemporaryDirectory() as raw_root:
            fake_root = Path(raw_root)
            source_lab, bepinex_lab = homm3_lab_roots(fake_root)
            assert homm3_lab_root(fake_root) == source_lab
            bepinex_12fps = (
                bepinex_lab / "h3_crusader" / "extracted_battle_source_12fps" / "CCRUSD.dir"
            )
            bepinex_12fps.mkdir(parents=True)
            _png(bepinex_12fps / "02_00.png")
            assert homm3_lab_root(fake_root) == bepinex_lab
            source_12fps = (
                source_lab / "h3_crusader" / "extracted_battle_source_12fps" / "CCRUSD.dir"
            )
            source_12fps.mkdir(parents=True)
            _png(source_12fps / "02_00.png")
            assert homm3_lab_root(fake_root) == source_lab

        root = Path(r"V:/Games/Olden Era Playtest Tweak")
        lab_root = homm3_lab_root(root)
        live = {}
        if lab_root.is_dir() and (lab_root / "h3_crusader" / "extracted_battle_source_12fps").is_dir():
            choices = _discover_lab_def_choices(root)
            units = {choice.unit_name for choice in choices}
            crusader_choices = [choice for choice in choices if choice.unit_sid == "h3_crusader"]
            cannon_choices = [choice for choice in choices if choice.unit_sid == "h3_cannon"]
            amalek = [choice for choice in choices if choice.unit_sid == "h3_amalek"]
            assert "crusader" in units, sorted(units)[:12]
            assert len(units) > 50, f"lab discovery collapsed to leftover units: {sorted(units)}"
            assert crusader_choices, "crusader authentic DEF sequences must be selectable"
            from run_crusader_gpu_cascade_animation_set import select_crusader_delivery_choices

            delivery = select_crusader_delivery_choices(choices)
            assert delivery, "idle-leading crusader delivery sequences must remain selectable"
            assert all(choice.def_lab_groups[:1] == (2,) for choice in delivery), [
                choice.def_lab_groups for choice in delivery
            ]
            assert not any(choice.sequence_kind == "motion_only" for choice in delivery)
            assert any(choice.def_lab_groups == (2,) for choice in crusader_choices)
            assert any(0 in choice.def_lab_groups for choice in crusader_choices)
            assert not any(choice.animation_name == "move_g0" for choice in crusader_choices)
            assert not any(choice.animation_name == "attack_down_g13" for choice in crusader_choices)
            assert any(choice.def_lab_groups[:2] == (2, 12) for choice in crusader_choices)
            assert any(choice.def_lab_groups == (2, 12, 2) for choice in crusader_choices)
            assert any(choice.def_lab_groups == (20, 0, 21) for choice in crusader_choices)
            assert any(choice.animation_name == "start_move_end" for choice in crusader_choices)
            assert any(
                choice.sequence_kind == "motion_only" and choice.def_lab_groups == (20, 0, 21)
                for choice in crusader_choices
            )
            assert any(
                choice.sequence_kind == "idle_leading" and choice.def_lab_groups[-1] == 2
                and 0 in choice.def_lab_groups
                for choice in crusader_choices
            )
            assert (
                remap_isolated_choice_id_to_idle_leading(
                    "h3_crusader:g20-g00-g21",
                    [choice.choice_id for choice in crusader_choices],
                )
                == "h3_crusader:g20-g00-g21"
            )
            assert any(
                0 in choice.def_lab_groups and 21 in choice.def_lab_groups and choice.def_lab_groups[-1] == 2
                for choice in crusader_choices
            )
            assert cannon_choices, "cannon should list idle+shoot even without a walk group"
            assert all(0 not in choice.def_lab_groups for choice in cannon_choices)
            assert amalek == [], "empty 12 fps alt DEFs must stay unlisted"
            live = {
                "units": len(units),
                "crusaderSequences": len(crusader_choices),
                "cannonSequences": len(cannon_choices),
            }
        live_manifest = Path(
            r"V:/Games/Olden Era Playtest Tweak/artifacts/pose_picker_runs/"
            r"h3_crusader/idle_start_move/frames_def12_nn_idle_start_move/def_frames.json"
        )
        if live_manifest.is_file():
            groups = require_idle_leading_source_manifest(live_manifest)
            assert groups[0] == 2, groups
            assert 0 in groups, groups
            live["idleStartMoveGroups"] = list(groups)

    return {"ok": True, "live": live}


if __name__ == "__main__":
    print(run())
