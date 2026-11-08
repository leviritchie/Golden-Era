"""Focused dispatch and parity tests for the phase-6 town pan validator."""
from __future__ import annotations

import contextlib
import hashlib
import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(TOOLS))

import validate_town_scene3d_contract as contract
import town_gpu_pan

STAGED_PARITY_RAYS = 128


def _base_npz(shape=(32, 32), x0=-1.0, z0=-1.0, res=0.1, frame_wh=(2, 2)):
    nz, nx = shape
    frame_w, frame_h = frame_wh
    heights = np.full((nz, nx), -1000.0, dtype=np.float32)
    outer = np.full((nz, nx), -np.inf, dtype=np.float32)
    covered = np.zeros((nz, nx), dtype=np.bool_)
    return {
        "h": heights,
        "outer_h": outer,
        "covered": covered,
        "x0": x0,
        "z0": z0,
        "res": res,
        "cam_pos": np.array([0.0, 0.0, 0.0], dtype=np.float64),
        "cam_fwd": np.array([0.0, 0.0, 1.0], dtype=np.float64),
        "cam_up": np.array([0.0, 1.0, 0.0], dtype=np.float64),
        "cam_right": np.array([1.0, 0.0, 0.0], dtype=np.float64),
        "frame_wh": np.array([frame_w, frame_h], dtype=np.int32),
        "frame_sky": np.ones((frame_h, frame_w), dtype=np.bool_),
        "fov": np.array(90.0, dtype=np.float64),
        "C": np.eye(3, dtype=np.float64),
        "cpos": np.zeros(3, dtype=np.float64),
        "depth_scale": np.array(1.0, dtype=np.float64),
        "dome_r": np.array(10.0, dtype=np.float64),
        "sky_az": np.array([-1.0, 1.0], dtype=np.float64),
        "sky_el": np.array([-1.0, 1.0], dtype=np.float64),
    }


def _cpu_cuda_parity(npz, origins, directions, strip_outer=False):
    expected = contract.pan_voids_cpu(npz, origins, directions, strip_outer=strip_outer)
    from town_full3d_gpu import gate as gpu_gate
    started = time.perf_counter()
    with gpu_gate("phase-6 pan CUDA parity", need_vram_gb=1.0, wait_min=0.5):
        engine = town_gpu_pan.PanVoidEngine(npz)
        actual = engine.voids(origins, directions, strip_outer=strip_outer)
        buffer_bytes = engine.estimated_peak_buffer_bytes
        del engine
    elapsed = time.perf_counter() - started
    print(f"town-pan parity fixture: rays={len(origins)} strip_outer={strip_outer} seconds={elapsed:.3f} "
          f"known_device_buffers_mib={buffer_bytes / (1024 * 1024):.3f} "
          f"(excludes driver/context/compiler allocations)", flush=True)
    np.testing.assert_array_equal(actual, expected)
    return expected


class PanDeviceDispatchTests(unittest.TestCase):
    def test_production_dispatch_defaults_to_cuda(self):
        self.assertEqual(contract.PAN_DEFAULT_DEVICE, "cuda")
        self.assertEqual(contract.pan_voids_device.__defaults__[1], "cuda")
        self.assertEqual(contract.check_pan_coverage.__defaults__[-1], "cuda")
        self.assertIs(contract.PAN_BATCH, town_gpu_pan.PAN_BATCH)
        self.assertIs(contract.PAN_MAX_STEPS, town_gpu_pan.MAX_STEPS)
        self.assertIs(contract.PAN_EL_MIN, town_gpu_pan.PAN_EL_MIN)
        self.assertEqual(contract.PAN_BATCH, 8192)
        self.assertEqual(contract.PAN_MAX_STEPS, 4000)
        self.assertEqual(contract.PAN_EL_MIN, -1.0)

    def test_invalid_frame_shape_fails_before_cuda_initialization(self):
        malformed = _base_npz()
        malformed["frame_wh"] = np.array([3, 2], dtype=np.int32)
        with patch.object(town_gpu_pan, "ensure_cuda_available", side_effect=AssertionError("unexpected CUDA")):
            with self.assertRaisesRegex(ValueError, "frame_sky shape"):
                town_gpu_pan.PanVoidEngine(malformed)

    def test_malformed_metadata_and_rays_fail_before_any_dispatch(self):
        cases = (
            ("res", np.array(0.0), "res must be greater"),
            ("fov", np.array(180.0), "fov must be between"),
            ("dome_r", np.array(np.nan), "dome_r must contain only finite"),
            ("sky_az", np.array([-1.0, 0.0, 1.0]), "sky_az must have shape"),
            ("sky_el", np.array([1.0, -1.0]), "sky_el bounds must be ordered"),
            ("cam_pos", np.array([0.0 + 1.0j, 0.0, 0.0]), "cam_pos must contain real numeric"),
            ("C", np.eye(2), "C must have shape"),
            ("depth_scale", np.array([1.0]), "depth_scale must be a finite real scalar"),
        )
        origins = np.zeros((1, 3), dtype=np.float64)
        directions = np.array([[0.0, 0.0, 1.0]], dtype=np.float64)
        with patch.object(town_gpu_pan, "ensure_cuda_available", side_effect=AssertionError("unexpected CUDA")), \
                patch.object(contract, "pan_voids_cpu", side_effect=AssertionError("invalid evidence dispatched")):
            for key, value, message in cases:
                with self.subTest(key=key):
                    malformed = _base_npz()
                    malformed[key] = value
                    with self.assertRaisesRegex(ValueError, message):
                        contract.pan_voids_device(malformed, origins, directions, device="cpu")

            with self.assertRaisesRegex(ValueError, "ray origins must contain real numeric"):
                contract.pan_voids_device(_base_npz(), origins.astype(np.complex128), directions, device="cpu")
            with self.assertRaisesRegex(ValueError, "ray directions must contain only finite"):
                contract.pan_voids_device(_base_npz(), origins, np.array([[np.nan, 0.0, 1.0]]), device="cpu")

    def test_explicit_cpu_dispatch_uses_reference_without_importing_cuda(self):
        npz = _base_npz()
        origins = np.array([[0.0, 1.0, 0.0]], dtype=np.float64)
        directions = np.array([[0.0, 0.0, 1.0]], dtype=np.float64)
        with patch.object(town_gpu_pan, "ensure_cuda_available", side_effect=AssertionError("unexpected CUDA")):
            expected = contract.pan_voids_cpu(npz, origins, directions)
            actual = contract.pan_voids_device(npz, origins, directions, device="cpu")
        np.testing.assert_array_equal(actual, expected)

    def test_cuda_failure_is_not_retried_on_cpu(self):
        npz = _base_npz()
        origins = np.zeros((1, 3), dtype=np.float64)
        directions = np.array([[0.0, 0.0, 1.0]], dtype=np.float64)
        with patch.object(contract, "pan_voids_cpu", side_effect=AssertionError("silent CPU fallback")):
            with patch.object(town_gpu_pan, "PanVoidEngine", side_effect=RuntimeError("CUDA launch failed")):
                with self.assertRaisesRegex(RuntimeError, "CUDA launch failed"):
                    contract.pan_voids_device(npz, origins, directions, device="cuda")

    def test_ray_batches_keep_complete_samples_and_one_catalog_upload(self):
        sizes = []
        strips = []
        instances = []

        class FakeEngine:
            def __init__(self, npz):
                self.npz = npz
                instances.append(self)

            def voids(self, origins, directions, strip_outer=False):
                sizes.append(len(origins))
                strips.append(strip_outer)
                return np.full(len(origins), strip_outer, dtype=np.bool_)

        @contextlib.contextmanager
        def fake_gate(*args, **kwargs):
            self.assertEqual(args, ("phase-6 pan coverage",))
            self.assertEqual(kwargs, {"need_vram_gb": 1.0, "wait_min": 0.5})
            yield

        ray_count = contract.PAN_BATCH + 2
        rays = {
            "16:9": {"O": np.zeros((ray_count, 3)), "D": np.ones((ray_count, 3)),
                     "mode": np.full(ray_count, "center")},
            "21:9": {"O": np.zeros((3, 3)), "D": np.ones((3, 3)), "mode": np.full(3, "edge")},
        }
        with patch("town_full3d_gpu.gate", side_effect=fake_gate), \
                patch.object(town_gpu_pan, "PanVoidEngine", FakeEngine):
            total, negative_share = contract._check_pan_rays(_base_npz(), rays, "dispatch-test", "cuda")

        self.assertEqual(total, ray_count + 3)
        self.assertEqual(negative_share, 1.0)
        self.assertEqual(len(instances), 1)
        self.assertEqual(sizes, [contract.PAN_BATCH, 2, contract.PAN_BATCH, 2, 3])
        self.assertEqual(strips, [False, False, True, True, False])


class PanCudaParityTests(unittest.TestCase):
    def test_frame_projection_border_tolerance(self):
        npz = _base_npz(shape=(41, 41), x0=-2.0, z0=-1.0, res=0.1)
        npz["h"][:] = 1.0
        npz["frame_sky"][:] = True
        npz["frame_sky"][1, 0] = False
        npz["frame_sky"][1, 1] = False
        slopes = (1.00005, 1.0002, -1.00005, -1.0002)
        directions = np.array([[slope, 0.0, 1.0] for slope in slopes], dtype=np.float64)
        directions /= np.linalg.norm(directions, axis=1, keepdims=True)
        origins = np.zeros_like(directions)
        result = _cpu_cuda_parity(npz, origins, directions)
        np.testing.assert_array_equal(result, [False, True, False, True])

    def test_dome_angular_inclusive_boundaries(self):
        # The dome window is inclusive. Exact zero is accepted; infinitesimal azimuth/elevation offsets are not.
        npz = _base_npz()
        npz["sky_az"] = np.array([0.0, 0.0])
        npz["sky_el"] = np.array([0.0, 0.0])
        origins = np.array([[0.0, 0.0, 3.0]] * 5, dtype=np.float64)
        directions = np.array([
            [0.0, 0.0, 1.0],
            [1e-8, 0.0, 1.0],
            [-1e-8, 0.0, 1.0],
            [0.0, 1e-8, 1.0],
            [0.0, -1e-8, 1.0],
        ], dtype=np.float64)
        directions /= np.linalg.norm(directions, axis=1, keepdims=True)
        result = _cpu_cuda_parity(npz, origins, directions)
        np.testing.assert_array_equal(result, [False, True, True, True, True])

    def test_float32_outer_height_and_strip_outer_disables_near_lip_step(self):
        npz = _base_npz(shape=(21, 32), x0=-1.0, z0=-1.0, res=0.1)
        row = 10
        npz["covered"][row, 7:10] = True
        npz["outer_h"][row, 7:10] = np.float32(-0.2)
        npz["outer_h"][row, 9] = np.float32(0.1)
        origins = np.array([[-0.6, 0.1, 0.0]], dtype=np.float64)
        directions = np.array([[1.0, 0.0, 0.0]], dtype=np.float64)
        self.assertFalse(contract.pan_voids_cpu(npz, origins, directions)[0])
        self.assertTrue(contract.pan_voids_cpu(npz, origins, directions, strip_outer=True)[0])
        np.testing.assert_array_equal(_cpu_cuda_parity(npz, origins, directions), [False])
        np.testing.assert_array_equal(_cpu_cuda_parity(npz, origins, directions, strip_outer=True), [True])

    def test_round_even_positive_and_negative_half_indices(self):
        npz = _base_npz(shape=(2, 3), x0=0.0, z0=0.0, res=1.0, frame_wh=(1, 1))
        npz["covered"][0, 0] = True
        npz["covered"][0, 2] = True
        npz["outer_h"][0, 0] = np.float32(1.0)
        npz["outer_h"][0, 2] = np.float32(1.0)
        npz["sky_el"] = np.array([-1.0, 1.0])
        xs = (1.5, np.nextafter(1.5, -np.inf), np.nextafter(1.5, np.inf),
              -0.5, np.nextafter(-0.5, -np.inf), np.nextafter(-0.5, np.inf), 1.0)
        origins = np.array([[x, 2.0, 0.5] for x in xs], dtype=np.float64)
        directions = np.tile([0.0, -1.0, 0.0], (len(xs), 1)).astype(np.float64)
        result = _cpu_cuda_parity(npz, origins, directions)
        np.testing.assert_array_equal(result, [False, True, False, False, True, False, True])

    def test_strict_frame_depth_boundary(self):
        npz = _base_npz(shape=(1, 1), x0=0.0, z0=0.3, res=0.1, frame_wh=(1, 1))
        npz["h"][0, 0] = np.float32(0.0)
        npz["frame_sky"][0, 0] = False
        npz["sky_az"] = np.array([90.0, 90.0])
        origins = np.array([[0.0, 0.0, 0.0]], dtype=np.float64)
        directions = np.array([[0.0, 0.0, 1.0]], dtype=np.float64)

        at_or_below = dict(npz, cam_pos=np.array([0.0, 0.0, 0.25]))
        just_above = dict(npz, cam_pos=np.array([0.0, 0.0, 0.2499999]))
        np.testing.assert_array_equal(_cpu_cuda_parity(at_or_below, origins, directions), [True])
        np.testing.assert_array_equal(_cpu_cuda_parity(just_above, origins, directions), [False])

    def test_loop_exhaustion_matches_exact_4000_check_cap(self):
        npz = _base_npz(shape=(1, 1), x0=0.0, z0=0.0, res=1.0, frame_wh=(1, 1))
        npz["cam_fwd"] = np.array([0.0, -1.0, 0.0])
        npz["cam_up"] = np.array([0.0, 0.0, 1.0])
        npz["cam_right"] = np.array([1.0, 0.0, 0.0])
        npz["frame_sky"][0, 0] = False

        t = np.float64(0.3)
        after_3999_checks = None
        after_4000_checks = None
        for check in range(contract.PAN_MAX_STEPS):
            if check == contract.PAN_MAX_STEPS - 1:
                after_3999_checks = t
            t += 0.25 + 0.01 * t
        after_4000_checks = t
        y_before_cap = -after_3999_checks
        y_at_next_check = -after_4000_checks
        threshold = np.float32((y_before_cap + y_at_next_check) * 0.5)
        self.assertGreater(y_before_cap, threshold)
        self.assertLessEqual(y_at_next_check, threshold)
        npz["h"][0, 0] = threshold

        origins = np.array([[0.0, 0.0, 0.0]], dtype=np.float64)
        directions = np.array([[0.0, -1.0, 0.0]], dtype=np.float64)
        self.assertTrue(contract.pan_voids_cpu(npz, origins, directions)[0])
        np.testing.assert_array_equal(_cpu_cuda_parity(npz, origins, directions), [True])


def run_cuda_parity(test_name: str | None = None) -> None:
    """Opt-in CUDA-only parity run; it never reduces ray counts or falls back to CPU."""
    started = time.perf_counter()
    town_gpu_pan.ensure_cuda_available()
    print("town-pan CUDA parity: backend=Numba CUDA; synthetic fixtures only", flush=True)
    if test_name is None:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(PanCudaParityTests)
    else:
        suite = unittest.defaultTestLoader.loadTestsFromName(f"PanCudaParityTests.{test_name}", sys.modules[__name__])
        if suite.countTestCases() != 1:
            raise SystemExit(f"unknown CUDA parity fixture {test_name!r}")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    elapsed = time.perf_counter() - started
    print(f"town-pan CUDA parity: seconds={elapsed:.3f} failed={len(result.failures)} "
          f"errors={len(result.errors)}", flush=True)
    if not result.wasSuccessful():
        raise SystemExit(1)


def _sample_staged_rays(npz, pan, sample_count=STAGED_PARITY_RAYS):
    """Build exact evenly spaced members of pan_rays_w's flattened outputs without materializing all rays."""
    city = pan.load()
    root_pos, root_rot = pan.root_frame(city)
    poses = pan.poses(city, per_seg=16)
    depth_scale = float(npz["depth_scale"])
    fov = float(npz["fov"])
    C = np.asarray(npz["C"], dtype=np.float64)
    cpos = np.asarray(npz["cpos"], dtype=np.float64)
    sampled = {}
    for name, aspect in pan.ASPECTS.items():
        kx = aspect / pan.REF_ASPECT
        k = np.array([kx, 1.0, 1.0])
        local_dirs = pan.image_rays(fov, aspect, nx=25, ny=15)
        rays_per_pose = len(local_dirs)
        full_count = len(poses) * rays_per_pose
        source_indices = np.linspace(0, full_count - 1, min(sample_count, full_count), dtype=np.int64)
        pose_indices = source_indices // rays_per_pose
        pixel_indices = source_indices % rays_per_pose
        origins = np.empty((len(source_indices), 3), dtype=np.float64)
        directions = np.empty_like(origins)
        modes = np.empty(len(source_indices), dtype=object)
        for pose_index in np.unique(pose_indices):
            selected = np.flatnonzero(pose_indices == pose_index)
            pose = poses[int(pose_index)]
            q = (root_rot.T @ (pose["p"] - root_pos)) / k
            d = (local_dirs @ pose["R"].T @ root_rot) / k
            origin_w = cpos + (q / depth_scale) @ C.T
            direction_w = (d / depth_scale) @ C.T
            direction_w /= np.linalg.norm(direction_w, axis=1, keepdims=True)
            origins[selected] = origin_w
            directions[selected] = direction_w[pixel_indices[selected]]
            modes[selected] = pose["mode"]
        sampled[name] = {"O": origins, "D": directions, "mode": modes, "indices": source_indices,
                         "source_count": full_count}
    return sampled


def run_staged_parity() -> None:
    """Read-only sampled parity for all staged catalogs; never changes production ray acceptance counts."""
    import numpy as np

    town_gpu_pan.ensure_cuda_available()
    from conflux_town_camera_pan import ASPECTS
    from town_full3d_gpu import gate as gpu_gate

    folders = sorted(p for p in contract.SCENE3D.iterdir() if p.is_dir())
    if len(folders) != 12:
        raise SystemExit(f"staged pan parity expected 12 scene3d catalogs, found {len(folders)}")
    started = time.perf_counter()
    print(f"town-pan staged parity: towns={len(folders)} raysPerAspect={STAGED_PARITY_RAYS} "
          "source=uniform flattened index; production remains full-ray", flush=True)

    for folder in folders:
        town_started = time.perf_counter()
        cat_path = folder / "catalog.json"
        cat = json.loads(cat_path.read_text(encoding="utf-8"))
        pc = cat.get("panCoverage")
        if not isinstance(pc, dict) or not pc.get("file"):
            raise SystemExit(f"{folder.name}: missing staged panCoverage")
        evidence_path = folder / pc["file"]
        if not evidence_path.is_file():
            raise SystemExit(f"{folder.name}: missing staged pan evidence {evidence_path}")
        size, digest = contract.file_sha256_and_size(evidence_path)
        if digest != pc.get("sha256"):
            raise SystemExit(f"{folder.name}: staged pan evidence SHA-256 mismatch")
        with np.load(evidence_path, allow_pickle=False) as data:
            npz = {name: data[name] for name in data.files}

        rays = _sample_staged_rays(npz, sys.modules["conflux_town_camera_pan"])
        if set(rays) != set(ASPECTS):
            raise SystemExit(f"{folder.name}: staged ray aspects drifted: {sorted(rays)}")
        cpu_masks = {}
        for name, cohort in rays.items():
            cpu_masks[name] = contract.pan_voids_cpu(npz, cohort["O"], cohort["D"])
        cpu_negative = contract.pan_voids_cpu(npz, rays["16:9"]["O"], rays["16:9"]["D"], strip_outer=True)
        cpu_elapsed = time.perf_counter() - town_started

        with gpu_gate(f"phase-6 staged pan parity {folder.name}", need_vram_gb=1.0, wait_min=0.5):
            engine = town_gpu_pan.PanVoidEngine(npz)
            gpu_masks = {name: engine.voids(cohort["O"], cohort["D"])
                         for name, cohort in rays.items()}
            gpu_negative = engine.voids(rays["16:9"]["O"], rays["16:9"]["D"], strip_outer=True)
            buffer_mib = engine.estimated_peak_buffer_bytes / (1024 * 1024)
            del engine
        gpu_elapsed = time.perf_counter() - town_started - cpu_elapsed

        for name, cohort in rays.items():
            if not np.array_equal(gpu_masks[name], cpu_masks[name]):
                bad = np.flatnonzero(gpu_masks[name] != cpu_masks[name])
                first = int(bad[0])
                raise SystemExit(f"{folder.name} {name}: staged CPU/CUDA parity mismatch at sample {first}, "
                                 f"sourceIndex={int(cohort['indices'][first])}, "
                                 f"mode={cohort['mode'][first]}")
        if not np.array_equal(gpu_negative, cpu_negative):
            bad = int(np.flatnonzero(gpu_negative != cpu_negative)[0])
            cohort = rays["16:9"]
            raise SystemExit(f"{folder.name} 16:9 strip_outer: staged parity mismatch at sample {bad}, "
                             f"sourceIndex={int(cohort['indices'][bad])}, mode={cohort['mode'][bad]}")

        for name, cohort in rays.items():
            index_digest = hashlib.sha256(cohort["indices"].tobytes()).hexdigest()[:16]
            print(f"town-pan staged parity: {folder.name} {name} source={cohort['source_count']} "
                  f"selected={len(cohort['indices'])} indices=linspace(0,{cohort['source_count'] - 1},"
                  f"{len(cohort['indices'])},dtype=int64) sha256={index_digest} "
                  f"cpuVoid={int(cpu_masks[name].sum())} cudaVoid={int(gpu_masks[name].sum())}", flush=True)
        neg_digest = hashlib.sha256(rays["16:9"]["indices"].tobytes()).hexdigest()[:16]
        print(f"town-pan staged parity: {folder.name} 16:9-strip_outer selected={len(cpu_negative)} "
              f"indices=linspace(0,{rays['16:9']['source_count'] - 1},{len(cpu_negative)},dtype=int64) "
              f"sha256={neg_digest} cpuVoid={int(cpu_negative.sum())} cudaVoid={int(gpu_negative.sum())} "
              f"evidenceMiB={size / (1024 * 1024):.2f} cpuSeconds={cpu_elapsed:.3f} "
              f"gpuSeconds={gpu_elapsed:.3f} knownDeviceBuffersMiB={buffer_mib:.3f} "
              "(excludes driver/context/compiler allocations)", flush=True)
        del cpu_masks, gpu_masks, cpu_negative, gpu_negative, rays, npz

    print(f"town-pan staged parity: OK towns={len(folders)} seconds={time.perf_counter() - started:.3f}", flush=True)


if __name__ == "__main__":
    if "--cuda-parity" in sys.argv:
        sys.argv.remove("--cuda-parity")
        run_cuda_parity()
    elif "--cuda-parity-test" in sys.argv:
        index = sys.argv.index("--cuda-parity-test")
        try:
            test_name = sys.argv[index + 1]
        except IndexError as exc:
            raise SystemExit("--cuda-parity-test requires a test method name") from exc
        del sys.argv[index:index + 2]
        run_cuda_parity(test_name)
    elif "--staged-parity" in sys.argv:
        sys.argv.remove("--staged-parity")
        run_staged_parity()
    else:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(PanDeviceDispatchTests)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        raise SystemExit(not result.wasSuccessful())
