#!/usr/bin/env python3
"""Local GPU image-embedding comparison for Roc sprite/mesh previews."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

import numpy as np
from PIL import Image


def require_cuda():
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("Semantic image embeddings require CUDA; refusing CPU inference.")
    return torch.device("cuda:0")


def normalize_embedding_layers(
    embedding_layer: str = "projected",
    embedding_layers: Sequence[str] | str | None = None,
) -> tuple[str, ...]:
    """Return unique canonical layer names in the order requested.

    ``embedding_layer`` is the historical single-layer API.  The plural form
    is the authoritative configuration for multi-layer cosine scoring.  The
    projected aliases all refer to the same model output, so selecting two of
    them must not silently give that output extra weight.
    """
    if embedding_layers is None:
        raw_layers = [embedding_layer]
    elif isinstance(embedding_layers, str):
        raw_layers = [part.strip() for part in embedding_layers.split(",")]
    else:
        raw_layers = list(embedding_layers)
    if not raw_layers:
        raise ValueError("embedding_layers must contain at least one layer")

    aliases = {
        "image_embeds": "projected",
        "model": "projected",
        "last_hidden_state": "last",
    }
    normalized = []
    for raw in raw_layers:
        layer = str(raw).strip().lower()
        if not layer:
            raise ValueError("embedding_layers cannot contain an empty layer name")
        layer = aliases.get(layer, layer)
        if layer not in {"projected", "pooler", "last"} and not layer.startswith("hidden:"):
            raise ValueError(
                f"unknown embedding layer {raw!r}; use projected, pooler, last, or hidden:<index>"
            )
        if layer.startswith("hidden:"):
            try:
                int(layer.split(":", 1)[1])
            except ValueError as exc:
                raise ValueError(f"invalid hidden-state layer {raw!r}") from exc
        if layer not in normalized:
            normalized.append(layer)
    return tuple(normalized)


class RocSemanticEmbedder:
    """Vision embeddings, kept local and batchable on the GPU."""

    def __init__(
        self,
        model_id: str = "openai/clip-vit-base-patch32",
        *,
        embedding_layer: str = "projected",
        embedding_layers: Sequence[str] | str | None = None,
        pooling: str = "model",
        subject_crop: bool = False,
        subject_padding_frac: float = 0.18,
    ):
        import torch
        from transformers import AutoModel, AutoProcessor, CLIPVisionModelWithProjection

        self.device = require_cuda()
        self.model_id = model_id
        self.embedding_layers = normalize_embedding_layers(embedding_layer, embedding_layers)
        # Compatibility for callers that inspect the old singular attribute.
        self.embedding_layer = self.embedding_layers[0]
        self.pooling = str(pooling).strip().lower()
        self.subject_crop = bool(subject_crop)
        self.subject_padding_frac = float(subject_padding_frac)
        self.processor = AutoProcessor.from_pretrained(model_id)
        if "siglip" in model_id.lower():
            # SigLIP2 exposes image features through AutoModel rather than
            # CLIPVisionModelWithProjection.image_embeds.
            self.model = AutoModel.from_pretrained(model_id).to(self.device).eval()
            self._feature_mode = "get_image_features"
        else:
            self.model = CLIPVisionModelWithProjection.from_pretrained(model_id).to(self.device).eval()
            self._feature_mode = "image_embeds"
        self.torch = torch

    def _images_for_encoder(self, images: list[Image.Image]) -> list[Image.Image]:
        if not self.subject_crop:
            return images
        # Cropping is opt-in because it removes position and scale information
        # that may be useful to the pose objective.
        return [self.load_subject_image_from_image(image, self.subject_padding_frac) for image in images]

    @staticmethod
    def load_subject_image_from_image(image: Image.Image, padding_frac: float) -> Image.Image:
        rgba = image.convert("RGBA")
        arr = np.asarray(rgba, dtype=np.int16)
        alpha = arr[:, :, 3]
        mask = alpha > 8 if int(alpha.min()) < 250 else np.linalg.norm(
            arr[:, :, :3].astype(np.float32) - np.median(arr[:8, :8, :3], axis=(0, 1)), axis=2
        ) > 18
        ys, xs = np.where(mask)
        if len(xs) == 0:
            return image.convert("RGB")
        x0, x1, y0, y1 = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
        pad = int(round(max(x1 - x0, y1 - y0) * float(padding_frac)))
        crop = rgba.crop((max(0, x0 - pad), max(0, y0 - pad), min(rgba.width, x1 + pad), min(rgba.height, y1 + pad)))
        side = max(crop.width, crop.height)
        canvas = Image.new("RGBA", (side, side), (32, 32, 32, 255))
        canvas.alpha_composite(crop, ((side - crop.width) // 2, (side - crop.height) // 2))
        return canvas.convert("RGB")

    @staticmethod
    def load_image(path: Path) -> Image.Image:
        rgba = Image.open(path).convert("RGBA")
        # Use the same neutral background for sprite and mesh previews. Do not
        # feed transparent RGB payloads into the semantic encoder.
        background = Image.new("RGBA", rgba.size, (32, 32, 32, 255))
        return Image.alpha_composite(background, rgba).convert("RGB")

    @staticmethod
    def subject_bbox(path: Path, *, alpha_threshold: int = 8, color_threshold: int = 18) -> tuple[int, int, int, int]:
        bbox, _meta = RocSemanticEmbedder.subject_bbox_with_meta(
            path,
            alpha_threshold=alpha_threshold,
            color_threshold=color_threshold,
        )
        return bbox

    @staticmethod
    def subject_bbox_with_meta(
        path: Path, *, alpha_threshold: int = 8, color_threshold: int = 18
    ) -> tuple[tuple[int, int, int, int], dict]:
        rgba = Image.open(path).convert("RGBA")
        arr = np.asarray(rgba, dtype=np.int16)
        alpha = arr[:, :, 3]
        if int(alpha.min()) < 250:
            mask = alpha > int(alpha_threshold)
            mode = "alpha"
            bg = None
        else:
            rgb = arr[:, :, :3]
            corners = np.concatenate(
                [
                    rgb[:8, :8].reshape(-1, 3),
                    rgb[:8, -8:].reshape(-1, 3),
                    rgb[-8:, :8].reshape(-1, 3),
                    rgb[-8:, -8:].reshape(-1, 3),
                ],
                axis=0,
            )
            bg = np.median(corners, axis=0)
            mask = np.linalg.norm(rgb.astype(np.float32) - bg.astype(np.float32), axis=2) > float(color_threshold)
        ys, xs = np.where(mask)
        meta = {
            "path": str(path),
            "mode": mode if int(alpha.min()) < 250 else "corner_color",
            "imageSize": [rgba.width, rgba.height],
            "maskPixels": int(len(xs)),
            "backgroundRgb": None if bg is None else [float(x) for x in bg],
        }
        if len(xs) == 0:
            meta["fallbackFullCanvas"] = True
            bbox = (0, 0, rgba.width, rgba.height)
        else:
            meta["fallbackFullCanvas"] = False
            bbox = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
        meta["bbox"] = list(bbox)
        return bbox, meta

    @classmethod
    def load_subject_image(cls, path: Path, *, padding_frac: float = 0.18) -> Image.Image:
        rgba = Image.open(path).convert("RGBA")
        x0, y0, x1, y1 = cls.subject_bbox(path)
        w, h = x1 - x0, y1 - y0
        pad = int(round(max(w, h) * float(padding_frac)))
        x0 = max(0, x0 - pad)
        y0 = max(0, y0 - pad)
        x1 = min(rgba.width, x1 + pad)
        y1 = min(rgba.height, y1 + pad)
        crop = rgba.crop((x0, y0, x1, y1))
        side = max(crop.width, crop.height)
        canvas = Image.new("RGBA", (side, side), (32, 32, 32, 255))
        canvas.alpha_composite(crop, ((side - crop.width) // 2, (side - crop.height) // 2))
        return canvas.convert("RGB")

    def embed_layers(self, images: list[Image.Image]) -> dict[str, np.ndarray]:
        """Return normalized image vectors for every configured layer.

        All configured layers share one processor pass and, for hidden-state
        selections, one vision forward pass.  Cosines must be computed per
        layer because projected and hidden vectors can have different widths;
        callers should average those scalar cosines rather than concatenating
        or averaging the vectors themselves.
        """
        images = self._images_for_encoder(images)
        inputs = self.processor(images=images, return_tensors="pt")
        pixels = inputs["pixel_values"].to(self.device)
        outputs: dict[str, np.ndarray] = {}
        with self.torch.inference_mode():
            projected = None
            vision_output = None
            needs_projected = "projected" in self.embedding_layers
            needs_hidden = any(layer != "projected" for layer in self.embedding_layers)
            # Ask the model for hidden states in the same forward pass as the
            # pooled/projected output whenever the backend exposes both. This
            # keeps multi-layer scoring from multiplying encoder inference cost.
            if self._feature_mode == "get_image_features":
                model_output = self.model.get_image_features(
                    pixel_values=pixels,
                    output_hidden_states=needs_hidden,
                    return_dict=True,
                )
                if hasattr(model_output, "shape"):
                    projected = model_output
                else:
                    image_embeds = getattr(model_output, "image_embeds", None)
                    projected = image_embeds if image_embeds is not None else getattr(model_output, "pooler_output", None)
                    if needs_hidden and hasattr(model_output, "hidden_states"):
                        vision_output = model_output
            elif needs_projected or needs_hidden:
                model_output = self.model(
                    pixel_values=pixels,
                    output_hidden_states=needs_hidden,
                    return_dict=True,
                )
                projected = getattr(model_output, "image_embeds", None)
                if needs_hidden:
                    vision_output = model_output
            for layer in self.embedding_layers:
                if layer == "projected":
                    vectors = projected
                    if vectors is None:
                        raise RuntimeError("vision model did not return projected image features")
                else:
                    if vision_output is None:
                        vision = getattr(self.model, "vision_model", self.model)
                        vision_output = vision(pixel_values=pixels, output_hidden_states=True, return_dict=True)
                    if layer == "pooler":
                        vectors = vision_output.pooler_output
                    elif layer == "last":
                        hidden = vision_output.last_hidden_state
                        vectors = hidden[:, 0] if self.pooling in {"cls", "token", "first"} else hidden.mean(dim=1)
                    else:
                        index = int(layer.split(":", 1)[1])
                        hidden = vision_output.hidden_states[index]
                        vectors = hidden[:, 0] if self.pooling in {"cls", "token", "first"} else hidden.mean(dim=1)
                    if vectors is None:
                        raise RuntimeError(f"vision model did not return vectors for layer {layer!r}")
                vectors = self.torch.nn.functional.normalize(vectors, dim=-1)
                outputs[layer] = vectors.detach().float().cpu().numpy()
        return outputs

    def embed(self, images: list[Image.Image]) -> np.ndarray:
        """Return the single configured layer for the legacy API.

        Multi-layer callers must use :meth:`embed_layers` and average their
        per-layer cosine scores.  Raising here prevents an accidental silent
        fallback to only the first selected layer.
        """
        if len(self.embedding_layers) != 1:
            raise ValueError(
                "embed() is only valid for one selected layer; use embed_layers() "
                "and average per-layer cosine scores"
            )
        return next(iter(self.embed_layers(images).values()))

    def embed_text(self, texts: list[str]) -> np.ndarray:
        """Encode text with the paired text tower for optional prompt scoring."""
        inputs = self.processor(text=texts, padding=True, return_tensors="pt")
        model_inputs = {
            key: value.to(self.device)
            for key, value in inputs.items()
            if hasattr(value, "to")
        }
        with self.torch.inference_mode():
            if hasattr(self.model, "get_text_features"):
                vectors = self.model.get_text_features(**model_inputs)
                if not hasattr(vectors, "shape"):
                    text_embeds = getattr(vectors, "text_embeds", None)
                    vectors = text_embeds if text_embeds is not None else getattr(vectors, "pooler_output", None)
            else:
                raise RuntimeError(f"model {self.model_id!r} does not expose a text feature path")
            if vectors is None:
                raise RuntimeError("text feature output has no tensor")
            vectors = self.torch.nn.functional.normalize(vectors, dim=-1)
        return vectors.detach().float().cpu().numpy()

    def compare_pairs(self, pairs: list[tuple[Path, Path]], batch_size: int = 16) -> list[dict]:
        rows = []
        for start in range(0, len(pairs), batch_size):
            batch = pairs[start:start + batch_size]
            images = [self.load_image(path) for pair in batch for path in pair]
            layer_vectors = self.embed_layers(images)
            layer_scores = {
                layer: (
                    vectors.reshape(len(batch), 2, -1)[:, 0, :]
                    * vectors.reshape(len(batch), 2, -1)[:, 1, :]
                ).sum(axis=1)
                for layer, vectors in layer_vectors.items()
            }
            scores = np.mean(np.stack(list(layer_scores.values()), axis=0), axis=0)
            for local_index, ((target, mesh), score) in enumerate(zip(batch, scores)):
                rows.append({
                    "target": str(target),
                    "mesh": str(mesh),
                    "cosine": float(score),
                    "distance": float(1.0 - score),
                    "embeddingLayers": list(self.embedding_layers),
                    "layerCosines": {
                        layer: float(values[local_index])
                        for layer, values in layer_scores.items()
                    },
                })
        return rows


def compare_directories(
    target_dir: Path,
    mesh_dir: Path,
    out: Path,
    *,
    model_id: str = "openai/clip-vit-base-patch32",
    embedding_layer: str = "projected",
    embedding_layers: Sequence[str] | str | None = None,
    batch_size: int = 16,
) -> dict:
    target_paths = sorted(Path(target_dir).glob("*.png"))
    pairs = []
    for target in target_paths:
        mesh = Path(mesh_dir) / f"mesh_{target.stem}.png"
        if not mesh.exists():
            mesh = Path(mesh_dir) / target.name
        if mesh.exists():
            pairs.append((target, mesh))
    if not pairs:
        raise RuntimeError(f"No matching target/mesh PNG pairs: {target_dir} vs {mesh_dir}")
    encoder = RocSemanticEmbedder(
        model_id=model_id,
        embedding_layer=embedding_layer,
        embedding_layers=embedding_layers,
    )
    rows = encoder.compare_pairs(pairs, batch_size=batch_size)
    report = {
        "model": model_id,
        "device": str(encoder.device),
        "embeddingLayers": list(encoder.embedding_layers),
        "pairs": rows,
        "meanCosine": float(np.mean([row["cosine"] for row in rows])),
        "proof": "local GPU image embeddings; semantic comparison only",
    }
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
