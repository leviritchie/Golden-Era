"""Place authentic 12 fps DEF groups on the pose-fit canvas; refuse RIFE plates."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from PIL import Image

from materialize_rife_source_frames import materialize_def_group_sequence


def _png(path: Path, value: int, size: tuple[int, int] = (8, 6)) -> None:
    Image.new("RGBA", size, (value, 0, 0, 255)).save(path)


def _upscale_meta(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "ok": True,
                "method": "shared_union_crop_nearest_neighbor",
                "sourceSize": [8, 6],
                "unionBBox": [0, 0, 7, 5],
                "cropSize": [8, 6],
                "pad": 0,
                "scale": 2,
                "outSize": [16, 12],
            }
        )
        + "\n",
        encoding="utf-8",
    )


def run() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        lab = root / "CCRUSD.dir"
        lab.mkdir()
        for index in range(3):
            _png(lab / f"02_{index:02d}.png", 40 + index)
        for index in range(2):
            _png(lab / f"20_{index:02d}.png", 70 + index)
        for index in range(3):
            _png(lab / f"00_{index:02d}.png", 10 + index)
        meta = root / "upscale_meta.json"
        _upscale_meta(meta)
        seed = root / "roc_sprite_camera_fit.json"
        seed.write_text(
            json.dumps(
                {
                    "sourceResolution": [16, 12],
                    "pxPerWorld": 40.0,
                    "screenOffsetPx": [8.0, 6.0],
                    "basisScreenRows": [[1, 0, 0], [0, 1, 0]],
                }
            ),
            encoding="utf-8",
        )
        out = root / "frames_def12_nn_idle_start_move"
        first = materialize_def_group_sequence(
            lab,
            out,
            groups=(2, 20, 0),
            expected_counts=(3, 2, 3),
            target_fps=12.0,
            nn_upscale_meta=meta,
            camera_fit=seed,
        )
        assert first["sourceKind"] == "authentic_def_nn_upscale_sequence", first
        assert first["frameCount"] == 8, first
        assert [clip["name"] for clip in first["clips"]] == ["idle", "move_start", "move"], first
        assert (out / "00.png").is_file()
        assert (out / "07.png").is_file()
        assert not (out / "rife_frames.json").exists()
        cached = materialize_def_group_sequence(
            lab,
            out,
            groups=(2, 20, 0),
            expected_counts=(3, 2, 3),
            target_fps=12.0,
            nn_upscale_meta=meta,
            camera_fit=seed,
        )
        assert cached["sourceFrameSha256"] == first["sourceFrameSha256"]

        idle_out = root / "frames_def12_nn_idle"
        idle = materialize_def_group_sequence(
            lab,
            idle_out,
            groups=(2,),
            expected_counts=(3,),
            target_fps=12.0,
            nn_upscale_meta=meta,
            camera_fit=seed,
        )
        assert idle["sourceGroups"] == [2], idle["sourceGroups"]
        assert idle["frameCount"] == 3, idle
        assert [clip["name"] for clip in idle["clips"]] == ["idle"], idle
        move_out = root / "frames_def12_nn_move"
        move_only = materialize_def_group_sequence(
            lab,
            move_out,
            groups=0,
            expected_counts=3,
            target_fps=12.0,
            nn_upscale_meta=meta,
            camera_fit=seed,
        )
        assert move_only["sourceGroups"] == [0], move_only["sourceGroups"]
        assert move_only["frameCount"] == 3, move_only

        moved = root / "moved_lab" / "CCRUSD.dir"
        moved.mkdir(parents=True)
        for path in lab.glob("*.png"):
            Image.open(path).save(moved / path.name)
        relocated = materialize_def_group_sequence(
            moved,
            out,
            groups=(2, 20, 0),
            expected_counts=(3, 2, 3),
            target_fps=12.0,
            nn_upscale_meta=meta,
            camera_fit=seed,
        )
        assert relocated["sourceFrameSha256"] == first["sourceFrameSha256"]
        assert Path(relocated["sourceDirectory"]) == moved.resolve()

        other = root / "other_lab" / "CCRUSD.dir"
        other.mkdir(parents=True)
        for index in range(3):
            _png(other / f"02_{index:02d}.png", 200 + index)
        for index in range(2):
            _png(other / f"20_{index:02d}.png", 210 + index)
        for index in range(3):
            _png(other / f"00_{index:02d}.png", 220 + index)
        try:
            materialize_def_group_sequence(
                other,
                out,
                groups=(2, 20, 0),
                expected_counts=(3, 2, 3),
                target_fps=12.0,
                nn_upscale_meta=meta,
                camera_fit=seed,
            )
            raise AssertionError("different DEF bytes must not reuse the same output folder")
        except RuntimeError as exc:
            assert "mix a new authentic DEF copy" in str(exc), str(exc)

        rife_lab = root / "rife_lab"
        rife_lab.mkdir()
        _png(rife_lab / "02_0000.png", 1)
        _png(rife_lab / "20_0000.png", 2)
        _png(rife_lab / "00_0000.png", 3)
        try:
            materialize_def_group_sequence(
                rife_lab,
                root / "frames_from_60fps_lab",
                groups=(2, 20, 0),
                expected_counts=(1, 1, 1),
                nn_upscale_meta=meta,
                camera_fit=seed,
            )
            raise AssertionError("RIFE four-digit plates must not count as authentic DEF")
        except RuntimeError as exc:
            assert "RIFE interpolated plates" in str(exc), str(exc)

        try:
            materialize_def_group_sequence(
                lab,
                root / "frames_rife60_nn_idle_start_move",
                groups=(2, 20, 0),
                expected_counts=(3, 2, 3),
                nn_upscale_meta=meta,
                camera_fit=seed,
            )
            raise AssertionError("DEF sequence must not write into a RIFE folder name")
        except ValueError as exc:
            assert "RIFE folder" in str(exc), str(exc)

        from roc_semantic_hybrid_experiment import RocHybridConfig

        try:
            RocHybridConfig(
                rife_lab_frame_dir=lab,
                rife_lab_group=0,
                rife_expected_count=3,
                rife_nn_upscale_meta=meta,
                def_lab_frame_dir=lab,
                def_lab_group=(2, 20, 0),
                def_expected_count=(3, 2, 3),
                def_nn_upscale_meta=meta,
                target_frame_dir="frames_def12_nn_idle_start_move",
                shadow_culled_frame_dir="frames_def12_nn_idle_start_move_shadow_culled",
                target_depth_dir="frames_def12_nn_idle_start_move_depth_vda",
            )
            raise AssertionError("RIFE and authentic DEF source must not be enabled together")
        except ValueError as exc:
            assert "together" in str(exc), str(exc)

        import materialize_rife_source_frames as frames_mod

        delattr(frames_mod, "normalize_def_group_plan")
        RocHybridConfig(
            def_lab_frame_dir=lab,
            def_lab_group=(2, 20, 0),
            def_expected_count=(3, 2, 3),
            def_nn_upscale_meta=meta,
            target_frame_dir="frames_def12_nn_idle_start_move",
            shadow_culled_frame_dir="frames_def12_nn_idle_start_move_shadow_culled",
            target_depth_dir="frames_def12_nn_idle_start_move_depth_vda",
        )
        assert hasattr(frames_mod, "normalize_def_group_plan"), dir(frames_mod)

        from roc_semantic_hybrid_widgets import homm3_lab_root

        live_def = (
            homm3_lab_root(Path(r"V:/Games/Olden Era Playtest Tweak"))
            / "h3_crusader"
            / "extracted_battle_source_12fps"
            / "CCRUSD.dir"
        )
        live_rife = Path(
            r"V:/Games/Olden Era Playtest Tweak/oldenera_factions/Assets/CustomUnits/"
            r"homm3_lab/h3_crusader/extracted_battle/CCRUSD.dir"
        )
        live_meta = Path(
            r"V:/Games/Olden Era Playtest Tweak/artifacts/crusader_pose_pipeline/"
            r"source_frames/nn_upscale/upscale_meta.json"
        )
        live_camera = Path(
            r"V:/Games/Olden Era Playtest Tweak/artifacts/pose_picker_runs/"
            r"h3_crusader/idle_start_move/roc_sprite_camera_fit.json"
        )
        live_manifest = None
        if live_def.is_dir() and live_meta.is_file() and live_camera.is_file():
            live_out = root / "frames_def12_nn_idle_start_move_live"
            live_manifest = materialize_def_group_sequence(
                live_def,
                live_out,
                groups=(2, 20, 0),
                expected_counts=(8, 2, 8),
                target_fps=12.0,
                nn_upscale_meta=live_meta,
                camera_fit=live_camera,
            )
            assert live_manifest["frameCount"] == 18, live_manifest
            assert [clip["frameCount"] for clip in live_manifest["clips"]] == [8, 2, 8], live_manifest
            live_attack = Path(
                r"V:/Games/Olden Era Playtest Tweak/artifacts/pose_picker_runs/"
                r"h3_crusader/idle_attack_front/frames_def12_nn_idle_attack_front"
            )
            live_attack_camera = live_attack.parent / "roc_sprite_camera_fit.json"
            if (live_attack / "def_frames.json").is_file() and live_attack_camera.is_file():
                reused_attack = materialize_def_group_sequence(
                    live_def,
                    live_attack,
                    groups=(2, 12),
                    expected_counts=(8, 7),
                    target_fps=12.0,
                    nn_upscale_meta=live_meta,
                    camera_fit=live_attack_camera,
                )
                assert reused_attack["sourceGroups"] == [2, 12], reused_attack["sourceGroups"]
                assert reused_attack["frameCount"] == 15, reused_attack["frameCount"]
                assert "BepInEx" in reused_attack["sourceDirectory"], reused_attack["sourceDirectory"]
        if live_rife.is_dir() and live_meta.is_file() and live_camera.is_file():
            try:
                materialize_def_group_sequence(
                    live_rife,
                    root / "frames_from_live_rife",
                    groups=(2, 20, 0),
                    expected_counts=(8, 2, 8),
                    nn_upscale_meta=live_meta,
                    camera_fit=live_camera,
                )
                raise AssertionError("live 60 fps lab must not be accepted as authentic DEF")
            except RuntimeError as exc:
                assert "RIFE interpolated plates" in str(exc), str(exc)
        return {
            "ok": True,
            "frameCount": first["frameCount"],
            "clips": first["clips"],
            "liveFrameCount": None if live_manifest is None else live_manifest["frameCount"],
        }


if __name__ == "__main__":
    print(run())
