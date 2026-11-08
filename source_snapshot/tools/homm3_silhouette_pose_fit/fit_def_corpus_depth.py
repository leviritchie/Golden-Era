#!/usr/bin/env python3
"""Fit one multi-frame depth sequence over an entire HoMM3 DEF corpus.

The DEF is treated as one ordered animation corpus, not as independent
animation groups.  This is intentional: the source groups are allowed to
chain in the game and the multi-frame model should see one shared reference
context across those transitions.  The movement preview is a filtered view
of group 0 only; it does not change the inference input sequence.

The input is always extracted from the authentic battle DEF named by the unit
inventory.  RIFE/interpolated directories are not accepted or consulted.
Every frame is alpha-shadow culled before inference.  DA3 depth maps are
stored for the complete corpus, while only the movement group gets a contact
sheet and GIF preview.

Example:

    python fit_def_corpus_depth.py --unit h3_hobgoblin --run-id final
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
TOOL_DIR = Path(__file__).resolve().parent
INVENTORY = ROOT / "tools" / "homm3_import" / "units_inventory.json"
LOD_EXTRACTOR = ROOT / "tools" / "lod_extract_entry_py3.py"
DEF_EXTRACTOR = ROOT / "tools" / "defextract_py3.py"
DEFAULT_MODEL = ROOT / "artifacts" / "model_cache" / "DA3-LARGE-1.1"
DEFAULT_OUTPUT = ROOT / "artifacts" / "depth_model_comparison" / "def_animation_sets"

GROUP_LABELS = {
    0: "move",
    1: "mouseover",
    2: "idle",
    3: "hitted",
    4: "defence",
    5: "death",
    6: "unknown_06",
    7: "turn_left",
    8: "turn_right",
    9: "unused_a",
    10: "unused_b",
    11: "attack_up",
    12: "attack_front",
    13: "attack_down",
    20: "move_start",
    21: "move_end",
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_inventory(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("units", []) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError(f"unit inventory must be a list or contain units[]: {path}")
    return [row for row in rows if isinstance(row, dict)]


def _unit_row(inventory: Path, unit: str) -> dict[str, Any]:
    rows = _load_inventory(inventory)
    for row in rows:
        if row.get("unitSid") == unit:
            return row
    available = ", ".join(sorted(str(row.get("unitSid")) for row in rows))
    raise KeyError(f"unit {unit!r} is not in {inventory}; available: {available}")


def _resolve_lod(row: dict[str, Any], explicit: Path | None) -> Path:
    if explicit is not None:
        path = explicit if explicit.is_absolute() else ROOT / explicit
        if not path.is_file():
            raise FileNotFoundError(f"explicit LOD is missing: {path}")
        return path.resolve()
    lod_name = str(row.get("battleLod") or "")
    if not lod_name:
        raise ValueError(f"inventory row has no battleLod: {row.get('unitSid')}")
    candidates = [
        ROOT / "HoMM 3 Complete" / "Data" / lod_name,
        ROOT / "vcmi" / "Data" / lod_name,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        "battle LOD is missing; checked: " + ", ".join(str(path) for path in candidates)
    )


def _extract_def(row: dict[str, Any], lod: Path, run_root: Path) -> tuple[Path, Path]:
    entry = str(row.get("battleLodEntry") or "")
    basename = str(row.get("battleExtractBasename") or Path(entry).stem)
    if not entry:
        raise ValueError(f"inventory row has no battleLodEntry: {row.get('unitSid')}")
    source_dir = run_root / "source_def"
    source_dir.mkdir(parents=True, exist_ok=True)
    def_path = source_dir / f"{basename}.def"
    subprocess.run(
        [sys.executable, str(LOD_EXTRACTOR), str(lod), entry, str(def_path)],
        check=True,
        cwd=str(ROOT),
    )
    extracted_dir = source_dir / "extracted"
    extracted_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [sys.executable, str(DEF_EXTRACTOR), str(def_path), str(extracted_dir)],
        check=True,
        cwd=str(ROOT),
    )
    metadata_path = extracted_dir / f"{basename.lower()}.json"
    if not metadata_path.is_file():
        raise FileNotFoundError(f"DEF extractor did not produce metadata: {metadata_path}")
    return def_path, metadata_path


def _resolve_extracted_frame(extracted_root: Path, name: str) -> Path:
    path = extracted_root / Path(name.replace("\\", "/"))
    if not path.is_file():
        raise FileNotFoundError(f"DEF metadata references missing frame: {path}")
    return path


def _neutral_rgb(rgba: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    alpha = rgba[..., 3].astype(np.float32) / 255.0
    rgb = rgba[..., :3].copy()
    for channel in range(3):
        rgb[..., channel] = np.clip(
            rgb[..., channel].astype(np.float32) * alpha + 128.0 * (1.0 - alpha),
            0.0,
            255.0,
        ).astype(np.uint8)
    return rgb, alpha > 0.08


def _save_u16(depth: np.ndarray, path: Path) -> None:
    image = Image.fromarray(np.clip(np.rint(depth * 65535.0), 0, 65535).astype(np.uint16))
    image.save(path)


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _source_preview(rgba: np.ndarray, size: tuple[int, int]) -> Image.Image:
    image = Image.fromarray(rgba, "RGBA")
    background = Image.new("RGBA", image.size, (8, 8, 8, 255))
    return Image.alpha_composite(background, image).convert("RGB").resize(
        size, Image.Resampling.LANCZOS
    )


def _depth_preview(depth: np.ndarray, size: tuple[int, int]) -> Image.Image:
    gray = Image.fromarray(
        np.clip(np.rint(depth * 255.0), 0, 255).astype(np.uint8), "L"
    )
    return gray.resize(size, Image.Resampling.BILINEAR).convert("RGB")


def _movement_panel(
    rgba: np.ndarray,
    depth: np.ndarray,
    frame_name: str,
    *,
    panel_width: int,
) -> Image.Image:
    height, width = rgba.shape[:2]
    panel_height = max(1, round(panel_width * height / width))
    gap = 6
    title_height = 32
    canvas = Image.new(
        "RGB", (panel_width * 2 + gap, panel_height + title_height), (22, 22, 22)
    )
    draw = ImageDraw.Draw(canvas)
    font = _font(16)
    panels = [
        ("movement sprite (shadow culled)", _source_preview(rgba, (panel_width, panel_height))),
        ("DA3 multi-frame depth (near=bright)", _depth_preview(depth, (panel_width, panel_height))),
    ]
    for index, (label, panel) in enumerate(panels):
        x = index * (panel_width + gap)
        draw.text((x + 5, 6), label, fill=(240, 240, 240), font=font)
        canvas.paste(panel, (x, title_height))
    draw.text((canvas.width - 92, 6), frame_name, fill=(180, 200, 215), font=font)
    return canvas


def _runtime_info(model_dir: Path, runner: Path) -> dict[str, Any]:
    import torch

    return {
        "python": platform.python_version(),
        "torch": str(torch.__version__),
        "torch_cuda": str(torch.version.cuda),
        "cuda_available": bool(torch.cuda.is_available()),
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "model_dir": str(model_dir),
        "model_files_sha256": {
            path.name: _sha256_file(path)
            for path in sorted(model_dir.iterdir())
            if path.is_file() and path.name in {"config.json", "model.safetensors"}
        },
        "runner_sha256": _sha256_file(runner),
    }


def run_corpus(
    *,
    unit: str,
    inventory: Path = INVENTORY,
    lod: Path | None = None,
    model_dir: Path = DEFAULT_MODEL,
    output_root: Path = DEFAULT_OUTPUT,
    run_id: str | None = None,
    reference_view: str = "middle",
    process_res: int = 504,
    fps: float = 12.0,
    panel_width: int = 420,
) -> dict[str, Any]:
    """Extract, cull, and infer one DA3 sequence over the complete DEF corpus."""
    if not model_dir.is_dir():
        raise FileNotFoundError(f"local DA3 model directory is missing: {model_dir}")
    if not inventory.is_file():
        raise FileNotFoundError(f"unit inventory is missing: {inventory}")
    row = _unit_row(inventory, unit)
    selected_lod = _resolve_lod(row, lod)
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_root = (output_root / unit / run_id).resolve()
    if run_root.exists():
        raise FileExistsError(f"output run already exists; choose another --run-id: {run_root}")
    run_root.mkdir(parents=True, exist_ok=False)

    def_path, metadata_path = _extract_def(row, selected_lod, run_root)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    sequences = metadata.get("sequences")
    if not isinstance(sequences, list) or not sequences:
        raise ValueError(f"DEF metadata has no sequences: {metadata_path}")

    # Preserve metadata order and frame order. Do not sort by group name: the
    # order is the corpus contract supplied by the DEF extractor.
    entries: list[dict[str, Any]] = []
    for sequence in sequences:
        group = int(sequence["group"])
        for local_index, relative_name in enumerate(sequence["frames"]):
            source_path = _resolve_extracted_frame(metadata_path.parent, str(relative_name))
            entries.append(
                {
                    "corpus_index": len(entries),
                    "group": group,
                    "group_label": GROUP_LABELS.get(group, f"unknown_{group:02d}"),
                    "group_frame_index": local_index,
                    "source_relative": str(relative_name).replace("\\", "/"),
                    "source_path": source_path,
                }
            )
    if not entries:
        raise ValueError("DEF corpus is empty")

    from compare_sprite_depth_models import (
        _load_da3,
        _predict_da3_sequence,
    )
    from def_soft_shadow import cull_def_soft_shadow_rgba

    culled_root = run_root / "corpus" / "source_shadow_culled"
    depth_root = run_root / "corpus" / "depth_da3_large_1_1_multiframe"
    culled_root.mkdir(parents=True, exist_ok=True)
    depth_root.mkdir(parents=True, exist_ok=True)
    rgb_frames: list[np.ndarray] = []
    masks: list[np.ndarray] = []
    rgba_frames: list[np.ndarray] = []
    cull_report: list[dict[str, Any]] = []
    frame_hashes: list[dict[str, str]] = []
    print(f"[{unit}] extracting complete DEF corpus: {len(entries)} frames", flush=True)
    for entry in entries:
        rgba = np.asarray(Image.open(entry["source_path"]).convert("RGBA"), dtype=np.uint8)
        culled, culled_count = cull_def_soft_shadow_rgba(rgba)
        if culled_count < 1:
            raise RuntimeError(
                "mandatory alpha-shadow culling did not remove any shadow pixels "
                f"from corpus frame {entry['source_relative']}"
            )
        group_dir = culled_root / f"g{entry['group']:02d}_{entry['group_label']}"
        group_dir.mkdir(parents=True, exist_ok=True)
        output_path = group_dir / f"{entry['group_frame_index']:02d}.png"
        Image.fromarray(culled, "RGBA").save(output_path)
        rgb, mask = _neutral_rgb(culled)
        rgb_frames.append(rgb)
        masks.append(mask)
        rgba_frames.append(culled)
        cull_report.append(
            {
                "corpus_index": entry["corpus_index"],
                "source_relative": entry["source_relative"],
                "output": str(output_path),
                "culled_pixels": culled_count,
            }
        )
        frame_hashes.append(
            {
                "source_sha256": _sha256_file(entry["source_path"]),
                "culled_sha256": _sha256_file(output_path),
            }
        )

    model, torch = _load_da3(model_dir.resolve(), device="cuda")
    print(
        f"[{unit}] DA3 corpus inference: {len(entries)} frames, "
        f"reference={reference_view}, process_res={process_res}",
        flush=True,
    )
    depth_frames, timing = _predict_da3_sequence(
        model,
        torch,
        rgb_frames,
        masks,
        reference_view=reference_view,
        process_res=process_res,
    )
    for entry, depth in zip(entries, depth_frames):
        group_dir = depth_root / f"g{entry['group']:02d}_{entry['group_label']}"
        group_dir.mkdir(parents=True, exist_ok=True)
        _save_u16(depth, group_dir / f"{entry['group_frame_index']:02d}.png")

    movement_indices = [
        index for index, entry in enumerate(entries) if entry["group"] == 0
    ]
    if not movement_indices:
        raise ValueError("DEF corpus contains no group 0 movement frames")
    movement_root = run_root / "movement_preview"
    movement_root.mkdir(parents=True, exist_ok=True)
    panels = [
        _movement_panel(
            rgba_frames[index],
            depth_frames[index],
            f"g00_{entries[index]['group_frame_index']:02d}",
            panel_width=panel_width,
        )
        for index in movement_indices
    ]
    contact = Image.new(
        "RGB",
        (panels[0].width, sum(panel.height for panel in panels)),
        (22, 22, 22),
    )
    y = 0
    for panel in panels:
        contact.paste(panel, (0, y))
        y += panel.height
    contact_path = movement_root / "movement_contact_sheet.png"
    contact.save(contact_path)
    gif_path = movement_root / "movement_da3_depth.gif"
    panels[0].save(
        gif_path,
        save_all=True,
        append_images=panels[1:],
        duration=max(1, round(1000.0 / fps)),
        loop=0,
        optimize=False,
    )

    corpus_order_digest = hashlib.sha256()
    for entry, hashes in zip(entries, frame_hashes):
        corpus_order_digest.update(
            f"{entry['corpus_index']}|{entry['group']}|{entry['group_frame_index']}|"
            f"{entry['source_relative']}|{hashes['source_sha256']}".encode("utf-8")
        )
        corpus_order_digest.update(b"\0")
    report = {
        "schema_version": 1,
        "unit": unit,
        "inventory": str(inventory.resolve()),
        "inventory_sha256": _sha256_file(inventory),
        "inventory_row": row,
        "lod_path": str(selected_lod),
        "lod_sha256": _sha256_file(selected_lod),
        "def_entry": row.get("battleLodEntry"),
        "def_path": str(def_path),
        "def_sha256": _sha256_file(def_path),
        "def_metadata_path": str(metadata_path),
        "model": "depth-anything-3/DA3-LARGE-1.1",
        "model_dir": str(model_dir.resolve()),
        "reference_view": reference_view,
        "process_res": process_res,
        "fps": fps,
        "source_policy": {
            "authentic_def_frames_only": True,
            "rife_interpolated_frames_used": False,
            "alpha_shadow_culling_required": True,
            "multi_frame_scope": "entire ordered DEF corpus as one sequence",
            "preview_scope": "group 0 movement frames only",
        },
        "runtime": _runtime_info(model_dir.resolve(), Path(__file__).resolve()),
        "timing": timing,
        "frame_count": len(entries),
        "movement_frame_count": len(movement_indices),
        "corpus_order_sha256": corpus_order_digest.hexdigest(),
        "frames": [
            {
                **{key: value for key, value in entry.items() if key != "source_path"},
                **frame_hashes[index],
                "culled_pixels": cull_report[index]["culled_pixels"],
            }
            for index, entry in enumerate(entries)
        ],
        "shadow_cull": {
            "frame_count": len(cull_report),
            "total_culled_pixels": sum(item["culled_pixels"] for item in cull_report),
            "frames": cull_report,
        },
        "depth_dir": str(depth_root),
        "movement_preview": {
            "group": 0,
            "contact_sheet": str(contact_path),
            "gif": str(gif_path),
            "frame_indices_in_corpus": movement_indices,
        },
    }
    manifest = run_root / "corpus_depth_manifest.json"
    manifest.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[{unit}] complete: {timing['seconds']:.2f}s; manifest={manifest}", flush=True)
    print(f"movement preview: {contact_path}", flush=True)
    print(f"movement GIF: {gif_path}", flush=True)
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", default="h3_hobgoblin")
    parser.add_argument("--inventory", type=Path, default=INVENTORY)
    parser.add_argument("--lod", type=Path, default=None)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--reference-view", default="middle")
    parser.add_argument("--process-res", type=int, default=504)
    parser.add_argument("--fps", type=float, default=12.0)
    parser.add_argument("--panel-width", type=int, default=420)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    report = run_corpus(
        unit=args.unit,
        inventory=args.inventory.resolve(),
        lod=args.lod.resolve() if args.lod else None,
        model_dir=args.model_dir.resolve(),
        output_root=args.output_root.resolve(),
        run_id=args.run_id,
        reference_view=args.reference_view,
        process_res=args.process_res,
        fps=args.fps,
        panel_width=args.panel_width,
    )
    print(json.dumps({"manifest": report["movement_preview"]["contact_sheet"]}, indent=2))


if __name__ == "__main__":
    main()
