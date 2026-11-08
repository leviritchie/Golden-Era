"""GPU clip JSON keeps poses and drops giant raster arrays."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np

from roc_gpu_cascade_experiment import persist_gpu_clip_result


def run() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as raw:
        output = Path(raw) / "gpu_depth_silhouette_simple"
        payload = persist_gpu_clip_result(
            {
                "poses": {0: {"Bone_000": {"x": 0.1, "y": 0.0, "z": 0.0}}},
                "rootPivot": [1.0, 2.0, 3.0],
                "cameraFitPath": "V:/cam.json",
                "targetMasks": np.zeros((1, 2, 2), dtype=np.float32),
                "predictedMasks": np.ones((1, 2, 2), dtype=np.float32),
                "targetDepth": np.zeros((1, 2, 2), dtype=np.float32),
                "predictedDepth": np.zeros((1, 2, 2), dtype=np.float32),
                "targetRgb": np.zeros((1, 2, 2, 3), dtype=np.float32),
                "predictedRgb": np.ones((1, 2, 2, 3), dtype=np.float32),
                "history": [{"noise": True}],
                "score": 0.7,
            },
            output,
        )
        assert payload.is_file(), payload
        data = json.loads(payload.read_text(encoding="utf-8"))
        assert "0" in data["poses"]
        assert data["score"] == 0.7
        assert "targetMasks" not in data
        assert "targetRgb" not in data
        assert "predictedRgb" not in data
        assert "history" not in data
        try:
            persist_gpu_clip_result({"score": 0.0}, output)
            raise AssertionError("empty poses must stay fail-closed")
        except RuntimeError as exc:
            assert "no poses" in str(exc)
        return {"ok": True, "path": str(payload)}


if __name__ == "__main__":
    print(run())
