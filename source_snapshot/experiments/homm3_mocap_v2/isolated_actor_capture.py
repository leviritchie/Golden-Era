"""Actor-isolated capture/control comparison on a shared fixed canvas.

Each manifest contains the same authored clip keys (idle, move, frontattack)
and may contain a different alpha-isolated plate.  No vendor per-frame crop or
recenter is used: DINO receives a fixed full-canvas window with center-crop off.
"""
from __future__ import annotations
import argparse, json, shutil, time
from pathlib import Path
import numpy as np
from capture_skin_corpus import _sha, validate_manifest
from intermediate_capture import run_capture
from dino_embed import encode_frames
from model_runner import load_model
from pin import sha256_files
from paths import REPO
from run_mocap_baseline import _gpu_lock_waiting
from vendor_reference import load_complete_package, package_paths

CLIPS = ("g02_idle", "g00_move", "g12_attack_front")
MOUNT_REF = "Coyote#Coyote-Attack1/y0"
RIDER_REF = "00160523-f3b6-5765-931a-351e339862d7#00160523-f3b6-5765-931a-351e339862d7/y0"

def _prov(kind, ref, package):
    paths = package_paths(kind, ref)
    return {"kind": kind, "refSeq": ref, "packageSha256": sha256_files([paths[k] for k in ("bvh", "pose", "train", "speciesInfo", "scaleCache")]), "jointCount": int(package["jointCount"]), "jointNames": list(package["jointNames"])}

def _load(path):
    value = validate_manifest(json.loads(path.read_text(encoding="utf-8")))
    wanted = {c["key"] for c in value["clips"]}
    if wanted != set(CLIPS):
        raise ValueError(f"manifest must contain exactly {CLIPS}")
    return value

def _fingerprint(path):
    p = Path(path)
    return (p.name, p.stat().st_size)

def _timeline(manifest):
    return {c["key"]: tuple(tuple((Path(p).parent.name, Path(p).name) for p in c[field])
        for field in ("contextBefore", "frames", "contextAfter")) for c in manifest["clips"]}

def capture_isolated(mount_manifest, rider_manifest, control_manifest, output, *, device="cuda"):
    started = time.perf_counter()
    if output.exists(): raise FileExistsError(f"refusing to overwrite output: {output}")
    manifests = {"isolated": {"mount": _load(mount_manifest), "rider": _load(rider_manifest)}, "control": {"mount": _load(control_manifest), "rider": _load(control_manifest)}}
    packages = {"mount": ("zoo", MOUNT_REF, load_complete_package("zoo", MOUNT_REF)), "rider": ("obj", RIDER_REF, load_complete_package("obj", RIDER_REF))}
    for condition in manifests.values():
        for key in CLIPS:
            if len(_timeline(condition["mount"])[key]) != len(_timeline(condition["rider"])[key]):
                raise ValueError(f"mount/rider timeline differs for {key}")
    base_timeline = _timeline(manifests["control"]["mount"])
    for condition in manifests.values():
        for actor in condition.values():
            if _timeline(actor) != base_timeline:
                raise ValueError("control and isolated context lengths differ")
    output.mkdir(parents=True)
    all_paths = []
    for condition in manifests.values():
        for actor in condition.values():
            all_paths += [Path(actor["idle"])] + [Path(p) for c in actor["clips"] for p in c["contextBefore"] + c["frames"] + c["contextAfter"]]
    unique = list(dict.fromkeys(all_paths)); canvas = None
    from PIL import Image
    for path in unique:
        size = Image.open(path).size
        canvas = canvas or size
        if size != canvas: raise ValueError("all actor/control plates must share one canvas")
    results = []
    import torch
    with _gpu_lock_waiting(REPO):
        encode_started = time.perf_counter()
        embed, preprocess = encode_frames(unique, device=device, canvas=canvas, window={"bboxXyxy": [0, 0, canvas[0], canvas[1]], "paddingRatio": 0.0, "bg": [1.0, 1.0, 1.0], "canvas": list(canvas)}, preprocess_policy="clip_locked_union_alpha_aabb", do_center_crop=False, dino_dtype="float16", encoder_input_dir=output / "encoder_cache")
        encode_seconds = time.perf_counter() - encode_started
        model = load_model(torch.device(device))[0]
        for condition, actors in manifests.items():
            for actor, (kind, ref, package) in packages.items():
                src = actors[actor]; actor_dir = output / condition / actor; actor_dir.mkdir(parents=True)
                rows = []
                for clip in src["clips"]:
                    if clip["key"] not in CLIPS: continue
                    paths = [Path(p) for p in clip["contextBefore"] + clip["frames"] + clip["contextAfter"]]; frame_dir = actor_dir / clip["key"] / "frames"; frame_dir.mkdir(parents=True)
                    for i, p in enumerate(paths): shutil.copy2(p, frame_dir / f"{i:06d}.png")
                    indices = [unique.index(p) for p in paths]
                    report = run_capture(package=package, frames_dir=frame_dir, out_dir=actor_dir / clip["key"] / "capture", image_embed=embed[indices], preprocess_meta=preprocess, model=model, source_kind=f"{condition}_actor_fixed_canvas", title=clip["key"], compare_gt=False)
                    print(f"captured {condition}/{actor}/{clip['key']}", flush=True)
                    raw = actor_dir / clip["key"] / "capture" / "raw_capture.npz"; start = len(clip["contextBefore"])
                    rows.append({"key": clip["key"], "frames": [str(p) for p in paths[start:start + len(clip["frames"])]], "capture": str(raw.resolve()), "captureSha256": _sha(raw), "sourceIndices": list(range(start, start + len(clip["frames"]))), "referenceIndex": 0, "contextBeforeCount": start, "contextAfterCount": len(clip["contextAfter"]), "report": report})
                manifest_path = control_manifest if condition == "control" else (mount_manifest if actor == "mount" else rider_manifest)
                corpus = {"schema": "homm3.skin-corpus.v1", "unit": f"{src['unit']}_{condition}_{actor}", "manifest": str(manifest_path.resolve()), "manifestSha256": _sha(manifest_path), "sourceFrames": {str(p): {"sha256": _sha(p)} for p in unique}, "package": _prov(kind, ref, package), "preprocess": preprocess, "captures": rows, "captureCondition": "fixed_canvas_actor_isolated" if condition == "isolated" else "fixed_canvas_full_plate_control"}
                path = actor_dir / "corpus.json"; path.write_text(json.dumps(corpus, indent=2), encoding="utf-8"); results.append({"unit": corpus["unit"], "path": str(path.resolve()), "sha256": _sha(path)})
    summary = {"schema": "homm3.isolated-actor-capture.v1", "fixedCanvas": list(canvas), "clips": list(CLIPS), "corpora": results,
               "encodeSeconds": encode_seconds, "elapsedSeconds": time.perf_counter()-started}
    (output / "isolated_actor_capture.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary

def main():
    p = argparse.ArgumentParser(); p.add_argument("--mount-manifest", type=Path, required=True); p.add_argument("--rider-manifest", type=Path, required=True); p.add_argument("--control-manifest", type=Path, required=True); p.add_argument("--output", type=Path, required=True); a = p.parse_args(); print(json.dumps(capture_isolated(a.mount_manifest, a.rider_manifest, a.control_manifest, a.output), indent=2))

if __name__ == "__main__": main()
