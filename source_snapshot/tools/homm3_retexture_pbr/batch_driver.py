"""Single CLI driver for deterministic Full-PBR retexture batch stages.

Subcommands:
  prep        Build DEF 2x2 refs, render Blender guides under gpu_gate, compose compact batch prep sheet.
  paint-api   Paint 2x2 sheets directly at native 2K via Gemini API (gemini-nano-banana-2.1) + IoU gate.
  check-sheet Resize 2x2 image-generator sheet and enforce panel alpha IoU >= 0.85.
  project     Run CUDA multi-view UV projection & Full-PBR Hex/Lit bake across unit:archetype pairs.
  qa-board    Render Hex/Lit QA tiles under gpu_gate and compose labeled batch_N_qa.png.
  prune-temp  Remove heavy guide/eval intermediates after batch QA passes (keeps out/, ref/, meta, QA boards).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

TOOL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL_DIR))

from build_def_refs import build_unit_ref  # noqa: E402
from compose_qa_board import compose_batch  # noqa: E402
from def_sprite_loader import DEFAULT_REPO_ROOT  # noqa: E402
from paint_api import main as paint_api_main  # noqa: E402
from save_and_check_sheet import save_and_check  # noqa: E402

DEFAULT_BLENDER = Path("V:/Tools/blender-mcp/blender-5.2.2/blender.exe")
DEFAULT_GPU_GATE = Path("V:/scratch_claude/unit_rebuild/_fortress_coord/gpu_gate.py")
DEFAULT_REBUILD_ROOT = Path("V:/scratch_claude/unit_rebuild")


def _run_blender_script(
    script_name: str,
    script_args: list[str],
    blender: Path,
    gpu_gate: Path,
    use_gpu_gate: bool,
) -> None:
    base_cmd = [str(blender), "-b", "--python-exit-code", "1", "--python", str(TOOL_DIR / script_name), "--", *script_args]
    if use_gpu_gate:
        if not gpu_gate.is_file():
            raise FileNotFoundError(f"gpu_gate.py not found: {gpu_gate}")
        cmd = [sys.executable, str(gpu_gate), "--slots", "2", "--min-vram", "3200", "--", *base_cmd]
    else:
        cmd = base_cmd
    res = subprocess.run(cmd, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"Blender step failed ({script_name}, exit={res.returncode})")


def _compose_prep_sheet(units: list[str], work_dir: Path, out_path: Path) -> Path:
    tile = 512
    lbl_w, hdr_h = 240, 40
    board = Image.new("RGB", (lbl_w + tile * 2, hdr_h + tile * len(units)), (30, 32, 30))
    draw = ImageDraw.Draw(board)
    font = ImageFont.load_default()
    draw.text((lbl_w + 16, 12), "HoMM3 DEF Reference (2x2)", fill=(240, 240, 220), font=font)
    draw.text((lbl_w + tile + 16, 12), "Primary Guide Sheet (right | left | front | top)", fill=(240, 240, 220), font=font)

    for ri, u in enumerate(units):
        y0 = hdr_h + ri * tile
        meta = json.loads((work_dir / u / "views/meta.json").read_text(encoding="utf-8"))
        flip_note = "\n[flipped normals]" if meta.get("flippedInwardNormals") else ""
        draw.text((12, y0 + tile // 2 - 12), f"{u}{flip_note}", fill=(225, 225, 205), font=font)
        ref_im = Image.open(work_dir / u / "ref/def_ref_2x2.png").convert("RGB").resize((tile, tile), Image.Resampling.LANCZOS)
        guide_im = Image.open(work_dir / u / "views/guide_sheet_primary.png").convert("RGB").resize((tile, tile), Image.Resampling.LANCZOS)
        board.paste(ref_im, (lbl_w, y0))
        board.paste(guide_im, (lbl_w + tile, y0))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    board.save(out_path)
    print(f"Wrote prep contact sheet {out_path} ({board.size})")
    return out_path


def cmd_prep(args: argparse.Namespace) -> int:
    units = [u.strip() for u in args.units.split(",") if u.strip()]
    for u in units:
        ref_p = args.work_dir / u / "ref/def_ref_2x2.png"
        if args.force or not ref_p.is_file():
            build_unit_ref(u, work_dir=args.work_dir, repo_root=args.repo_root)
        meta_p = args.work_dir / u / "views/meta.json"
        need_base = args.force or not meta_p.is_file()
        need_tert = args.tertiary and (
            need_base or not (args.work_dir / u / "views/guide_sheet_tertiary.png").is_file()
        )
        if need_base or need_tert:
            bargs = ["--unit", u, "--work-dir", str(args.work_dir), "--rebuild-root", str(args.rebuild_root)]
            if args.source_slice_root:
                bargs.extend(["--source-slice-root", str(args.source_slice_root.resolve())])
            if need_tert:
                bargs.append("--tertiary" if need_base else "--tertiary-only")
            _run_blender_script(
                "render_guides_unit.py",
                bargs,
                blender=args.blender,
                gpu_gate=args.gpu_gate,
                use_gpu_gate=not args.no_gpu_gate,
            )
    if args.batch_out:
        _compose_prep_sheet(units, args.work_dir, args.batch_out)
    return 0


def cmd_check_sheet(args: argparse.Namespace) -> int:
    ok, worst, _ = save_and_check(args.unit, args.work_dir, args.sheet, args.src, min_iou=args.min_iou)
    return 0 if ok else 2


def cmd_project(args: argparse.Namespace) -> int:
    for item in [x.strip() for x in args.units.split(",") if x.strip()]:
        if ":" in item:
            unit, arch = item.split(":", 1)
        else:
            unit, arch = item, ""
        cmd = [
            sys.executable, str(TOOL_DIR / "project_unit.py"),
            "--unit", unit, "--work-dir", str(args.work_dir),
            "--rebuild-root", str(args.rebuild_root),
            "--device", args.device,
        ]
        if arch:
            cmd.extend(["--archetype", arch])
        if args.parity_unit and unit == args.parity_unit:
            cmd.append("--parity-check")
        if args.coverage_over_visible:
            cmd.append("--coverage-over-visible")
        if args.extra_views:
            cmd.append("--extra-views")
        res = subprocess.run(cmd, check=False)
        if res.returncode != 0:
            raise RuntimeError(f"project_unit failed for {unit} (exit={res.returncode})")
    return 0


def cmd_qa_board(args: argparse.Namespace) -> int:
    units = [u.strip() for u in args.units.split(",") if u.strip()]
    bargs = [
        "--work-dir", str(args.work_dir.resolve()),
        "--units", ",".join(units),
        "--rebuild-root", str(args.rebuild_root.resolve()),
    ]
    if args.shipped_root:
        bargs.extend(["--shipped-root", str(args.shipped_root.resolve())])
    if args.source_slice_root:
        bargs.extend(["--source-slice-root", str(args.source_slice_root.resolve())])
    if args.compare_pbr:
        bargs.append("--compare-pbr")
    _run_blender_script(
        "render_batch_qa.py",
        bargs,
        blender=args.blender,
        gpu_gate=args.gpu_gate,
        use_gpu_gate=not args.no_gpu_gate,
    )
    label = "Old Shipped Front3/4" if args.shipped_root else "Raw Rebuild Front3/4"
    compose_batch(units, args.work_dir, args.out, repo_root=args.repo_root, shipped_label=label, compare_pbr=args.compare_pbr)
    return 0


def cmd_prune_temp(args: argparse.Namespace) -> int:
    units = [u.strip() for u in args.units.split(",") if u.strip()]
    reclaimed = 0
    for u in units:
        udir = args.work_dir / u
        patterns = [
            "views/*_alpha.npy",
            "views/*_depth.npy",
            "views/*_nrm.npy",
            "views/*_guide.png",
            "views/guide_sheet_*.png",
            "proj/eval_mesh.npz",
            "proj/*.npy",
            "out/raw_api_*.png",
            "renders/qa_tiles/*.png",
        ]
        for pat in patterns:
            for p in udir.glob(pat):
                if p.is_file():
                    reclaimed += p.stat().st_size
                    p.unlink()
    print(f"Pruned temporary projection/QA artifacts across {len(units)} units: freed {reclaimed / (1024 ** 2):.1f} MiB")
    return 0


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "paint-api":
        return paint_api_main(sys.argv[2:])

    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="subcmd", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--work-dir", required=True, type=Path)
        p.add_argument("--rebuild-root", type=Path, default=DEFAULT_REBUILD_ROOT)

    p_prep = sub.add_parser("prep")
    add_common(p_prep)
    p_prep.add_argument("--units", required=True)
    p_prep.add_argument("--source-slice-root", type=Path, default=None)
    p_prep.add_argument("--batch-out", type=Path, default=None)
    p_prep.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    p_prep.add_argument("--blender", type=Path, default=DEFAULT_BLENDER)
    p_prep.add_argument("--gpu-gate", type=Path, default=DEFAULT_GPU_GATE)
    p_prep.add_argument("--no-gpu-gate", action="store_true")
    p_prep.add_argument("--force", action="store_true")
    p_prep.add_argument("--tertiary", action="store_true",
                        help="opt-in: also render the 4 low tertiary guide views (guide_sheet_tertiary.png); on a unit "
                             "already prepped, renders only those views and appends them to views/meta.json")
    p_prep.set_defaults(func=cmd_prep)

    p_chk = sub.add_parser("check-sheet")
    p_chk.add_argument("--work-dir", required=True, type=Path)
    p_chk.add_argument("--unit", required=True)
    p_chk.add_argument("--sheet", required=True, choices=["primary", "secondary"])
    p_chk.add_argument("--src", required=True, type=Path)
    p_chk.add_argument("--min-iou", type=float, default=0.85)
    p_chk.set_defaults(func=cmd_check_sheet)

    p_proj = sub.add_parser("project")
    add_common(p_proj)
    p_proj.add_argument("--units", required=True, help="Comma-separated unit or unit:archetype")
    p_proj.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    p_proj.add_argument("--parity-unit", default="", help="Optional single unit to run CPU vs CUDA parity check on")
    p_proj.add_argument("--coverage-over-visible", action="store_true",
                        help="opt-in: gate coverage on outside-visible texels only (see project_unit.py)")
    p_proj.add_argument("--extra-views", action="store_true",
                        help="opt-in: also project the low tertiary views (prep --tertiary + paint-api --sheet tertiary)")
    p_proj.set_defaults(func=cmd_project)

    p_qa = sub.add_parser("qa-board")
    add_common(p_qa)
    p_qa.add_argument("--units", required=True)
    p_qa.add_argument("--out", required=True, type=Path)
    p_qa.add_argument("--source-slice-root", type=Path, default=None)
    p_qa.add_argument("--shipped-root", type=Path, default=None)
    p_qa.add_argument("--repo-root", type=Path, default=DEFAULT_REPO_ROOT)
    p_qa.add_argument("--blender", type=Path, default=DEFAULT_BLENDER)
    p_qa.add_argument("--gpu-gate", type=Path, default=DEFAULT_GPU_GATE)
    p_qa.add_argument("--no-gpu-gate", action="store_true")
    p_qa.add_argument("--compare-pbr", action="store_true")
    p_qa.set_defaults(func=cmd_qa_board)

    p_prune = sub.add_parser("prune-temp")
    p_prune.add_argument("--work-dir", required=True, type=Path)
    p_prune.add_argument("--units", required=True)
    p_prune.set_defaults(func=cmd_prune_temp)

    p_api = sub.add_parser("paint-api", add_help=False)
    p_api.add_argument("api_args", nargs=argparse.REMAINDER)
    p_api.set_defaults(func=lambda a: paint_api_main(a.api_args))

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
