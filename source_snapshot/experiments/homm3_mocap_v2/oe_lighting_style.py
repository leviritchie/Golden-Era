"""Generate an explicitly separate, gentler OE-style lighting candidate.

This module never edits the verified rollout. It reuses a hash-pinned engine
material and light solution, creates a separate neutral matte bake material,
changes only the key/flood balance, and invokes the existing Blender bake.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
sys.path.insert(0, str(TOOL))
from gpu_cascade_delivery import glb_basecolor_image_payload
from showcase_prebaked_clip import BAKE_MARGIN_PX, BAKE_SAMPLES, BAKE_SIZE, BLENDER, write_glb_with_basecolor

DEFAULT_KEY_SCALE = 0.65
DEFAULT_FLOOD_SCALE = 1.35


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_comparison(baseline: Path, candidate: Path, out: Path) -> None:
    """Make a neutral side-by-side preview; pixel values are not rescaled."""
    from PIL import Image, ImageDraw

    left = Image.open(baseline).convert("RGB")
    right = Image.open(candidate).convert("RGB")
    if left.size != right.size:
        raise ValueError(f"comparison images have different sizes: {left.size} vs {right.size}")
    sheet = Image.new("RGB", (left.width * 2, left.height + 28), (32, 32, 32))
    sheet.paste(left, (0, 28))
    sheet.paste(right, (left.width, 28))
    draw = ImageDraw.Draw(sheet)
    draw.text((8, 8), "baseline", fill=(255, 255, 255))
    draw.text((left.width + 8, 8), "oe-soft", fill=(255, 255, 255))
    sheet.save(out)


def _bake_cycles_cuda(glb: Path, solution: Path, out_png: Path, *, timeout_s: int) -> None:
    """Invoke the existing bake script on Cycles CUDA. CPU Cycles is forbidden."""
    if not Path(BLENDER).is_file():
        raise FileNotFoundError(BLENDER)
    script = TOOL / "showcase_prebaked_clip.py"
    completed = subprocess.run(
        [str(BLENDER), "-b", "--python", str(script), "--",
         "--glb", str(glb.resolve()), "--solution", str(solution.resolve()),
         "--out-png", str(out_png.resolve()), "--size", str(BAKE_SIZE), "--samples", str(BAKE_SAMPLES)],
        text=True, capture_output=True, timeout=timeout_s,
        env={**os.environ, "BLENDER_USER_CONFIG": str(ROOT / ".blender_oe_style_config")},
    )
    if completed.returncode != 0 or not out_png.is_file():
        raise RuntimeError(f"matte bake failed ({completed.returncode})\n{completed.stdout[-3000:]}\n{completed.stderr[-3000:]}")


def soften_solution(solution: dict[str, Any], *, key_scale: float = DEFAULT_KEY_SCALE,
                    flood_scale: float = DEFAULT_FLOOD_SCALE, glb: Path | None = None) -> dict[str, Any]:
    """Copy a solved solution and rebalance strengths without changing colour."""
    key_scale = float(key_scale)
    flood_scale = float(flood_scale)
    if not (math.isfinite(key_scale) and math.isfinite(flood_scale)
            and 0.0 < key_scale <= 1.0 and flood_scale >= 1.0):
        raise ValueError("key_scale must be in (0,1] and flood_scale must be >= 1")
    out = json.loads(json.dumps(solution))
    for name, scale in (("keyLight", key_scale), ("floodLight", flood_scale)):
        row = out.get(name)
        if not isinstance(row, dict) or not isinstance(row.get("strength"), (int, float)):
            raise ValueError(f"solution missing finite {name}.strength")
        source_strength = float(row["strength"])
        if not math.isfinite(source_strength) or source_strength <= 0.0:
            raise ValueError(f"{name}.strength must be finite and positive")
        value = source_strength * scale
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(f"{name}.strength became non-positive")
        row["strength"] = value
    out["oeStyle"] = {
        "schema": "oe-gentler-lighting-v1",
        "keyStrengthScale": float(key_scale),
        "floodStrengthScale": float(flood_scale),
        "colourPolicy": "preserve-solved-linear-colours",
        "glossPolicy": "matte dielectric; no metallic/specular extensions; combined bake retains dielectric BRDF",
    }
    if glb is not None:
        # The solved source may be the immutable pre-bake mesh; the candidate
        # must explicitly bind the same solution to this rollout's byte-identical mesh.
        out["glb"] = str(Path(glb).resolve())
    return out


def redistribute_energy(solution: dict[str, Any], *, key_scale: float = 0.60,
                        fill_fraction: float = 0.25, glb: Path | None = None) -> dict[str, Any]:
    """Reduce the key and move a bounded fraction of its radiance into world fill."""
    key_scale = float(key_scale)
    fill_fraction = float(fill_fraction)
    if not (math.isfinite(key_scale) and math.isfinite(fill_fraction)
            and 0.0 < key_scale <= 1.0 and 0.0 <= fill_fraction <= 1.0):
        raise ValueError("energy redistribution parameters are not finite or in range")
    out = json.loads(json.dumps(solution))
    key = out.get("keyLight")
    flood = out.get("floodLight")
    if not isinstance(key, dict) or not isinstance(flood, dict):
        raise ValueError("solution requires keyLight and floodLight")
    key_strength = float(key.get("strength")); flood_strength = float(flood.get("strength"))
    key_rgb = [float(x) for x in key.get("colorLinear", [])]
    flood_rgb = [float(x) for x in flood.get("colorLinear", [])]
    if (len(key_rgb) != 3 or len(flood_rgb) != 3 or key_strength <= 0.0 or flood_strength <= 0.0
            or any(x < 0.0 for x in [*key_rgb, *flood_rgb])
            or not all(math.isfinite(x) for x in [key_strength, flood_strength, *key_rgb, *flood_rgb])):
        raise ValueError("non-finite or malformed light solution")
    added = [(1.0 - key_scale) * key_strength * c * fill_fraction for c in key_rgb]
    world = [flood_strength * c + a for c, a in zip(flood_rgb, added)]
    new_flood = max(world)
    if not math.isfinite(new_flood) or new_flood <= 0.0:
        raise ValueError("redistributed world energy is invalid")
    key["strength"] = key_strength * key_scale
    flood["strength"] = new_flood
    flood["colorLinear"] = [v / new_flood for v in world]
    flood.pop("kelvin", None)
    flood.pop("colorSrgbHex", None)
    out["oeStyle"] = {"schema": "oe-gentler-lighting-v3", "profile": "energy-redistributed",
                       "keyStrengthScale": key_scale, "fillFraction": fill_fraction,
                       "colourPolicy": "preserve-key-colour; recompute-world-rgb",
                       "glossPolicy": "matte dielectric; no metallic/specular extensions; combined bake retains dielectric BRDF"}
    if glb is not None:
        out["glb"] = str(Path(glb).resolve())
    return out


def build_variant(manifest_path: Path, output_root: Path, *, key_scale: float = DEFAULT_KEY_SCALE,
                  flood_scale: float = DEFAULT_FLOOD_SCALE, timeout_s: int = 3600,
                  profile: str = "soft-key-fill") -> dict[str, Any]:
    """Bake one unit into a new output directory, refusing existing output."""
    started = time.perf_counter()
    manifest_path = Path(manifest_path).resolve()
    output_root = Path(output_root).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sid = str(manifest["labSid"])
    engine_ref = manifest["engineMaterial"]["output"] if isinstance(manifest["engineMaterial"], dict) else manifest["engineMaterial"]
    if not Path(engine_ref).is_absolute():
        raise ValueError(f"{sid}: engine material path must be absolute")
    engine = Path(engine_ref)
    evidence_keys = [key for key in ("freshSolve", "cacheEvidence") if key in manifest]
    if len(evidence_keys) != 1:
        raise ValueError(f"{sid}: lighting manifest must contain exactly one solution evidence block")
    evidence = manifest[evidence_keys[0]]
    solution_ref = evidence["solution"]
    if not Path(solution_ref).is_absolute():
        raise ValueError(f"{sid}: solution path must be absolute")
    solution = Path(solution_ref)
    if not engine.is_file() or not solution.is_file():
        raise FileNotFoundError(f"{sid}: verified engine or solution is missing")
    expected_engine = manifest["engineMaterialSha256"]
    if sha(engine) != expected_engine:
        raise ValueError(f"{sid}: engine material hash changed")
    if sha(solution) != evidence["solutionSha256"]:
        raise ValueError(f"{sid}: solution hash changed")
    if not Path(manifest["bakedTexture"]).is_absolute():
        raise ValueError(f"{sid}: baseline texture path must be absolute")
    baseline = Path(manifest["bakedTexture"])
    if sha(baseline) != manifest["bakedTextureSha256"]:
        raise ValueError(f"{sid}: baseline baked texture hash changed")
    unit = output_root / "lighting" / sid
    if unit.exists():
        raise FileExistsError(unit)
    unit.mkdir(parents=True)
    # Extract the current albedo and create a new matte GLB before baking. This
    # is deliberately not the delivery GLB and leaves the verified rollout intact.
    albedo_png = unit / "source_albedo.png"
    albedo_png.write_bytes(glb_basecolor_image_payload(engine)[0])
    matte_engine = unit / "matte_engine_material.glb"
    write_glb_with_basecolor(engine, matte_engine, albedo_png, neutralize_pbr=True)
    if profile == "soft-key-fill":
        soft = soften_solution(json.loads(solution.read_text(encoding="utf-8")), key_scale=key_scale,
                               flood_scale=flood_scale, glb=matte_engine)
    elif profile == "energy-redistributed":
        soft = redistribute_energy(json.loads(solution.read_text(encoding="utf-8")), glb=matte_engine)
    else:
        raise ValueError(f"unknown lighting profile {profile!r}")
    soft_path = unit / "soft_solution.json"
    soft_path.write_text(json.dumps(soft, indent=2) + "\n", encoding="utf-8")
    baked = unit / "soft_baked_lit.png"
    _bake_cycles_cuda(matte_engine, soft_path, baked, timeout_s=timeout_s)
    comparison = unit / "baseline_vs_oe_soft.png"
    _write_comparison(baseline, baked, comparison)
    report = {
        "schema": "oe-gentler-lighting-report-v2", "labSid": sid,
        "sourceLightingManifest": str(manifest_path.resolve()),
        "sourceLightingManifestSha256": sha(manifest_path),
        "engineMaterial": str(engine), "engineMaterialSha256": sha(engine),
        "matteEngineMaterial": str(matte_engine), "matteEngineMaterialSha256": sha(matte_engine),
        "sourceSolution": str(solution), "sourceSolutionSha256": sha(solution),
        "softSolution": str(soft_path), "softSolutionSha256": sha(soft_path),
        "bakedTexture": str(baked), "bakedTextureSha256": sha(baked),
        "baselineTexture": str(baseline), "baselineTextureSha256": sha(baseline),
        "comparisonPreview": str(comparison), "comparisonPreviewSha256": sha(comparison),
        "parameters": soft["oeStyle"], "accepted": False,
        "note": "diagnostic style candidate; baseline delivery is unchanged",
        "matteBake": {"sourceAlbedo": str(albedo_png), "roughness": 1.0, "metallic": 0.0,
                      "normal": "flat", "bakePass": "COMBINED with neutral matte material",
                      "cpuThreads": 8},
        "elapsedSeconds": time.perf_counter() - started,
    }
    (unit / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rollout", type=Path, required=True)
    parser.add_argument("--units", nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", choices=("soft-key-fill", "energy-redistributed"), required=True)
    parser.add_argument("--key-scale", type=float, default=DEFAULT_KEY_SCALE)
    parser.add_argument("--flood-scale", type=float, default=DEFAULT_FLOOD_SCALE)
    args = parser.parse_args()
    for sid in args.units:
        report = build_variant(args.rollout / "units" / sid / "lighting_manifest.json", args.output,
                               key_scale=args.key_scale, flood_scale=args.flood_scale, profile=args.profile)
        print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
