"""HoMM3 / HotA VCMI JSON+PNG transparency helpers.

HotA battle sequences shipped as shared-palette mode-P PNGs (e.g. COLGOIX /
CJUGGER) encode transparency in the first eight special palette indices.
Index 0 is typically pure cyan (#00FFFF). These PNGs usually have no tRNS
chunk, so Pillow ``Image.convert("RGBA")`` leaves the cyan key fully opaque.

DEF extraction already applies special-slot alpha in ``defextract_py3``.
JSON+PNG production paths must apply the same index-based contract before
RIFE / Unity ingest. Do not revive picker ``lab_png_palette`` RGBA palette
reconstruction for discovering remaps — that path is preview-only.
"""

from __future__ import annotations

from PIL import Image

# All eight VCMI special slots -> neutral black + alpha.
# Slots 2/3 can be classic magenta keys (COLGOIX) or remapped near-black
# shadow indices (CJUGGER); both must become alpha, never opaque RGB.
SPECIAL_SLOT_ALPHA: dict[int, int] = {
	0: 0,
	1: 32,
	2: 48,
	3: 80,
	4: 128,
	5: 0,
	6: 128,
	7: 64,
}


def mode_p_to_rgba_special_slots(image: Image.Image) -> Image.Image:
	"""Convert a mode-P HotA frame to RGBA using special-slot index alpha."""
	if image.mode != "P":
		raise ValueError(f"expected mode-P frame, got {image.mode}")
	indices = image.copy()
	rgba = image.convert("RGBA")
	pixel_indices = (
		indices.get_flattened_data() if hasattr(indices, "get_flattened_data") else indices.getdata()
	)
	pixels = list(rgba.get_flattened_data() if hasattr(rgba, "get_flattened_data") else rgba.getdata())
	normalized = []
	for pixel, index in zip(pixels, pixel_indices):
		if index in SPECIAL_SLOT_ALPHA:
			normalized.append((0, 0, 0, SPECIAL_SLOT_ALPHA[index]))
		else:
			normalized.append(pixel)
	rgba.putdata(normalized)
	return rgba


def is_opaque_key_cyan(r: int, g: int, b: int, a: int, *, alpha_min: int = 200) -> bool:
	return a >= alpha_min and r < 40 and g > 200 and b > 200


def assert_rgba_transparency_contract(image: Image.Image, label: str, *, allow_empty: bool = False) -> None:
	"""Fail-closed: require true alpha and no opaque cyan key plate.

	Some HotA death/empty frames are intentionally all special-slot / fully
	transparent; pass allow_empty=True for those, but still reject cyan plates.
	"""
	rgba = image.convert("RGBA")
	pixels = list(rgba.get_flattened_data() if hasattr(rgba, "get_flattened_data") else rgba.getdata())
	if not pixels:
		raise RuntimeError(f"{label}: empty frame")
	alpha0 = sum(1 for p in pixels if p[3] == 0)
	opaque = sum(1 for p in pixels if p[3] >= 200)
	cyan_opaque = sum(1 for r, g, b, a in pixels if is_opaque_key_cyan(r, g, b, a))
	if cyan_opaque > 64:
		raise RuntimeError(
			f"{label}: opaque cyan key plate still present ({cyan_opaque} pixels); "
			"JSON+PNG special-slot alpha was not applied"
		)
	if opaque < 1:
		if allow_empty and alpha0 == len(pixels):
			return
		if allow_empty and opaque < 1 and cyan_opaque == 0 and alpha0 > 0:
			# Soft-shadow-only frame (no solid subject) is acceptable.
			return
		raise RuntimeError(f"{label}: no opaque subject pixels after special-slot alpha convert")
	if alpha0 < 1:
		raise RuntimeError(f"{label}: no fully transparent pixels after special-slot alpha convert")
	w, h = rgba.size
	for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
		r, g, b, a = rgba.getpixel((x, y))
		if a != 0:
			raise RuntimeError(f"{label}: corner ({x},{y}) is not transparent: {(r, g, b, a)}")



def open_sprite_rgba(path) -> Image.Image:
	"""Load a sprite PNG as RGBA, applying special-slot alpha for mode-P inputs."""
	image = Image.open(path)
	if image.mode == "P":
		rgba = mode_p_to_rgba_special_slots(image)
		assert_rgba_transparency_contract(rgba, str(path))
		return rgba
	return image.convert("RGBA")
