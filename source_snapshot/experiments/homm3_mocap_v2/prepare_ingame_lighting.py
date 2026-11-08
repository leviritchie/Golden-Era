"""Prepare the existing solved-light texture bake for explicit mocap test delivery.

Animation is never taken from a lighting cache. Cache reuse requires byte-identical
engine-material geometry and a baked image embedded in the recorded prebaked GLB.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
sys.path.insert(0, str(TOOL))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from asset_profiles import get_profile, profile_mesh
from gpu_cascade_delivery import glb_basecolor_image_payload
from showcase_prebaked_clip import bake_lit_texture, write_engine_material_glb
from oe_lighting_style import redistribute_energy, _bake_cycles_cuda, write_glb_with_basecolor


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(row: dict, out: Path, prepare_only: bool = False, reuse_prepared: bool = False,
            *, style_profile: str = "baseline", solution_root: Path | None = None,
            solve_only: bool = False) -> dict:
    if solve_only and (style_profile != "baseline" or prepare_only or reuse_prepared):
        raise ValueError("solve-only requires baseline and cannot combine with prepare-only or reuse-prepared")
    if style_profile == "approved-oe-v1":
        return prepare_styled(row, out, prepare_only=prepare_only,
                              reuse_prepared=reuse_prepared, solution_root=solution_root)
    if style_profile != "baseline":
        raise ValueError(f"unknown lighting style {style_profile!r}")
    started = time.perf_counter()
    sid = row["labSid"]
    source = profile_mesh(get_profile(row["assetId"])).resolve()
    if sha(ROOT / row["sourceReport"]) != row["sourceReportSha256"]:
        raise ValueError(f"{sid}: selected source report changed")
    unit = out / "units" / sid
    unit.mkdir(parents=True, exist_ok=True)
    engine = unit / f"{sid}_engine_material.glb"
    material = write_engine_material_glb(source, engine)
    existing = unit / "lighting_manifest.json"
    if reuse_prepared:
        record = json.loads(existing.read_text(encoding="utf-8"))
        if (record["sourceSha256"] != sha(source) or record["engineMaterialSha256"] != sha(engine)
                or record["bakedTextureSha256"] != sha(Path(record["bakedTexture"]))):
            raise ValueError(f"{sid}: prepared lighting content changed")
        evidence = record.get("freshSolve") if not record["verifiedLightingCache"] else record["cacheEvidence"]
        if sha(Path(evidence["solution"])) != evidence["solutionSha256"]:
            raise ValueError(f"{sid}: prepared light solution changed")
        corpus = ROOT / row["corpus"]
        if corpus.is_file() and sha(corpus) != row["corpusSha256"]:
            raise ValueError(f"{sid}: selected corpus changed")
        if "freshSolve" in record and record["freshSolve"]["corpusSha256"] != row["corpusSha256"]:
            raise ValueError(f"{sid}: prepared bake used another corpus")
        record.update({key: row[key] for key in ("sourceReport", "sourceReportSha256", "corpus", "corpusSha256")})
        record["verifiedReuseSeconds"] = time.perf_counter() - started
        existing.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        return record
    old = ROOT / "artifacts/prebaked_continuous_stronghold_rollout/units" / sid
    old_engine = old / engine.name
    old_bake = old / "baked_lit.png"
    old_prebaked = old / f"{sid}_prebaked.glb"
    old_solution = ROOT / "artifacts/pose_picker_runs" / sid / "light_palette_solve_blackbody/light_solution.json"
    cache = all(p.is_file() for p in (old_engine, old_bake, old_prebaked, old_solution))
    if cache:
        cache = sha(engine) == sha(old_engine)
    if cache:
        solution = json.loads(old_solution.read_text(encoding="utf-8"))
        cache = Path(solution["glb"]).resolve() == old_engine.resolve()
    if cache:
        payload = glb_basecolor_image_payload(old_prebaked)
        # The image helper returns the embedded bytes together with MIME metadata.
        embedded = payload[0]
        cache = hashlib.sha256(embedded).hexdigest() == sha(old_bake)
    record = {
        "labSid": sid, "source": str(source), "sourceSha256": sha(source),
        "engineMaterial": material, "engineMaterialSha256": sha(engine),
        "verifiedLightingCache": bool(cache), "pbrNeutralized": True,
        "animationAuthority": "none; lighting stage only",
        "sourceReport": row["sourceReport"], "sourceReportSha256": row["sourceReportSha256"],
        "corpus": row["corpus"], "corpusSha256": row["corpusSha256"],
    }
    if prepare_only:
        return record
    baked = unit / "baked_lit.png"
    if cache:
        if not solve_only:
            shutil.copy2(old_bake, baked)
        record["cacheEvidence"] = {
            "engineMaterial": str(old_engine), "prebakedGlb": str(old_prebaked),
            "prebakedGlbSha256": sha(old_prebaked), "solution": str(old_solution),
            "solutionSha256": sha(old_solution),
        }
    else:
        # Sprite identity is taken from the current mocap corpus, not old tracker paths.
        corpus_path = ROOT / row["corpus"]
        if not corpus_path.is_file():
            raise ValueError(f"{sid}: no verified light cache and corpus is not a file: {corpus_path}")
        if sha(corpus_path) != row["corpusSha256"]:
            raise ValueError(f"{sid}: selected corpus changed")
        corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
        source_frames = corpus["sourceFrames"]
        if not source_frames:
            raise ValueError(f"{sid}: empty source frame set")
        sprites = unit / "light_source_frames"
        sprites.mkdir(exist_ok=True)
        for index, (filename, evidence) in enumerate(source_frames.items()):
            frame = Path(filename)
            if not frame.is_absolute():
                frame = corpus_path.parent / frame
            if sha(frame) != evidence["sha256"]:
                raise ValueError(f"{sid}: source sprite changed: {frame}")
            shutil.copy2(frame, sprites / f"{index:04d}.png")
        light_dir = unit / "light_palette_solve_blackbody"
        light_dir.mkdir(exist_ok=True)
        print(f"{sid}: solving lighting on verified corpus sprites", flush=True)
        command = [sys.executable, str(TOOL / "solve_unit_light_palette.py"),
                   "--unit", sid, "--glb", str(engine), "--sprite-dir", str(sprites),
                   "--out", str(light_dir), "--light-model", "blackbody"]
        with (light_dir / "solve.log").open("w", encoding="utf-8") as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=1800, check=True)
        solution_path = light_dir / "light_solution.json"
        if not solve_only:
            print(f"{sid}: baking solved lighting", flush=True)
            bake_lit_texture(engine, solution_path, baked)
        record["freshSolve"] = {"corpus": str(corpus_path), "corpusSha256": sha(corpus_path),
                                "sourceFrameCount": len(source_frames), "solution": str(solution_path),
                                "solutionSha256": sha(solution_path)}
    if solve_only:
        record["rawSolutionOnly"] = True
    else:
        record.update({"bakedTexture": str(baked), "bakedTextureSha256": sha(baked)})
    record["elapsedSeconds"] = time.perf_counter() - started
    (unit / "lighting_manifest.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def validate_styled_lighting(record: dict) -> None:
    """Validate approved-profile provenance independently of unit quality acceptance."""
    if record.get("styleProfile") != "approved-oe-v1":
        raise ValueError("lighting does not declare approved-oe-v1")
    for path_key, hash_key in (("source", "sourceSha256"),
                               ("bakedTexture", "bakedTextureSha256")):
        if sha(Path(record[path_key])) != record[hash_key]:
            raise ValueError(f"styled lighting {path_key} changed")
    evidence = record["approvedStyle"]
    for key in ("sourceManifest", "rawSolution", "matteEngine", "styledSolution"):
        if sha(Path(evidence[key])) != evidence[key + "Sha256"]:
            raise ValueError(f"styled lighting {key} changed")
    engine = Path(record["engineMaterial"]["output"])
    if sha(engine) != record["engineMaterialSha256"]:
        raise ValueError("styled lighting engine changed")
    baseline = json.loads(Path(evidence["sourceManifest"]).read_text(encoding="utf-8"))
    keys = [k for k in ("freshSolve", "cacheEvidence") if k in baseline]
    if (len(keys) != 1 or baseline.get("styleProfile", "baseline") != "baseline"
            or baseline["sourceSha256"] != record["sourceSha256"]
            or baseline["engineMaterialSha256"] != record["engineMaterialSha256"]):
        raise ValueError("styled lighting source manifest identity mismatch")
    source_evidence = baseline[keys[0]]
    if (Path(source_evidence["solution"]).resolve() != Path(evidence["rawSolution"]).resolve()
            or source_evidence["solutionSha256"] != evidence["rawSolutionSha256"]):
        raise ValueError("styled lighting raw solve is not the pinned source solve")
    raw = json.loads(Path(evidence["rawSolution"]).read_text(encoding="utf-8"))
    if "oeStyle" in raw:
        raise ValueError("raw solution must not already be styled")
    expected = redistribute_energy(raw, glb=Path(evidence["matteEngine"]))
    actual = json.loads(Path(evidence["styledSolution"]).read_text(encoding="utf-8"))
    if actual != expected or evidence["parameters"] != expected["oeStyle"]:
        raise ValueError("styled solution differs from approved profile")


def prepare_styled(row: dict, out: Path, *, prepare_only: bool,
                   reuse_prepared: bool, solution_root: Path | None) -> dict:
    """Reuse only a pinned raw solve, never its baseline baked pixels."""
    started = time.perf_counter()
    if prepare_only and reuse_prepared:
        raise ValueError("prepare-only and reuse-prepared are mutually exclusive")
    sid = row["labSid"]
    unit = out / "units" / sid
    manifest_path = unit / "lighting_manifest.json"
    if sha(ROOT / row["sourceReport"]) != row["sourceReportSha256"]:
        raise ValueError(f"{sid}: selected source report changed")
    source = profile_mesh(get_profile(row["assetId"])).resolve()
    if reuse_prepared:
        record = json.loads(manifest_path.read_text(encoding="utf-8"))
        validate_styled_lighting(record)
        if record["source"] != str(source) or any(record[k] != row[k] for k in
                ("sourceReport", "sourceReportSha256", "corpus", "corpusSha256")):
            raise ValueError(f"{sid}: prepared lighting belongs to a different selection")
        return record
    if solution_root is None:
        raise ValueError("approved-oe-v1 requires explicit --solution-root with pinned raw solves")
    source_manifest = solution_root.resolve() / "units" / sid / "lighting_manifest.json"
    if source_manifest.resolve() == manifest_path.resolve():
        raise ValueError("styled output must be separate from raw solution rollout")
    baseline = json.loads(source_manifest.read_text(encoding="utf-8"))
    keys = [k for k in ("freshSolve", "cacheEvidence") if k in baseline]
    if len(keys) != 1 or baseline.get("styleProfile", "baseline") != "baseline":
        raise ValueError(f"{sid}: expected exactly one baseline raw-solve evidence block")
    evidence = baseline[keys[0]]
    raw_path = Path(evidence["solution"])
    if sha(raw_path) != evidence["solutionSha256"] or sha(source) != baseline["sourceSha256"]:
        raise ValueError(f"{sid}: raw solution or source hash changed")
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    if "oeStyle" in raw:
        raise ValueError(f"{sid}: refusing double-applied lighting style")
    if keys[0] == "freshSolve" and evidence["corpusSha256"] != row["corpusSha256"]:
        raise ValueError(f"{sid}: raw solve belongs to another corpus")
    unit.mkdir(parents=True, exist_ok=True)
    engine = unit / f"{sid}_engine_material.glb"
    material = write_engine_material_glb(source, engine)
    if sha(engine) != baseline["engineMaterialSha256"]:
        raise ValueError(f"{sid}: raw solve engine identity mismatch")
    if sha(Path(raw["glb"])) != sha(engine):
        raise ValueError(f"{sid}: raw solution mesh identity mismatch")
    albedo = unit / "source_albedo.png"
    albedo.write_bytes(glb_basecolor_image_payload(engine)[0])
    matte = unit / "matte_engine_material.glb"
    write_glb_with_basecolor(engine, matte, albedo, neutralize_pbr=True)
    styled = redistribute_energy(raw, glb=matte)
    styled_path = unit / "styled_solution.json"
    styled_path.write_text(json.dumps(styled, indent=2) + "\n", encoding="utf-8")
    record = {"labSid": sid, "source": str(source), "sourceSha256": sha(source),
              "engineMaterial": material, "engineMaterialSha256": sha(engine),
              "styleProfile": "approved-oe-v1", "verifiedLightingCache": False,
              "pbrNeutralized": True, "animationAuthority": "none; lighting stage only",
              "approvedStyle": {"parameters": styled["oeStyle"],
                                "visualProfileAccepted": True, "unitQualityAccepted": False}}
    record.update({k: row[k] for k in ("sourceReport", "sourceReportSha256", "corpus", "corpusSha256")})
    for key, path in (("sourceManifest", source_manifest), ("rawSolution", raw_path),
                      ("matteEngine", matte), ("styledSolution", styled_path)):
        record["approvedStyle"].update({key: str(path.resolve()), key + "Sha256": sha(path)})
    if prepare_only:
        return record
    baked = unit / "baked_lit.png"
    bake_started = time.perf_counter()
    _bake_cycles_cuda(matte, styled_path, baked, timeout_s=300)
    record["bakeSeconds"] = time.perf_counter() - bake_started
    record.update({"bakedTexture": str(baked.resolve()), "bakedTextureSha256": sha(baked)})
    validate_styled_lighting(record)
    record["elapsedSeconds"] = time.perf_counter() - started
    manifest_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, default=ROOT / "experiments/homm3_mocap_v2/stronghold_ingame_test.json")
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/homm3_mocap_v2/stronghold_ingame_test_v1")
    parser.add_argument("--units", default="")
    parser.add_argument("--style-profile", choices=("baseline", "approved-oe-v1"), default="baseline")
    parser.add_argument("--solution-root", type=Path, help="Explicit raw-solve rollout for approved style; any faction")
    parser.add_argument("--solve-only", action="store_true", help="Record a pinned baseline raw light solve without baking; input for approved style")
    parser.add_argument("--prepare-only", action="store_true", help="Write engine material and inspect cache; do not bake textures")
    parser.add_argument("--reuse-prepared", action="store_true", help="Require and verify this rollout's prepared textures; no new solve")
    args = parser.parse_args()
    rows = json.loads(args.selection.read_text(encoding="utf-8"))["units"]
    wanted = set(args.units.split(",")) if args.units else None
    for row in rows:
        if wanted is not None and row["labSid"] not in wanted:
            continue
        result = prepare(row, args.out.resolve(), args.prepare_only, args.reuse_prepared,
                         style_profile=args.style_profile, solution_root=args.solution_root,
                         solve_only=args.solve_only)
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
