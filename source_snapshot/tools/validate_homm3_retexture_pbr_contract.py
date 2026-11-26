"""Contract validator for tools/homm3_retexture_pbr (FullValidation build gate).

Checks:
  1. All required package scripts, skill, and doc files exist and compile via py_compile.
  2. Required fail-closed invariants remain intact in source:
     - render_guides_unit.py reverses inward faces (svol < 0.0) BEFORE bake_uv_ao.
     - project_unit.py keeps e_uv > 0.14 seam filter, cov >= 75.0, ao_mean >= 0.30, and --device cpu reference.
     - def_sprite_loader.py reads frames.json sources before cmp_*.png fallback.
  3. Synthetic 64x64 cube parity test (CPU vs CUDA when CUDA is available) + negative-volume flip assertion.
"""
from __future__ import annotations

import argparse
import os
import py_compile
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
PKG_DIR = ROOT / "tools/homm3_retexture_pbr"
REQUIRED_FILES = [
    PKG_DIR / "__init__.py",
    PKG_DIR / "def_sprite_loader.py",
    PKG_DIR / "build_def_refs.py",
    PKG_DIR / "render_guides_unit.py",
    PKG_DIR / "save_and_check_sheet.py",
    PKG_DIR / "paint_api.py",
    PKG_DIR / "project_unit.py",
    PKG_DIR / "render_batch_qa.py",
    PKG_DIR / "compose_qa_board.py",
    PKG_DIR / "batch_driver.py",
    ROOT / ".agents/skills/homm3-full-pbr-retexture/SKILL.md",
    ROOT / "docs/homm3_full_pbr_retexture.md",
]


def check_sources(repo_root: Path) -> list[str]:
    errors: list[str] = []
    for p in REQUIRED_FILES:
        rel = p.relative_to(ROOT)
        target = repo_root / rel
        if not target.is_file():
            errors.append(f"missing required file: {rel.as_posix()}")
            continue
        if target.suffix == ".py":
            try:
                py_compile.compile(str(target), doraise=True)
            except py_compile.PyCompileError as exc:
                errors.append(f"py_compile failed for {rel.as_posix()}: {exc}")

    guides_src = (repo_root / "tools/homm3_retexture_pbr/render_guides_unit.py").read_text(encoding="utf-8")
    idx_fix = guides_src.find("fix_inward_normals_if_needed(")
    idx_main_fix = guides_src.find("fix_inward_normals_if_needed(obj")
    idx_ao = guides_src.find("bake_uv_ao(sc, obj")
    if idx_fix < 0 or idx_main_fix < 0 or idx_ao < 0 or idx_main_fix > idx_ao:
        errors.append("render_guides_unit.py must run fix_inward_normals_if_needed(obj, ...) BEFORE bake_uv_ao(sc, obj, ...)")
    if "bmesh.ops.reverse_faces" not in guides_src:
        errors.append("render_guides_unit.py must use bmesh.ops.reverse_faces when signed volume < 0")

    proj_src = (repo_root / "tools/homm3_retexture_pbr/project_unit.py").read_text(encoding="utf-8")
    for token in ("e_uv > 0.14", "cov >= 75.0", "ao_mean >= 0.30", '"cpu"', '"cuda"', "svol < 0.0"):
        if token not in proj_src:
            errors.append(f"project_unit.py missing required invariant token: {token}")

    loader_src = (repo_root / "tools/homm3_retexture_pbr/def_sprite_loader.py").read_text(encoding="utf-8")
    if "_def_retarget.blend.frames.json" not in loader_src or "alpha >= 200" not in loader_src:
        errors.append("def_sprite_loader.py must prefer frames.json sources with alpha >= 200 shadow filtering")
    return errors


def _build_synthetic_cube_npz(out_npz: Path, inverted: bool) -> None:
    """Create a unit-cube eval_mesh.npz with per-face UV quads for synthetic parity + svol checks."""
    v = np.array([
        [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
        [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1],
    ], dtype=np.float32) - 0.5
    quads = [
        ((0, 3, 2, 1), (0, 0, -1)),
        ((4, 5, 6, 7), (0, 0, 1)),
        ((0, 1, 5, 4), (0, -1, 0)),
        ((2, 3, 7, 6), (0, 1, 0)),
        ((0, 4, 7, 3), (-1, 0, 0)),
        ((1, 2, 6, 5), (1, 0, 0)),
    ]
    tris = []
    uvs = []
    lnorms = []
    # Map 6 quads onto a crisp 3x2 UV grid inside [0.05, 0.95] keeping edge lengths <= 0.12
    #Wait: keep UV triangle edges < 0.12 (< 0.14 seam filter!) so every triangle rasterizes cleanly.
    for qi, (q, nrm) in enumerate(quads):
        col = qi % 3
        row = qi // 3
        u0, v0 = 0.08 + col * 0.14, 0.08 + row * 0.14
        u1, v1 = u0 + 0.08, v0 + 0.08
        tri_pairs = [(q[0], q[1], q[2]), (q[0], q[2], q[3])]
        uv_pairs = [((u0, v0), (u1, v0), (u1, v1)), ((u0, v0), (u1, v1), (u0, v1))]
        for tri, uv_t in zip(tri_pairs, uv_pairs):
            if inverted:
                tri = (tri[0], tri[2], tri[1])
                uv_t = (uv_t[0], uv_t[2], uv_t[1])
                n = (-nrm[0], -nrm[1], -nrm[2])
            else:
                n = nrm
            tris.append(tri)
            uvs.append(uv_t)
            lnorms.append([n, n, n])
    np.savez(
        out_npz,
        verts=v,
        tris=np.array(tris, dtype=np.int32),
        uvs=np.array(uvs, dtype=np.float32),
        lnorms=np.array(lnorms, dtype=np.float32),
    )


def run_synthetic_tests(repo_root: Path) -> dict[str, object]:
    sys.path.insert(0, str(repo_root / "tools/homm3_retexture_pbr"))
    import paint_api as PA  # noqa: E402
    import project_unit as PU  # noqa: E402

    # Offline paint_api contract checks (zero network)
    if PA.mask_api_key("AQ.Ab812345678908zww") != "AQ.Ab8...8zww":
        raise AssertionError("mask_api_key contract mismatch")

    old_env = os.environ.get("GEMINI_API_KEY")
    try:
        os.environ["GEMINI_API_KEY"] = "AIzaSySTALE_ENV_KEY"
        resolved_reg = PA.resolve_gemini_api_key(
            source="auto",
            _winreg_reader=lambda hive, sub, name: "AQ.Ab8LIVE_REG_KEY" if hive == "HKCU" else None,
        )
        if resolved_reg != "AQ.Ab8LIVE_REG_KEY":
            raise AssertionError(f"expected HKCU registry key to win over stale env, got {PA.mask_api_key(resolved_reg)}")
        resolved_fallback = PA.resolve_gemini_api_key(
            source="auto",
            _winreg_reader=lambda hive, sub, name: None,
        )
        if resolved_fallback != "AIzaSySTALE_ENV_KEY":
            raise AssertionError("expected env fallback when registry key absent")
    finally:
        if old_env is None:
            os.environ.pop("GEMINI_API_KEY", None)
        else:
            os.environ["GEMINI_API_KEY"] = old_env

    cost_est = PA.estimate_cost_usd("gemini-nano-banana-2.1", "2K", input_tokens=2000, text_output_tokens=600)
    if abs(cost_est - 0.0579) >= 1e-5:
        raise AssertionError(f"estimate_cost_usd mismatch: got {cost_est}, expected 0.0579")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        dummy_png = tmp_dir / "dummy.png"
        from PIL import Image
        Image.new("RGB", (8, 8), (127, 127, 127)).save(dummy_png)
        req = PA.build_request_body("test prompt", [dummy_png], model="gemini-nano-banana-2.1", image_size="2K", aspect_ratio="1:1")
        from google.genai._gaos.types.interactions import ImageResponseFormat
        rf = ImageResponseFormat.model_validate(req["response_format"])
        if rf.image_size != "2K" or rf.mime_type is not None or rf.aspect_ratio != "1:1":
            raise AssertionError(f"ImageResponseFormat validation mismatch: {rf}")

        # Enclosed background hole regression test (e.g. Evil Eye tentacles)
        ref_ring = np.zeros((64, 64), dtype=np.uint8)
        ref_ring[8:56, 8:56] = 1
        ref_ring[20:44, 20:44] = 0
        ring_rgb = np.full((64, 64, 3), 127, dtype=np.uint8)
        ring_rgb[ref_ring > 0] = (210, 120, 40)
        ring_rgb[12:14, 12:14] = (127, 127, 127)
        _, _, ring_rep = PU.register_panel_to_alpha(ring_rgb, ref_ring.astype(np.float32), "ring_test")
        if float(ring_rep["iouPost"]) < 0.95:
            raise AssertionError(f"enclosed background hole regression failed: iouPost={ring_rep['iouPost']}")

        cube_out = tmp_dir / "cube_out.npz"
        cube_inv = tmp_dir / "cube_inv.npz"
        _build_synthetic_cube_npz(cube_out, inverted=False)
        _build_synthetic_cube_npz(cube_inv, inverted=True)

        # Verify CPU rasterization & negative-volume normal flip recover outward normals
        dev_cpu = PU.resolve_device("cpu")
        p_out, n_out, _, _, m_out = PU.rasterize_uv_buffers(cube_out, 64, dev_cpu)
        p_inv, n_inv, _, _, m_inv = PU.rasterize_uv_buffers(cube_inv, 64, dev_cpu)
        cov_count = int(m_out.sum().item())
        if cov_count < 30:
            raise AssertionError(f"synthetic cube rasterized too few UV pixels: {cov_count}")
        if int(m_inv.sum().item()) != cov_count:
            raise AssertionError("inverted cube mask mismatch after orientation flip")
        nrm_recovery_diff = float((n_out[m_out] - n_inv[m_out]).abs().max().item())
        if nrm_recovery_diff > 1e-4:
            raise AssertionError(f"negative signed volume normal flip failed: max_diff={nrm_recovery_diff}")

        metrics: dict[str, object] = {
            "uvPixels": cov_count,
            "nrmFlipDiff": round(nrm_recovery_diff, 6),
            "ringHoleIoU": ring_rep["iouPost"],
            "cudaTested": torch.cuda.is_available(),
            "paintApiTested": True,
        }
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
            parity = PU.run_parity_check_npz(cube_out, uv_res=64)
            metrics["parity"] = parity
            metrics["peakVramMiB"] = round(torch.cuda.max_memory_allocated() / (1024 ** 2), 2)
        return metrics


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", type=Path, default=ROOT)
    args = ap.parse_args()

    tracemalloc.start()
    t0 = time.perf_counter()
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

    errs = check_sources(args.repo_root)
    if errs:
        for e in errs:
            print(f"FAIL: {e}", file=sys.stderr)
        return 1

    metrics = run_synthetic_tests(args.repo_root)
    elapsed = time.perf_counter() - t0
    _, peak_py = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(
        f"OK tools/validate_homm3_retexture_pbr_contract.py: elapsed={elapsed:.3f}s "
        f"peakPyRAM={peak_py / (1024 ** 2):.2f} MiB metrics={metrics}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
