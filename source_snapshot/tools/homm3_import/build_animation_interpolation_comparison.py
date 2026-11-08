#!/usr/bin/env python3
"""Build side-by-side GIF comparisons for HoMM3 battle animation smoothing experiments."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
LAB_ROOT = REPO_ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_lab"
DEFAULT_OUT = REPO_ROOT / "experiments/homm3_animation_interpolation_comparison"

GROUP_IDLE = 2
GROUP_MOVEMENT = 0
GROUP_MOUSEOVER = 1
GROUP_HITTED = 3
GROUP_DEATH = 5
GROUP_ATTACK_FRONT = 12
MELEE_ATTACK_GROUPS = (11, 12, 13)

UNITS = (
    ("h3_angel", "Castle Angel"),
    ("h3_hydra", "Fortress Hydra"),
    ("h3_vampire", "Necropolis Vampire"),
)

CLIPS = (
    ("idle", GROUP_IDLE, True),
    ("walk", GROUP_MOVEMENT, True),
    ("attack", GROUP_ATTACK_FRONT, False),
    ("damage", GROUP_HITTED, False),
    ("death", GROUP_DEATH, False),
)

FPS_SHIPPED = 12
FRAME_MS = int(1000 / FPS_SHIPPED)


def repo_path(path: Path) -> Path:
    return Path(os.path.abspath(path))


def load_manifest(unit_sid: str) -> tuple[Path, dict]:
    battle_dir = LAB_ROOT / unit_sid / "extracted_battle"
    if not battle_dir.is_dir():
        raise FileNotFoundError(f"missing extracted_battle for {unit_sid}")
    json_files = sorted(battle_dir.glob("*.json"))
    json_files = [p for p in json_files if p.name.lower() != "manifest.json"]
    if not json_files:
        raise FileNotFoundError(f"no defextract JSON in {battle_dir}")
    manifest_path = json_files[0]
    return manifest_path, json.loads(manifest_path.read_text(encoding="utf-8-sig"))


def group_frame_paths(manifest: dict, group_id: int) -> list[str]:
    for sequence in manifest.get("sequences") or []:
        if int(sequence.get("group", -1)) != group_id:
            continue
        frames = sequence.get("frames") or []
        return [str(f).strip() for f in frames if str(f or "").strip()]
    return []


def resolve_frame_path(battle_dir: Path, rel: str) -> Path:
    rel = rel.replace("\\", "/")
    return battle_dir / rel


def load_rgba(path: Path) -> Image.Image:
    img = Image.open(path).convert("RGBA")
    return img


def canvas_size(images: list[Image.Image]) -> tuple[int, int]:
    w = max(im.width for im in images)
    h = max(im.height for im in images)
    return w, h


def center_on_canvas(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    w, h = size
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    out.paste(img, ((w - img.width) // 2, (h - img.height) // 2), img)
    return out


def load_group_frames(battle_dir: Path, rel_paths: list[str]) -> list[Image.Image]:
    frames: list[Image.Image] = []
    for rel in rel_paths:
        path = resolve_frame_path(battle_dir, rel)
        if not path.is_file():
            raise FileNotFoundError(path)
        frames.append(load_rgba(path))
    return frames


def premultiply(img: Image.Image) -> Image.Image:
    rgba = img.convert("RGBA")
    r, g, b, a = rgba.split()
    rgb = Image.merge("RGB", (r, g, b))
    alpha = a.point(lambda x: x / 255.0)
    # manual premul via numpy-free approach
    out = Image.new("RGBA", rgba.size)
    px = rgba.load()
    opx = out.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            pr, pg, pb, pa = px[x, y]
            if pa == 0:
                opx[x, y] = (0, 0, 0, 0)
            else:
                a = pa / 255.0
                opx[x, y] = (int(pr * a), int(pg * a), int(pb * a), pa)
    return out


def unpremultiply(img: Image.Image) -> Image.Image:
    out = Image.new("RGBA", img.size)
    px = img.load()
    opx = out.load()
    for y in range(img.height):
        for x in range(img.width):
            pr, pg, pb, pa = px[x, y]
            if pa == 0:
                opx[x, y] = (0, 0, 0, 0)
            else:
                a = pa / 255.0
                opx[x, y] = (
                    min(255, int(pr / a)),
                    min(255, int(pg / a)),
                    min(255, int(pb / a)),
                    pa,
                )
    return out


def blend_rgba(a: Image.Image, b: Image.Image, t: float) -> Image.Image:
    if a.size != b.size:
        b = b.resize(a.size, Image.Resampling.NEAREST)
    ap = premultiply(a)
    bp = premultiply(b)
    out = Image.new("RGBA", a.size)
    apx = ap.load()
    bpx = bp.load()
    opx = out.load()
    for y in range(a.height):
        for x in range(a.width):
            ar, ag, ab, aa = apx[x, y]
            br, bg, bb, ba = bpx[x, y]
            opx[x, y] = (
                int(ar * (1 - t) + br * t),
                int(ag * (1 - t) + bg * t),
                int(ab * (1 - t) + bb * t),
                int(aa * (1 - t) + ba * t),
            )
    return unpremultiply(out)


def normalize_frames(frames: list[Image.Image]) -> list[Image.Image]:
    if not frames:
        return []
    size = canvas_size(frames)
    return [center_on_canvas(f, size) for f in frames]


def write_gif(path: Path, frames: list[Image.Image], duration_ms: int, loop: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    paletted = [f.convert("P", palette=Image.Palette.ADAPTIVE, colors=256) for f in frames]
    paletted[0].save(
        path,
        save_all=True,
        append_images=paletted[1:],
        duration=duration_ms,
        loop=0 if loop else 1,
        disposal=2,
        optimize=False,
    )


def method_baseline(frames: list[Image.Image], loop: bool) -> tuple[list[Image.Image], int]:
    return frames, FRAME_MS


def method_crossfade_insert(
    frames: list[Image.Image], loop: bool, steps: tuple[float, ...] = (0.5,)
) -> tuple[list[Image.Image], int]:
    if len(frames) < 2:
        return frames, FRAME_MS
    out: list[Image.Image] = []
    count = len(frames)
    for i in range(count):
        out.append(frames[i])
        nxt = frames[(i + 1) % count] if loop else (frames[i + 1] if i + 1 < count else None)
        if nxt is None:
            continue
        for t in steps:
            out.append(blend_rgba(frames[i], nxt, t))
    return out, FRAME_MS


def method_crossfade_same_duration(
    frames: list[Image.Image], loop: bool, steps: tuple[float, ...] = (0.5,)
) -> tuple[list[Image.Image], int]:
    expanded, _ = method_crossfade_insert(frames, loop, steps)
    if not expanded:
        return expanded, FRAME_MS
    baseline_ms = len(frames) * FRAME_MS
    per_frame_ms = max(20, baseline_ms // len(expanded))
    return expanded, per_frame_ms


def method_crossfade_playback_sim(
    frames: list[Image.Image], loop: bool, substeps: int = 4
) -> tuple[list[Image.Image], int]:
    if len(frames) < 2:
        return frames, FRAME_MS
    out: list[Image.Image] = []
    count = len(frames)
    segment_ms = FRAME_MS // substeps
    for i in range(count):
        out.append(frames[i])
        nxt = frames[(i + 1) % count] if loop else (frames[i + 1] if i + 1 < count else None)
        if nxt is None:
            continue
        for s in range(1, substeps):
            t = s / substeps
            out.append(blend_rgba(frames[i], nxt, t))
    return out, max(20, segment_ms)


def method_duplicate_hold(frames: list[Image.Image], loop: bool) -> tuple[list[Image.Image], int]:
    out: list[Image.Image] = []
    for f in frames:
        out.append(f)
        out.append(f)
    return out, FRAME_MS // 2


def method_fps_24_discrete(frames: list[Image.Image], loop: bool) -> tuple[list[Image.Image], int]:
    return frames, FRAME_MS // 2


METHODS = (
    ("01_baseline_12fps", "Shipped: discrete frames @ 12 FPS", method_baseline),
    (
        "02_crossfade_insert_12fps",
        "Insert 50% blend between each frame; still 12 FPS per displayed frame (longer loop)",
        lambda f, l: method_crossfade_insert(f, l, (0.5,)),
    ),
    (
        "03_crossfade_same_duration",
        "Insert 50% blends; compress timing so loop duration matches baseline",
        lambda f, l: method_crossfade_same_duration(f, l, (0.5,)),
    ),
    (
        "04_crossfade_quarters",
        "Insert 25/50/75% blends between each frame @ 12 FPS (much longer loop)",
        lambda f, l: method_crossfade_insert(f, l, (0.25, 0.5, 0.75)),
    ),
    (
        "05_crossfade_playback_sim",
        "Simulate runtime crossfade: 4 substeps between keyframes (~48 FPS display)",
        method_crossfade_playback_sim,
    ),
    (
        "06_duplicate_hold_24fps",
        "Hold each source frame twice @ 24 FPS (same loop time as baseline)",
        method_duplicate_hold,
    ),
    (
        "07_fps_24_discrete",
        "Same frames @ 24 FPS (faster, not more poses)",
        method_fps_24_discrete,
    ),
)

WALK_ALT_METHOD = (
    "08_walk_group1_unused",
    "Walk using DEF group 1 (mouseover) — not used when group 0 exists in shipped build",
)


def build_walk_alt(unit_sid: str, battle_dir: Path, manifest: dict, out_dir: Path) -> None:
    rel = group_frame_paths(manifest, GROUP_MOUSEOVER)
    if not rel:
        return
    frames = normalize_frames(load_group_frames(battle_dir, rel))
    seq, ms = method_baseline(frames, True)
    write_gif(out_dir / unit_sid / "walk" / f"{WALK_ALT_METHOD[0]}.gif", seq, ms, True)


def build_attack_direction_comparison(
    unit_sid: str, battle_dir: Path, manifest: dict, out_dir: Path
) -> None:
    parts: list[Image.Image] = []
    labels: list[str] = []
    for gid in MELEE_ATTACK_GROUPS:
        rel = group_frame_paths(manifest, gid)
        if not rel:
            continue
        parts.extend(normalize_frames(load_group_frames(battle_dir, rel)))
        labels.append(f"g{gid}={len(rel)}")
    front = group_frame_paths(manifest, GROUP_ATTACK_FRONT)
    if not front or not parts or len(parts) <= len(front):
        return
    seq, ms = method_baseline(parts, False)
    write_gif(
        out_dir / unit_sid / "attack" / "09_attack_all_melee_directions.gif",
        seq,
        ms,
        False,
    )
    meta = out_dir / unit_sid / "attack" / "09_attack_all_melee_directions.txt"
    meta.write_text(
        "Concatenates DEF groups 11+12+13 (up+front+down). Shipped 14.Attack uses one group only.\n"
        + " ".join(labels),
        encoding="utf-8",
    )


def write_index(out_dir: Path, unit_meta: dict[str, dict]) -> None:
    rows: list[str] = []
    rows.append("<!DOCTYPE html><html><head><meta charset='utf-8'>")
    rows.append("<title>HoMM3 battle animation interpolation comparison</title>")
    rows.append(
        "<style>body{font-family:system-ui,sans-serif;background:#111;color:#eee;margin:1.5rem}"
        "h1,h2{color:#fff}table{border-collapse:collapse;width:100%;margin:1rem 0}"
        "td,th{border:1px solid #333;padding:.5rem;vertical-align:top}"
        "th{background:#222}img{max-width:320px;height:auto;background:#000;border:1px solid #444}"
        ".label{font-size:.85rem;color:#aaa;max-width:320px}code{color:#9cf}</style></head><body>"
    )
    rows.append("<h1>HoMM3 battle animation interpolation comparison</h1>")
    rows.append(
        "<p>Generated from <code>homm3_lab/*/extracted_battle</code> DEF frames. "
        f"Baseline matches shipped flip-book timing ({FPS_SHIPPED} FPS). "
        "Open GIFs in a browser; loop is enabled for idle/walk.</p>"
    )
    for unit_sid, display in UNITS:
        rows.append(f"<h2>{display} (<code>{unit_sid}</code>)</h2>")
        if unit_sid in unit_meta:
            m = unit_meta[unit_sid]
            rows.append(
                f"<p>Manifest: <code>{m.get('manifest', '?')}</code>. "
                f"Group frame counts: {m.get('group_counts', '')}</p>"
            )
        for clip_name, _gid, _loop in CLIPS:
            rows.append(f"<h3>{clip_name}</h3><table><tr><th>Method</th><th>Preview</th></tr>")
            clip_dir = out_dir / unit_sid / clip_name
            if not clip_dir.is_dir():
                continue
            gifs = sorted(clip_dir.glob("*.gif"))
            for gif in gifs:
                rel = gif.relative_to(out_dir).as_posix()
                label_path = gif.with_suffix(".txt")
                label = label_path.read_text(encoding="utf-8").strip() if label_path.is_file() else gif.stem
                for _name, desc, _fn in METHODS:
                    if gif.stem == _name:
                        label = desc
                        break
                if gif.stem == "09_attack_all_melee_directions":
                    label = "All melee attack directions (11+12+13) vs shipped front-only"
                if gif.stem == "08_walk_group1_unused":
                    label = WALK_ALT_METHOD[1]
                rows.append(
                    f"<tr><td class='label'><strong>{gif.stem}</strong><br>{label}</td>"
                    f"<td><img src='{rel}' alt='{gif.stem}' loading='lazy'></td></tr>"
                )
            rows.append("</table>")
    rows.append("</body></html>")
    (out_dir / "index.html").write_text("\n".join(rows), encoding="utf-8")


def summarize_groups(manifest: dict) -> str:
    bits: list[str] = []
    for sequence in manifest.get("sequences") or []:
        gid = sequence.get("group")
        frames = sequence.get("frames") or []
        n = len([f for f in frames if str(f or "").strip()])
        if n:
            bits.append(f"{gid}:{n}")
    return ", ".join(bits)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--units", nargs="*", default=[u[0] for u in UNITS])
    args = parser.parse_args()
    out_dir = repo_path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    unit_meta: dict[str, dict] = {}
    readme_lines = [
        "# HoMM3 animation interpolation comparison",
        "",
        f"Output folder: `{out_dir}`",
        "",
        "Open **index.html** in a browser to compare methods.",
        "",
        "## Units",
    ]

    for unit_sid, display in UNITS:
        if unit_sid not in args.units:
            continue
        manifest_path, manifest = load_manifest(unit_sid)
        battle_dir = manifest_path.parent
        unit_meta[unit_sid] = {
            "manifest": str(manifest_path.relative_to(REPO_ROOT)),
            "group_counts": summarize_groups(manifest),
        }
        readme_lines.append(f"- **{display}** (`{unit_sid}`): {unit_meta[unit_sid]['group_counts']}")

        for clip_name, group_id, loop in CLIPS:
            rel = group_frame_paths(manifest, group_id)
            if not rel:
                continue
            frames = normalize_frames(load_group_frames(battle_dir, rel))
            clip_out = out_dir / unit_sid / clip_name
            for method_name, desc, fn in METHODS:
                seq, ms = fn(frames, loop)
                gif_path = clip_out / f"{method_name}.gif"
                write_gif(gif_path, seq, ms, loop)
                (clip_out / f"{method_name}.txt").write_text(desc, encoding="utf-8")

        build_walk_alt(unit_sid, battle_dir, manifest, out_dir)
        if (group_frame_paths(manifest, GROUP_MOUSEOVER)):
            desc = WALK_ALT_METHOD[1]
            (out_dir / unit_sid / "walk" / f"{WALK_ALT_METHOD[0]}.txt").write_text(
                desc, encoding="utf-8"
            )

        build_attack_direction_comparison(unit_sid, battle_dir, manifest, out_dir)

    write_index(out_dir, unit_meta)
    readme_lines.extend(
        [
            "",
            "## Methods",
            "",
        ]
    )
    for method_name, desc, _fn in METHODS:
        readme_lines.append(f"- `{method_name}`: {desc}")
    readme_lines.append(f"- `{WALK_ALT_METHOD[0]}`: {WALK_ALT_METHOD[1]}")
    readme_lines.append("- `09_attack_all_melee_directions`: groups 11+12+13 concatenated")
    (out_dir / "README.md").write_text("\n".join(readme_lines) + "\n", encoding="utf-8")
    print(f"Wrote comparisons to {out_dir}")
    print(f"Open {out_dir / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
