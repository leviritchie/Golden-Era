"""Load HoMM3 DEF sprite frames from canonical frames.json sources with cmp_*.png fallback."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]


def _crop_and_fill(rgb: np.ndarray, fg_mask: np.ndarray, bg_rgb: tuple[int, int, int], pad: int = 4) -> np.ndarray | None:
    ys, xs = np.where(fg_mask)
    if len(xs) < 16:
        return None
    y0 = max(0, int(ys.min()) - pad)
    y1 = min(rgb.shape[0], int(ys.max()) + pad + 1)
    x0 = max(0, int(xs.min()) - pad)
    x1 = min(rgb.shape[1], int(xs.max()) + pad + 1)
    crop_rgb = rgb[y0:y1, x0:x1].copy()
    crop_fg = fg_mask[y0:y1, x0:x1]
    crop_rgb[~crop_fg] = list(bg_rgb)
    return crop_rgb


def extract_sprite_from_source(src_path: Path, bg_rgb: tuple[int, int, int]) -> np.ndarray | None:
    """Extract creature RGB from native DEF PNG (alpha >= 200 drops HoMM3 64/128 shadows)."""
    im = Image.open(src_path)
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        rgba = np.array(im.convert("RGBA"))
        fg = rgba[..., 3] >= 200
        return _crop_and_fill(rgba[..., :3], fg, bg_rgb)
    arr = np.array(im.convert("RGB"))
    bg = arr[0, 0]
    fg = np.any(np.abs(arr.astype(int) - bg.astype(int)) > 6, axis=-1)
    return _crop_and_fill(arr, fg, bg_rgb)


def extract_sprite_from_cmp(cmp_path: Path, bg_rgb: tuple[int, int, int]) -> np.ndarray | None:
    """Extract left-strip HoMM3 DEF sprite from legacy cmp_*.png render."""
    arr = np.array(Image.open(cmp_path).convert("RGB"))
    q = arr[26:, : arr.shape[1] // 4]
    if q.size == 0:
        return None
    bg = q[0, 0]
    fg = np.any(np.abs(q.astype(int) - bg.astype(int)) > 6, axis=-1)
    return _crop_and_fill(q, fg, bg_rgb)


# Units whose DEF retarget data lives under another sid (same creature, separate slice).
DEF_SID_ALIASES = {"toa_boar_rider": "h3_boar_rider"}


ALT_RECOLOR_REFS = "artifacts/homm3_alt_recolor_refs"


def resolve_def_sources(unit: str, repo_root: Path) -> tuple[str, list[Path]]:
    """Return ('sources'|'cmp', paths) or fail closed with FileNotFoundError.

    HotA alt upgrades (``*_upg_alt``) use their owner-approved material_class_hs sprite recolor
    (build_alt_recolor_refs.py), never the raw lab frames: those are the plain HotA upgrade's colours."""
    if unit.endswith("_upg_alt"):
        ref_dir = repo_root / ALT_RECOLOR_REFS / unit
        meta = ref_dir / "meta.json"
        if not meta.is_file():
            raise FileNotFoundError(
                f"{unit}: alt-upgrade recolor refs missing ({meta}); run tools/homm3_retexture_pbr/build_alt_recolor_refs.py")
        frames = [ref_dir / n for n in json.loads(meta.read_text(encoding="utf-8"))["frames"]]
        if not frames or not all(p.is_file() for p in frames):
            raise FileNotFoundError(f"{unit}: alt-upgrade recolor refs incomplete under {ref_dir}")
        return "sources", frames
    try:
        return _resolve_def_sources_exact(unit, repo_root)
    except FileNotFoundError:
        if unit not in DEF_SID_ALIASES:
            raise
        return _resolve_def_sources_exact(DEF_SID_ALIASES[unit], repo_root)


def _resolve_def_sources_exact(unit: str, repo_root: Path) -> tuple[str, list[Path]]:
    retarg = repo_root / "artifacts/homm3_def_retarget" / unit
    frames_json = retarg / f"{unit}_def_retarget.blend.frames.json"
    if frames_json.is_file():
        data = json.loads(frames_json.read_text(encoding="utf-8"))
        seen: set[Path] = set()
        resolved: list[Path] = []
        for raw in data.get("sources") or []:
            if not isinstance(raw, str) or not raw.strip():
                continue
            p = Path(raw)
            if not p.is_absolute():
                p = repo_root / p
            if p.is_file() and p not in seen:
                seen.add(p)
                resolved.append(p)
        if resolved:
            return "sources", resolved

    cmps = sorted((retarg / "renders").glob("cmp_*.png"))
    if cmps:
        return "cmp", cmps

    raise FileNotFoundError(
        f"{unit}: neither readable frames.json sources nor renders/cmp_*.png found under {retarg}"
    )


def _extract_by_kind(kind: str, path: Path, bg_rgb: tuple[int, int, int]) -> np.ndarray | None:
    if kind == "sources":
        return extract_sprite_from_source(path, bg_rgb)
    return extract_sprite_from_cmp(path, bg_rgb)


def pick_diverse_def_crops(
    unit: str,
    repo_root: Path = DEFAULT_REPO_ROOT,
    count: int = 4,
    bg_rgb: tuple[int, int, int] = (127, 127, 127),
) -> list[tuple[int, np.ndarray]]:
    """Pick `count` visually distinct DEF sprite crops evenly across a unit's animation."""
    kind, paths = resolve_def_sources(unit, repo_root)
    n = len(paths)
    cand_indices = sorted({
        0, max(0, min(n - 1, n // 8)), min(n - 1, n // 4), min(n - 1, (3 * n) // 8),
        min(n - 1, n // 2), min(n - 1, (5 * n) // 8), min(n - 1, (3 * n) // 4), max(0, n - 4),
    })
    order = cand_indices + [i for i in range(n) if i not in cand_indices]

    picks: list[tuple[int, np.ndarray]] = []
    seen_sigs: list[np.ndarray] = []
    for idx in order:
        crop = _extract_by_kind(kind, paths[idx], bg_rgb)
        if crop is None:
            continue
        sig = np.array(Image.fromarray(crop).resize((24, 24), Image.Resampling.BILINEAR), dtype=np.float32)
        if not seen_sigs or all(np.mean(np.abs(sig - s)) > 3.5 for s in seen_sigs):
            picks.append((idx, crop))
            seen_sigs.append(sig)
        if len(picks) == count:
            break

    while len(picks) < count:
        idx = len(picks) % n
        crop = _extract_by_kind(kind, paths[idx], bg_rgb)
        if crop is None:
            crop = np.full((64, 64, 3), bg_rgb, dtype=np.uint8)
        picks.append((idx, crop))
    return picks


def make_single_def_tile(
    unit: str,
    repo_root: Path = DEFAULT_REPO_ROOT,
    tile_size: int = 384,
    bg_rgb: tuple[int, int, int] = (44, 46, 44),
) -> Image.Image:
    """Render one crisp nearest-neighbor upscaled HoMM3 DEF tile centered on `bg_rgb`."""
    kind, paths = resolve_def_sources(unit, repo_root)
    crop = None
    for p in paths:
        crop = _extract_by_kind(kind, p, bg_rgb)
        if crop is not None:
            break
    if crop is None:
        return Image.new("RGB", (tile_size, tile_size), bg_rgb)
    im = Image.fromarray(crop)
    sc = max(1, min((tile_size - 40) // max(1, im.width), (tile_size - 40) // max(1, im.height)))
    up = im.resize((im.width * sc, im.height * sc), Image.Resampling.NEAREST)
    canvas = Image.new("RGB", (tile_size, tile_size), bg_rgb)
    canvas.paste(up, ((tile_size - up.width) // 2, (tile_size - up.height) // 2))
    return canvas
