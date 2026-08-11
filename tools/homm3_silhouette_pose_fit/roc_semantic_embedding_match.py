#!/usr/bin/env python3
"""Local GPU image-embedding comparison for Roc sprite/mesh previews."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image


def require_cuda():
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("Semantic image embeddings require CUDA; refusing CPU inference.")
    return torch.device("cuda:0")


class RocSemanticEmbedder:
    """CLIP image embeddings, kept local and batchable on the GPU."""

    def __init__(self, model_id: str = "openai/clip-vit-base-patch32"):
        import torch
        from transformers import AutoModel, AutoProcessor, CLIPVisionModelWithProjection

        self.device = require_cuda()
        self.model_id = model_id
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

    @staticmethod
    def load_image(path: Path) -> Image.Image:
        rgba = Image.open(path).convert("RGBA")
        # Use the same neutral background for sprite and mesh previews. Do not
        # feed transparent RGB payloads into the semantic encoder.
        background = Image.new("RGBA", rgba.size, (32, 32, 32, 255))
        return Image.alpha_composite(background, rgba).convert("RGB")

    def embed(self, images: list[Image.Image]) -> np.ndarray:
        inputs = self.processor(images=images, return_tensors="pt")
        pixels = inputs["pixel_values"].to(self.device)
        with self.torch.inference_mode():
            if self._feature_mode == "get_image_features":
                vectors = self.model.get_image_features(pixel_values=pixels)
            else:
                vectors = self.model(pixel_values=pixels).image_embeds
            vectors = self.torch.nn.functional.normalize(vectors, dim=-1)
        return vectors.detach().float().cpu().numpy()

    def compare_pairs(self, pairs: list[tuple[Path, Path]], batch_size: int = 16) -> list[dict]:
        rows = []
        for start in range(0, len(pairs), batch_size):
            batch = pairs[start:start + batch_size]
            images = [self.load_image(path) for pair in batch for path in pair]
            vectors = self.embed(images).reshape(len(batch), 2, -1)
            scores = (vectors[:, 0, :] * vectors[:, 1, :]).sum(axis=1)
            for (target, mesh), score in zip(batch, scores):
                rows.append({"target": str(target), "mesh": str(mesh), "cosine": float(score), "distance": float(1.0 - score)})
        return rows


def compare_directories(target_dir: Path, mesh_dir: Path, out: Path, *, model_id: str = "openai/clip-vit-base-patch32", batch_size: int = 16) -> dict:
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
    encoder = RocSemanticEmbedder(model_id=model_id)
    rows = encoder.compare_pairs(pairs, batch_size=batch_size)
    report = {"model": model_id, "device": str(encoder.device), "pairs": rows, "meanCosine": float(np.mean([row["cosine"] for row in rows])), "proof": "local GPU CLIP image embeddings; semantic comparison only"}
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
