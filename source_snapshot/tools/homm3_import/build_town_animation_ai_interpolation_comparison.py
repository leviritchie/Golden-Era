#!/usr/bin/env python3
"""RIFE dual-stream town building animation previews @ 50 FPS.

Reads deployed town-scene layer anims from homm3_runtime_assets (metadata.json + frame PNGs).
Same browser WebM contract as map/creature comparison: 10 FPS native (100ms/frame) → 50 FPS
with rife-v4.6 dual-stream alpha. Preview-only — does not change runtime town anim assets.
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
    configure_fps,
    interpolate_rgba_sequence_dual_stream,
    normalize_frames,
    target_frame_count,
    v_env,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS = REPO_ROOT / "tools"
TOWN_REFS = (
    REPO_ROOT
    / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_runtime_assets/town_scene_refs"
)
WORK_ROOT = TOOLS / ".cache/vfi-work-town50"
WEBM_STAGE_ROOT = TOOLS / ".cache/vfi-webm-frames-town50"
DEFAULT_OUT = REPO_ROOT / "experiments/homm3_town_animation_ai_interpolation_comparison"

TOWN_SOURCE_FPS = 10
TOWN_TARGET_FPS = 50
RIFE_MODEL = "rife-v4.6"

# faction folder, anim metadata id, display title
DEFAULT_ANIMS = (
    ("homm3_stronghold", "extraCapitol_4", "Stronghold — Capitol (town hall level 4)"),
    ("homm3_fortress", "tbfrmage_3", "Fortress — Magic Guild (level 3)"),
    ("homm3_cove", "tbcvtave", "Cove — Tavern"),
)


def resolve_ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def anims_root(faction: str) -> Path:
    return TOWN_REFS / faction / "layers" / "anims"


def load_anim_entry(faction: str, anim_id: str) -> dict:
    meta_path = anims_root(faction) / "metadata.json"
    if not meta_path.is_file():
        raise FileNotFoundError(meta_path)
    entries = json.loads(meta_path.read_text(encoding="utf-8-sig"))
    for entry in entries:
        if str(entry.get("id", "")).strip() == anim_id:
            return entry
    raise KeyError(f"{anim_id} not in {meta_path}")


def load_town_frames(faction: str, anim_id: str) -> tuple[list[Image.Image], str]:
    entry = load_anim_entry(faction, anim_id)
    frame_names = [str(f).strip() for f in (entry.get("frames") or []) if str(f or "").strip()]
    if len(frame_names) < 2:
        raise ValueError(f"{faction}/{anim_id} has {len(frame_names)} frames; need >= 2 for RIFE")
    anim_dir = anims_root(faction) / anim_id
    if not anim_dir.is_dir():
        raise FileNotFoundError(anim_dir)
    frames: list[Image.Image] = []
    for name in frame_names:
        path = anim_dir / name
        if not path.is_file():
            raise FileNotFoundError(path)
        frames.append(Image.open(path).convert("RGBA"))
    ms = int(entry.get("frameRateMs") or 100)
    native_fps = max(1, round(1000 / ms)) if ms > 0 else TOWN_SOURCE_FPS
    label = (
        f"Town DEF anim <code>{anim_id}</code>: {len(frames)} frames "
        f"(metadata frameRateMs={ms}, ~{native_fps} FPS in-game)"
    )
    return normalize_frames(frames), label


def baseline_hold_frames(frames: list[Image.Image], hold: int) -> list[Image.Image]:
    held: list[Image.Image] = []
    for frame in frames:
        held.extend([frame] * hold)
    return held


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


def parse_anim_spec(spec: str) -> tuple[str, str]:
    if ":" not in spec:
        raise ValueError(f"expected faction:anim_id, got {spec!r}")
    faction, anim_id = spec.split(":", 1)
    faction = faction.strip()
    anim_id = anim_id.strip()
    if not faction or not anim_id:
        raise ValueError(f"expected faction:anim_id, got {spec!r}")
    return faction, anim_id


def write_index(
    out_dir: Path,
    anim_specs: list[tuple[str, str, str]],
    anim_notes: dict[str, str],
    *,
    source_fps: int,
    target_fps: int,
) -> None:
    hold = target_fps // source_fps
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>HoMM3 town scene RIFE @ {target_fps} FPS</title>
<style>
body{{font-family:system-ui,sans-serif;background:#fff;color:#111;margin:1.5rem;max-width:1200px}}
h1,h2,h3{{color:#000}}
table{{border-collapse:collapse;width:100%;margin:1rem 0}}
td,th{{border:1px solid #ccc;padding:.5rem;vertical-align:top}}
th{{background:#f0f0f0;width:28%}}
video{{max-width:480px;max-height:520px;background:#fff;border:1px solid #999;display:block}}
.note{{color:#444;font-size:.9rem;line-height:1.45}}
a{{color:#06c}} code{{color:#06c;background:#f5f5f5;padding:.1em .25em;border-radius:3px}}
</style></head><body>
<h1>HoMM3 town building animations — dual-stream RIFE @ {target_fps} FPS</h1>
<p class="note">Town-screen building DEF cycles from <code>homm3_runtime_assets/town_scene_refs/*/layers/anims</code>.
Native runtime uses <strong>~{source_fps} FPS</strong> (<code>frameRateMs=100</code>); previews target <strong>{target_fps} FPS</strong>
({hold}×). Dual-stream row: <strong>rife-v4.6</strong> gray-plate RGB + separate alpha-mask RIFE
(same as <code>HOMM3_DUAL_STREAM_ALPHA</code>).</p>
<p class="note"><strong>Rows:</strong> <code>01_*</code> native @ {source_fps} FPS;
<code>01b_*</code> hold {hold}× @ {target_fps} FPS;
<code>04_rife_dual_stream_{target_fps}fps</code> dual-stream RIFE.</p>
<p class="note">Related:
<a href="../homm3_map_animation_ai_interpolation_comparison/index.html">map unit billboards</a>,
<a href="../homm3_animation_ai_interpolation_comparison/index.html">battle sprites</a>.</p>
"""
    for faction, anim_id, display in anim_specs:
        key = f"{faction}:{anim_id}"
        html += f"<h2>{display}</h2>"
        html += f"<p class='note'><code>{faction}</code> / <code>{anim_id}</code></p>"
        if key in anim_notes:
            html += f"<p class='note'>{anim_notes[key]}</p>"
        clip_dir = out_dir / faction / anim_id
        if not clip_dir.is_dir():
            continue
        html += "<table><tr><th>Method</th><th>Preview</th></tr>"
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


def process_anim(
    faction: str,
    anim_id: str,
    out_dir: Path,
    *,
    source_fps: int,
    target_fps: int,
    encode_only: bool,
    rife_exe: Path,
) -> str:
    native_frames, native_label = load_town_frames(faction, anim_id)
    native_count = len(native_frames)
    hold = target_fps // source_fps
    target_n = target_frame_count(native_count)
    clip_out = out_dir / faction / anim_id
    if clip_out.exists():
        for stale in clip_out.glob("*"):
            if stale.is_file():
                stale.unlink()
    clip_out.mkdir(parents=True, exist_ok=True)

    work_dir = WORK_ROOT / faction / anim_id
    print(f"  native frames: {native_count} -> target {target_n} @ {target_fps} FPS")

    write_webm(clip_out / f"01_baseline_{source_fps}fps.webm", native_frames, float(source_fps))
    (clip_out / f"01_baseline_{source_fps}fps.txt").write_text(
        f"{native_label} (no AI in-betweens)", encoding="utf-8"
    )

    hold_stem = f"01b_baseline_{target_fps}fps_hold"
    write_webm(
        clip_out / f"{hold_stem}.webm",
        baseline_hold_frames(native_frames, hold),
        float(target_fps),
    )
    (clip_out / f"{hold_stem}.txt").write_text(
        f"Each native frame held {hold}× @ {target_fps} FPS (no AI in-betweens)",
        encoding="utf-8",
    )

    dual_stem = f"04_rife_dual_stream_{target_fps}fps"
    dual_desc = (
        "Dual-stream RIFE v4.6: gray-plate RGB + separate alpha-mask RIFE "
        f"({target_n} frames @ {target_fps} FPS VP9+alpha)"
    )
    if encode_only:
        seq = interpolate_rgba_sequence_dual_stream(
            native_frames,
            rife_exe=rife_exe,
            work_dir=work_dir,
            model_name=RIFE_MODEL,
            reuse_cache=True,
        )
    else:
        if work_dir.exists():
            shutil.rmtree(work_dir)
        print(f"  RIFE dual-stream ({faction}/{anim_id})...")
        seq = interpolate_rgba_sequence_dual_stream(
            native_frames,
            rife_exe=rife_exe,
            work_dir=work_dir,
            model_name=RIFE_MODEL,
            reuse_cache=False,
        )
    if not seq:
        raise RuntimeError("dual-stream RIFE returned no frames")
    print(f"  WebM {dual_stem} ({len(seq)} frames)...")
    write_webm(clip_out / f"{dual_stem}.webm", seq, float(target_fps))
    (clip_out / f"{dual_stem}.txt").write_text(dual_desc, encoding="utf-8")

    rel = (anims_root(faction) / anim_id).relative_to(REPO_ROOT).as_posix()
    return (
        f"Source <code>{rel}</code> — {native_count} native frames, "
        f"dual-stream {len(seq)} @ {target_fps} FPS."
    )


def resolve_anim_list(
    anim_args: list[str] | None,
) -> list[tuple[str, str, str]]:
    if not anim_args:
        return list(DEFAULT_ANIMS)
    out: list[tuple[str, str, str]] = []
    catalog = {f"{f}:{a}": (f, a, d) for f, a, d in DEFAULT_ANIMS}
    for spec in anim_args:
        if spec.count(":") >= 2:
            parts = spec.split(":", 2)
            out.append((parts[0].strip(), parts[1].strip(), parts[2].strip()))
            continue
        faction, anim_id = parse_anim_spec(spec)
        display = catalog.get(f"{faction}:{anim_id}", (faction, anim_id, f"{faction} — {anim_id}"))[2]
        out.append((faction, anim_id, display))
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--anims",
        nargs="*",
        help="Animations as faction:anim_id or faction:anim_id:Title (default: Stronghold Capitol, Fortress Mage, Cove Tavern)",
    )
    parser.add_argument("--source-fps", type=int, default=10)
    parser.add_argument("--target-fps", type=int, default=50)
    parser.add_argument("--encode-only", action="store_true")
    args = parser.parse_args()

    source_fps, target_fps, _ = configure_fps(args.source_fps, args.target_fps)
    anim_specs = resolve_anim_list(args.anims)

    rife_exe = DEFAULT_RIFE_EXE
    if not args.encode_only and not rife_exe.is_file():
        print("Run setup first: bash tools/homm3_import/setup_vfi_env.sh", file=sys.stderr)
        return 1

    try:
        resolve_ffmpeg()
    except FileNotFoundError as ex:
        print(ex, file=sys.stderr)
        return 1

    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    anim_notes: dict[str, str] = {}

    for faction, anim_id, display in anim_specs:
        key = f"{faction}:{anim_id}"
        print(f"{display} ({key})")
        try:
            anim_notes[key] = process_anim(
                faction,
                anim_id,
                out_dir,
                source_fps=source_fps,
                target_fps=target_fps,
                encode_only=args.encode_only,
                rife_exe=rife_exe,
            )
        except (FileNotFoundError, KeyError, ValueError, RuntimeError, subprocess.CalledProcessError) as ex:
            print(f"  FAIL: {ex}")
            anim_notes[key] = f"<strong>Error:</strong> {ex}"

    write_index(out_dir, anim_specs, anim_notes, source_fps=source_fps, target_fps=target_fps)
    hold = target_fps // source_fps
    readme = f"""# HoMM3 town scene animation RIFE @ {target_fps} FPS

Open **index.html** in a browser. Previews use **WebM VP9 + alpha** at **{target_fps} FPS**
from `homm3_runtime_assets/town_scene_refs/*/layers/anims` (native **~{source_fps} FPS**).

**Preview-only** — does not rewrite deployed town anim PNGs or `metadata.json`.

## Default clips

- Stronghold Capitol (`homm3_stronghold` / `extraCapitol_4`)
- Fortress Magic Guild level 3 (`homm3_fortress` / `tbfrmage_3`)
- Cove Tavern (`homm3_cove` / `tbcvtave`)

## Regenerate

```bash
tools/.venv-homm3-vfi/Scripts/python.exe tools/homm3_import/build_town_animation_ai_interpolation_comparison.py
```

Re-encode from `tools/.cache/vfi-work-town50/`:

```bash
tools/.venv-homm3-vfi/Scripts/python.exe tools/homm3_import/build_town_animation_ai_interpolation_comparison.py --encode-only
```

Custom anim:

```bash
tools/.venv-homm3-vfi/Scripts/python.exe tools/homm3_import/build_town_animation_ai_interpolation_comparison.py --anims homm3_tower:dwellingUp2Lvl1_1
```
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8")
    print(f"Done: {out_dir / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
