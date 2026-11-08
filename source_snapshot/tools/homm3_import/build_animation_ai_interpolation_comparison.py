#!/usr/bin/env python3
"""AI frame interpolation comparisons for HoMM3 prerendered battle sprites (RIFE via Vulkan).

Outputs WebM (VP9 + alpha) for accurate high-FPS preview. All tooling on V:, not C:.

RIFE-ncnn-vulkan expects opaque RGB input. Feeding RGBA corrupts output; we composite on a
gray plate, run RIFE, restore alpha, then encode PNG sequences to WebM with imageio-ffmpeg.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

from homm3_rife_core import (
    configure_target_fps as rife_configure_target_fps,
    interpolate_rgba_sequence_dual_stream,
    target_frame_count as rife_target_frame_count,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_RIFE_MODEL = "rife-v4.6"
TOOLS = REPO_ROOT / "tools"
LAB_ROOT = REPO_ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_lab"
RIFE_EXE = TOOLS / "vendor/rife-ncnn-vulkan-20221029-windows/rife-ncnn-vulkan.exe"
WORK_ROOT = TOOLS / ".cache/vfi-work"
WEBM_STAGE_ROOT = TOOLS / ".cache/vfi-webm-frames"
DEFAULT_OUT = REPO_ROOT / "experiments/homm3_animation_ai_interpolation_comparison"

RIFE_PLATE_RGBA = (32, 32, 32, 255)
NCNN_STRIDE = 32

GROUP_IDLE = 2
GROUP_MOVEMENT = 0
GROUP_HITTED = 3
GROUP_DEATH = 5
GROUP_ATTACK_FRONT = 12

UNITS = (
    ("h3_gnoll", "Fortress Gnoll"),
    ("h3_lizardman", "Fortress Lizardman"),
    ("h3_skeleton", "Necropolis Skeleton"),
)

# Legacy comparison units (re-enable with --units h3_angel h3_hydra h3_vampire).
LEGACY_UNITS = (
    ("h3_angel", "Castle Angel"),
    ("h3_hydra", "Fortress Hydra"),
    ("h3_vampire", "Necropolis Vampire"),
)

LAB_RIFE_METHOD = (
    "04_lab_rife120_120fps",
    None,
    "Production RIFE v4 @ 120 FPS from current homm3_lab PNGs (matches in-game bundle)",
)

CLIPS = (
    ("idle", GROUP_IDLE, True),
    ("walk", GROUP_MOVEMENT, True),
    ("attack", GROUP_ATTACK_FRONT, True),
    ("damage", GROUP_HITTED, True),
    ("death", GROUP_DEATH, True),
)

SOURCE_FPS = 12
TARGET_FPS = 120
INTERP_MULT = TARGET_FPS // SOURCE_FPS
SOURCE_FRAME_MS = int(1000 / SOURCE_FPS)

RIFE_MODELS_WITH_NUMFRAME = frozenset({"rife-v4"})


def ai_methods_for_target_fps(target_fps: int) -> tuple[tuple[str, str, str], ...]:
    fps = int(target_fps)
    return (
        (
            f"02_rife_v46_{fps}fps",
            "rife-v4.6",
            f"RIFE v4.6 — chained 2× passes to ~{fps} FPS",
        ),
        (
            f"03_rife_anime_{fps}fps",
            "rife-anime",
            f"RIFE anime — chained 2× passes to ~{fps} FPS (stylized)",
        ),
        (
            f"04_rife_v4_{fps}fps",
            "rife-v4",
            f"RIFE v4.0 — direct -n target frame count @ {fps} FPS",
        ),
    )


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


def resolve_ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as ex:
        raise FileNotFoundError(
            "ffmpeg not on PATH and imageio-ffmpeg is not installed. "
            "Run: tools/.venv-homm3-vfi/Scripts/python.exe -m pip install imageio-ffmpeg"
        ) from ex


def load_manifest(unit_sid: str) -> tuple[Path, dict]:
    battle_dir = LAB_ROOT / unit_sid / "extracted_battle"
    json_files = sorted(
        p
        for p in battle_dir.glob("*.json")
        if not p.name.startswith(".") and p.name.lower() != "manifest.json"
    )
    if not json_files:
        raise FileNotFoundError(battle_dir)
    path = json_files[0]
    return path, json.loads(path.read_text(encoding="utf-8-sig"))


def load_rife120_meta(battle_dir: Path) -> dict | None:
    path = battle_dir / ".rife120_done.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return None


def native_subset_from_dense(
    dense_frames: list[Image.Image], group_id: int, rife_meta: dict | None
) -> tuple[list[Image.Image], str]:
    """When lab PNGs were replaced by RIFE, recover sparse DEF keyframes for native baselines."""
    if not dense_frames or not rife_meta:
        return dense_frames, "source DEF frames"
    group_meta = (rife_meta.get("groups") or {}).get(str(group_id))
    if not group_meta or not group_meta.get("interpolated"):
        return dense_frames, "source DEF frames"
    source_count = int(group_meta.get("sourceCount") or 0)
    output_count = int(group_meta.get("outputCount") or len(dense_frames))
    if source_count <= 0 or len(dense_frames) != output_count or source_count >= len(dense_frames):
        return dense_frames, "source DEF frames"
    if source_count == 1:
        return [dense_frames[0]], f"{source_count} native DEF keyframe (from RIFE output)"
    step = (len(dense_frames) - 1) / (source_count - 1)
    indices = [round(i * step) for i in range(source_count)]
    native = [dense_frames[i] for i in indices]
    return native, f"{source_count} native DEF keyframes @ 12 FPS (recovered from .rife120_done.json)"


def group_frame_paths(manifest: dict, group_id: int) -> list[str]:
    for sequence in manifest.get("sequences") or []:
        if int(sequence.get("group", -1)) != group_id:
            continue
        return [str(f).strip() for f in (sequence.get("frames") or []) if str(f or "").strip()]
    return []


def load_group_frames(battle_dir: Path, rel_paths: list[str]) -> list[Image.Image]:
    frames: list[Image.Image] = []
    for rel in rel_paths:
        path = battle_dir / rel.replace("\\", "/")
        frames.append(Image.open(path).convert("RGBA"))
    return frames


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


def pad_to_stride(img: Image.Image, stride: int = NCNN_STRIDE) -> tuple[Image.Image, tuple[int, int]]:
    w, h = img.size
    pw = (stride - (w % stride)) % stride
    ph = (stride - (h % stride)) % stride
    if pw == 0 and ph == 0:
        return img, (w, h)
    plate = img if img.mode == "RGB" else rgba_to_rife_rgb(img)
    padded = Image.new("RGB", (w + pw, h + ph), RIFE_PLATE_RGBA[:3])
    padded.paste(plate, (0, 0))
    return padded, (w, h)


def unpad_rgb(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    w, h = size
    return img.crop((0, 0, w, h))


def rgba_to_rife_rgb(img: Image.Image) -> Image.Image:
    rgba = img.convert("RGBA")
    plate = Image.new("RGBA", rgba.size, RIFE_PLATE_RGBA)
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


def baseline_hold_frames(frames: list[Image.Image]) -> list[Image.Image]:
    held: list[Image.Image] = []
    for frame in frames:
        held.extend([frame] * INTERP_MULT)
    return held


def idle_tail_lead_native_attack(
    idle_dense: list[Image.Image],
    attack_dense: list[Image.Image],
    rife_meta: dict | None,
) -> list[Image.Image] | None:
    """Prepend the last recovered native idle key as the first attack key (RIFE experiment)."""
    idle_native, _ = native_subset_from_dense(idle_dense, GROUP_IDLE, rife_meta)
    attack_native, _ = native_subset_from_dense(attack_dense, GROUP_ATTACK_FRONT, rife_meta)
    if not idle_native or not attack_native:
        return None
    return [idle_native[-1].copy(), *attack_native]


def even_rgba(frame: Image.Image) -> Image.Image:
    rgba = frame.convert("RGBA")
    w, h = rgba.size
    ew, eh = w + (w % 2), h + (h % 2)
    if (ew, eh) == (w, h):
        return rgba
    canvas = Image.new("RGBA", (ew, eh), (0, 0, 0, 0))
    canvas.paste(rgba, (0, 0), rgba)
    return canvas


def write_webm(path: Path, frames: list[Image.Image], fps: float) -> None:
    if not frames:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = WEBM_STAGE_ROOT / path.stem
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    for i, frame in enumerate(frames):
        even_rgba(frame).save(staging / f"{i:08d}.png")

    ffmpeg = resolve_ffmpeg()
    cmd = [
        ffmpeg,
        "-y",
        "-framerate",
        f"{fps:.6f}",
        "-i",
        str(staging / "%08d.png"),
        "-c:v",
        "libvpx-vp9",
        "-pix_fmt",
        "yuva420p",
        "-auto-alt-ref",
        "0",
        "-crf",
        "28",
        "-b:v",
        "0",
        "-an",
        str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, env=v_env())
    shutil.rmtree(staging, ignore_errors=True)


def export_rife_input_sequence(frames: list[Image.Image], dest: Path) -> tuple[int, int]:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    content_size = frames[0].size
    for i, frame in enumerate(frames):
        rgb = rgba_to_rife_rgb(frame)
        padded, content_size = pad_to_stride(rgb)
        padded.save(dest / f"{i:08d}.png")
    return content_size


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
    num_frames: int | None = None,
) -> None:
    if not RIFE_EXE.is_file():
        raise FileNotFoundError(
            f"Missing {RIFE_EXE}. Run: bash tools/homm3_import/setup_vfi_env.sh"
        )
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    cmd = [
        str(RIFE_EXE),
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
    subprocess.run(cmd, check=True, cwd=RIFE_EXE.parent, env=v_env())


def run_rife_to_target_count(
    input_dir: Path, output_dir: Path, model_name: str, source_frame_count: int
) -> None:
    target = target_frame_count(source_frame_count)
    if model_name in RIFE_MODELS_WITH_NUMFRAME:
        run_rife_pass(input_dir, output_dir, model_name, num_frames=target)
        return

    chain_root = output_dir.parent / f"{output_dir.name}_chain"
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
        run_rife_pass(current_in, step_out, model_name)
        current_in = step_out
        pass_idx += 1
        if pass_idx > 10:
            raise RuntimeError(
                f"RIFE chain for {model_name} did not reach {target} frames (stuck at {count})"
            )

    paths = sorted(current_in.glob("*.png"))
    if len(paths) != target:
        pick = [
            round(i * (len(paths) - 1) / max(target - 1, 1)) for i in range(target)
        ]
        paths = [paths[i] for i in pick]
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    for i, src in enumerate(paths):
        shutil.copy2(src, output_dir / f"{i:08d}.png")
    shutil.rmtree(chain_root, ignore_errors=True)


def write_index(out_dir: Path, unit_notes: dict[str, str] | None = None) -> None:
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>HoMM3 AI interpolation @ {TARGET_FPS} FPS</title>
<style>
body{{font-family:system-ui,sans-serif;background:#fff;color:#111;margin:1.5rem;max-width:1200px}}
h1,h2,h3{{color:#000}}
table{{border-collapse:collapse;width:100%;margin:1rem 0}}
td,th{{border:1px solid #ccc;padding:.5rem;vertical-align:top}}
th{{background:#f0f0f0;width:28%}}
video{{max-width:380px;max-height:420px;background:#fff;border:1px solid #999;display:block}}
.note{{color:#444;font-size:.9rem;line-height:1.45}}
a{{color:#06c}} code{{color:#06c;background:#f5f5f5;padding:.1em .25em;border-radius:3px}}
</style></head><body>
<h1>HoMM3 AI interpolation (prerendered sprites)</h1>
<p class="note">Previews are <strong>WebM VP9 + alpha</strong> at <strong>{TARGET_FPS} FPS</strong>
({INTERP_MULT}× 12 FPS native keyframe density). Fresh RIFE rows are inferred from recovered native DEF keys on a
<strong>dark gray plate</strong> (32,32,32); alpha is reattached after inference — expect dark smears on bright backgrounds.
White page background to expose halos and plate artifacts. Looping enabled for all clips.</p>
<p class="note"><strong>Rows:</strong> <code>01_*</code> = native DEF only;
<code>01b_*</code> = each native key held {INTERP_MULT}× (no AI);
<code>02/03/04_rife_*</code> = fresh RIFE v4.6 / anime / v4 @ {TARGET_FPS} FPS;
<code>04_lab_production_*</code> = current <code>homm3_lab/extracted_battle</code> PNGs (in-game bundle source);
<code>05_rife_dual_stream_idle_tail_lead_*</code> (skeleton attack only) = production dual-stream RIFE on idle tail + attack keys.</p>
<p class="note">Other packs:
<a href="../homm3_animation_interpolation_comparison/index.html">alpha/crossfade GIFs</a>,
<a href="../homm3_animation_advanced_interpolation_comparison/index.html">OpenCV flow</a>.</p>
"""
    for unit_sid, display in UNITS:
        if not (out_dir / unit_sid).is_dir():
            continue
        html += f"<h2>{display} (<code>{unit_sid}</code>)</h2>"
        if unit_notes and unit_sid in unit_notes:
            html += f"<p class='note'>{unit_notes[unit_sid]}</p>"
        for clip_name, _, _ in CLIPS:
            html += f"<h3>{clip_name}</h3><table><tr><th>Method</th><th>Preview</th></tr>"
            clip_dir = out_dir / unit_sid / clip_name
            if not clip_dir.is_dir():
                continue
            for webm in sorted(clip_dir.glob("*.webm")):
                rel = webm.relative_to(out_dir).as_posix()
                txt = webm.with_suffix(".txt")
                label = txt.read_text(encoding="utf-8") if txt.is_file() else webm.stem
                html += (
                    f"<tr><td><strong>{webm.stem}</strong><br>{label}</td>"
                    f"<td><video src='{rel}' autoplay loop muted playsinline></video></td></tr>"
                )
            html += "</table>"
    html += "</body></html>"
    (out_dir / "index.html").write_text(html, encoding="utf-8")


def process_idle_tail_lead_rife_dual_stream(
    unit_sid: str,
    clip_name: str,
    lead_native: list[Image.Image],
    clip_out: Path,
    work_root: Path,
    *,
    encode_only: bool,
) -> None:
    """Production dual-stream RIFE on attack keys with idle's last native key prepended."""
    rife_configure_target_fps(TARGET_FPS)
    native_count = len(lead_native)
    target_n = rife_target_frame_count(native_count)
    method_id = f"05_rife_dual_stream_idle_tail_lead_{TARGET_FPS}fps"
    work_dir = work_root / unit_sid / clip_name / "idle_tail_lead_dual"
    desc = (
        f"Production dual-stream RIFE v4.6 @ {TARGET_FPS} FPS (gray-plate RGB + alpha-mask RIFE), "
        f"last native idle key prepended before attack keys ({native_count} source keys)"
    )

    try:
        if encode_only:
            rgb_cache = work_dir / PRODUCTION_RIFE_MODEL
            alpha_cache = work_dir / f"{PRODUCTION_RIFE_MODEL}_alpha_mask"
            if not rgb_cache.is_dir() or not alpha_cache.is_dir():
                print(
                    f"  skip encode idle-tail-lead dual-stream: no cache under {work_dir}"
                )
                return
            seq = interpolate_rgba_sequence_dual_stream(
                lead_native,
                rife_exe=RIFE_EXE,
                work_dir=work_dir,
                model_name=PRODUCTION_RIFE_MODEL,
                reuse_cache=True,
            )
        else:
            if work_dir.exists():
                shutil.rmtree(work_dir)
            print(
                f"  RIFE {PRODUCTION_RIFE_MODEL} dual-stream (idle tail lead) -> {target_n} frames "
                f"from {native_count} keys ({unit_sid}/{clip_name})..."
            )
            seq = interpolate_rgba_sequence_dual_stream(
                lead_native,
                rife_exe=RIFE_EXE,
                work_dir=work_dir,
                model_name=PRODUCTION_RIFE_MODEL,
                reuse_cache=False,
            )
    except (subprocess.CalledProcessError, RuntimeError, ValueError) as ex:
        print(f"    FAIL RIFE idle-tail-lead dual-stream: {ex}")
        return

    if not seq:
        print("    WARN: no frames for idle-tail-lead dual-stream RIFE")
        return

    try:
        print(f"  WebM {method_id} ({len(seq)} frames @ {TARGET_FPS} FPS)...")
        write_webm(clip_out / f"{method_id}.webm", seq, float(TARGET_FPS))
        (clip_out / f"{method_id}.txt").write_text(
            f"{desc} ({len(seq)} frames @ {TARGET_FPS} FPS VP9+alpha)",
            encoding="utf-8",
        )
    except subprocess.CalledProcessError as ex:
        err = ex.stderr.decode(errors="replace") if ex.stderr else str(ex)
        print(f"    FAIL WebM idle-tail-lead: {err[:200]}")


def process_clip(
    unit_sid: str,
    clip_name: str,
    group_id: int,
    frames: list[Image.Image],
    battle_dir: Path,
    out_dir: Path,
    *,
    encode_only: bool,
    from_lab_rife: bool,
    run_extra_rife_models: bool,
    rife_meta: dict | None,
    idle_tail_lead_native: list[Image.Image] | None = None,
) -> None:
    clip_out = out_dir / unit_sid / clip_name
    if clip_out.exists():
        for stale in clip_out.glob("*"):
            if stale.is_file():
                stale.unlink()
    clip_out.mkdir(parents=True, exist_ok=True)

    native_frames, native_label = native_subset_from_dense(frames, group_id, rife_meta)
    native_count = len(native_frames)
    target_n = target_frame_count(native_count)
    work_root = WORK_ROOT / f"fps{TARGET_FPS}"
    work_in = work_root / unit_sid / clip_name / "in_rgb"

    write_webm(clip_out / "01_baseline_12fps.webm", native_frames, float(SOURCE_FPS))
    (clip_out / "01_baseline_12fps.txt").write_text(
        f"Native baseline: {native_label} (no AI in-betweens)",
        encoding="utf-8",
    )

    hold_frames = baseline_hold_frames(native_frames)
    hold_stem = f"01b_baseline_{TARGET_FPS}fps_hold"
    write_webm(clip_out / f"{hold_stem}.webm", hold_frames, float(TARGET_FPS))
    (clip_out / f"{hold_stem}.txt").write_text(
        f"Each native keyframe held {INTERP_MULT}× @ {TARGET_FPS} FPS (no AI in-betweens)",
        encoding="utf-8",
    )

    if from_lab_rife and len(frames) > native_count:
        method_id = (
            LAB_RIFE_METHOD[0]
            if TARGET_FPS == 120
            else f"04_lab_production_{TARGET_FPS}fps"
        )
        desc = (
            LAB_RIFE_METHOD[2]
            if TARGET_FPS == 120
            else f"Production homm3_lab RIFE @ {TARGET_FPS} FPS (matches in-game bundle)"
        )
        print(f"  WebM {method_id} ({len(frames)} lab frames @ {TARGET_FPS} FPS)...")
        write_webm(clip_out / f"{method_id}.webm", frames, float(TARGET_FPS))
        (clip_out / f"{method_id}.txt").write_text(
            f"{desc} ({len(frames)} frames @ {TARGET_FPS} FPS VP9+alpha)",
            encoding="utf-8",
        )

    content_size = native_frames[0].size
    all_methods = ai_methods_for_target_fps(TARGET_FPS)
    methods = all_methods if run_extra_rife_models else (all_methods[2],)

    run_fresh_rife = not encode_only and (run_extra_rife_models or not from_lab_rife)
    if run_fresh_rife:
        export_rife_input_sequence(native_frames, work_in)

    for method_id, model, desc in methods:
        work_out = work_root / unit_sid / clip_name / model
        if not run_fresh_rife and not encode_only:
            continue
        if not encode_only:
            print(
                f"  RIFE {model} -> {target_n} frames from {native_count} keys "
                f"({unit_sid}/{clip_name})..."
            )
            try:
                run_rife_to_target_count(work_in, work_out, model, native_count)
            except (subprocess.CalledProcessError, RuntimeError, ValueError) as ex:
                print(f"    FAIL RIFE: {model}: {ex}")
                continue
        elif not work_out.is_dir() or not list(work_out.glob("*.png")):
            print(f"  skip encode {model}: no cached PNGs in {work_out}")
            continue

        try:
            seq = load_rife_output_sequence(
                work_out, content_size, native_frames, target_count=target_n
            )
            if not seq:
                print(f"    WARN: no frames for {model}")
                continue
            print(f"  WebM {method_id} ({len(seq)} frames @ {TARGET_FPS} FPS)...")
            write_webm(clip_out / f"{method_id}.webm", seq, float(TARGET_FPS))
            (clip_out / f"{method_id}.txt").write_text(
                f"{desc} ({len(seq)} frames @ {TARGET_FPS} FPS VP9+alpha)",
                encoding="utf-8",
            )
        except subprocess.CalledProcessError as ex:
            err = ex.stderr.decode(errors="replace") if ex.stderr else str(ex)
            print(f"    FAIL WebM: {method_id}: {err[:200]}")

    if idle_tail_lead_native:
        process_idle_tail_lead_rife_dual_stream(
            unit_sid,
            clip_name,
            idle_tail_lead_native,
            clip_out,
            work_root,
            encode_only=encode_only,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--units",
        nargs="*",
        default=[u[0] for u in UNITS],
        help="Unit SIDs (default: h3_gnoll h3_lizardman)",
    )
    parser.add_argument("--clips", nargs="*", default=None)
    parser.add_argument("--target-fps", type=int, default=120)
    parser.add_argument(
        "--encode-only",
        action="store_true",
        help="Skip RIFE; encode WebM from existing tools/.cache/vfi-work PNG caches",
    )
    parser.add_argument(
        "--from-lab-rife",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Encode production RIFE from current homm3_lab PNGs (default: on when .rife120_done.json exists)",
    )
    parser.add_argument(
        "--extra-rife-models",
        action="store_true",
        help="Also run RIFE v4.6 and rife-anime (slow); default is native baseline + lab v4 + optional fresh v4",
    )
    args = parser.parse_args()

    if not args.encode_only and not RIFE_EXE.is_file():
        print("Run setup first: bash tools/homm3_import/setup_vfi_env.sh", file=sys.stderr)
        return 1

    try:
        resolve_ffmpeg()
    except FileNotFoundError as ex:
        print(ex, file=sys.stderr)
        return 1

    global TARGET_FPS, INTERP_MULT
    TARGET_FPS = max(SOURCE_FPS, args.target_fps)
    INTERP_MULT = max(1, TARGET_FPS // SOURCE_FPS)

    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    clip_filter = set(args.clips) if args.clips else None
    unit_notes: dict[str, str] = {}

    unit_catalog = {u[0]: u[1] for u in UNITS}
    unit_catalog.update({u[0]: u[1] for u in LEGACY_UNITS})

    for unit_sid in args.units:
        display = unit_catalog.get(unit_sid, unit_sid)
        print(f"{display} ({unit_sid})")
        manifest_path, manifest = load_manifest(unit_sid)
        battle_dir = manifest_path.parent
        rife_meta = load_rife120_meta(battle_dir)
        from_lab_rife = (
            args.from_lab_rife
            if args.from_lab_rife is not None
            else rife_meta is not None
        )
        if rife_meta:
            groups = rife_meta.get("groups") or {}
            parts = [
                f"g{gid}: {meta.get('sourceCount')}→{meta.get('outputCount')}"
                for gid, meta in sorted(groups.items(), key=lambda x: int(x[0]))
                if meta.get("interpolated")
            ]
            unit_notes[unit_sid] = (
                "Lab has <code>.rife120_done.json</code> ("
                + ", ".join(parts[:8])
                + ("…" if len(parts) > 8 else "")
                + "). Native baselines use recovered DEF keyframes; "
                + (
                    f"<code>04_lab_production_{TARGET_FPS}fps</code> matches the in-game bundle."
                    if from_lab_rife
                    else "re-run with <code>--from-lab-rife</code> for production output."
                )
            )
        idle_dense_by_unit: dict[str, list[Image.Image]] = {}
        for clip_name, group_id, _loop in CLIPS:
            if clip_filter and clip_name not in clip_filter:
                continue
            rel = group_frame_paths(manifest, group_id)
            if not rel:
                print(f"  skip {clip_name}: no group {group_id}")
                continue
            frames = normalize_frames(load_group_frames(battle_dir, rel))
            if clip_name == "idle":
                idle_dense_by_unit[unit_sid] = frames
            idle_tail_lead_native = None
            if unit_sid == "h3_skeleton" and clip_name == "attack":
                idle_dense = idle_dense_by_unit.get(unit_sid)
                if idle_dense is None:
                    idle_rel = group_frame_paths(manifest, GROUP_IDLE)
                    if idle_rel:
                        idle_dense = normalize_frames(load_group_frames(battle_dir, idle_rel))
                        idle_dense_by_unit[unit_sid] = idle_dense
                if idle_dense:
                    idle_tail_lead_native = idle_tail_lead_native_attack(
                        idle_dense, frames, rife_meta
                    )
                if idle_tail_lead_native and unit_sid in unit_notes:
                    unit_notes[unit_sid] += (
                        " Attack experiment: <code>05_rife_dual_stream_idle_tail_lead_"
                        f"{TARGET_FPS}fps</code> uses production dual-stream RIFE on idle tail + attack keys."
                    )
            process_clip(
                unit_sid,
                clip_name,
                group_id,
                frames,
                battle_dir,
                out_dir,
                encode_only=args.encode_only,
                from_lab_rife=from_lab_rife,
                run_extra_rife_models=args.extra_rife_models,
                rife_meta=rife_meta,
                idle_tail_lead_native=idle_tail_lead_native,
            )

    write_index(out_dir, unit_notes)
    readme = f"""# HoMM3 AI interpolation comparison (WebM)

Open **index.html** in a browser (Chrome/Edge/Firefox). Previews use **WebM VP9 + alpha** at **{TARGET_FPS} FPS**.

## Regenerate

```bash
bash tools/homm3_import/setup_vfi_env.sh
tools/.venv-homm3-vfi/Scripts/python.exe -m pip install imageio-ffmpeg
tools/.venv-homm3-vfi/Scripts/python.exe tools/homm3_import/build_animation_ai_interpolation_comparison.py
```

Re-encode only (RIFE PNG caches already under `tools/.cache/vfi-work/`):

```bash
tools/.venv-homm3-vfi/Scripts/python.exe tools/homm3_import/build_animation_ai_interpolation_comparison.py --encode-only
```

## Methods

- **01_baseline_12fps.webm** — source DEF @ 12 FPS
- **01b_baseline_120fps_hold.webm** — each source key held {INTERP_MULT}× @ {TARGET_FPS} FPS
- **04_lab_rife120_120fps.webm** — current homm3_lab RIFE output (matches in-game when present)
- **04_rife_v4_120fps.webm** — fresh RIFE v4 from native keys (optional; skipped with `--from-lab-rife` unless `--no-from-lab-rife`)
- **02/03_rife_*_120fps.webm** — extra models with `--extra-rife-models`
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8")
    print(f"Done: {out_dir / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
