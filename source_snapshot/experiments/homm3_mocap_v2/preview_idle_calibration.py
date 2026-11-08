"""Cached CPU before/after comparison; never overwrites outputs or preparation."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageOps

EXPERIMENT = Path(__file__).resolve().parent
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))

from donor_eagle import compute_rest_joints, skin_dense
from eagle_preview import _mesh
from evaluation import EVALUATION_CASES
from idle_calibration import load_or_create
from paths import SOURCE_FRAME_MS
from pin import numbered_pngs
from reconstruct_adapted import reconstruct_adapted
from run_shape_preserved import (
    CAPTURE_BY_CASE, IDLE_CALIBRATION_VERSION, _load_frozen_prep,
    asset_dir, get_profile, load_saved_capture, load_shape_donor,
)
from shared_camera import freeze_shared_camera


def render_case(case: str, output: Path, width: int = 256) -> dict[str, str]:
    if output.exists():
        raise FileExistsError(f"diagnostic output already exists: {output}")
    if width < 256:
        raise ValueError("panel width must be at least 256")
    freeze, skin = _load_frozen_prep("h3_roc")
    profile = get_profile("h3_roc")
    donor = load_shape_donor(profile)
    capture = load_saved_capture(CAPTURE_BY_CASE[case], donor)["pred_position"]
    calibration_path = asset_dir("h3_roc") / "calibration" / f"{IDLE_CALIBRATION_VERSION}.json"
    if not calibration_path.is_file():
        raise FileNotFoundError("Run calibrated motion before this comparison diagnostic")
    reference = load_or_create(
        calibration_path=calibration_path,
        capture_path=CAPTURE_BY_CASE["roc_attack"],
        reference_png=numbered_pngs(EVALUATION_CASES["roc_attack"].frames)[0],
        known_idle_png=EVALUATION_CASES["roc_attack"].idle,
        research_skin=Path(freeze["researchSkin"]),
        capture_positions=load_saved_capture(CAPTURE_BY_CASE["roc_attack"], donor)["pred_position"],
        names=skin["names"], parents=skin["parents"],
    )["referencePositions"]
    common = dict(
        capture_positions=capture, capture_offsets=skin["captureOffsets"],
        fitted_offsets=skin["offsets"], parents=skin["parents"],
        names=skin["names"], hub_names=tuple(profile["wholeBodyHubs"]),
    )
    meshes = []
    for anchor in (compute_rest_joints(skin["captureOffsets"], skin["parents"]), reference):
        result = reconstruct_adapted(capture_reference_positions=anchor, **common)
        meshes.append(np.asarray([
            skin_dense(skin["vertices"], skin["weights"], world, skin["inverseBind"])
            for world in result["jointWorld"]
        ]))
    meshes.append(skin["vertices"][None])
    cameras = freeze_shared_camera(
        np.concatenate([mesh.reshape(-1, 3) for mesh in meshes]),
        width=width, height=width, space="targetBindSpace",
    )
    sprites = numbered_pngs(EVALUATION_CASES[case].frames)
    if len(sprites) != len(capture):
        raise ValueError("source sprite and capture frame counts differ")
    output.mkdir(parents=True)
    frames = []
    for index, path in enumerate(sprites):
        row = Image.new("RGB", (width * 4, width + 32), (12, 12, 16))
        with Image.open(path) as raw:
            sprite = Image.new("RGBA", raw.size, (12, 12, 16, 255))
            sprite.alpha_composite(raw.convert("RGBA"))
            sprite = ImageOps.contain(sprite.convert("RGB"), (width, width))
        row.paste(sprite, ((width - sprite.width) // 2, 32 + (width - sprite.height) // 2))
        draw = ImageDraw.Draw(row)
        draw.text((4, 2), f"{case} frame {index:02d}", fill="white")
        draw.text((4, 18), "Source sprite (own view)", fill="white")
        for column, (label, mesh) in enumerate(zip(("Before", "Calibrated", "Original idle"), meshes), 1):
            current = mesh[0 if len(mesh) == 1 else index]
            panel = _mesh(cameras, "front", current, skin["triangles"], skin["uvs"], skin["albedo"])
            row.paste(panel, (column * width, 32))
            draw.text((column * width + 4, 18), label, fill="white")
        frames.append(row)
        if index in (0, min(12, len(capture) - 1), len(capture) - 1):
            row.save(output / f"contact_f{index:02d}.png")
    gif = output / "comparison.gif"
    frames[0].save(gif, save_all=True, append_images=frames[1:], duration=max(1, int(round(SOURCE_FRAME_MS))), loop=0)
    return {"gif": str(gif), "output": str(output)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=tuple(CAPTURE_BY_CASE), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--width", type=int, default=256)
    args = parser.parse_args()
    print(render_case(args.case, args.output, args.width))


if __name__ == "__main__":
    main()
