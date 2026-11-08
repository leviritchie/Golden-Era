#!/usr/bin/env python3
"""GPU local anatomical box detection and alignment for the Roc experiment.

This is intentionally a local, zero-shot detector lane.  It does not call a
remote vision API.  Grounding DINO is loaded through Transformers and fails
closed when CUDA is unavailable. The approved vocabulary is shared by sprite
and mesh detections, while the prominent feature subset is generated per
sprite frame so no human-authored per-frame list is required.
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
    # L/R is biological laterality in the creature's own frame, never the
    # screen-space left/right of a profile render. Profile limbs can cross in
    # 2D, so screen X is not a valid identity signal.
    side: str | None = None

    def as_dict(self):
        return asdict(self)


LATERAL_PARTS = frozenset({
    "eye",
    "shoulder",
    "upper wing",
    "lower wing",
    "wing tip",
    "upper leg",
    "knee",
    "lower leg",
    "ankle",
    "foot",
    "talon",
})


def _part_label(item: PartBox | tuple[str, str | None]) -> str:
    part, side = (item.part, item.side) if isinstance(item, PartBox) else item
    return f"{part} [{side}]" if side in {"L", "R"} else str(part)


def _depth_array(depth: Image.Image | np.ndarray | None) -> np.ndarray | None:
    if depth is None:
        return None
    if isinstance(depth, Image.Image):
        array = np.asarray(depth, dtype=np.float32)
    else:
        array = np.asarray(depth, dtype=np.float32)
    if array.ndim == 3:
        array = array[:, :, 0]
    if array.ndim != 2:
        raise ValueError(f"laterality depth must be a 2D image, got shape {array.shape}")
    if array.size and float(np.nanmax(array)) > 1.5:
        array = array / (65535.0 if float(np.nanmax(array)) > 255.5 else 255.0)
    return np.clip(array, 0.0, 1.0)


def _box_depth(depth: np.ndarray, box: tuple[float, float, float, float]) -> float | None:
    height, width = depth.shape
    x0 = max(0, min(width, int(np.floor(box[0]))))
    y0 = max(0, min(height, int(np.floor(box[1]))))
    x1 = max(x0 + 1, min(width, int(np.ceil(box[2]))))
    y1 = max(y0 + 1, min(height, int(np.ceil(box[3]))))
    values = depth[y0:y1, x0:x1]
    values = values[np.isfinite(values) & (values > 0.01)]
    if values.size == 0:
        return None
    # Median is less sensitive to the detector box including a background
    # strip or a single badly predicted foreground pixel.
    return float(np.median(values))


def _subject_depth_reference(
    depth: np.ndarray,
    image: Image.Image | None,
    boxes: Iterable[PartBox],
) -> float | None:
    values = []
    if image is not None and "A" in image.getbands():
        alpha = np.asarray(image.getchannel("A"), dtype=np.uint8)
        if alpha.shape == depth.shape:
            visible = depth[(alpha >= 20) & np.isfinite(depth) & (depth > 0.01)]
            if visible.size:
                return float(np.median(visible))
    for item in boxes:
        value = _box_depth(depth, item.box)
        if value is not None:
            values.append(value)
    return float(np.median(values)) if values else None


def assign_laterality(
    boxes: Iterable[PartBox],
    *,
    image: Image.Image | None = None,
    depth: Image.Image | np.ndarray | None = None,
    enabled: bool = True,
    near_side: str = "R",
    depth_margin: float = 0.04,
    center_margin_frac: float | None = None,
) -> list[PartBox]:
    """Attach biological L/R using profile depth, never screen X.

    ``near_side`` comes from the authored profile-camera contract. In the
    current bird-right profile, the camera-near side is biological R. When two
    detections of one lateral part are visible, their depth rank provides the
    identity even when their 2D positions have crossed. A lone detection is
    assigned only when it is sufficiently nearer/farther than the subject
    depth reference; otherwise it remains unsided instead of becoming a false
    positive. With no depth input, this function deliberately leaves sides
    unset rather than falling back to image-space laterality.
    """
    if not enabled:
        return list(boxes)
    near_side = str(near_side).upper().strip()
    if near_side not in {"L", "R"}:
        raise ValueError(f"near_side must be 'L' or 'R', got {near_side!r}")
    far_side = "L" if near_side == "R" else "R"
    depth_array = _depth_array(depth)
    source = list(boxes)
    if depth_array is None:
        return [
            item if item.part not in LATERAL_PARTS else PartBox(item.part, item.box, item.score, None)
            for item in source
        ]
    reference = _subject_depth_reference(depth_array, image, source)
    margin = max(0.0, float(depth_margin))
    groups: dict[str, list[tuple[int, float]]] = {}
    for index, item in enumerate(source):
        if item.part in LATERAL_PARTS:
            value = _box_depth(depth_array, item.box)
            if value is not None:
                groups.setdefault(item.part, []).append((index, value))
    side_by_index: dict[int, str] = {}
    for group in groups.values():
        # Depth files use near=bright. Ranking is the identity cue, so this
        # remains valid even if both limbs exchange their screen-space X.
        ordered = sorted(group, key=lambda pair: pair[1], reverse=True)
        if len(ordered) >= 2:
            side_by_index[ordered[0][0]] = near_side
            side_by_index[ordered[-1][0]] = far_side
            # Any middle detections are ambiguous and must not inherit a
            # side merely because the detector returned them in some order.
    if reference is not None:
        for index, item in enumerate(source):
            if index in side_by_index or item.part not in LATERAL_PARTS:
                continue
            value = _box_depth(depth_array, item.box)
            if value is None:
                continue
            if value >= reference + margin:
                side_by_index[index] = near_side
            elif value <= reference - margin:
                side_by_index[index] = far_side
    return [
        item if item.part not in LATERAL_PARTS else PartBox(
            item.part,
            item.box,
            item.score,
            side_by_index.get(index),
        )
        for index, item in enumerate(source)
    ]


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

    def detect(
        self,
        image: Image.Image | np.ndarray,
        *,
        allowed_parts: Iterable[str] | None = None,
        laterality_enabled: bool = True,
        laterality_depth: Image.Image | np.ndarray | None = None,
        laterality_near_side: str = "R",
        laterality_depth_margin: float = 0.04,
        laterality_center_margin_frac: float | None = None,
    ) -> list[PartBox]:
        if isinstance(image, np.ndarray):
            image = Image.fromarray(image.astype(np.uint8), "RGBA" if image.shape[-1] == 4 else "RGB")
        # Preserve alpha for the subject-depth reference before converting to
        # RGB for Grounding DINO.
        source_image = image
        image = image.convert("RGB")
        # Grounding DINO accepts a nested label list and returns labels tied to
        # the same fixed prompt order, making sprite/mesh output comparable.
        vocabulary = tuple(FIXED_PART_LIBRARY if allowed_parts is None else allowed_parts)
        if not vocabulary:
            return []
        labels = [[part for part in vocabulary]]
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
            part = next((candidate for candidate in vocabulary if candidate in normalized), normalized)
            if part in vocabulary:
                out.append(PartBox(part, tuple(float(v) for v in box), float(score)))
        return assign_laterality(
            out,
            image=source_image,
            depth=laterality_depth,
            enabled=laterality_enabled,
            near_side=laterality_near_side,
            depth_margin=laterality_depth_margin,
            center_margin_frac=laterality_center_margin_frac,
        )


def best_by_part(boxes: Iterable[PartBox]) -> dict[str, PartBox]:
    best: dict[str, PartBox] = {}
    for box in boxes:
        key = (_part_label(box))
        if key not in best or box.score > best[key].score:
            best[key] = box
    return best


def select_prominent_features(
    boxes: Iterable[PartBox],
    *,
    width: int,
    height: int,
    max_features: int = 8,
    min_area_frac: float = 0.001,
) -> list[PartBox]:
    """Select a variable, frame-specific subset from the approved vocabulary.

    The detector still searches the complete approved anatomical vocabulary,
    but the objective is driven by the features that are actually visible and
    prominent in this frame. No per-frame feature list is authored by hand.
    """
    image_area = max(float(width) * float(height), 1.0)
    candidates = []
    for item in best_by_part(boxes).values():
        x0, y0, x1, y1 = item.box
        area_frac = max(0.0, x1 - x0) * max(0.0, y1 - y0) / image_area
        if area_frac < float(min_area_frac):
            continue
        # Favor confident, visible features without making the largest box
        # automatically win every frame.
        prominence = float(item.score) * max(0.1, min(1.0, area_frac * 32.0) ** 0.5)
        candidates.append((prominence, item))
    candidates.sort(key=lambda row: (-row[0], row[1].part))
    return [item for _, item in candidates[: max(0, int(max_features))]]


def box_iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0, ix1, iy1 = max(ax0, bx0), max(ay0, by0), min(ax1, bx1), min(ay1, by1)
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    return inter / max(area_a + area_b - inter, 1e-6)


def anatomical_feature_alignment(
    target: Iterable[PartBox],
    candidate: Iterable[PartBox],
    *,
    width: int,
    height: int,
    center_weight: float = 0.70,
    extent_weight: float = 0.30,
) -> dict:
    """Compare detector locations for the target-selected feature set.

    Distance is normalized to [0, 1] and combines candidate-vs-target center
    displacement with box width/height displacement. Missing candidate
    detections receive the maximum distance. Extra candidate detections do not
    change the score because the sprite defines the feature set to match.
    """
    target_map, candidate_map = best_by_part(target), best_by_part(candidate)
    rows = []
    diagonal = max(float((float(width) ** 2 + float(height) ** 2) ** 0.5), 1.0)
    weight_sum = max(float(center_weight) + float(extent_weight), 1e-6)
    center_weight = float(center_weight) / weight_sum
    extent_weight = float(extent_weight) / weight_sum
    for part_key in sorted(target_map):
        target_item = target_map[part_key]
        target_box = target_item.box
        candidate_box = candidate_map.get(part_key)
        if candidate_box is None:
            rows.append({
                "part": target_item.part,
                "side": target_item.side,
                "label": part_key,
                "distance": 1.0,
                "score": 0.0,
                "present": False,
            })
            continue
        tx = (target_box[0] + target_box[2]) * 0.5
        ty = (target_box[1] + target_box[3]) * 0.5
        cx = (candidate_box.box[0] + candidate_box.box[2]) * 0.5
        cy = (candidate_box.box[1] + candidate_box.box[3]) * 0.5
        center_distance = min(1.0, (((cx - tx) ** 2 + (cy - ty) ** 2) ** 0.5) / diagonal)
        target_w = max(target_box[2] - target_box[0], 1.0)
        target_h = max(target_box[3] - target_box[1], 1.0)
        candidate_w = max(candidate_box.box[2] - candidate_box.box[0], 1.0)
        candidate_h = max(candidate_box.box[3] - candidate_box.box[1], 1.0)
        extent_distance = min(
            1.0,
            0.5 * abs(candidate_w - target_w) / max(target_w, candidate_w)
            + 0.5 * abs(candidate_h - target_h) / max(target_h, candidate_h),
        )
        distance = min(1.0, center_weight * center_distance + extent_weight * extent_distance)
        rows.append({
            "part": target_item.part,
            "side": target_item.side,
            "label": part_key,
            "distance": float(distance),
            "score": float(1.0 - distance),
            "present": True,
            "centerDistance": float(center_distance),
            "extentDistance": float(extent_distance),
            "targetBox": tuple(float(v) for v in target_box),
            "candidateBox": tuple(float(v) for v in candidate_box.box),
        })
    mean_distance = float(sum(row["distance"] for row in rows) / max(len(rows), 1))
    return {
        "score": float(1.0 - mean_distance),
        "distance": mean_distance,
        "parts": rows,
        "targetCount": len(target_map),
        "candidateCount": len(candidate_map),
        "used": bool(target_map),
    }


def part_alignment(target: Iterable[PartBox], mesh: Iterable[PartBox]) -> dict:
    """Legacy pixel-IoU wrapper retained for older callers."""
    target_map, mesh_map = best_by_part(target), best_by_part(mesh)
    parts = sorted(set(target_map) | set(mesh_map))
    matches = []
    for part in parts:
        t, m = target_map.get(part), mesh_map.get(part)
        score = box_iou(t.box, m.box) if t is not None and m is not None else 0.0
        matches.append({
            "part": t.part if t is not None else m.part,
            "side": t.side if t is not None else m.side,
            "label": part,
            "score": score,
            "present": t is not None and m is not None,
        })
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
        label = f"{_part_label(item)} {item.score:.2f}"
        bbox = draw.textbbox((x0, max(0, y0 - 12)), label, font=font)
        draw.rectangle(bbox, fill=(8, 8, 12, 235))
        draw.text((x0, max(0, y0 - 12)), label, fill=color, font=font)
    draw.rectangle((6, 6, 6 + max(180, len(title) * 6), 21), fill=(8, 8, 12, 235))
    draw.text((10, 9), title, fill=(245, 245, 245, 255), font=font)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)


def draw_feature_dot_preview(
    target_image: Image.Image,
    candidate_image: Image.Image,
    target: Iterable[PartBox],
    candidate: Iterable[PartBox],
    out: Path,
    *,
    title: str = "anatomical feature alignment",
) -> None:
    """Render a low-clutter target/candidate feature view with a side legend."""
    target_image = target_image.convert("RGB")
    candidate_image = candidate_image.convert("RGB")
    candidate_width, candidate_height = candidate_image.size
    candidate_image = candidate_image.resize(target_image.size)
    target_map, candidate_map = best_by_part(target), best_by_part(candidate)
    parts = sorted(target_map)
    palette = (
        (239, 83, 80),
        (255, 167, 38),
        (253, 216, 53),
        (102, 187, 106),
        (38, 198, 218),
        (66, 165, 245),
        (126, 87, 194),
        (236, 64, 122),
    )
    legend_width = 230
    header = 28
    canvas = Image.new(
        "RGB",
        (target_image.width * 2 + legend_width, target_image.height + header),
        (12, 12, 16),
    )
    canvas.paste(target_image, (0, header))
    canvas.paste(candidate_image, (target_image.width, header))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    draw.text((8, 8), "target RGB", fill=(240, 240, 240), font=font)
    draw.text((target_image.width + 8, 8), "candidate RGB", fill=(240, 240, 240), font=font)
    draw.text((target_image.width * 2 + 10, 8), title, fill=(240, 240, 240), font=font)

    def center(box):
        return ((float(box[0]) + float(box[2])) * 0.5, (float(box[1]) + float(box[3])) * 0.5)

    for index, part in enumerate(parts):
        color = palette[index % len(palette)]
        target_item = target_map[part]
        target_box = target_item
        tx, ty = center(target_box.box)
        radius = max(3, min(target_image.width, target_image.height) // 90)
        draw.ellipse((tx - radius, header + ty - radius, tx + radius, header + ty + radius), fill=color)
        candidate_box = candidate_map.get(part)
        if candidate_box is not None:
            cx, cy = center(candidate_box.box)
            cx *= target_image.width / max(candidate_width, 1)
            cy *= target_image.height / max(candidate_height, 1)
            draw.ellipse(
                (
                    target_image.width + cx - radius,
                    header + cy - radius,
                    target_image.width + cx + radius,
                    header + cy + radius,
                ),
                fill=color,
            )
        y = header + 12 + index * 22
        draw.rectangle(
            (target_image.width * 2 + 10, y, target_image.width * 2 + 22, y + 12),
            fill=color,
        )
        status = "matched" if candidate_box is not None else "missing"
        draw.text(
            (target_image.width * 2 + 28, y),
            f"{_part_label(target_item)} ({status})",
            fill=(235, 235, 235),
            font=font,
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    temp = out.with_suffix(out.suffix + ".tmp.png")
    canvas.save(temp, format="PNG")
    temp.replace(out)


def write_boxes(path: Path, boxes: Iterable[PartBox], *, image: Path, device: str, model_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "image": str(image),
        "device": device,
        "model": model_id,
        "parts": [box.as_dict() for box in boxes],
        "library": list(FIXED_PART_LIBRARY),
        "laterality": "image-space L/R from alpha-bounded subject center",
        "proof": "local GPU zero-shot anatomical detection; detector output is not runtime proof",
    }, indent=2) + "\n", encoding="utf-8")
