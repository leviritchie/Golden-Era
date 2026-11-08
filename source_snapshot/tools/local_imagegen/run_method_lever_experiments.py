#!/usr/bin/env python3
"""Run the six methodological-lever experiments for collapse-authentic upscale.

Levers:
  1. staged_scale     — 4x then 4x instead of one 16x jump
  2. hybrid_lanes     — SD3.5 ↔ SD1.5 Tile in both orders
  3. split_control    — ESRGAN/lanczos init + blurred Tile hint
  4. sd3_controlnet   — InstantX SD3 Tile on SD3.5 Medium (experimental)
  5. style_adapter    — RetroCGI strength / prompt-only contrasts on soft Tile
  6. scoring_policy   — collapse auth + anti-block / detail proxies together

Writes candidates under artifacts/collapse_authentic_upscale/candidates/lever_*
and a combined report at artifacts/collapse_authentic_upscale/reports/method_levers.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent.parent
CAND = ROOT / "artifacts" / "collapse_authentic_upscale" / "candidates"
ORIG = ROOT / "artifacts" / "collapse_authentic_upscale" / "original" / "h3_wood_elf.png"
REPORTS = ROOT / "artifacts" / "collapse_authentic_upscale" / "reports"
VERIFY = ROOT / "tools" / "verify_upscale_collapse_authenticity.py"
SD15 = ROOT / "tools" / "local_imagegen" / "comfy_exact_img2img.py"
SD35 = ROOT / "tools" / "local_imagegen" / "comfy_exact_img2img_sd35.py"

POS = (
    "late 1990s pre-rendered 3D CGI character portrait, Heroes of Might and Magic III "
    "Rampart wood elf archer, soft era CGI shading, plastic 90s render materials, "
    "profile facing right drawing bow, blonde hair pointed ear green tunic red glove, "
    "wooden fort background, not hand-painted, not oil painting, not photoreal modern, not anime"
)
NEG = (
    "pixel art, mosaic, nearest neighbor blocks, hand-painted, oil painting, illustration, "
    "watercolor, anime, photoreal skin pores, modern CGI, text, watermark, logo"
)
W, H = 928, 1024


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=str(ROOT))


def sd15(out: Path, image: Path, **kw) -> None:
    cmd = [
        sys.executable,
        str(SD15),
        "--image",
        str(image),
        "--out",
        str(out),
        "--width",
        str(kw.get("width", W)),
        "--height",
        str(kw.get("height", H)),
        "--positive",
        kw.get("positive", POS),
        "--negative",
        kw.get("negative", NEG),
        "--denoise",
        str(kw.get("denoise", 0.4)),
        "--seed",
        str(kw.get("seed", 7)),
        "--steps",
        str(kw.get("steps", 28)),
        "--cfg",
        str(kw.get("cfg", 4.5)),
        "--filename-prefix",
        kw.get("prefix", "lever_sd15"),
    ]
    if kw.get("tile", True):
        cmd.append("--controlnet-tile")
        cmd += ["--controlnet-strength", str(kw.get("tile_strength", 0.7))]
        cmd += ["--controlnet-end", str(kw.get("tile_end", 1.0))]
    if kw.get("lora"):
        cmd.append("--lora")
        cmd += ["--lora-strength", str(kw["lora"])]
    if kw.get("control_blur_radius"):
        cmd += ["--control-blur-radius", str(kw["control_blur_radius"])]
        cmd += ["--control-blur-sigma", str(kw.get("control_blur_sigma", 1.5))]
    if kw.get("init_upscale_model"):
        cmd += ["--init-upscale-model", kw["init_upscale_model"]]
    run(cmd)


def sd35(out: Path, image: Path, **kw) -> None:
    cmd = [
        sys.executable,
        str(SD35),
        "--image",
        str(image),
        "--out",
        str(out),
        "--width",
        str(kw.get("width", W)),
        "--height",
        str(kw.get("height", H)),
        "--positive",
        kw.get("positive", POS),
        "--negative",
        kw.get("negative", NEG),
        "--denoise",
        str(kw.get("denoise", 0.4)),
        "--seed",
        str(kw.get("seed", 7)),
        "--steps",
        str(kw.get("steps", 28)),
        "--cfg",
        str(kw.get("cfg", 4.5)),
        "--filename-prefix",
        kw.get("prefix", "lever_sd35"),
    ]
    if kw.get("tile"):
        cmd.append("--controlnet-tile")
        cmd += ["--controlnet-strength", str(kw.get("tile_strength", 0.7))]
        cmd += ["--controlnet-end", str(kw.get("tile_end", 0.85))]
        if kw.get("control_blur_radius"):
            cmd += ["--control-blur-radius", str(kw["control_blur_radius"])]
    run(cmd)


def perceptual_proxies(path: Path, block: int = 16) -> dict:
    im = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    gx = np.abs(im[:, 1:] - im[:, :-1]).mean()
    gy = np.abs(im[1:, :] - im[:-1, :]).mean()
    h, w, _ = im.shape
    block_vars = []
    for y in range(0, h - block + 1, block):
        for x in range(0, w - block + 1, block):
            block_vars.append(im[y : y + block, x : x + block].reshape(-1, 3).var(axis=0).mean())
    bv = np.asarray(block_vars, dtype=np.float32)
    # Higher within-block variance => less NN-locked. Soft CGI usually lands mid-high.
    return {
        "edge_energy": float((gx + gy) / 2.0),
        "within_block_var": float(bv.mean()),
        "flat_block_frac": float((bv < 1.0).mean()),
        "detail_proxy": float(min(1.0, bv.mean() / 250.0)),  # ~lanczos baseline ≈1.0
        "anti_block_proxy": float(1.0 - (bv < 1.0).mean()),
    }


def score_candidates(paths: list[Path]) -> dict[str, dict]:
    if not paths:
        return {}
    out_json = REPORTS / "_tmp_lever_scores.json"
    cmd = [
        sys.executable,
        str(VERIFY),
        "--original",
        str(ORIG),
        "--json-out",
        str(out_json),
        "--out-dir",
        str(REPORTS.parent),
    ]
    for p in paths:
        cmd += ["--candidate", str(p)]
    run(cmd)
    ranked = json.loads(out_json.read_text(encoding="utf-8"))["ranked"]
    by_name = {Path(r["candidate"]).name: r for r in ranked}
    merged = {}
    for p in paths:
        auth = by_name[p.name]
        prox = perceptual_proxies(p)
        # Combined: keep collapse authenticity, but penalize flat NN blocks.
        combined = 0.65 * float(auth["authenticity_score"]) + 0.35 * prox["anti_block_proxy"] * (
            0.5 + 0.5 * prox["detail_proxy"]
        )
        merged[p.name] = {
            "path": str(p),
            "authenticity_score": float(auth["authenticity_score"]),
            "global_mae_rgb": float(auth["global_mae_rgb"]),
            "region_pass_soft_frac": float(auth["region_pass_soft_frac"]),
            **prox,
            "combined_cgi_collapse_score": float(combined),
        }
    return merged


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--only",
        nargs="*",
        default=None,
        help="Optional subset: staged hybrid split sd3cn style scoring",
    )
    args = ap.parse_args()
    only = set(args.only) if args.only else None

    CAND.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    results: dict = {"schema": "local_imagegen.method_levers.v1", "levers": {}}

    def want(name: str) -> bool:
        return only is None or name in only

    # ---- 1. Staged scale (SD1.5 soft Tile): 4x -> 4x ----
    if want("staged"):
        mid = CAND / "lever_staged_mid_232x256.png"
        final = CAND / "lever_staged_final_928x1024.png"
        # 58*4=232, 64*4=256 — multiples of 8
        sd15(mid, ORIG, width=232, height=256, denoise=0.42, tile_strength=0.7, seed=7, prefix="lever_staged_mid")
        sd15(final, mid, width=W, height=H, denoise=0.35, tile_strength=0.7, seed=7, prefix="lever_staged_final")
        results["levers"]["staged_scale"] = {
            "description": "SD1.5 soft Tile 4x then 4x",
            "candidates": [str(mid), str(final)],
        }

    # ---- 2. Hybrid lanes ----
    if want("hybrid"):
        # Need a soft SD3.5 seed; reuse existing d040 if present else generate.
        sd35_base = CAND / "sd35_soft_d040_seed7.png"
        if not sd35_base.is_file():
            sd35(sd35_base, ORIG, denoise=0.4, seed=7, prefix="lever_hybrid_sd35")
        a = CAND / "lever_hybrid_sd35_then_sd15tile.png"
        b = CAND / "lever_hybrid_sd15tile_then_sd35.png"
        sd15_base = CAND / "lever_hybrid_sd15_soft_tile.png"
        sd15(sd15_base, ORIG, denoise=0.4, tile_strength=0.7, seed=7, prefix="lever_hybrid_sd15")
        sd15(a, sd35_base, denoise=0.35, tile_strength=0.75, tile_end=0.85, seed=7, prefix="lever_hyb_a")
        sd35(b, sd15_base, denoise=0.35, seed=7, prefix="lever_hyb_b")
        results["levers"]["hybrid_lanes"] = {
            "description": "SD3.5→SD1.5 Tile and SD1.5 Tile→SD3.5",
            "candidates": [str(a), str(b), str(sd15_base)],
        }

    # ---- 3. Split init vs control ----
    if want("split"):
        blur = CAND / "lever_split_blur_control.png"
        esrgan = CAND / "lever_split_esrgan_init_blur_control.png"
        early = CAND / "lever_split_tile_end075.png"
        sd15(
            blur,
            ORIG,
            denoise=0.42,
            tile_strength=0.7,
            control_blur_radius=3,
            control_blur_sigma=1.5,
            seed=7,
            prefix="lever_split_blur",
        )
        sd15(
            esrgan,
            ORIG,
            denoise=0.4,
            tile_strength=0.65,
            control_blur_radius=2,
            control_blur_sigma=1.2,
            init_upscale_model="RealESRGAN_x4plus.pth",
            seed=7,
            prefix="lever_split_esrgan",
        )
        sd15(
            early,
            ORIG,
            denoise=0.42,
            tile_strength=0.7,
            tile_end=0.75,
            seed=7,
            prefix="lever_split_end",
        )
        results["levers"]["split_control"] = {
            "description": "Blurred Tile hint; ESRGAN init+blur; Tile end_percent=0.75",
            "candidates": [str(blur), str(esrgan), str(early)],
        }

    # ---- 4. SD3 ControlNet Tile ----
    if want("sd3cn"):
        cn = Path(r"V:/ml/ComfyUI/models/controlnet/sd3_controlnet_tile_instantx.safetensors")
        out = CAND / "lever_sd3cn_tile_d045.png"
        status = {"description": "InstantX SD3 Tile on SD3.5 Medium", "candidates": []}
        if not cn.is_file():
            status["error"] = f"missing {cn}"
            status["proof"] = "skipped — ControlNet weights not on disk"
        else:
            try:
                sd35(
                    out,
                    ORIG,
                    denoise=0.45,
                    tile=True,
                    tile_strength=0.7,
                    tile_end=0.85,
                    control_blur_radius=2,
                    seed=7,
                    prefix="lever_sd3cn",
                )
                status["candidates"] = [str(out)]
                status["proof"] = "local generation smoke"
            except subprocess.CalledProcessError as exc:
                status["error"] = f"ComfyUI job failed ({exc.returncode})"
                status["proof"] = "attempted; InstantX SD3 Tile may be incompatible with SD3.5 Medium"
        results["levers"]["sd3_controlnet"] = status

    # ---- 5. Style adapter ----
    if want("style"):
        no_lora = CAND / "lever_style_soft_tile_no_lora.png"
        l050 = CAND / "lever_style_soft_tile_lora050.png"
        l085 = CAND / "lever_style_soft_tile_lora085.png"
        l100 = CAND / "lever_style_soft_tile_lora100.png"
        sd15(no_lora, ORIG, denoise=0.4, tile_strength=0.7, seed=7, prefix="lever_style_nolora")
        sd15(l050, ORIG, denoise=0.4, tile_strength=0.7, lora=0.5, seed=7, prefix="lever_style_l050")
        sd15(l085, ORIG, denoise=0.4, tile_strength=0.7, lora=0.85, seed=7, prefix="lever_style_l085")
        sd15(l100, ORIG, denoise=0.4, tile_strength=0.7, lora=1.0, seed=7, prefix="lever_style_l100")
        results["levers"]["style_adapter"] = {
            "description": "Soft Tile RetroCGI strength sweep (no dedicated HoMM3 LoRA yet)",
            "candidates": [str(no_lora), str(l050), str(l085), str(l100)],
            "note": "True HoMM3/CGI LoRA training remains future work; this measures adapter strength only.",
        }

    # ---- 6. Scoring policy over everything produced ----
    if want("scoring") or only is None:
        # Collect all lever_*.png plus useful baselines if present.
        paths = sorted(CAND.glob("lever_*.png"))
        for extra in [
            "sd35_soft_d040_seed7.png",
            "tile_soft_s075_d040_seed7.png",
            "_baseline_lanczos_x16.png",
        ]:
            p = CAND / extra
            if p.is_file():
                paths.append(p)
        # unique preserve order
        seen = set()
        uniq = []
        for p in paths:
            if p.name not in seen:
                seen.add(p.name)
                uniq.append(p)
        scores = score_candidates(uniq)
        ranked = sorted(scores.values(), key=lambda r: r["combined_cgi_collapse_score"], reverse=True)
        results["levers"]["scoring_policy"] = {
            "description": "combined = 0.65*collapse_auth + 0.35*anti_block*detail_proxy",
            "ranked": ranked,
        }
        results["scores"] = scores

    out = REPORTS / "method_levers.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps({"wrote": str(out), "lever_keys": list(results["levers"].keys())}, indent=2))

    # Human-readable summary
    if "scores" in results:
        print("\nTop by combined_cgi_collapse_score:")
        for row in results["levers"]["scoring_policy"]["ranked"][:12]:
            name = Path(row["path"]).name
            print(
                f"  {name:48s}  combined={row['combined_cgi_collapse_score']:.3f}  "
                f"auth={row['authenticity_score']:.3f}  flat={row['flat_block_frac']:.3f}  "
                f"detail={row['detail_proxy']:.3f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
