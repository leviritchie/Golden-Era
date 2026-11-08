#!/usr/bin/env python3
"""RIFE v4.6 plate / matting / alpha experiments for HoMM3 battle sprites.

Plate / matting / dual-stream alpha experiments for gray-plate smear on bright backgrounds.
All variants use rife-v4.6 unless noted. Includes production-style gray plate reference.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

from homm3_rife_core import (
    DEFAULT_RIFE_EXE,
    RIFE_PLATE_RGBA,
    configure_target_fps,
    export_alpha_mask_rgb_sequence,
    export_rife_input_sequence,
    load_rife_dual_stream_sequence,
    load_rife_output_sequence_assembled,
    normalize_frames,
    run_rife_v4_to_target_count,
    target_frame_count,
    v_env,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS = REPO_ROOT / "tools"
LAB_ROOT = REPO_ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_lab"
RIFE_EXE = DEFAULT_RIFE_EXE
WORK_ROOT = TOOLS / ".cache/vfi-work/plate-exp"
WEBM_STAGE_ROOT = TOOLS / ".cache/vfi-webm-frames"
DEFAULT_OUT = REPO_ROOT / "experiments/homm3_animation_rife_plate_comparison"

PLATE_GRAY = RIFE_PLATE_RGBA
PLATE_BLACK = (0, 0, 0, 255)
RIFE_MODEL = "rife-v4.6"

GROUP_IDLE = 2
GROUP_MOVEMENT = 0
GROUP_HITTED = 3
GROUP_DEATH = 5
GROUP_ATTACK_FRONT = 12

UNITS = (
    ("h3_gnoll", "Fortress Gnoll"),
    ("h3_lizardman", "Fortress Lizardman"),
)

CLIPS = (
    ("idle", GROUP_IDLE),
    ("walk", GROUP_MOVEMENT),
    ("attack", GROUP_ATTACK_FRONT),
    ("damage", GROUP_HITTED),
    ("death", GROUP_DEATH),
)

# stem, plate_rgba, assemble mode, description, optional matte kwargs for plate_matte
MATTE_GENTLE = {
    "matte_tol_lo": 5.0,
    "matte_tol_hi": 96.0,
    "matte_fringe_above": 210,
    "matte_fringe_band": 48,
    "matte_legacy_multiply": False,
}
MATTE_STRICT = {
    "matte_tol_lo": 10.0,
    "matte_tol_hi": 48.0,
    "matte_legacy_multiply": True,
}

VARIANTS = (
    (
        "00_reference_gray_plate",
        PLATE_GRAY,
        "key_alpha",
        "Reference: gray plate (32,32,32) + keyframe alpha only (current production style)",
        {},
    ),
    (
        "01_black_plate",
        PLATE_BLACK,
        "key_alpha",
        "Black compositing plate (0,0,0) + keyframe alpha only",
        {},
    ),
    (
        "02_plate_matte",
        PLATE_GRAY,
        "plate_matte",
        "Gray plate + fringe-only matting (tol 5–96, plate cut only where key alpha &lt; ~210)",
        MATTE_GENTLE,
    ),
    (
        "02b_plate_matte_strict",
        PLATE_GRAY,
        "plate_matte",
        "Previous strict matting: global key×plate multiply (tol 10–48) — can eat solid pixels",
        MATTE_STRICT,
    ),
    (
        "03_premul_rgba_crossfade",
        PLATE_GRAY,
        "premul_crossfade",
        "Gray plate + premultiplied RGBA crossfade under RIFE RGB (interpolate color & alpha)",
        {},
    ),
    (
        "04_rife_dual_stream_alpha",
        PLATE_GRAY,
        "rife_dual_alpha",
        "Dual-stream RIFE v4.6: gray-plate RGB + separate RIFE on alpha mask (RIFE-with-Transparency style)",
        {},
    ),
)


def plate_tag(plate_rgba: tuple[int, int, int, int]) -> str:
    r, g, b, _ = plate_rgba
    return f"plate{r:02x}{g:02x}{b:02x}"


def resolve_ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


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
        return [dense_frames[0]], f"{source_count} native DEF keyframe"
    step = (len(dense_frames) - 1) / (source_count - 1)
    indices = [round(i * step) for i in range(source_count)]
    return [dense_frames[i] for i in indices], f"{source_count} native DEF keyframes"


def group_frame_paths(manifest: dict, group_id: int) -> list[str]:
    for sequence in manifest.get("sequences") or []:
        if int(sequence.get("group", -1)) != group_id:
            continue
        return [str(f).strip() for f in (sequence.get("frames") or []) if str(f or "").strip()]
    return []


def load_group_frames(battle_dir: Path, rel_paths: list[str]) -> list[Image.Image]:
    return [
        Image.open(battle_dir / rel.replace("\\", "/")).convert("RGBA") for rel in rel_paths
    ]


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


def ensure_rife_cache(
    native_frames: list[Image.Image],
    work_in: Path,
    work_out: Path,
    *,
    plate_rgba: tuple[int, int, int, int],
    encode_only: bool,
) -> bool:
    if work_out.is_dir() and len(list(work_out.glob("*.png"))) >= 2:
        return True
    if encode_only:
        return False
    export_rife_input_sequence(native_frames, work_in, plate_rgba=plate_rgba)
    run_rife_v4_to_target_count(
        work_in,
        work_out,
        len(native_frames),
        rife_exe=RIFE_EXE,
        model_name=RIFE_MODEL,
        work_root=work_out.parent,
    )
    return work_out.is_dir() and len(list(work_out.glob("*.png"))) >= 2


def write_index(out_dir: Path, target_fps: int, interp_mult: int) -> None:
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>HoMM3 RIFE plate experiments @ {target_fps} FPS</title>
<style>
:root {{
  --page-bg: #ffffff;
  --page-fg: #111111;
  --panel-bg: #f0f0f0;
  --border: #cccccc;
  --video-bg: #ffffff;
}}
body.backdrop-black {{
  --page-bg: #000000;
  --page-fg: #eeeeee;
  --panel-bg: #1a1a1a;
  --border: #444444;
  --video-bg: #000000;
}}
body {{
  font-family: system-ui, sans-serif;
  background: var(--page-bg);
  color: var(--page-fg);
  margin: 1.5rem;
  max-width: 1200px;
  transition: background 0.15s, color 0.15s;
}}
h1, h2, h3 {{ color: var(--page-fg); }}
.toolbar {{
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  align-items: center;
  padding: 0.75rem 1rem;
  background: var(--panel-bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  margin: 1rem 0;
}}
.toolbar label {{ cursor: pointer; user-select: none; }}
table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
td, th {{
  border: 1px solid var(--border);
  padding: 0.5rem;
  vertical-align: top;
}}
th {{ background: var(--panel-bg); width: 28%; }}
video {{
  max-width: 380px;
  max-height: 420px;
  background: var(--video-bg);
  border: 1px solid var(--border);
  display: block;
}}
.note {{ color: var(--page-fg); opacity: 0.85; font-size: 0.9rem; line-height: 1.45; }}
code {{
  background: var(--panel-bg);
  padding: 0.1em 0.25em;
  border-radius: 3px;
}}
a {{ color: #06c; }}
body.backdrop-black a {{ color: #8cf; }}
</style></head><body>
<h1>RIFE v4.6 plate / matting experiments</h1>
<div class="toolbar">
  <label><input type="checkbox" id="backdrop-black"> Black backdrop (off = white)</label>
  <span class="note">Toggle to check for background overfitting. Videos use VP9 alpha; page color is only behind the preview.</span>
</div>
<p class="note">All rows: <strong>RIFE v4.6</strong> @ <strong>{target_fps} FPS</strong> ({interp_mult}× native DEF keys).
<code>04_rife_dual_stream_alpha</code> runs RIFE on gray-plate RGB and a separate RIFE pass on the alpha mask.
Use the backdrop toggle — if a fix only works on one color, it is masking smear rather than fixing motion.</p>
<p class="note"><a href="../homm3_animation_ai_interpolation_comparison/index.html">Full AI model comparison</a>
· <a href="../homm3_animation_interpolation_comparison/index.html">Crossfade GIF pack</a></p>
<script>
(function() {{
  const box = document.getElementById('backdrop-black');
  const apply = () => document.body.classList.toggle('backdrop-black', box.checked);
  box.addEventListener('change', apply);
  apply();
}})();
</script>
"""
    for unit_sid, display in UNITS:
        html += f"<h2>{display} (<code>{unit_sid}</code>)</h2>"
        for clip_name, _ in CLIPS:
            html += f"<h3>{clip_name}</h3><table><tr><th>Variant</th><th>Preview</th></tr>"
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


def process_clip(
    unit_sid: str,
    clip_name: str,
    group_id: int,
    dense_frames: list[Image.Image],
    out_dir: Path,
    *,
    target_fps: int,
    rife_meta: dict | None,
    encode_only: bool,
    matte_tol_lo: float,
    matte_tol_hi: float,
) -> None:
    clip_out = out_dir / unit_sid / clip_name
    if clip_out.exists():
        for stale in clip_out.glob("*"):
            if stale.is_file():
                stale.unlink()
    clip_out.mkdir(parents=True, exist_ok=True)

    native_frames = normalize_frames(dense_frames)
    native_frames, native_label = native_subset_from_dense(native_frames, group_id, rife_meta)
    if len(native_frames) < 2:
        print(f"  skip {clip_name}: need >=2 native keys (have {len(native_frames)})")
        return

    target_n = target_frame_count(len(native_frames))
    content_size = native_frames[0].size
    work_base = WORK_ROOT / f"fps{target_fps}" / unit_sid / clip_name

    # One RIFE run per plate color
    plate_runs: dict[str, tuple[tuple[int, int, int, int], Path, Path]] = {}
    for _stem, plate_rgba, _mode, _desc, _matte in VARIANTS:
        tag = plate_tag(plate_rgba)
        if tag in plate_runs:
            continue
        work_in = work_base / f"in_{tag}"
        work_out = work_base / f"rife-v46_{tag}"
        plate_runs[tag] = (plate_rgba, work_in, work_out)

    for tag, (plate_rgba, work_in, work_out) in plate_runs.items():
        print(f"  RIFE {RIFE_MODEL} [{tag}] -> {target_n} frames ({unit_sid}/{clip_name})...")
        if not ensure_rife_cache(
            native_frames, work_in, work_out, plate_rgba=plate_rgba, encode_only=encode_only
        ):
            print(f"    skip: no cache at {work_out}")
            for stem, pr, *_rest in VARIANTS:
                if plate_tag(pr) == tag:
                    print(f"      missing WebM for {stem}")
            continue

    gray_tag = plate_tag(PLATE_GRAY)
    dual_rgb_out = plate_runs[gray_tag][2]
    dual_alpha_in = work_base / "in_alpha_mask"
    dual_alpha_out = work_base / "rife-v46_alpha_mask"
    dual_ok = dual_rgb_out.is_dir() and len(list(dual_rgb_out.glob("*.png"))) >= 2
    if dual_ok:
        if dual_alpha_out.is_dir() and len(list(dual_alpha_out.glob("*.png"))) >= 2:
            pass
        elif encode_only:
            dual_ok = False
            print(f"  skip dual-stream: no alpha cache at {dual_alpha_out}")
        else:
            print(
                f"  RIFE {RIFE_MODEL} [alpha_mask] -> {target_n} frames "
                f"({unit_sid}/{clip_name})..."
            )
            export_alpha_mask_rgb_sequence(native_frames, dual_alpha_in)
            run_rife_v4_to_target_count(
                dual_alpha_in,
                dual_alpha_out,
                len(native_frames),
                rife_exe=RIFE_EXE,
                model_name=RIFE_MODEL,
                work_root=work_base,
            )
            dual_ok = dual_alpha_out.is_dir() and len(list(dual_alpha_out.glob("*.png"))) >= 2
    else:
        print(f"  skip dual-stream: missing RGB cache at {dual_rgb_out}")

    for stem, plate_rgba, mode, desc, matte_kw in VARIANTS:
        if mode == "rife_dual_alpha":
            if not dual_ok:
                continue
            seq = load_rife_dual_stream_sequence(
                dual_rgb_out,
                dual_alpha_out,
                content_size,
                target_count=target_n,
            )
            if not seq:
                print(f"    WARN: empty dual-stream sequence")
                continue
            print(f"  WebM {stem} ({len(seq)} @ {target_fps} FPS)...")
            write_webm(clip_out / f"{stem}.webm", seq, float(target_fps))
            (clip_out / f"{stem}.txt").write_text(
                f"{desc}. {native_label}. {len(seq)} frames @ {target_fps} FPS VP9+alpha.",
                encoding="utf-8",
            )
            continue

        tag = plate_tag(plate_rgba)
        work_out = plate_runs[tag][2]
        if not work_out.is_dir():
            continue
        assemble_kw: dict = {}
        if mode == "plate_matte":
            strict = bool(matte_kw.get("matte_legacy_multiply"))
            base = MATTE_STRICT if strict else MATTE_GENTLE
            assemble_kw = {**base, **matte_kw}
            if not strict:
                assemble_kw["matte_tol_lo"] = matte_tol_lo
                assemble_kw["matte_tol_hi"] = matte_tol_hi
        seq = load_rife_output_sequence_assembled(
            work_out,
            content_size,
            native_frames,
            target_count=target_n,
            mode=mode,
            plate_rgb=plate_rgba[:3],
            **assemble_kw,
        )
        if not seq:
            print(f"    WARN: empty sequence {stem}")
            continue
        print(f"  WebM {stem} ({len(seq)} @ {target_fps} FPS)...")
        write_webm(clip_out / f"{stem}.webm", seq, float(target_fps))
        (clip_out / f"{stem}.txt").write_text(
            f"{desc}. {native_label}. {len(seq)} frames @ {target_fps} FPS VP9+alpha.",
            encoding="utf-8",
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--units", nargs="*", default=[u[0] for u in UNITS])
    parser.add_argument("--clips", nargs="*", default=None)
    parser.add_argument("--target-fps", type=int, default=60)
    parser.add_argument("--encode-only", action="store_true")
    parser.add_argument(
        "--matte-tol-lo",
        type=float,
        default=MATTE_GENTLE["matte_tol_lo"],
        help="Plate distance (RGB) below which matte starts (gentle row)",
    )
    parser.add_argument(
        "--matte-tol-hi",
        type=float,
        default=MATTE_GENTLE["matte_tol_hi"],
        help="Plate distance where matte reaches full strength (gentle row)",
    )
    args = parser.parse_args()

    if not args.encode_only and not RIFE_EXE.is_file():
        print("Run: bash tools/homm3_import/setup_vfi_env.sh", file=sys.stderr)
        return 1

    try:
        resolve_ffmpeg()
    except FileNotFoundError as ex:
        print(ex, file=sys.stderr)
        return 1

    target_fps, interp_mult = configure_target_fps(args.target_fps)
    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    clip_filter = set(args.clips) if args.clips else None

    for unit_sid in args.units:
        display = next((d for s, d in UNITS if s == unit_sid), unit_sid)
        print(f"{display} ({unit_sid})")
        manifest_path, manifest = load_manifest(unit_sid)
        battle_dir = manifest_path.parent
        rife_meta = load_rife120_meta(battle_dir)
        for clip_name, group_id in CLIPS:
            if clip_filter and clip_name not in clip_filter:
                continue
            rel = group_frame_paths(manifest, group_id)
            if not rel:
                print(f"  skip {clip_name}: no group {group_id}")
                continue
            dense = load_group_frames(battle_dir, rel)
            process_clip(
                unit_sid,
                clip_name,
                group_id,
                dense,
                out_dir,
                target_fps=target_fps,
                rife_meta=rife_meta,
                encode_only=args.encode_only,
                matte_tol_lo=args.matte_tol_lo,
                matte_tol_hi=args.matte_tol_hi,
            )

    write_index(out_dir, target_fps, interp_mult)
    print(f"Done: {out_dir / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
