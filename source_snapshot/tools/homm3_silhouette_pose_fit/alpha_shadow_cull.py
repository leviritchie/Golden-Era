"""Content-addressed DEF/RIFE alpha-shadow cull shared by setup and GPU profile init."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

ALPHA_SHADOW_CULL_VERSION = 1


def alpha_cull_signature(source_dir, sources):
    return hashlib.sha256(
        json.dumps(
            {
                "version": ALPHA_SHADOW_CULL_VERSION,
                "sourceDir": str(Path(source_dir).resolve()),
                "files": [
                    (
                        source.name,
                        hashlib.sha256(source.read_bytes()).hexdigest(),
                    )
                    for source in sources
                ],
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def cull_alpha_shadows(source_dir, output_dir):
    """Remove the dark, grayscale, partially transparent shadow pass.

    The result is content-addressed by the source frame inventory so every
    animation initialization can reuse an already-proven cull without
    decoding and rewriting the same PNGs. A source change or cull-version
    change invalidates the entire output set rather than mixing generations.
    """
    source_dir, output_dir = Path(source_dir), Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    sources = sorted(source_dir.glob("*.png"))
    if not sources:
        raise RuntimeError(f"no source frames found for alpha shadow culling: {source_dir}")
    signature = alpha_cull_signature(source_dir, sources)
    manifest_path = output_dir / ".alpha_shadow_cull_manifest.json"
    expected_names = {source.name for source in sources}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = None
    outputs = sorted(output_dir.glob("*.png"))
    if (
        isinstance(manifest, dict)
        and manifest.get("version") == ALPHA_SHADOW_CULL_VERSION
        and manifest.get("sourceSignature") == signature
        and {output.name for output in outputs} == expected_names
    ):
        return sources, outputs
    for output in outputs:
        output.unlink(missing_ok=True)
    for source in sources:
        # PIL-backed arrays can be read-only; culling mutates alpha in place.
        rgba = np.array(Image.open(source).convert("RGBA"), dtype=np.uint8, copy=True)
        rgb = rgba[:, :, :3].astype(np.int16)
        alpha = rgba[:, :, 3]
        chroma = rgb.max(axis=2) - rgb.min(axis=2)
        value = rgb.max(axis=2)
        shadow = (alpha > 0) & (alpha < 255) & (chroma <= 10) & (value <= 70)
        rgba[shadow, 3] = 0
        Image.fromarray(rgba, "RGBA").save(output_dir / source.name, format="PNG")
    outputs = sorted(output_dir.glob("*.png"))
    if len(outputs) != len(sources):
        raise RuntimeError(f"shadow culling incomplete: {len(outputs)}/{len(sources)} outputs")
    manifest_path.write_text(
        json.dumps(
            {
                "version": ALPHA_SHADOW_CULL_VERSION,
                "sourceDirectory": str(source_dir.resolve()),
                "sourceSignature": signature,
                "frameNames": [source.name for source in sources],
                "alphaRule": "partial-alpha grayscale pixels with chroma<=10 and value<=70",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return sources, outputs
