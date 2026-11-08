"""Video Depth Anything pipeline cache: whole-clip only, never mixed with DAV2."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from run_vda_movement_depth import (
    DAV2_MODEL_ID,
    PIPELINE_MANIFEST_NAME,
    VDA_MODEL_ID,
    assert_vda_pipeline_cache,
    ensure_vda_pipeline_cache,
    source_signature,
    _sha256,
)


def _write_rgba(path: Path, value: int) -> None:
    Image.fromarray(np.full((4, 4, 4), value, dtype=np.uint8), "RGBA").save(path)


def _write_depth(path: Path, value: float) -> None:
    Image.fromarray(np.full((4, 4), int(round(value * 65535)), dtype=np.uint16)).save(path)


def _checkpoint(directory: Path) -> Path:
    path = directory / "video_depth_anything_vits.pth"
    path.write_bytes(b"fake-vda-checkpoint")
    return path


def _infer(source_dir: Path, checkpoint: Path, input_size: int, fps: float, calls: list[int]):
    calls.append(1)
    maps = []
    for path in sorted(Path(source_dir).glob("*.png"), key=lambda item: int(item.stem)):
        maps.append(np.full((4, 4), 0.2 + 0.1 * int(path.stem), dtype=np.float32))
    return maps


def run() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        source = root / "frames"
        source.mkdir()
        _write_rgba(source / "00.png", 40)
        _write_rgba(source / "01.png", 80)
        checkpoint = _checkpoint(root)
        owned = root / "frames_ground_truth_depth_vda"
        calls: list[int] = []

        first = ensure_vda_pipeline_cache(
            source,
            owned,
            checkpoint=checkpoint,
            infer_fn=lambda *args: _infer(*args, calls=calls),
        )
        assert first["status"] == "inferred", first
        assert len(calls) == 1, calls
        assert_vda_pipeline_cache(owned)
        assert (owned / "00.png").is_file()
        assert (owned / "01.png").is_file()

        second = ensure_vda_pipeline_cache(
            source,
            owned,
            checkpoint=checkpoint,
            infer_fn=lambda *args: _infer(*args, calls=calls),
        )
        assert second["status"] == "reused", second
        assert len(calls) == 1, "matching VDA cache must not infer again"

        dav2 = root / "frames_ground_truth_depth_predicted"
        dav2.mkdir()
        _write_depth(dav2 / "00.png", 0.5)
        (dav2 / PIPELINE_MANIFEST_NAME).write_text(
            json.dumps({"version": 1, "model": DAV2_MODEL_ID}),
            encoding="utf-8",
        )
        try:
            ensure_vda_pipeline_cache(
                source,
                dav2,
                checkpoint=checkpoint,
                infer_fn=lambda *args: _infer(*args, calls=calls),
            )
            raise AssertionError("DAV2 leftover must be refused, not overwritten")
        except RuntimeError as exc:
            assert "refusing to mix" in str(exc), str(exc)
        try:
            assert_vda_pipeline_cache(dav2)
            raise AssertionError("GPU loader must refuse DAV2 leftover")
        except RuntimeError as exc:
            assert "requires Video-Depth-Anything-Small" in str(exc) or "refusing Depth Anything V2" in str(exc), str(exc)

        unlabeled = root / "mystery_depth"
        unlabeled.mkdir()
        _write_depth(unlabeled / "00.png", 0.3)
        try:
            ensure_vda_pipeline_cache(
                source,
                unlabeled,
                checkpoint=checkpoint,
                infer_fn=lambda *args: _infer(*args, calls=calls),
            )
            raise AssertionError("unlabelled depth PNGs must be refused")
        except RuntimeError as exc:
            assert "unlabelled" in str(exc), str(exc)

        run_dir = root / "vda_small"
        (run_dir / "depth").mkdir(parents=True)
        imported_owned = root / "imported_vda"
        for name, value in (("00.png", 0.9), ("01.png", 0.1)):
            _write_depth(run_dir / "depth" / name, value)
        (run_dir / "vda_s_manifest.json").write_text(
            json.dumps(
                {
                    "model": VDA_MODEL_ID,
                    "checkpoint_sha256": _sha256(checkpoint),
                    "source_frame_sha256": [
                        _sha256(source / "00.png"),
                        _sha256(source / "01.png"),
                    ],
                }
            ),
            encoding="utf-8",
        )
        imported = ensure_vda_pipeline_cache(
            source,
            imported_owned,
            checkpoint=checkpoint,
            import_run_dir=run_dir,
            infer_fn=lambda *args: (_ for _ in ()).throw(AssertionError("matching comparison run must copy, not infer")),
        )
        assert imported["status"] == "imported", imported
        assert_vda_pipeline_cache(imported_owned)

        stale_run = root / "stale_vda_small"
        (stale_run / "depth").mkdir(parents=True)
        _write_depth(stale_run / "depth" / "00.png", 0.4)
        _write_depth(stale_run / "depth" / "01.png", 0.4)
        (stale_run / "vda_s_manifest.json").write_text(
            json.dumps(
                {
                    "model": VDA_MODEL_ID,
                    "checkpoint_sha256": _sha256(checkpoint),
                    "source_frame_sha256": ["dead" * 16, "beef" * 16],
                }
            ),
            encoding="utf-8",
        )
        stale_owned = root / "stale_import"
        stale_calls: list[int] = []
        inferred = ensure_vda_pipeline_cache(
            source,
            stale_owned,
            checkpoint=checkpoint,
            import_run_dir=stale_run,
            infer_fn=lambda *args: _infer(*args, calls=stale_calls),
        )
        assert inferred["status"] == "inferred", inferred
        assert stale_calls == [1], stale_calls

        _write_rgba(source / "00.png", 200)
        assert source_signature(source) != json.loads(
            (owned / PIPELINE_MANIFEST_NAME).read_text(encoding="utf-8")
        )["sourceSignature"]
        refreshed_calls: list[int] = []
        refreshed = ensure_vda_pipeline_cache(
            source,
            owned,
            checkpoint=checkpoint,
            infer_fn=lambda *args: _infer(*args, calls=refreshed_calls),
        )
        assert refreshed["status"] == "inferred", refreshed
        assert refreshed_calls == [1], "source hash change must rebuild the whole clip"

        missing_ckpt = root / "no_checkpoint.pth"
        try:
            ensure_vda_pipeline_cache(
                source,
                root / "unused",
                checkpoint=missing_ckpt,
                infer_fn=lambda *args: _infer(*args, calls=[]),
            )
            raise AssertionError("missing VDA checkpoint must be refused")
        except FileNotFoundError as exc:
            assert "VDA-S checkpoint is missing" in str(exc), str(exc)

    return {"ok": True}


if __name__ == "__main__":
    print(run())
