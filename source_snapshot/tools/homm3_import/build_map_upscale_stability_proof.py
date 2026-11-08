#!/usr/bin/env python3
"""Build a browser proof for deterministic adventure-map sprite upscaling.

This is an offline diagnostic artifact. It reads current `extracted_map` PNG
cycles and emits per-method 2x PNG sequences plus a browser viewer that plays
all methods from the same frame clock so temporal shimmer is easy to compare.
"""
from __future__ import annotations

import json
import math
import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter


REPO_ROOT = Path(__file__).resolve().parents[2]
LAB_ROOT = REPO_ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_lab"
OUT_ROOT = REPO_ROOT / "experiments/homm3_map_upscale_stability_proof"

SOURCE_FPS = 10
SCALE = 2


@dataclass(frozen=True)
class UnitSpec:
    sid: str
    title: str
    manifest: str


UNITS = (
    UnitSpec("toa_goblin_trapper", "Goblin Trapper", "lvl1alt.json"),
    UnitSpec("h3_infernal_troglodyte", "Infernal Troglodyte", "AvWInfr.json"),
)


METHODS = (
    ("nearest_2x", "Nearest 2x", "Integer preserve; sharp but blocky.", Image.Resampling.NEAREST),
    ("bilinear_2x", "Bilinear 2x", "Cheap linear filtering; softens small details.", Image.Resampling.BILINEAR),
    ("lanczos_2x", "Lanczos 2x", "Higher-quality static resize; can ring on hard edges.", Image.Resampling.LANCZOS),
)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def resolve_frame_path(map_dir: Path, rel: str) -> Path:
    rel_norm = rel.replace("\\", "/")
    direct = map_dir / rel_norm
    if direct.is_file():
        return direct
    parts = rel_norm.split("/")
    if len(parts) == 2:
        want_dir, want_file = parts
        for child in map_dir.iterdir():
            if child.is_dir() and child.name.lower() == want_dir.lower():
                candidate = child / want_file
                if candidate.is_file():
                    return candidate
                for png in child.glob("*.png"):
                    if png.name.lower() == want_file.lower():
                        return png
    return direct


def group_zero_frames(manifest: dict) -> list[str]:
    for sequence in manifest.get("sequences") or []:
        if int(sequence.get("group", -1)) == 0:
            return [str(f) for f in sequence.get("frames") or [] if str(f).strip()]
    raise ValueError("manifest has no group 0 map cycle")


def normalize_frames(frames: list[Image.Image]) -> list[Image.Image]:
    max_w = max(frame.width for frame in frames)
    max_h = max(frame.height for frame in frames)
    normalized: list[Image.Image] = []
    for frame in frames:
        rgba = frame.convert("RGBA")
        if rgba.size == (max_w, max_h):
            normalized.append(rgba)
            continue
        canvas = Image.new("RGBA", (max_w, max_h), (0, 0, 0, 0))
        canvas.paste(rgba, (0, 0), rgba)
        normalized.append(canvas)
    return normalized


def load_unit_frames(unit: UnitSpec) -> tuple[Path, list[Image.Image]]:
    map_dir = LAB_ROOT / unit.sid / "extracted_map"
    manifest = read_json(map_dir / unit.manifest)
    paths = [resolve_frame_path(map_dir, rel) for rel in group_zero_frames(manifest)]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(missing[0])
    return map_dir, normalize_frames([Image.open(path).convert("RGBA") for path in paths])


def premultiplied_lanczos(frame: Image.Image) -> Image.Image:
    rgba = np.asarray(frame.convert("RGBA"), dtype=np.float32) / 255.0
    alpha = rgba[:, :, 3:4]
    premul = rgba[:, :, :3] * alpha
    premul_u8 = np.clip(np.concatenate([premul, alpha], axis=2) * 255.0, 0, 255).astype(np.uint8)
    resized = Image.fromarray(premul_u8, "RGBA").resize(
        (frame.width * SCALE, frame.height * SCALE),
        Image.Resampling.LANCZOS,
    )
    arr = np.asarray(resized, dtype=np.float32) / 255.0
    out_alpha = arr[:, :, 3:4]
    out_rgb = np.divide(
        arr[:, :, :3],
        np.maximum(out_alpha, 1.0 / 255.0),
        out=np.zeros_like(arr[:, :, :3]),
        where=out_alpha > 0,
    )
    out = np.clip(np.concatenate([out_rgb, out_alpha], axis=2) * 255.0, 0, 255).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def edge_bleed_lanczos(frame: Image.Image) -> Image.Image:
    rgba = frame.convert("RGBA")
    alpha = rgba.getchannel("A")
    color = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    color.paste(rgba, (0, 0), alpha)
    bleed = color
    mask = alpha
    for _ in range(5):
        blurred = bleed.filter(ImageFilter.MaxFilter(3))
        grown = mask.filter(ImageFilter.MaxFilter(3))
        bleed = Image.composite(blurred, bleed, Image.eval(mask, lambda v: 255 if v == 0 else 0))
        mask = grown
    bleed.putalpha(alpha)
    return premultiplied_lanczos(bleed)


def resize_method(frame: Image.Image, method_id: str, resampling: Image.Resampling | None = None) -> Image.Image:
    if method_id == "premultiplied_lanczos_2x":
        return premultiplied_lanczos(frame)
    if method_id == "edge_bleed_lanczos_2x":
        return edge_bleed_lanczos(frame)
    if resampling is None:
        raise ValueError(method_id)
    return frame.resize((frame.width * SCALE, frame.height * SCALE), resampling)


def composite_gray(frame: Image.Image) -> np.ndarray:
    rgba = np.asarray(frame.convert("RGBA"), dtype=np.float32)
    alpha = rgba[:, :, 3:4] / 255.0
    rgb = rgba[:, :, :3] * alpha + 96.0 * (1.0 - alpha)
    return rgb


def temporal_metrics(frames: list[Image.Image]) -> dict[str, float]:
    if len(frames) < 2:
        return {"mean_delta": 0.0, "p95_delta": 0.0, "delta_cv": 0.0, "alpha_edge_delta": 0.0}
    means: list[float] = []
    p95s: list[float] = []
    edge_means: list[float] = []
    prev_rgb = composite_gray(frames[0])
    prev_a = np.asarray(frames[0].getchannel("A"), dtype=np.float32)
    for frame in frames[1:] + frames[:1]:
        rgb = composite_gray(frame)
        alpha = np.asarray(frame.getchannel("A"), dtype=np.float32)
        diff = np.abs(rgb - prev_rgb).mean(axis=2)
        means.append(float(diff.mean()))
        p95s.append(float(np.percentile(diff, 95)))
        edge_means.append(float(np.abs(alpha - prev_a).mean()))
        prev_rgb = rgb
        prev_a = alpha
    mean_delta = float(np.mean(means))
    return {
        "mean_delta": round(mean_delta, 4),
        "p95_delta": round(float(np.mean(p95s)), 4),
        "delta_cv": round(float(np.std(means) / mean_delta), 4) if mean_delta > 0 else 0.0,
        "alpha_edge_delta": round(float(np.mean(edge_means)), 4),
    }


def save_sequence(unit_dir: Path, method_id: str, frames: list[Image.Image]) -> list[str]:
    seq_dir = unit_dir / method_id
    if seq_dir.exists():
        shutil.rmtree(seq_dir)
    seq_dir.mkdir(parents=True)
    rels: list[str] = []
    for i, frame in enumerate(frames):
        path = seq_dir / f"{i:04d}.png"
        frame.save(path)
        rels.append(path.relative_to(OUT_ROOT).as_posix())
    return rels


def build_unit(unit: UnitSpec) -> dict:
    map_dir, source_frames = load_unit_frames(unit)
    unit_dir = OUT_ROOT / unit.sid
    unit_dir.mkdir(parents=True, exist_ok=True)

    methods: list[dict] = []
    native_rels = save_sequence(unit_dir, "native", source_frames)
    methods.append(
        {
            "id": "native",
            "title": "Native source",
            "description": "Original extracted map frames, drawn 2x in browser with image smoothing disabled.",
            "frames": native_rels,
            "naturalScale": 1,
            "metrics": temporal_metrics(source_frames),
        }
    )

    for method_id, title, description, resampling in METHODS:
        resized = [resize_method(frame, method_id, resampling) for frame in source_frames]
        methods.append(
            {
                "id": method_id,
                "title": title,
                "description": description,
                "frames": save_sequence(unit_dir, method_id, resized),
                "naturalScale": SCALE,
                "metrics": temporal_metrics(resized),
            }
        )

    for method_id, title, description in (
        (
            "premultiplied_lanczos_2x",
            "Premultiplied Lanczos 2x",
            "Lanczos over premultiplied color/alpha to reduce transparent-edge color shimmer.",
        ),
        (
            "edge_bleed_lanczos_2x",
            "Edge-Bleed Lanczos 2x",
            "Color bleed into transparent pixels before premultiplied Lanczos; strongest halo control.",
        ),
    ):
        resized = [resize_method(frame, method_id) for frame in source_frames]
        methods.append(
            {
                "id": method_id,
                "title": title,
                "description": description,
                "frames": save_sequence(unit_dir, method_id, resized),
                "naturalScale": SCALE,
                "metrics": temporal_metrics(resized),
            }
        )

    return {
        "sid": unit.sid,
        "title": unit.title,
        "source": str(map_dir.relative_to(REPO_ROOT)).replace("\\", "/"),
        "fps": SOURCE_FPS,
        "frameCount": len(source_frames),
        "sourceSize": [source_frames[0].width, source_frames[0].height],
        "methods": methods,
    }


def write_viewer(payload: dict) -> None:
    data_js = "const PROOF_DATA = " + json.dumps(payload, indent=2) + ";\n"
    (OUT_ROOT / "proof-data.js").write_text(data_js, encoding="utf-8")
    html = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HoMM3 Map Upscale Stability Proof</title>
<style>
:root{color-scheme:light;--ink:#172018;--muted:#5d675f;--line:#c8d0c7;--panel:#f4f6f1;--accent:#2d6b3f;--warn:#8c4b17}
*{box-sizing:border-box}body{margin:0;background:#fbfbf7;color:var(--ink);font:14px/1.45 system-ui,Segoe UI,sans-serif}
header{padding:18px 22px;border-bottom:1px solid var(--line);background:#eef3ea;position:sticky;top:0;z-index:3}
h1{margin:0 0 8px;font-size:22px;letter-spacing:0}p{margin:0;color:var(--muted);max-width:1100px}
.controls{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-top:14px}.controls button,.controls select{height:34px;border:1px solid var(--line);background:#fff;border-radius:6px;padding:0 10px;color:var(--ink)}.controls button{min-width:38px}.controls label{display:flex;align-items:center;gap:7px;color:var(--ink)}
main{padding:18px 22px 28px}.unit{margin-bottom:28px}.unit h2{font-size:18px;margin:0 0 4px}.source{color:var(--muted);margin-bottom:12px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}.card{border:1px solid var(--line);background:#fff;border-radius:8px;overflow:hidden}.card header{position:static;background:#fff;border-bottom:1px solid var(--line);padding:10px 12px}.card h3{font-size:15px;margin:0}.desc{font-size:12px;color:var(--muted);min-height:35px;margin-top:3px}
.stage{height:260px;display:grid;place-items:center;background:repeating-conic-gradient(#dde3dc 0 25%,#f8faf6 0 50%) 50%/24px 24px;border-bottom:1px solid var(--line);overflow:hidden}.stage.black{background:#242822}.stage.white{background:#fff}.stage.gray{background:#90978e}
canvas{max-width:96%;max-height:244px}.pixelated{image-rendering:pixelated}.smooth{image-rendering:auto}
.metrics{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1px;background:var(--line);font-size:12px}.metric{background:var(--panel);padding:7px 9px}.metric b{display:block;color:var(--ink);font-size:13px}.metric span{color:var(--muted)}
.strip{height:54px;display:flex;gap:2px;align-items:center;overflow:hidden;background:#eef1ec;padding:5px;border-top:1px solid var(--line)}.strip img{height:44px;width:auto;object-fit:contain;background:#fff;border:1px solid #d0d6cf}
.note{margin:16px 0;padding:10px 12px;border-left:4px solid var(--accent);background:#eef6ef;color:#314035}.warn{border-left-color:var(--warn);background:#fff3e8}
</style>
</head>
<body>
<header>
<h1>HoMM3 Adventure-Map Upscale Stability Proof</h1>
<p>All cards use the same source frame clock. The stability metrics measure composited frame-to-frame delta; lower coefficient of variation means the method changes more evenly across the loop.</p>
<div class="controls">
<button id="play">Pause</button>
<button id="prev">&lsaquo;</button>
<button id="next">&rsaquo;</button>
<label>Unit <select id="unitSelect"></select></label>
<label>FPS <input id="fps" type="range" min="2" max="24" value="10"><span id="fpsLabel">10</span></label>
<label>Background <select id="bg"><option value="">checker</option><option value="white">white</option><option value="gray">gray</option><option value="black">black</option></select></label>
<label><input id="smoothNative" type="checkbox"> browser smoothing on native</label>
<span id="frameLabel"></span>
</div>
</header>
<main id="app"></main>
<script src="proof-data.js"></script>
<script>
const app=document.getElementById('app');const unitSelect=document.getElementById('unitSelect');const fpsSlider=document.getElementById('fps');const fpsLabel=document.getElementById('fpsLabel');const frameLabel=document.getElementById('frameLabel');const bg=document.getElementById('bg');const smoothNative=document.getElementById('smoothNative');
let unitIndex=0, frame=0, playing=true, last=0, loaded=new Map();
for(let i=0;i<PROOF_DATA.units.length;i++){const o=document.createElement('option');o.value=i;o.textContent=PROOF_DATA.units[i].title;unitSelect.appendChild(o)}
function imgFor(src){if(!loaded.has(src)){const img=new Image();img.src=src;loaded.set(src,img)}return loaded.get(src)}
function renderUnit(){const unit=PROOF_DATA.units[unitIndex];app.innerHTML='';const section=document.createElement('section');section.className='unit';section.innerHTML=`<h2>${unit.title}</h2><div class="source">${unit.sid} &middot; ${unit.frameCount} frames @ ${unit.fps} FPS &middot; source ${unit.sourceSize[0]}&times;${unit.sourceSize[1]} &middot; ${unit.source}</div><div class="note">Inspect for frame-to-frame sparkle on outlines, weapons, and shadow edges. Use black/white/gray backgrounds to expose alpha halos.</div><div class="grid"></div><div class="note warn">This proof does not run Unity lighting or fog. It isolates the source-frame upscale question for the adventure-map array pipeline.</div>`;app.appendChild(section);const grid=section.querySelector('.grid');for(const method of unit.methods){const card=document.createElement('article');card.className='card';card.innerHTML=`<header><h3>${method.title}</h3><div class="desc">${method.description}</div></header><div class="stage"><canvas width="1" height="1"></canvas></div><div class="metrics"><div class="metric"><b>${method.metrics.mean_delta}</b><span>mean delta</span></div><div class="metric"><b>${method.metrics.p95_delta}</b><span>p95 delta</span></div><div class="metric"><b>${method.metrics.delta_cv}</b><span>delta CV</span></div><div class="metric"><b>${method.metrics.alpha_edge_delta}</b><span>alpha delta</span></div></div><div class="strip"></div>`;grid.appendChild(card);const strip=card.querySelector('.strip');const step=Math.max(1,Math.floor(method.frames.length/10));for(let i=0;i<method.frames.length;i+=step){const im=document.createElement('img');im.src=method.frames[i];strip.appendChild(im)}}frame=0;draw()}
function draw(){const unit=PROOF_DATA.units[unitIndex];const stages=document.querySelectorAll('.stage');document.querySelectorAll('.card').forEach((card,i)=>{const method=unit.methods[i];const canvas=card.querySelector('canvas');const ctx=canvas.getContext('2d');const img=imgFor(method.frames[frame%method.frames.length]);if(!img.complete)return;canvas.width=img.naturalWidth;canvas.height=img.naturalHeight;canvas.className=(method.id==='native'&&!smoothNative.checked)?'pixelated':'smooth';ctx.clearRect(0,0,canvas.width,canvas.height);ctx.imageSmoothingEnabled=method.id!=='native'||smoothNative.checked;ctx.drawImage(img,0,0)});stages.forEach(s=>{s.className='stage '+bg.value});frameLabel.textContent=`Frame ${(frame%unit.frameCount)+1} / ${unit.frameCount}`}
function tick(ts){const fps=Number(fpsSlider.value);if(playing&&ts-last>1000/fps){frame=(frame+1)%PROOF_DATA.units[unitIndex].frameCount;last=ts;draw()}requestAnimationFrame(tick)}
document.getElementById('play').onclick=e=>{playing=!playing;e.target.textContent=playing?'Pause':'Play'};document.getElementById('prev').onclick=()=>{const u=PROOF_DATA.units[unitIndex];frame=(frame+u.frameCount-1)%u.frameCount;draw()};document.getElementById('next').onclick=()=>{const u=PROOF_DATA.units[unitIndex];frame=(frame+1)%u.frameCount;draw()};unitSelect.onchange=e=>{unitIndex=Number(e.target.value);renderUnit()};fpsSlider.oninput=()=>{fpsLabel.textContent=fpsSlider.value};bg.onchange=draw;smoothNative.onchange=draw;
renderUnit();requestAnimationFrame(tick);
</script>
</body>
</html>
"""
    (OUT_ROOT / "index.html").write_text(html, encoding="utf-8")
    readme = f"""# HoMM3 map upscale stability proof

Open `index.html` in a browser. This is an offline diagnostic gallery for source
upscaling adventure-map unit frames before they enter the map Texture2DArray path.

Units:
- `toa_goblin_trapper`
- `h3_infernal_troglodyte`

Methods:
- native source, rendered 2x in browser
- nearest 2x
- bilinear 2x
- Lanczos 2x
- premultiplied Lanczos 2x
- edge-bleed premultiplied Lanczos 2x

Metrics are computed from composited frame-to-frame deltas at {SOURCE_FPS} FPS.
"""
    (OUT_ROOT / "README.md").write_text(readme, encoding="utf-8")


def main() -> int:
    if OUT_ROOT.exists():
        shutil.rmtree(OUT_ROOT)
    OUT_ROOT.mkdir(parents=True)
    units = [build_unit(unit) for unit in UNITS]
    payload = {
        "sourceFps": SOURCE_FPS,
        "scale": SCALE,
        "units": units,
    }
    write_viewer(payload)
    print(OUT_ROOT / "index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
