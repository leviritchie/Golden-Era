"""Render a saved skin-weight candidate; never trains or overwrites diagnostics."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import numpy as np
import torch
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path: sys.path.insert(0, str(HERE))
from paths import SOURCE_FRAME_MS
from run_shape_preserved import CAPTURE_BY_CASE, _load_frozen_prep, _write_json
from run_skin_weight_pilot import SkinImageRenderer, deformed_candidates, skin_with, prepare_motion, digest
from gpu_cascade_batch_lock import cascade_batch_lock


def render(pilot_dir: Path, output: Path, resolution: int = 192) -> dict[str, str]:
    if output.exists():
        raise FileExistsError(f"refusing to overwrite diagnostic output: {output}")
    freeze, skin = _load_frozen_prep("h3_roc")
    weights = np.asarray(np.load(pilot_dir / "candidate_weights.npz", allow_pickle=False)["weights"], dtype=np.float32)
    if weights.shape != skin["weights"].shape or not np.isfinite(weights).all():
        raise ValueError("candidate weights do not match frozen skin")
    camera = json.loads((pilot_dir / "camera.json").read_text(encoding="utf-8"))
    calibration_path = Path(freeze["preparationDir"]).parents[1] / "calibration/idle_reference_v1.json"
    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    reference = np.asarray(calibration["referencePositions"], dtype=np.float64)
    report = json.loads((pilot_dir / "pilot_report.json").read_text(encoding="utf-8"))
    # Use a genuine 90-degree yaw off the registered view, then fit one camera
    # to the union of every before/after frame rather than refitting per frame.
    def yaw90(value):
        out = dict(value)
        rot = np.asarray(((0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (-1.0, 0.0, 0.0)))
        out["right"] = (rot @ np.asarray(value["right"])).tolist()
        out["down"] = (rot @ np.asarray(value["down"])).tolist()
        out["forward"] = (rot @ np.asarray(value["forward"])).tolist()
        out["yawDeg"] = float(value.get("yawDeg", 0.0)) + 90.0
        return out
    camera = yaw90(camera)
    output.mkdir(parents=True)
    written = {}
    with cascade_batch_lock(Path(__file__).resolve().parents[2]):
      original = torch.as_tensor(skin["weights"], device="cuda", dtype=torch.float32)
      candidate = torch.as_tensor(weights, device="cuda", dtype=torch.float32)
      meshes = {}
      for case in CAPTURE_BY_CASE:
        motion = prepare_motion(skin, reference, case)
        if digest(motion["jointWorld"]) != report["cases"][case]["fixedMotionSha256"]:
            raise ValueError("saved candidate motion changed")
        candidates = deformed_candidates(skin, motion)
        meshes[case] = (skin_with(candidates, original), skin_with(candidates, candidate))
      points = np.concatenate([value.cpu().numpy().reshape(-1, 3) for pair in meshes.values() for value in pair])
      projected = points @ np.asarray([camera["right"], camera["down"], camera["forward"]]).T
      low, high = projected.min(axis=0), projected.max(axis=0)
      center = (low + high) / 2
      camera["scale"] = float((resolution - 1) * .85 / max(high[:2] - low[:2]))
      camera["offset"] = ((resolution - 1) / 2 - center[:2] * camera["scale"]).tolist()
      camera["depth_center"] = float(center[2])
      camera["depth_span"] = float(max(high[2] - low[2], 1e-3) * 1.1)
      _write_json(output / "diagnostic_camera.json", camera)
      renderer = SkinImageRenderer(skin["triangles"], skin["uvs"], skin["albedo"], camera, resolution)
      for case, pair in meshes.items():
        with torch.no_grad():
            before = renderer.render(pair[0])[0].cpu().numpy()
            after = renderer.render(pair[1])[0].cpu().numpy()
        frames = []
        for index in range(len(before)):
            row = Image.new("RGB", (resolution * 2, resolution + 28), (12, 12, 16))
            ImageDraw.Draw(row).text((4, 2), f"{case} off-axis fixed camera f{index:02d}", fill="white")
            for col, (label, image) in enumerate((("Frozen skin", before[index]), ("Candidate", after[index]))):
                panel = Image.fromarray(np.uint8(np.clip(image, 0, 1) * 255))
                row.paste(panel, (col * resolution, 28))
                ImageDraw.Draw(row).text((col * resolution + 4, 12), label, fill="white")
            frames.append(row)
        path = output / f"{case}_original_vs_candidate.gif"
        frames[0].save(path, save_all=True, append_images=frames[1:], duration=max(1, int(round(SOURCE_FRAME_MS))), loop=0)
        selected = np.linspace(0, len(frames) - 1, 4).astype(int)
        sheet = Image.new("RGB", (resolution * 2, (resolution + 28) * 4))
        for row, index in enumerate(selected):
            sheet.paste(frames[index], (0, row * (resolution + 28)))
        sheet.save(path.with_suffix(".png"))
        written[case] = str(path)
    return written


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pilot-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resolution", type=int, default=192)
    args = parser.parse_args()
    print(json.dumps(render(args.pilot_dir, args.output, args.resolution), indent=2))


if __name__ == "__main__":
    main()
