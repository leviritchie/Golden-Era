#!/usr/bin/env python3
"""GPU local anatomical box detection and alignment for the Roc experiment.

This is intentionally a local, zero-shot detector lane.  It does not call a
remote vision API.  Grounding DINO is loaded through Transformers and fails
closed when CUDA is unavailable.  The fixed vocabulary is shared by sprite
and mesh detections so the box term has a stable class contract.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FIXED_PART_LIBRARY = (
    "head",
    "beak",
    "eye",
    "neck",
    "torso",
    "shoulder",
    "upper wing",
    "lower wing",
    "wing tip",
    "tail",
    "upper leg",
    "knee",
    "lower leg",
    "ankle",
    "foot",
    "talon",
)


@dataclass(frozen=True)
class PartBox:
    part: str
    box: tuple[float, float, float, float]
    score: float

    def as_dict(self):
        return asdict(self)


def require_cuda():
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("Anatomical box detection requires CUDA; refusing CPU inference.")
    return torch.device("cuda:0")


class RocAnatomicalBoxDetector:
    """Grounding DINO detector with one fixed label per anatomical part."""

    def __init__(self, model_id: str = "IDEA-Research/grounding-dino-tiny", *, box_threshold: float = 0.24, text_threshold: float = 0.18):
        import torch
        from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

        self.device = require_cuda()
        self.model_id = model_id
        self.box_threshold = float(box_threshold)
        self.text_threshold = float(text_threshold)
        self.processor = AutoProcessor.from_pretrained(model_id)
        self.model = AutoModelForZeroShotObjectDetection.from_pretrained(model_id).to(self.device).eval()
        self.torch = torch

    def detect(self, image: Image.Image | np.ndarray) -> list[PartBox]:
        if isinstance(image, np.ndarray):
            image = Image.fromarray(image.astype(np.uint8), "RGBA" if image.shape[-1] == 4 else "RGB")
        image = image.convert("RGB")
        # Grounding DINO accepts a nested label list and returns labels tied to
        # the same fixed prompt order, making sprite/mesh output comparable.
        labels = [[part for part in FIXED_PART_LIBRARY]]
        inputs = self.processor(images=image, text=labels, return_tensors="pt")
        inputs = {key: value.to(self.device) if hasattr(value, "to") else value for key, value in inputs.items()}
        with self.torch.inference_mode():
            outputs = self.model(**inputs)
        result = self.processor.post_process_grounded_object_detection(
            outputs,
            inputs["input_ids"],
            threshold=self.box_threshold,
            text_threshold=self.text_threshold,
            target_sizes=[(image.height, image.width)],
        )[0]
        boxes = result["boxes"].detach().float().cpu().numpy()
        scores = result["scores"].detach().float().cpu().numpy()
        detected_labels = result["labels"]
        out = []
        for box, score, label in zip(boxes, scores, detected_labels):
            normalized = str(label).lower().strip().rstrip(".")
            part = next((candidate for candidate in FIXED_PART_LIBRARY if candidate in normalized), normalized)
            if part in FIXED_PART_LIBRARY:
                out.append(PartBox(part, tuple(float(v) for v in box), float(score)))
        return out


def best_by_part(boxes: Iterable[PartBox]) -> dict[str, PartBox]:
    best: dict[str, PartBox] = {}
    for box in boxes:
        if box.part not in best or box.score > best[box.part].score:
            best[box.part] = box
    return best


def box_iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0, ix1, iy1 = max(ax0, bx0), max(ay0, by0), min(ax1, bx1), min(ay1, by1)
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    return inter / max(area_a + area_b - inter, 1e-6)


def part_alignment(target: Iterable[PartBox], mesh: Iterable[PartBox]) -> dict:
    target_map, mesh_map = best_by_part(target), best_by_part(mesh)
    parts = sorted(set(target_map) | set(mesh_map))
    matches = []
    for part in parts:
        t, m = target_map.get(part), mesh_map.get(part)
        if t is None or m is None:
            score = 0.0
            present = False
        else:
            score = box_iou(t.box, m.box)
            present = True
        matches.append({"part": part, "score": score, "present": present})
    weighted = sum(row["score"] for row in matches) / max(len(matches), 1)
    return {"score": float(weighted), "parts": matches, "targetCount": len(target_map), "meshCount": len(mesh_map)}


def draw_boxes(image: Image.Image, boxes: Iterable[PartBox], out: Path, title: str) -> None:
    image = image.convert("RGBA").copy()
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    for item in boxes:
        x0, y0, x1, y1 = item.box
        color = (40, 230, 255, 255)
        draw.rectangle((x0, y0, x1, y1), outline=color, width=3)
        label = f"{item.part} {item.score:.2f}"
        bbox = draw.textbbox((x0, max(0, y0 - 12)), label, font=font)
        draw.rectangle(bbox, fill=(8, 8, 12, 235))
        draw.text((x0, max(0, y0 - 12)), label, fill=color, font=font)
    draw.rectangle((6, 6, 6 + max(180, len(title) * 6), 21), fill=(8, 8, 12, 235))
    draw.text((10, 9), title, fill=(245, 245, 245, 255), font=font)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)


def write_boxes(path: Path, boxes: Iterable[PartBox], *, image: Path, device: str, model_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "image": str(image),
        "device": device,
        "model": model_id,
        "parts": [box.as_dict() for box in boxes],
        "library": list(FIXED_PART_LIBRARY),
        "proof": "local GPU zero-shot anatomical detection; detector output is not runtime proof",
    }, indent=2) + "\n", encoding="utf-8")
