"""Place lab RIFE frames onto the pose-fit nn-upscale canvas without rescaling the camera."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from PIL import Image

from materialize_rife_source_frames import (
    load_nn_upscale_contract,
    materialize_rife_group_frames,
    materialize_rife_group_sequence,
    nn_upscale_native_frame,
    normalize_rife_group_plan,
)


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
        for index in range(5):
            _png(lab / f"00_{index:04d}.png", 10 + index)
        _png(lab / "02_0000.png", 99)
        meta = root / "upscale_meta.json"
        _upscale_meta(meta)
        out = root / "frames_rife60_nn"
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
        first = materialize_rife_group_frames(
            lab,
            out,
            group=0,
            expected_count=5,
            target_fps=60.0,
            nn_upscale_meta=meta,
            camera_fit=seed,
        )
        assert first["frameCount"] == 5, first
        assert first["sourceKind"] == "lab_rife_nn_upscale", first
        assert first["sourceResolution"] == [16, 12], first
        assert (out / "00.png").is_file()
        assert (out / "04.png").is_file()
        assert not (out / "02_0000.png").exists()
        with Image.open(out / "00.png") as image:
            assert image.size == (16, 12), image.size
        camera = json.loads(seed.read_text(encoding="utf-8"))
        assert camera["sourceResolution"] == [16, 12], camera
        assert abs(float(camera["pxPerWorld"]) - 40.0) < 1e-9, camera

        second = materialize_rife_group_frames(
            lab,
            out,
            group=0,
            expected_count=5,
            nn_upscale_meta=meta,
            camera_fit=seed,
        )
        assert second["frameCount"] == 5

        for index in range(3):
            _png(lab / f"02_{index:04d}.png", 40 + index)
        _png(lab / "20_0000.png", 70)
        _png(lab / "20_0001.png", 71)
        sequence = root / "frames_rife60_nn_idle_start_move"
        try:
            normalize_rife_group_plan((2, 20, 0), 8)
            raise AssertionError("a single expected_count must not cover a sequence")
        except ValueError as exc:
            assert "length must match" in str(exc), str(exc)
        try:
            materialize_rife_group_sequence(
                lab,
                sequence,
                groups=(2, 20),
                expected_counts=(3,),
                nn_upscale_meta=meta,
                camera_fit=seed,
            )
            raise AssertionError("mismatched sequence counts must be refused")
        except ValueError as exc:
            assert "length must match" in str(exc), str(exc)

        first_sequence = materialize_rife_group_sequence(
            lab,
            sequence,
            groups=(2, 20, 0),
            expected_counts=(3, 2, 5),
            nn_upscale_meta=meta,
            camera_fit=seed,
            target_fps=60.0,
        )
        assert first_sequence["sourceKind"] == "lab_rife_nn_upscale_sequence", first_sequence
        assert first_sequence["frameCount"] == 10, first_sequence
        assert [clip["name"] for clip in first_sequence["clips"]] == ["idle", "move_start", "move"]
        assert first_sequence["clips"][0]["startIndex"] == 0
        assert first_sequence["clips"][1]["startIndex"] == 3
        assert first_sequence["clips"][2]["startIndex"] == 5
        assert (sequence / "00.png").is_file()
        assert (sequence / "09.png").is_file()
        cached_sequence = materialize_rife_group_sequence(
            lab,
            sequence,
            groups=(2, 20, 0),
            expected_counts=(3, 2, 5),
            nn_upscale_meta=meta,
            camera_fit=seed,
        )
        assert cached_sequence["frameCount"] == 10
        try:
            materialize_rife_group_frames(
                lab, sequence, group=0, expected_count=5, nn_upscale_meta=meta, camera_fit=seed
            )
            raise AssertionError("a single group must not mix into a sequence folder")
        except RuntimeError as exc:
            assert "refusing to mix" in str(exc), str(exc)
        try:
            materialize_rife_group_sequence(
                lab,
                out,
                groups=(2, 0),
                expected_counts=(3, 5),
                nn_upscale_meta=meta,
                camera_fit=seed,
            )
            raise AssertionError("a sequence must not mix into a single-group folder")
        except RuntimeError as exc:
            assert "refusing to mix" in str(exc), str(exc)

        native_camera = root / "native_plate_camera.json"
        native_camera.write_text(
            json.dumps(
                {
                    "sourceResolution": [8, 6],
                    "pxPerWorld": 20.0,
                    "screenOffsetPx": [4.0, 3.0],
                }
            ),
            encoding="utf-8",
        )
        try:
            materialize_rife_group_frames(
                lab,
                root / "frames_rife_native_camera",
                group=0,
                expected_count=5,
                nn_upscale_meta=meta,
                camera_fit=native_camera,
            )
            raise AssertionError("a native-plate camera must not be accepted for the nn canvas")
        except ValueError as exc:
            assert "native RIFE plate" in str(exc) or "does not match" in str(exc), str(exc)

        try:
            materialize_rife_group_frames(lab, out, group=2, expected_count=3, nn_upscale_meta=meta)
            raise AssertionError("a different RIFE group must not mix into the same folder")
        except RuntimeError as exc:
            assert "refusing to mix" in str(exc), str(exc)

        try:
            materialize_rife_group_frames(lab, out, group=0, expected_count=4, nn_upscale_meta=meta)
            raise AssertionError("wrong expected_count must be refused")
        except RuntimeError as exc:
            assert "expected 4" in str(exc), str(exc)

        blocked = root / "frames_ground_truth"
        blocked.mkdir()
        (blocked / "keep.txt").write_text("no\n", encoding="utf-8")
        try:
            materialize_rife_group_frames(
                lab, blocked, group=0, expected_count=5, nn_upscale_meta=meta
            )
            raise AssertionError("non-empty unlabelled folder must be refused")
        except FileExistsError:
            pass

        contract = load_nn_upscale_contract(meta)
        with Image.open(lab / "00_0000.png") as image:
            placed = nn_upscale_native_frame(image, contract)
        assert placed.size == (16, 12)

        overflow_lab = root / "overflow.dir"
        overflow_lab.mkdir()
        _png(overflow_lab / "00_0000.png", 10, size=(10, 6))
        try:
            materialize_rife_group_frames(
                overflow_lab,
                root / "frames_overflow",
                group=0,
                expected_count=1,
                nn_upscale_meta=meta,
            )
            raise AssertionError("a plate larger than sourceSize must be refused")
        except ValueError as exc:
            assert "sourceSize" in str(exc), str(exc)

        tight = root / "tight_meta.json"
        tight.write_text(
            json.dumps(
                {
                    "ok": True,
                    "method": "shared_union_crop_nearest_neighbor",
                    "sourceSize": [8, 6],
                    "unionBBox": [2, 2, 5, 4],
                    "cropSize": [4, 3],
                    "pad": 0,
                    "scale": 2,
                    "outSize": [8, 6],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        subject_lab = root / "subject.dir"
        subject_lab.mkdir()
        # Opaque pixel at (0,0) sits outside unionBBox [2,2,5,4].
        _png(subject_lab / "00_0000.png", 10, size=(8, 6))
        try:
            materialize_rife_group_frames(
                subject_lab,
                root / "frames_subject_overflow",
                group=0,
                expected_count=1,
                nn_upscale_meta=tight,
            )
            raise AssertionError("subject overflow outside the union bbox must be refused")
        except RuntimeError as exc:
            assert "exceeds the recorded nn-upscale union bbox" in str(exc), str(exc)
    return {"ok": True}


if __name__ == "__main__":
    print(run())
