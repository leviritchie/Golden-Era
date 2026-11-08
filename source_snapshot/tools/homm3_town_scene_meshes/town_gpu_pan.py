"""Fused CUDA implementation of the phase-6 sampled pan-coverage ray test.

The NumPy implementation in validate_town_scene3d_contract.py remains the
reference. This kernel preserves its per-ray march and classifications; one
CUDA thread runs one complete ray so the 4000-step bound does not become a
Python-driven launch/synchronization loop.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

MAX_STEPS = 4000
PAN_BATCH = 8192
PAN_EL_MIN = -1.0

_CUDA = None
_MARCH_KERNEL = None


def _real_array(value: Any, name: str, shape: tuple[int, ...] | None = None, *, finite: bool = True) -> np.ndarray:
    array = np.asarray(value)
    if shape is not None and array.shape != shape:
        raise ValueError(f"pan GPU {name} must have shape {shape}, got {array.shape}")
    if not (np.issubdtype(array.dtype, np.integer) or np.issubdtype(array.dtype, np.floating)):
        raise ValueError(f"pan GPU {name} must contain real numeric values")
    if finite and not np.isfinite(array).all():
        raise ValueError(f"pan GPU {name} must contain only finite values")
    return array


def _real_scalar(npz: dict[str, Any], name: str) -> float:
    value = _real_array(npz[name], name)
    if value.shape != ():
        raise ValueError(f"pan GPU {name} must be a finite real scalar, got shape {value.shape}")
    return float(value)


def validate_pan_evidence(npz: dict[str, Any]) -> None:
    """Validate pan metadata without initializing CUDA or scanning heightfield contents."""
    required = ("h", "outer_h", "covered", "x0", "z0", "res", "cam_pos", "cam_fwd", "cam_up", "cam_right",
                "frame_wh", "frame_sky", "fov", "C", "cpos", "depth_scale", "dome_r", "sky_az", "sky_el")
    missing = [key for key in required if key not in npz]
    if missing:
        raise ValueError(f"pan GPU evidence lacks {missing}")

    heights = _real_array(npz["h"], "h", finite=False)
    outer = _real_array(npz["outer_h"], "outer_h", finite=False)
    covered = np.asarray(npz["covered"])
    if heights.ndim != 2 or heights.size == 0 or outer.shape != heights.shape:
        raise ValueError("pan GPU heightfields must be non-empty, same-shape 2D real arrays")
    if covered.dtype != np.bool_ or covered.shape != heights.shape:
        raise ValueError("pan GPU covered map must be same-shape boolean data")
    sky = np.asarray(npz["frame_sky"])
    if sky.dtype != np.bool_ or sky.ndim != 2:
        raise ValueError("pan GPU frame_sky must be a 2D boolean array")

    frame_wh = np.asarray(npz["frame_wh"])
    if frame_wh.shape != (2,) or not np.issubdtype(frame_wh.dtype, np.integer) or np.any(frame_wh <= 0):
        raise ValueError("pan GPU frame_wh must be a positive integer [W, H] vector")
    frame_w, frame_h = (int(v) for v in frame_wh)
    if sky.shape != (frame_h, frame_w):
        raise ValueError(f"pan GPU frame_sky shape {sky.shape} does not match frame_wh {(frame_w, frame_h)}")

    for name in ("x0", "z0"):
        _real_scalar(npz, name)
    res = _real_scalar(npz, "res")
    fov = _real_scalar(npz, "fov")
    dome_r = _real_scalar(npz, "dome_r")
    depth_scale = _real_scalar(npz, "depth_scale")
    if res <= 0.0:
        raise ValueError("pan GPU res must be greater than zero")
    if not 0.0 < fov < 180.0:
        raise ValueError("pan GPU fov must be between 0 and 180 degrees")
    if dome_r <= 0.0:
        raise ValueError("pan GPU dome_r must be greater than zero")
    if depth_scale <= 0.0:
        raise ValueError("pan GPU depth_scale must be greater than zero")

    for name in ("cam_pos", "cam_fwd", "cam_up", "cam_right", "cpos"):
        _real_array(npz[name], name, (3,))
    _real_array(npz["C"], "C", (3, 3))
    for name in ("sky_az", "sky_el"):
        angles = _real_array(npz[name], name, (2,))
        if angles[0] > angles[1]:
            raise ValueError(f"pan GPU {name} bounds must be ordered")


def validate_pan_rays(origins: Any, directions: Any) -> tuple[np.ndarray, np.ndarray]:
    origin_array = _real_array(origins, "ray origins")
    direction_array = _real_array(directions, "ray directions")
    if origin_array.ndim != 2 or origin_array.shape[1:] != (3,) or direction_array.shape != origin_array.shape:
        raise ValueError(f"pan GPU rays must be matching (n, 3) arrays, got {origin_array.shape} and "
                         f"{direction_array.shape}")
    return origin_array, direction_array


def ensure_cuda_available():
    """Require the installed Numba CUDA backend and a usable CUDA device."""
    global _CUDA
    if _CUDA is None:
        try:
            from numba import cuda
        except Exception as exc:  # pragma: no cover - depends on the host runtime
            raise RuntimeError(f"town_gpu_pan requires Numba CUDA; use --device cpu explicitly ({exc})") from exc
        try:
            available = cuda.is_available()
        except Exception as exc:  # pragma: no cover - depends on the host runtime
            raise RuntimeError(f"town_gpu_pan could not initialize CUDA; use --device cpu explicitly ({exc})") from exc
        if not available:
            raise RuntimeError("town_gpu_pan requested CUDA but no usable CUDA device is available; "
                               "use --device cpu explicitly")
        _CUDA = cuda
    return _CUDA


def _kernel():
    global _MARCH_KERNEL
    if _MARCH_KERNEL is not None:
        return _MARCH_KERNEL

    cuda = ensure_cuda_available()
    from numba import int64

    @cuda.jit(device=True, inline=True)
    def round_even(value):
        lower = int(math.floor(value))
        fraction = value - lower
        if fraction < 0.5:
            return lower
        if fraction > 0.5:
            return lower + 1
        if lower & 1:
            return lower + 1
        return lower

    @cuda.jit
    def march_kernel(origins, directions, heights, outer_heights, covered, frame_sky,
                     cam_pos, cam_fwd, cam_up, cam_right,
                     x0, z0, res, tan_half_fov, dome_r, sky_az0, sky_az1, sky_el0, sky_el1,
                     frame_w, frame_height, n, nz, nx, strip_outer, out_ok):
        ray = cuda.grid(1)
        if ray >= n:
            return

        t = 0.3
        hit = False
        escaped = False
        for _ in range(MAX_STEPS):
            px_world = origins[ray, 0] + directions[ray, 0] * t
            py_world = origins[ray, 1] + directions[ray, 1] * t
            pz_world = origins[ray, 2] + directions[ray, 2] * t
            gx_f = round_even((px_world - x0) / res)
            gz_f = round_even((pz_world - z0) / res)
            if gx_f < 0 or gx_f >= nx or gz_f < 0 or gz_f >= nz:
                escaped = True
                break

            gx, gz = int(gx_f), int(gz_f)
            outer_h = float(outer_heights[gz, gx])
            frame_surface_h = float(heights[gz, gx])
            outer_hit = (not strip_outer) and covered[gz, gx] and py_world <= outer_h
            frame_hit = py_world <= frame_surface_h

            if frame_hit and not outer_hit:
                dx = px_world - cam_pos[0]
                dy = py_world - cam_pos[1]
                dz = pz_world - cam_pos[2]
                zc = (dx * cam_fwd[0] + dy * cam_fwd[1]) + dz * cam_fwd[2]
                rx = (dx * cam_right[0] + dy * cam_right[1]) + dz * cam_right[2]
                uy = (dx * cam_up[0] + dy * cam_up[1]) + dz * cam_up[2]
                zden = zc if zc > 1e-6 else 1e-6
                px = ((rx / (zden * tan_half_fov * frame_w / frame_height) + 1.0) * 0.5) * frame_w
                py = (1.0 - uy / (zden * tan_half_fov)) * 0.5 * frame_height
                if zc > 0.05 and px >= -1e-4 and px <= frame_w + 1e-4 \
                        and py >= -1e-4 and py <= frame_height + 1e-4:
                    ix = int64(px)
                    iy = int64(py)
                    if ix < 0:
                        ix = 0
                    elif ix >= frame_w:
                        ix = int64(frame_w) - 1
                    if iy < 0:
                        iy = 0
                    elif iy >= frame_height:
                        iy = int64(frame_height) - 1
                    frame_hit = not frame_sky[iy, ix]
                else:
                    frame_hit = False

            if outer_hit or frame_hit:
                hit = True
                break

            step = 0.25 + 0.01 * t
            if (not strip_outer) and covered[gz, gx] and py_world > outer_h and py_world - outer_h < 0.5:
                lip_step = 0.05 + 0.002 * t
                if lip_step < step:
                    step = lip_step
            t += step
        else:
            escaped = True

        if hit:
            out_ok[ray] = True
            return

        # NumPy's escape/dome rule intentionally uses the unit-ray quadratic without an a term and does not reject a
        # negative root. Keep this entire tail on CUDA, including its transcendental sky classification.
        if escaped:
            fx = cam_fwd[0]
            fz = cam_fwd[2]
            fn = math.sqrt(fx * fx + fz * fz)
            if fn == 0.0:
                fx, fz = math.nan, math.nan
            else:
                fx, fz = fx / fn, fz / fn
            rx, rz = fz, -fx
            ox = origins[ray, 0] - cam_pos[0]
            oy = origins[ray, 1] - cam_pos[1]
            oz = origins[ray, 2] - cam_pos[2]
            b = (ox * directions[ray, 0] + oy * directions[ray, 1]) + oz * directions[ray, 2]
            c = ((ox * ox + oy * oy) + oz * oz) - dome_r * dome_r
            discriminant = b * b - c
            if discriminant < 0.0:
                discriminant = 0.0
            distance = -b + math.sqrt(discriminant)
            qx = ox + directions[ray, 0] * distance
            qy = oy + directions[ray, 1] * distance
            qz = oz + directions[ray, 2] * distance
            qn = math.sqrt((qx * qx + qy * qy) + qz * qz)
            qx, qy, qz = qx / qn, qy / qn, qz / qn
            az = math.atan2(qx * rx + qz * rz, qx * fx + qz * fz) * (180.0 / math.pi)
            if qy < -1.0:
                qy = -1.0
            elif qy > 1.0:
                qy = 1.0
            el = math.asin(qy) * (180.0 / math.pi)
            out_ok[ray] = az >= sky_az0 and az <= sky_az1 and el >= sky_el0 and el <= sky_el1
        else:
            out_ok[ray] = False

    _MARCH_KERNEL = march_kernel
    return _MARCH_KERNEL


class PanVoidEngine:
    """Per-catalog CUDA state. Heightfields and frame sky are uploaded once, then ray batches are reused."""

    def __init__(self, npz: dict[str, Any]):
        validate_pan_evidence(npz)
        self.heights_host = np.ascontiguousarray(npz["h"])
        self.outer_host = np.ascontiguousarray(npz["outer_h"])
        self.covered_host = np.ascontiguousarray(npz["covered"])
        self.sky_host = np.ascontiguousarray(npz["frame_sky"])
        frame_wh = np.asarray(npz["frame_wh"])
        self.frame_w, self.frame_h = (int(v) for v in frame_wh)

        self.nz, self.nx = self.heights_host.shape
        self.x0, self.z0, self.res = float(npz["x0"]), float(npz["z0"]), float(npz["res"])
        camera = {}
        for key in ("cam_pos", "cam_fwd", "cam_up", "cam_right"):
            vector = np.asarray(npz[key])
            camera[key] = np.ascontiguousarray(vector, dtype=np.float64)
        self.cam_pos = camera["cam_pos"]
        self.cam_fwd = camera["cam_fwd"]
        self.cam_up = camera["cam_up"]
        self.cam_right = camera["cam_right"]
        self.tan_half_fov = math.tan(math.radians(float(npz["fov"])) / 2)
        self.dome_r = float(npz["dome_r"])
        self.sky_az0, self.sky_az1 = (float(v) for v in npz["sky_az"])
        self.sky_el0 = max(float(npz["sky_el"][0]), PAN_EL_MIN)
        self.sky_el1 = float(npz["sky_el"][1])

        self.cuda = ensure_cuda_available()
        self.kernel = _kernel()
        self.d_heights = self.cuda.to_device(self.heights_host)
        self.d_outer = self.cuda.to_device(self.outer_host)
        self.d_covered = self.cuda.to_device(self.covered_host)
        self.d_sky = self.cuda.to_device(self.sky_host)
        self.d_cam_pos = self.cuda.to_device(self.cam_pos)
        self.d_cam_fwd = self.cuda.to_device(self.cam_fwd)
        self.d_cam_up = self.cuda.to_device(self.cam_up)
        self.d_cam_right = self.cuda.to_device(self.cam_right)
        self.static_upload_bytes = sum(a.nbytes for a in (
            self.heights_host, self.outer_host, self.covered_host, self.sky_host, self.cam_pos, self.cam_fwd,
            self.cam_up, self.cam_right))
        self.last_batch_buffer_bytes = 0

    def voids(self, origins, directions, strip_outer: bool = False) -> np.ndarray:
        origins, directions = validate_pan_rays(origins, directions)
        O = np.ascontiguousarray(origins, dtype=np.float64)
        D = np.ascontiguousarray(directions, dtype=np.float64)
        n = len(O)
        if n > PAN_BATCH:
            raise ValueError(f"pan GPU batch {n} exceeds bounded PAN_BATCH={PAN_BATCH}")
        if n == 0:
            return np.zeros(0, dtype=np.bool_)

        d_O = self.cuda.to_device(O)
        d_D = self.cuda.to_device(D)
        d_ok = self.cuda.device_array(n, dtype=np.bool_)
        self.last_batch_buffer_bytes = O.nbytes + D.nbytes + n
        threads = 128
        blocks = (n + threads - 1) // threads
        self.kernel[blocks, threads](
            d_O, d_D, self.d_heights, self.d_outer, self.d_covered, self.d_sky,
            self.d_cam_pos, self.d_cam_fwd, self.d_cam_up, self.d_cam_right,
            self.x0, self.z0, self.res, self.tan_half_fov, self.dome_r,
            self.sky_az0, self.sky_az1, self.sky_el0, self.sky_el1,
            self.frame_w, self.frame_h, n, self.nz, self.nx, bool(strip_outer), d_ok)
        return ~d_ok.copy_to_host()

    @property
    def estimated_peak_buffer_bytes(self) -> int:
        """Known static and active-ray buffers; excludes driver/context/compiler allocations."""
        return self.static_upload_bytes + self.last_batch_buffer_bytes
