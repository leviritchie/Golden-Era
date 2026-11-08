"""Profile-init scale must use the PNG alpha channel, not RGB luma."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

from gpu_depth_silhouette_solver import _discover_idle_profile_target_dir
from gpu_profile_camera_initializer import _load_alpha_mask


def run() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        rife_like = np.full((40, 50, 4), 32, dtype=np.uint8)
        rife_like[:, :, 3] = 0
        rife_like[10:18, 20:28, 3] = 255
        rife_path = root / "rife00.png"
        Image.fromarray(rife_like, "RGBA").save(rife_path)
        mask = _load_alpha_mask(rife_path, (50, 40), 8)
        assert mask.shape == (40, 50), mask.shape
        assert not bool(mask[0, 0]), "zero-alpha gray RGB must not count as the subject"
        assert bool(mask[10, 20])
        ys, xs = np.where(mask)
        assert (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())) == (20, 10, 27, 17)

        luma = np.asarray(Image.open(rife_path).convert("L"))
        assert int((luma >= 8).sum()) == 50 * 40, "this fixture must keep the convert(L) trap"

        rgb_only = root / "rgb.png"
        Image.fromarray(rife_like[:, :, :3], "RGB").save(rgb_only)
        try:
            _load_alpha_mask(rgb_only, (50, 40), 8)
            raise AssertionError("RGB-only sprites must not be treated as silhouettes")
        except ValueError as exc:
            assert "alpha" in str(exc), str(exc)

        real = Path(
            r"V:/Games/Olden Era Playtest Tweak/artifacts/pose_picker_runs/h3_crusader/move_g0/frames_rife60_nn_shadow_culled/00.png"
        )
        if not real.is_file():
            raise FileNotFoundError(f"RIFE frame 00 is missing for the scale regression check: {real}")
        real_mask = _load_alpha_mask(real, (256, 204), 8)
        rys, rxs = np.where(real_mask)
        assert int(rxs.min()) > 0 and int(rys.min()) > 0, (int(rxs.min()), int(rys.min()))
        assert int(rxs.max()) < 255 and int(rys.max()) < 203, (int(rxs.max()), int(rys.max()))

        unit_root = root / "artifacts" / "pose_picker_runs" / "h3_crusader"
        idle = unit_root / "idle_g2" / "frames_ground_truth_shadow_culled"
        idle.mkdir(parents=True)
        Image.fromarray(rife_like, "RGBA").save(idle / "00.png")
        move = unit_root / "move_g0"
        config = SimpleNamespace(
            root=root,
            unit_name="crusader",
            unit_sid=None,
            shadow_culled_frame_dir="frames_rife60_nn_shadow_culled",
        )
        found = _discover_idle_profile_target_dir(config, move, move / "frames_rife60_nn_shadow_culled")
        assert found == idle.resolve(), found

        missing_root = root / "missing_unit"
        missing_pilot = missing_root / "move_g0"
        missing_pilot.mkdir(parents=True)
        try:
            _discover_idle_profile_target_dir(
                SimpleNamespace(
                    root=missing_root,
                    unit_name="nobody",
                    unit_sid=None,
                    shadow_culled_frame_dir="frames_rife60_nn_shadow_culled",
                ),
                missing_pilot,
                missing_pilot / "frames_rife60_nn_shadow_culled",
            )
            raise AssertionError("idle discovery must not fall back to the movement folder")
        except FileNotFoundError as exc:
            assert "idle bind silhouette" in str(exc), str(exc)

        idle_leading = missing_pilot / "frames_def12_nn_idle_start_move"
        idle_leading.mkdir(parents=True)
        Image.fromarray(rife_like, "RGBA").save(idle_leading / "00.png")
        found_sequence = _discover_idle_profile_target_dir(
            SimpleNamespace(
                root=missing_root,
                unit_name="nobody",
                unit_sid=None,
                shadow_culled_frame_dir="frames_def12_nn_idle_start_move_shadow_culled",
                def_lab_group=(2, 20, 0),
            ),
            missing_pilot,
            idle_leading,
        )
        assert found_sequence == idle_leading.resolve(), found_sequence

        hob_root = root / "artifacts" / "pose_picker_runs" / "h3_hobgoblin"
        attack_pilot = hob_root / "attack_front"
        attack_pilot.mkdir(parents=True)
        wrong = hob_root / "idle" / "frames_def12_nn_attack_front_shadow_culled"
        wrong.mkdir(parents=True)
        Image.fromarray(rife_like, "RGBA").save(wrong / "00.png")
        try:
            _discover_idle_profile_target_dir(
                SimpleNamespace(
                    root=root,
                    unit_name="hobgoblin",
                    unit_sid="h3_hobgoblin",
                    shadow_culled_frame_dir="frames_def12_nn_attack_front_shadow_culled",
                    def_lab_group=(12,),
                    def_lab_frame_dir=None,
                    def_nn_upscale_meta=None,
                ),
                attack_pilot,
                attack_pilot / "frames_def12_nn_attack_front_shadow_culled",
            )
            raise AssertionError("must not treat idle/frames_def12_nn_attack_front_shadow_culled as idle")
        except FileNotFoundError as exc:
            assert "idle bind silhouette" in str(exc), str(exc)
            assert "frames_def12_nn_idle_shadow_culled" in str(exc), str(exc)

        idle_def = hob_root / "idle" / "frames_def12_nn_idle_shadow_culled"
        idle_def.mkdir(parents=True)
        Image.fromarray(rife_like, "RGBA").save(idle_def / "00.png")
        found_motion = _discover_idle_profile_target_dir(
            SimpleNamespace(
                root=root,
                unit_name="hobgoblin",
                unit_sid="h3_hobgoblin",
                shadow_culled_frame_dir="frames_def12_nn_attack_front_shadow_culled",
                def_lab_group=(12,),
            ),
            attack_pilot,
            attack_pilot / "frames_def12_nn_attack_front_shadow_culled",
        )
        assert found_motion == idle_def.resolve(), found_motion

        lab = root / "hob_lab"
        lab.mkdir()
        plate = Image.fromarray(rife_like, "RGBA").resize((8, 6))
        plate.save(lab / "02_00.png")
        plate.save(lab / "12_00.png")
        meta = root / "hob_upscale_meta.json"
        meta.write_text(
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
        fresh_unit = root / "artifacts" / "pose_picker_runs" / "h3_fresh"
        fresh_attack = fresh_unit / "attack_front"
        fresh_attack.mkdir(parents=True)
        prepared = _discover_idle_profile_target_dir(
            SimpleNamespace(
                root=root,
                unit_name="fresh",
                unit_sid="h3_fresh",
                shadow_culled_frame_dir="frames_def12_nn_attack_front_shadow_culled",
                def_lab_group=(12,),
                def_lab_frame_dir=lab,
                def_nn_upscale_meta=meta,
                depth_video_fps=12.0,
            ),
            fresh_attack,
            fresh_attack / "frames_def12_nn_attack_front_shadow_culled",
        )
        expected_idle = (fresh_unit / "idle" / "frames_def12_nn_idle_shadow_culled").resolve()
        assert prepared == expected_idle, prepared
        assert (expected_idle / "00.png").is_file()
    return {"ok": True}


if __name__ == "__main__":
    print(run())
