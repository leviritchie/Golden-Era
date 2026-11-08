"""Owned GPU run slots replace leftover artifact folders instead of mixing frames."""
from __future__ import annotations

import tempfile
from pathlib import Path

from gpu_raster_depth_animation import (
    replace_owned_run_artifacts,
    render_pose_depth_animation,
    render_pose_rgb_animation,
)


def run() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as raw:
        leftover = Path(raw) / "gpu_depth_silhouette_simple"
        solved = leftover / "solved_depth"
        solved.mkdir(parents=True)
        (solved / "00.png").write_bytes(b"old")
        rgb = leftover / "solved_rgb"
        rgb.mkdir()
        (rgb / "00.png").write_bytes(b"old-rgb")
        (leftover / "preview").mkdir()
        unrelated = leftover / "keep_me.txt"
        unrelated.write_text("not an owned child\n", encoding="utf-8")
        poses = leftover / "gpu_clip_result.json"
        poses.write_text('{"poses": {"0": {}}}\n', encoding="utf-8")

        replace_owned_run_artifacts(leftover)
        assert not solved.exists(), solved
        assert not rgb.exists(), rgb
        assert not (leftover / "preview").exists()
        assert unrelated.is_file(), "unrelated files in the slot parent must survive"
        assert poses.is_file(), "persisted poses must survive leftover raster folders"

        blocked = leftover / "solved_depth"
        blocked.mkdir()
        replace_owned_run_artifacts(leftover, children=("solved_depth", "solved_alpha", "solved_rgb", "preview"))
        assert not blocked.exists()
        assert (leftover / "gpu_clip_result.json").is_file()

        blocked = leftover / "solved_depth"
        blocked.mkdir()
        try:
            render_pose_depth_animation(None, {}, output_dir=blocked, frame_indices=(0,))
            raise AssertionError("direct raster into an existing folder must stay fail-closed")
        except FileExistsError as exc:
            assert "refusing to overwrite raster output" in str(exc), str(exc)

        blocked_rgb = leftover / "solved_rgb"
        blocked_rgb.mkdir()
        try:
            render_pose_rgb_animation(None, {}, output_dir=blocked_rgb, frame_indices=(0,))
            raise AssertionError("direct RGB raster into an existing folder must stay fail-closed")
        except FileExistsError as exc:
            assert "refusing to overwrite raster RGB output" in str(exc), str(exc)

        replace_owned_run_artifacts(leftover)
        assert not blocked.exists()
        assert not blocked_rgb.exists()
        return {"ok": True}


if __name__ == "__main__":
    print(run())
