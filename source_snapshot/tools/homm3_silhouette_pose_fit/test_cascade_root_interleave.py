from roc_gpu_cascade_experiment import GpuCascadeConfig


def test_root_interleave_requires_optimize_root_rotation() -> None:
    try:
        GpuCascadeConfig(
            articulated_root_interleave_enabled=True,
            optimize_root_rotation=False,
            root_rotation_defer_camera_up=False,
        ).validate()
    except ValueError as exc:
        assert "articulated_root_interleave_enabled requires optimize_root_rotation" in str(exc)
    else:
        raise AssertionError("expected fail-closed validate")


def test_root_interleave_accepts_modest_window() -> None:
    GpuCascadeConfig(
        articulated_root_interleave_enabled=True,
        optimize_root_rotation=True,
        root_rotation_defer_camera_up=False,
        articulated_root_interleave_rotation_deg=8.0,
        articulated_root_interleave_rotation_step_deg=4.0,
    ).validate()


if __name__ == "__main__":
    test_root_interleave_requires_optimize_root_rotation()
    test_root_interleave_accepts_modest_window()
    print("ok")
