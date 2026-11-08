"""Fast validator for persisted V2 contracts and source provenance."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def validate_result(path: str | Path) -> dict:
    source = Path(path).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if int(payload.get("schemaVersion", 0)) != 2:
        raise ValueError("V2 result schemaVersion must be 2")
    provenance = payload.get("provenance", {})
    if provenance.get("backend") != "nvdiffrast_cuda_triangle":
        raise ValueError("V2 result was not produced by the exact CUDA triangle backend")
    if provenance.get("rendererBackend") != "nvdiffrast_cuda_triangle":
        raise ValueError("V2 rendererBackend is not nvdiffrast_cuda_triangle")
    if str(provenance.get("sourceKind", "")).lower() != "def":
        raise ValueError("V2 result sourceKind must be def")
    if not provenance.get("frameIndices"):
        raise ValueError("V2 result has no authentic frame indices")
    durations = provenance.get("frameDurations")
    if not isinstance(durations, list) or len(durations) != len(provenance["frameIndices"]) or any(float(value) <= 0.0 for value in durations):
        raise ValueError("V2 result does not preserve one positive native duration per frame")
    source_dir = str(provenance.get("sourceDir", "")).lower().replace("\\", "/")
    if any(token in source_dir for token in ("rife", "interpolat", "upscale")):
        raise ValueError("V2 result sourceDir points at an interpolated target")
    shadow = provenance.get("shadowCullReport", {})
    if not isinstance(shadow, dict) or not shadow.get("applied"):
        raise ValueError("V2 result does not prove mandatory alpha-shadow culling")
    selected = payload.get("selected", {})
    pose = selected.get("pose", {})
    for key in ("registration", "motionTranslation", "motionRotation", "boneRotation"):
        if key not in pose:
            raise ValueError(f"V2 result is missing canonical pose field: {key}")
    canonical = payload.get("canonicalPose")
    if not isinstance(canonical, dict):
        raise ValueError("V2 result is missing canonicalPose serialization")
    for key in (
        "registration", "motionTranslation", "motionRotation", "boneRotation",
        "frameIndices", "rotationRepresentation", "rootRepresentation",
    ):
        if key not in canonical:
            raise ValueError(f"V2 canonicalPose is missing {key}")
    if canonical["rotationRepresentation"] != "axis_angle_radians_glTF_world_axes":
        raise ValueError("V2 canonical rotation representation is not the documented axis-angle contract")
    parity = payload.get("parity")
    if isinstance(parity, dict) and "meanIoU" in parity:
        if float(parity.get("meanIoU", 0.0)) < 0.98 or float(parity.get("minIoU", 0.0)) < 0.95:
            raise ValueError("V2 Blender parity report is below the export thresholds")
        if any(float(row.get("centerErrorPx", 999.0)) >= 1.0 for row in parity.get("frames", [])):
            raise ValueError("V2 Blender parity report exceeds the centroid threshold")
    return {"ok": True, "schemaVersion": 2, "frameCount": len(provenance["frameIndices"]), "path": str(source)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate_result(args.result), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
