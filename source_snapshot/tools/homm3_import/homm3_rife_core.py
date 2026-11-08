"""Shared RIFE v4 battle-frame interpolation for HoMM3 lab sequences (Vulkan rife-ncnn)."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS = REPO_ROOT / "tools"
DEFAULT_RIFE_EXE = TOOLS / "vendor/rife-ncnn-vulkan-20221029-windows/rife-ncnn-vulkan.exe"
DEFAULT_WORK_ROOT = TOOLS / ".cache/vfi-work"
DEFAULT_RIFE_MODEL = "rife-v4"

RIFE_PLATE_RGBA = (32, 32, 32, 255)
NCNN_STRIDE = 32
RIFE_MODELS_WITH_NUMFRAME = frozenset({"rife-v4"})

SOURCE_FPS = 12
# Production battle RIFE uses HOMM3_TARGET_FPS=60 (run_homm3_rife_production.cmd). Scripts call configure_target_fps().
TARGET_FPS = 60
INTERP_MULT = TARGET_FPS // SOURCE_FPS


def v_env() -> dict[str, str]:
    cache = TOOLS / ".cache"
    env = os.environ.copy()
    env["PIP_CACHE_DIR"] = str(cache / "pip")
    env["TMPDIR"] = str(cache / "tmp")
    env["TEMP"] = env["TMPDIR"]
    env["TMP"] = env["TMPDIR"]
    env["LOCALAPPDATA"] = str(cache / "localappdata")
    env["PYTHONPYCACHEPREFIX"] = str(cache / "pycache")
    return env


def configure_target_fps(target_fps: int) -> tuple[int, int]:
    global TARGET_FPS, INTERP_MULT
    TARGET_FPS = max(SOURCE_FPS, int(target_fps))
    INTERP_MULT = max(1, TARGET_FPS // SOURCE_FPS)
    return TARGET_FPS, INTERP_MULT


def configure_fps(source_fps: int, target_fps: int) -> tuple[int, int, int]:
    """Set native preview FPS and RIFE output FPS (e.g. map 10→50, battle 12→60)."""
    global SOURCE_FPS, TARGET_FPS, INTERP_MULT
    SOURCE_FPS = max(1, int(source_fps))
    TARGET_FPS = max(SOURCE_FPS, int(target_fps))
    INTERP_MULT = max(1, TARGET_FPS // SOURCE_FPS)
    return SOURCE_FPS, TARGET_FPS, INTERP_MULT


def unpad_rgb(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    w, h = size
    return img.crop((0, 0, w, h))


def rgba_to_rife_rgb(
    img: Image.Image, plate_rgba: tuple[int, int, int, int] | None = None
) -> Image.Image:
    rgba = img.convert("RGBA")
    plate = Image.new("RGBA", rgba.size, plate_rgba or RIFE_PLATE_RGBA)
    return Image.alpha_composite(plate, rgba).convert("RGB")


def alpha_for_output_index(
    out_index: int, out_count: int, sources: list[Image.Image]
) -> Image.Image:
    n = len(sources)
    if n == 0:
        raise ValueError("no source frames")
    if n == 1 or out_count <= 1:
        return sources[0].split()[3]
    t = out_index / (out_count - 1)
    pos = t * (n - 1)
    i0 = int(pos)
    i1 = min(i0 + 1, n - 1)
    frac = pos - i0
    a0 = sources[i0].split()[3]
    if frac <= 0.0 or i0 == i1:
        return a0
    a1 = sources[i1].split()[3]
    return Image.blend(a0, a1, frac)


def rife_rgb_to_rgba(rgb: Image.Image, alpha: Image.Image) -> Image.Image:
    out = rgb.convert("RGB").convert("RGBA")
    out.putalpha(alpha.convert("L"))
    return out


def _output_keyframe_indices(out_index: int, out_count: int, source_count: int) -> tuple[int, int, float]:
    if source_count <= 1 or out_count <= 1:
        return 0, 0, 0.0
    t = out_index / (out_count - 1)
    pos = t * (source_count - 1)
    i0 = int(pos)
    i1 = min(i0 + 1, source_count - 1)
    return i0, i1, pos - i0


def rgba_for_output_index(
    out_index: int, out_count: int, sources: list[Image.Image]
) -> Image.Image:
    n = len(sources)
    if n == 0:
        raise ValueError("no source frames")
    if n == 1 or out_count <= 1:
        return sources[0].convert("RGBA")
    i0, i1, frac = _output_keyframe_indices(out_index, out_count, n)
    if frac <= 0.0 or i0 == i1:
        return sources[i0].convert("RGBA")
    return Image.blend(sources[i0].convert("RGBA"), sources[i1].convert("RGBA"), frac)


def premul_rgba_for_output_index(
    out_index: int, out_count: int, sources: list[Image.Image]
) -> Image.Image:
    """Premultiplied RGBA crossfade between native keyframes (full color + alpha)."""
    import numpy as np

    n = len(sources)
    if n == 0:
        raise ValueError("no source frames")
    if n == 1 or out_count <= 1:
        return sources[0].convert("RGBA")
    i0, i1, frac = _output_keyframe_indices(out_index, out_count, n)
    a = sources[i0].convert("RGBA")
    if frac <= 0.0 or i0 == i1:
        return a
    b = sources[i1].convert("RGBA")
    fa = frac
    arr_a = np.asarray(a, dtype=np.float32)
    arr_b = np.asarray(b, dtype=np.float32)
    alpha_a = arr_a[:, :, 3:4] / 255.0
    alpha_b = arr_b[:, :, 3:4] / 255.0
    premul_a = arr_a[:, :, :3] * alpha_a
    premul_b = arr_b[:, :, :3] * alpha_b
    out_a = alpha_a * (1.0 - fa) + alpha_b * fa
    out_rgb = premul_a * (1.0 - fa) + premul_b * fa
    safe = np.maximum(out_a, 1e-6)
    out_rgb = out_rgb / safe
    out = np.concatenate([out_rgb, out_a * 255.0], axis=2)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), mode="RGBA")


def matte_alpha_from_plate_rgb(
    rgb: Image.Image,
    plate_rgb: tuple[int, int, int],
    *,
    tol_lo: float = 5.0,
    tol_hi: float = 96.0,
) -> Image.Image:
    """Lower alpha where RIFE RGB is still close to the compositing plate."""
    import numpy as np

    arr = np.asarray(rgb.convert("RGB"), dtype=np.float32)
    plate = np.array(plate_rgb, dtype=np.float32)
    dist = np.linalg.norm(arr - plate, axis=2)
    span = max(tol_hi - tol_lo, 1e-6)
    matte = (np.clip((dist - tol_lo) / span, 0.0, 1.0) * 255.0).astype(np.uint8)
    return Image.fromarray(matte, mode="L")


def apply_plate_matte_to_key_alpha(
    key_alpha: Image.Image,
    matte_alpha: Image.Image,
    *,
    fringe_above: int = 210,
    fringe_band: int = 48,
) -> Image.Image:
    """Apply plate matting mainly on soft edges; solid key interior keeps full alpha."""
    import numpy as np

    ka = np.asarray(key_alpha.convert("L"), dtype=np.float32)
    ma = np.asarray(matte_alpha.convert("L"), dtype=np.float32) / 255.0
    band = max(float(fringe_band), 1.0)
    weight = np.clip((float(fringe_above) - ka) / band, 0.0, 1.0)
    combined = ka * ((1.0 - weight) + weight * ma)
    return Image.fromarray(np.clip(combined, 0, 255).astype(np.uint8), mode="L")


def multiply_alpha(a: Image.Image, b: Image.Image) -> Image.Image:
    from PIL import ImageChops

    return ImageChops.multiply(a.convert("L"), b.convert("L"))


def assemble_rife_frame(
    rife_rgb: Image.Image,
    sources: list[Image.Image],
    out_index: int,
    out_count: int,
    *,
    mode: str,
    plate_rgb: tuple[int, int, int],
    matte_tol_lo: float = 5.0,
    matte_tol_hi: float = 96.0,
    matte_fringe_above: int = 210,
    matte_fringe_band: int = 48,
    matte_legacy_multiply: bool = False,
) -> Image.Image:
    key_alpha = alpha_for_output_index(out_index, out_count, sources)
    if mode == "key_alpha":
        return rife_rgb_to_rgba(rife_rgb, key_alpha)
    if mode == "plate_matte":
        matte = matte_alpha_from_plate_rgb(
            rife_rgb, plate_rgb, tol_lo=matte_tol_lo, tol_hi=matte_tol_hi
        )
        if matte_legacy_multiply:
            final_alpha = multiply_alpha(key_alpha, matte)
        else:
            final_alpha = apply_plate_matte_to_key_alpha(
                key_alpha,
                matte,
                fringe_above=matte_fringe_above,
                fringe_band=matte_fringe_band,
            )
        return rife_rgb_to_rgba(rife_rgb, final_alpha)
    if mode == "premul_crossfade":
        cross = premul_rgba_for_output_index(out_index, out_count, sources)
        rife_layer = rife_rgb.convert("RGB").convert("RGBA")
        rife_layer.putalpha(key_alpha)
        return Image.alpha_composite(cross, rife_layer)
    raise ValueError(f"unknown assemble mode: {mode}")


def load_rife_output_sequence_assembled(
    folder: Path,
    content_size: tuple[int, int],
    sources: list[Image.Image],
    *,
    target_count: int | None = None,
    mode: str,
    plate_rgb: tuple[int, int, int],
    matte_tol_lo: float = 5.0,
    matte_tol_hi: float = 96.0,
    matte_fringe_above: int = 210,
    matte_fringe_band: int = 48,
    matte_legacy_multiply: bool = False,
) -> list[Image.Image]:
    paths = sorted(folder.glob("*.png"))
    if not paths:
        return []
    if target_count is not None and len(paths) != target_count:
        indices = [
            round(i * (len(paths) - 1) / max(target_count - 1, 1)) for i in range(target_count)
        ]
        paths = [paths[i] for i in indices]
    out: list[Image.Image] = []
    for i, path in enumerate(paths):
        rgb = unpad_rgb(Image.open(path).convert("RGB"), content_size)
        out.append(
            assemble_rife_frame(
                rgb,
                sources,
                i,
                len(paths),
                mode=mode,
                plate_rgb=plate_rgb,
                matte_tol_lo=matte_tol_lo,
                matte_tol_hi=matte_tol_hi,
                matte_fringe_above=matte_fringe_above,
                matte_fringe_band=matte_fringe_band,
                matte_legacy_multiply=matte_legacy_multiply,
            )
        )
    return out


def normalize_frames(frames: list[Image.Image]) -> list[Image.Image]:
    if not frames:
        return []
    size = (max(f.width for f in frames), max(f.height for f in frames))
    out: list[Image.Image] = []
    for f in frames:
        canvas = Image.new("RGBA", size, (0, 0, 0, 0))
        canvas.paste(f, ((size[0] - f.width) // 2, (size[1] - f.height) // 2), f)
        out.append(canvas)
    return out


def pad_to_stride(
    img: Image.Image,
    stride: int = NCNN_STRIDE,
    *,
    plate_rgb: tuple[int, int, int] | None = None,
) -> tuple[Image.Image, tuple[int, int]]:
    w, h = img.size
    pw = (stride - (w % stride)) % stride
    ph = (stride - (h % stride)) % stride
    if pw == 0 and ph == 0:
        return img, (w, h)
    fill = plate_rgb or RIFE_PLATE_RGBA[:3]
    plate = img if img.mode == "RGB" else rgba_to_rife_rgb(img, (*fill, 255))
    padded = Image.new("RGB", (w + pw, h + ph), fill)
    padded.paste(plate, (0, 0))
    return padded, (w, h)


def export_rife_input_sequence(
    frames: list[Image.Image],
    dest: Path,
    *,
    plate_rgba: tuple[int, int, int, int] | None = None,
) -> tuple[int, int]:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    content_size = frames[0].size
    plate_rgb = (plate_rgba or RIFE_PLATE_RGBA)[:3]
    for i, frame in enumerate(frames):
        rgb = rgba_to_rife_rgb(frame, plate_rgba)
        padded, content_size = pad_to_stride(rgb, plate_rgb=plate_rgb)
        padded.save(dest / f"{i:08d}.png")
    return content_size


def export_alpha_mask_rgb_sequence(frames: list[Image.Image], dest: Path) -> tuple[int, int]:
    """Export keyframe alpha as grayscale RGB on black for a separate RIFE pass."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    content_size = frames[0].size
    black = (0, 0, 0)
    for i, frame in enumerate(frames):
        alpha = frame.convert("RGBA").split()[3]
        rgb = Image.merge("RGB", (alpha, alpha, alpha))
        padded, content_size = pad_to_stride(rgb, plate_rgb=black)
        padded.save(dest / f"{i:08d}.png")
    return content_size


def _resample_png_paths(paths: list[Path], target_count: int) -> list[Path]:
    if not paths:
        return []
    if len(paths) == target_count:
        return paths
    indices = [
        round(i * (len(paths) - 1) / max(target_count - 1, 1)) for i in range(target_count)
    ]
    return [paths[i] for i in indices]


def load_rife_dual_stream_sequence(
    rgb_folder: Path,
    alpha_folder: Path,
    content_size: tuple[int, int],
    *,
    target_count: int | None = None,
) -> list[Image.Image]:
    """Merge RIFE RGB output with a separate RIFE pass on the alpha mask (RIFE-with-Transparency style)."""
    rgb_paths = sorted(rgb_folder.glob("*.png"))
    alpha_paths = sorted(alpha_folder.glob("*.png"))
    if not rgb_paths or not alpha_paths:
        return []
    if target_count is not None:
        rgb_paths = _resample_png_paths(rgb_paths, target_count)
        alpha_paths = _resample_png_paths(alpha_paths, target_count)
    count = min(len(rgb_paths), len(alpha_paths))
    out: list[Image.Image] = []
    for i in range(count):
        rgb = unpad_rgb(Image.open(rgb_paths[i]).convert("RGB"), content_size)
        alpha_rgb = unpad_rgb(Image.open(alpha_paths[i]).convert("RGB"), content_size)
        alpha = alpha_rgb.split()[0]
        out.append(rife_rgb_to_rgba(rgb, alpha))
    return out


def load_rife_output_sequence(
    folder: Path,
    content_size: tuple[int, int],
    sources: list[Image.Image],
    *,
    target_count: int | None = None,
) -> list[Image.Image]:
    paths = sorted(folder.glob("*.png"))
    if not paths:
        return []
    if target_count is not None and len(paths) != target_count:
        indices = [
            round(i * (len(paths) - 1) / max(target_count - 1, 1)) for i in range(target_count)
        ]
        paths = [paths[i] for i in indices]
    out: list[Image.Image] = []
    for i, path in enumerate(paths):
        rgb = unpad_rgb(Image.open(path).convert("RGB"), content_size)
        alpha = alpha_for_output_index(i, len(paths), sources)
        out.append(rife_rgb_to_rgba(rgb, alpha))
    return out


def target_frame_count(source_frames: int) -> int:
    return max(2, source_frames * INTERP_MULT)


def run_rife_pass(
    input_dir: Path,
    output_dir: Path,
    model_name: str,
    *,
    rife_exe: Path,
    num_frames: int | None = None,
) -> None:
    if not rife_exe.is_file():
        raise FileNotFoundError(f"Missing {rife_exe}. Run: bash tools/homm3_import/setup_vfi_env.sh")
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    cmd = [
        str(rife_exe),
        "-i",
        str(input_dir),
        "-o",
        str(output_dir),
        "-m",
        model_name,
        "-g",
        "0",
        "-f",
        "%08d.png",
    ]
    if num_frames is not None:
        if model_name not in RIFE_MODELS_WITH_NUMFRAME:
            raise ValueError(f"model {model_name} does not support -n in this Vulkan build")
        cmd.extend(["-n", str(num_frames)])
    attempts = max(1, int(os.environ.get("HOMM3_RIFE_PASS_ATTEMPTS", "3") or "3"))
    last_error: subprocess.CalledProcessError | None = None
    for attempt in range(1, attempts + 1):
        try:
            subprocess.run(cmd, check=True, cwd=rife_exe.parent, env=v_env())
            return
        except subprocess.CalledProcessError as ex:
            last_error = ex
            if attempt >= attempts:
                break
            if output_dir.exists():
                shutil.rmtree(output_dir)
            output_dir.mkdir(parents=True)
            time.sleep(2 * attempt)
            print(
                f"    retry RIFE pass {attempt + 1}/{attempts} after exit {ex.returncode}",
                flush=True,
            )
    if last_error is not None:
        raise last_error


def run_rife_v4_to_target_count(
    input_dir: Path,
    output_dir: Path,
    source_frame_count: int,
    *,
    rife_exe: Path,
    model_name: str = DEFAULT_RIFE_MODEL,
    work_root: Path | None = None,
) -> list[Image.Image]:
    """Run RIFE v4 with -n and return RGBA frames (caller supplies sources for alpha restore)."""
    target = target_frame_count(source_frame_count)
    if model_name in RIFE_MODELS_WITH_NUMFRAME:
        run_rife_pass(input_dir, output_dir, model_name, rife_exe=rife_exe, num_frames=target)
        return []

    chain_root = (work_root or output_dir.parent) / f"{output_dir.name}_chain"
    if chain_root.exists():
        shutil.rmtree(chain_root)
    chain_root.mkdir(parents=True)
    current_in = input_dir
    pass_idx = 0
    while True:
        count = len(list(current_in.glob("*.png")))
        if count >= target:
            break
        step_out = chain_root / f"pass_{pass_idx:02d}"
        run_rife_pass(current_in, step_out, model_name, rife_exe=rife_exe)
        current_in = step_out
        pass_idx += 1
        if pass_idx > 10:
            raise RuntimeError(
                f"RIFE chain for {model_name} did not reach {target} frames (stuck at {count})"
            )

    paths = sorted(current_in.glob("*.png"))
    if len(paths) != target:
        pick = [round(i * (len(paths) - 1) / max(target - 1, 1)) for i in range(target)]
        paths = [paths[i] for i in pick]
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    for i, src in enumerate(paths):
        shutil.copy2(src, output_dir / f"{i:08d}.png")
    shutil.rmtree(chain_root, ignore_errors=True)
    return []


def interpolate_rgba_sequence(
    frames: list[Image.Image],
    *,
    rife_exe: Path,
    work_dir: Path,
    model_name: str = DEFAULT_RIFE_MODEL,
    reuse_cache: bool = False,
    dual_stream_alpha: bool = False,
) -> list[Image.Image]:
    """Normalize, run RIFE @ configured TARGET_FPS, return dense RGBA frames."""
    if dual_stream_alpha:
        return interpolate_rgba_sequence_dual_stream(
            frames,
            rife_exe=rife_exe,
            work_dir=work_dir,
            model_name=model_name,
            reuse_cache=reuse_cache,
        )

    normalized = normalize_frames(frames)
    if len(normalized) < 2:
        if len(normalized) == 1:
            return normalized * INTERP_MULT
        return []

    target_n = target_frame_count(len(normalized))
    work_in = work_dir / "in_rgb"
    work_out = work_dir / model_name
    content_size = normalized[0].size

    if reuse_cache and work_out.is_dir() and len(list(work_out.glob("*.png"))) >= 2:
        return load_rife_output_sequence(
            work_out, content_size, normalized, target_count=target_n
        )

    export_rife_input_sequence(normalized, work_in)
    run_rife_v4_to_target_count(
        work_in,
        work_out,
        len(normalized),
        rife_exe=rife_exe,
        model_name=model_name,
        work_root=work_dir,
    )
    return load_rife_output_sequence(
        work_out, content_size, normalized, target_count=target_n
    )


def interpolate_rgba_sequence_dual_stream(
    frames: list[Image.Image],
    *,
    rife_exe: Path,
    work_dir: Path,
    model_name: str = "rife-v4.6",
    reuse_cache: bool = False,
) -> list[Image.Image]:
    """Gray-plate RGB RIFE + separate alpha-mask RIFE (RIFE-with-Transparency style)."""
    normalized = normalize_frames(frames)
    if len(normalized) < 2:
        if len(normalized) == 1:
            return normalized * INTERP_MULT
        return []

    target_n = target_frame_count(len(normalized))
    content_size = normalized[0].size
    work_in_rgb = work_dir / "in_rgb"
    work_out_rgb = work_dir / model_name
    work_in_alpha = work_dir / "in_alpha_mask"
    work_out_alpha = work_dir / f"{model_name}_alpha_mask"

    rgb_ready = work_out_rgb.is_dir() and len(list(work_out_rgb.glob("*.png"))) >= 2
    alpha_ready = work_out_alpha.is_dir() and len(list(work_out_alpha.glob("*.png"))) >= 2
    if reuse_cache and rgb_ready and alpha_ready:
        return load_rife_dual_stream_sequence(
            work_out_rgb,
            work_out_alpha,
            content_size,
            target_count=target_n,
        )

    export_rife_input_sequence(normalized, work_in_rgb)
    export_alpha_mask_rgb_sequence(normalized, work_in_alpha)
    run_rife_v4_to_target_count(
        work_in_rgb,
        work_out_rgb,
        len(normalized),
        rife_exe=rife_exe,
        model_name=model_name,
        work_root=work_dir,
    )
    run_rife_v4_to_target_count(
        work_in_alpha,
        work_out_alpha,
        len(normalized),
        rife_exe=rife_exe,
        model_name=model_name,
        work_root=work_dir,
    )
    return load_rife_dual_stream_sequence(
        work_out_rgb,
        work_out_alpha,
        content_size,
        target_count=target_n,
    )
