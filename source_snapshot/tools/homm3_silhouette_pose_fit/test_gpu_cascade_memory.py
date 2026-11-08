"""GPU cascade RAM/speed guards: exclusive lock and one CUDA raster context."""
from __future__ import annotations

import inspect
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import numpy as np
from PIL import Image

from gpu_cascade_batch_lock import (
    SCRIPT_TOKENS,
    acquire_cascade_batch_lock,
    global_cascade_batch_lock_path,
    live_cascade_batch_pids,
    release_cascade_batch_lock,
)
from gpu_raster_depth_animation import (
    occupancy_stack_for_preview,
    render_pose_depth_animation,
)


def run() -> dict[str, object]:
    scratch = Path(__file__).resolve().parent / "_scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    source = inspect.getsource(render_pose_depth_animation)
    assert "RasterizeCudaContext(" not in source, source
    assert "_exact_raster_context" in source, source
    assert global_cascade_batch_lock_path(Path("V:/repo")) == (
        Path("V:/repo/artifacts/pose_picker_runs/gpu_cascade_global.lock")
    )
    for runner_path in sorted(Path(__file__).resolve().parent.glob("run_*.py")):
        runner_source = runner_path.read_text(encoding="utf-8")
        if "run_gpu_depth_fit_from_hybrid_config(" not in runner_source:
            continue
        runner_name = runner_path.name
        assert "global_cascade_batch_lock_path" in runner_source, runner_name
        assert runner_name in SCRIPT_TOKENS, runner_name

    token = uuid.uuid4().hex
    lock_path = scratch / f"gpu_cascade_memory_{token}.lock"
    alpha_dir = scratch / f"gpu_cascade_memory_{token}_alpha"
    alpha_path = alpha_dir / "00.png"
    try:
        acquire_cascade_batch_lock(
            lock_path,
            pid=4242,
            pid_alive=lambda pid: False,
            processes=(),
        )
        assert lock_path.read_text(encoding="utf-8").strip() == "4242"

        acquire_cascade_batch_lock(
            lock_path,
            pid=4243,
            pid_alive=lambda pid: False,
            processes=(),
        )
        assert lock_path.read_text(encoding="utf-8").strip() == "4243"
        release_cascade_batch_lock(lock_path, pid=4243)

        lock_path.write_text("31337\n", encoding="utf-8")
        barrier = Barrier(3)

        def _contend(pid: int) -> str | None:
            barrier.wait()
            try:
                acquire_cascade_batch_lock(
                    lock_path,
                    pid=pid,
                    pid_alive=lambda owner: False,
                    processes=(),
                )
            except RuntimeError as exc:
                return str(exc)
            return None

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(_contend, pid) for pid in (4242, 4243)]
            barrier.wait()
            contender_results = [future.result() for future in futures]
        winners = [pid for pid, err in zip((4242, 4243), contender_results) if err is None]
        assert len(winners) == 1, contender_results
        assert lock_path.read_text(encoding="utf-8").strip() == str(winners[0])
        assert any(err for err in contender_results), contender_results
        release_cascade_batch_lock(lock_path, pid=winners[0])
        acquire_cascade_batch_lock(
            lock_path,
            pid=4243,
            pid_alive=lambda pid: False,
            processes=(),
        )
        assert lock_path.read_text(encoding="utf-8").strip() == "4243"

        release_cascade_batch_lock(lock_path, pid=4243)
        lock_path.touch()
        try:
            acquire_cascade_batch_lock(
                lock_path,
                pid=9001,
                pid_alive=lambda pid: False,
                processes=(),
            )
            raise AssertionError("an empty in-flight lock must fail closed")
        except RuntimeError as exc:
            assert "empty or malformed" in str(exc), str(exc)
        release_cascade_batch_lock(lock_path, pid=9001)
        assert lock_path.exists(), "release must not remove an unowned empty lock"
        lock_path.unlink()
        acquire_cascade_batch_lock(
            lock_path,
            pid=4243,
            pid_alive=lambda pid: False,
            processes=(),
        )

        try:
            acquire_cascade_batch_lock(
                lock_path,
                pid=9001,
                pid_alive=lambda pid: pid == 4243,
                processes=(),
            )
            raise AssertionError("a live lock pid must refuse a second batch")
        except RuntimeError as exc:
            assert "live pid 4243" in str(exc), str(exc)

        try:
            acquire_cascade_batch_lock(
                lock_path,
                pid=9001,
                pid_alive=lambda pid: False,
                processes=((5724, "C:/Python312/python.exe run_crusader_gpu_cascade_animation_set.py --skip-existing"),),
            )
            raise AssertionError("a live sibling cascade process must refuse a second batch")
        except RuntimeError as exc:
            assert "5724" in str(exc), str(exc)

        release_cascade_batch_lock(lock_path, pid=4243)
        assert not lock_path.exists()

        others = live_cascade_batch_pids(
            self_pid=11,
            processes=(
                (11, "run_crusader_gpu_cascade_animation_set.py"),
                (12, "ipykernel_launcher"),
                (13, "python.exe run_crusader_gpu_cascade_animation_set.py --fit-only"),
                (14, "python.exe run_dinov3_branch_vector_examples.py --out elsewhere"),
            ),
        )
        assert others == [13, 14], others

        alpha_dir.mkdir()
        Image.fromarray(np.full((2, 2), 255, dtype=np.uint8), "L").save(alpha_path)

        class _Experiment:
            target_masks = np.array([[[1.0, 0.0], [0.0, 1.0]]], dtype=np.float32)

        target, predicted = occupancy_stack_for_preview(
            _Experiment(),
            alpha_dir=alpha_dir,
            frame_indices=(0,),
            height=4,
            width=4,
        )
        assert target.shape == (1, 4, 4), target.shape
        assert predicted.shape == (1, 4, 4), predicted.shape
        assert float(predicted[0, 0, 0]) == 1.0
    finally:
        lock_path.unlink(missing_ok=True)
        alpha_path.unlink(missing_ok=True)
        if alpha_dir.exists():
            alpha_dir.rmdir()

    return {"ok": True}


if __name__ == "__main__":
    print(run())
