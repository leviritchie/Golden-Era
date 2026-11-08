"""Prove the vendored nvdiffrast install is visible to the depth notebook preflight."""
from __future__ import annotations

from pathlib import Path
import sys

TOOL = Path(__file__).resolve().parent
if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from nvdiffrast_local import LOCAL_NVDIFFRAST_DIR, ensure_local_nvdiffrast
from roc_gpu_cascade_experiment import capability_report


def run() -> dict[str, object]:
    path = ensure_local_nvdiffrast(required=True)
    assert path == LOCAL_NVDIFFRAST_DIR
    assert (path / "nvdiffrast" / "__init__.py").is_file()
    native = tuple(path.glob("_nvdiffrast_c.*"))
    assert native, f"compiled nvdiffrast extension missing in {path}"
    report = capability_report()
    assert report["nvdiffrast"] is True, report
    assert report["exactTriangleRenderer"] == "nvdiffrast", report
    if not report.get("cuda"):
        raise RuntimeError(f"CUDA is required for exact triangle depth: {report}")
    import nvdiffrast.torch as dr

    ctx = dr.RasterizeCudaContext()
    return {
        "ok": True,
        "report": {key: report[key] for key in ("torch", "torchVersion", "cuda", "cudaDevice", "nvdiffrast", "exactTriangleRenderer")},
        "context": type(ctx).__name__,
        "localDir": str(path),
    }


if __name__ == "__main__":
    print(run())
