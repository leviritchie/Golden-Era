#!/usr/bin/env python3
"""Generate Factory/Bulwark alt-upgrade sprite-edit review galleries.

Uses native HotA battle standing frames (animation group 2), not portrait icons.
Edits are material-class remaps (cloth / metal / glow / base) plus optional
pixel accents — not a single global hue filter.

Evidence level: generated sprite-edit previews from extracted battle frames.
Nothing is locked until the user picks an option.
"""

from __future__ import annotations

import argparse
import colorsys
import html
import json
import pathlib
import re
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont

from hota_zip_unit_prep import ALT_RECOLOR_GALLERIES

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT_ROOT = HERE / "recolor_galleries"
UNITY_LAB = ROOT / "oldenera_factions" / "Assets" / "CustomUnits" / "homm3_lab"
TILE = 192
PAD = 10
LABEL_H = 44


def load_json(path: pathlib.Path):
	return json.loads(path.read_text(encoding="utf-8-sig"))


def gallery_slug(gallery: dict) -> str:
	parts = [str(gallery["faction"]), f"t{gallery['tier']}", str(gallery.get("baseSid") or "unit")]
	if gallery.get("line"):
		parts.append(str(gallery["line"]))
	return "__".join(parts)


def standing_frame_path(lab_sid: str) -> pathlib.Path:
	extracted = UNITY_LAB / lab_sid / "extracted_battle"
	manifests = sorted(extracted.glob("*.json"))
	if len(manifests) != 1:
		raise FileNotFoundError(f"{lab_sid}: expected one battle manifest under {extracted}")
	manifest = load_json(manifests[0])
	group = next((row for row in manifest.get("sequences") or [] if int(row.get("group", -1)) == 2), None)
	if not group or not group.get("frames"):
		raise FileNotFoundError(f"{lab_sid}: battle animation group 2 has no frames")
	rel = pathlib.PureWindowsPath(str(group["frames"][0]))
	path = extracted.joinpath(*rel.parts)
	if not path.is_file():
		raise FileNotFoundError(f"{lab_sid}: missing standing frame {path}")
	return path


def crop_sprite(im: Image.Image, pad: int = 2) -> Image.Image:
	rgba = im.convert("RGBA")
	alpha = rgba.getchannel("A")
	bbox = alpha.getbbox()
	if bbox is None:
		raise ValueError("standing frame has no opaque pixels")
	l, t, r, b = bbox
	l = max(0, l - pad)
	t = max(0, t - pad)
	r = min(rgba.width, r + pad)
	b = min(rgba.height, b + pad)
	return rgba.crop((l, t, r, b))


def _hsv(r: int, g: int, b: int) -> tuple[float, float, float]:
	return colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)


def classify_pixel(r: int, g: int, b: int, a: int) -> str:
	"""Assign a material class. Skin/shadow stay immutable."""
	if a < 8:
		return "empty"
	# Soft ground-shadow / near-black key residue.
	if a < 140 and max(r, g, b) <= 40:
		return "preserve"
	h, s, v = _hsv(r, g, b)
	hdeg = h * 360.0
	# Skin / fur / natural flesh — keep readable faces and underbellies.
	if (
		r >= 70
		and g >= 35
		and b >= 24
		and hdeg <= 38.0
		and 0.08 <= s <= 0.62
		and (g / max(r, 1)) >= 0.50
		and (b / max(g, 1)) >= 0.70
		and v >= 0.28
	):
		return "preserve"
	# Bright spark / muzzle / rune / heat.
	if v >= 0.62 and s >= 0.42 and (hdeg <= 65.0 or hdeg >= 300.0 or 160.0 <= hdeg <= 210.0):
		return "glow"
	# Gold / brass / steel trim.
	if s >= 0.18 and v >= 0.28 and (
		(12.0 <= hdeg <= 70.0 and (r + g) > b * 1.35)
		or (s <= 0.38 and v >= 0.45)
	):
		return "metal"
	# Saturated cloth / armor plates / dyed kit.
	if s >= 0.22 and v >= 0.16:
		return "cloth"
	return "base"


def apply_class_shift(rgb: tuple[int, int, int], shift: dict | None) -> tuple[int, int, int]:
	if not shift:
		return rgb
	r, g, b = [c / 255.0 for c in rgb]
	h, s, v = colorsys.rgb_to_hsv(r, g, b)
	h = (h + float(shift.get("hue", 0.0)) / 360.0) % 1.0
	s = max(0.0, min(1.0, s * float(shift.get("sat", 1.0))))
	v = max(0.0, min(1.0, v * float(shift.get("val", 1.0))))
	rr, gg, bb = colorsys.hsv_to_rgb(h, s, v)
	return (int(round(rr * 255)), int(round(gg * 255)), int(round(bb * 255)))


def material_remap(im: Image.Image, materials: dict) -> Image.Image:
	src = im.convert("RGBA")
	pixels = list(src.getdata())
	out: list[tuple[int, int, int, int]] = []
	for r, g, b, a in pixels:
		klass = classify_pixel(r, g, b, a)
		if klass in {"empty", "preserve"}:
			out.append((r, g, b, a))
			continue
		nr, ng, nb = apply_class_shift((r, g, b), materials.get(klass))
		out.append((nr, ng, nb, a))
	dst = Image.new("RGBA", src.size)
	dst.putdata(out)
	return dst


def _put(px, w: int, h: int, x: int, y: int, color: tuple[int, int, int, int]) -> None:
	if 0 <= x < w and 0 <= y < h:
		idx = y * w + x
		# Only stamp over opaque sprite body / near it.
		base = px[idx]
		if base[3] < 20 and color[3] < 180:
			return
		if color[3] >= 220 or base[3] >= 40:
			px[idx] = color


def stamp_accents(im: Image.Image, accents: Iterable[str]) -> Image.Image:
	"""Small readable pixel accents so options are not palette-only."""
	img = im.convert("RGBA")
	w, h = img.size
	px = list(img.getdata())
	cx, cy = w // 2, h // 2

	for accent in accents or ():
		name = str(accent)
		if name == "goggles":
			# Brass goggles on hat brim (upper third).
			y0 = max(1, h // 5)
			for dx in range(-4, 5):
				_put(px, w, h, cx + dx - 3, y0, (180, 140, 60, 255))
				_put(px, w, h, cx + dx + 3, y0, (180, 140, 60, 255))
			_put(px, w, h, cx - 3, y0 + 1, (40, 70, 90, 255))
			_put(px, w, h, cx + 3, y0 + 1, (40, 70, 90, 255))
		elif name == "fuse_bundle":
			y0 = int(h * 0.62)
			x0 = max(1, cx - 8)
			for i in range(3):
				for dy in range(6):
					_put(px, w, h, x0 + i * 2, y0 + dy, (210, 190, 40, 255))
				_put(px, w, h, x0 + i * 2, y0, (255, 90, 20, 255))
		elif name == "rifle":
			x0 = min(w - 2, cx + 8)
			for dy in range(int(h * 0.25), int(h * 0.78)):
				_put(px, w, h, x0, dy, (70, 45, 25, 255))
				_put(px, w, h, x0 + 1, dy, (110, 85, 45, 255))
			_put(px, w, h, x0, int(h * 0.28), (160, 160, 170, 255))
		elif name == "scarf":
			y0 = int(h * 0.34)
			for dx in range(-6, 7):
				_put(px, w, h, cx + dx, y0, (170, 30, 30, 255))
				_put(px, w, h, cx + dx, y0 + 1, (120, 20, 20, 255))
		elif name == "canister":
			x0 = max(1, cx - 12)
			y0 = int(h * 0.48)
			for dy in range(10):
				for dx in range(5):
					_put(px, w, h, x0 + dx, y0 + dy, (90, 70, 55, 255))
			for dy in range(3):
				_put(px, w, h, x0 + 2, y0 + 2 + dy, (255, 140, 30, 255))
		elif name == "chevrons":
			y0 = int(h * 0.42)
			for i in range(3):
				yy = y0 + i * 3
				for dx in range(6):
					color = (220, 190, 40, 255) if (dx + i) % 2 == 0 else (20, 20, 20, 255)
					_put(px, w, h, cx - 8 + dx, yy, color)
					_put(px, w, h, cx - 8 + dx + 1, yy + 1, color)
		elif name == "runes":
			color = (120, 220, 255, 255)
			for ox, oy in ((-6, -4), (4, -2), (-2, 6), (6, 8), (0, 0)):
				_put(px, w, h, cx + ox, cy + oy, color)
				_put(px, w, h, cx + ox + 1, cy + oy, color)
		elif name == "violet_runes":
			color = (170, 90, 255, 255)
			for ox, oy in ((-5, -5), (5, -3), (-3, 5), (4, 7)):
				_put(px, w, h, cx + ox, cy + oy, color)
				_put(px, w, h, cx + ox, cy + oy + 1, color)
		elif name == "spikes":
			x0 = min(w - 2, int(w * 0.78))
			for i in range(4):
				y0 = int(h * 0.35) + i * 5
				for t in range(4):
					_put(px, w, h, x0 + t, y0 - t // 2, (150, 150, 160, 255))
		elif name == "coil":
			x0 = cx
			y0 = max(2, int(h * 0.18))
			for dy in range(8):
				_put(px, w, h, x0, y0 + dy, (80, 180, 255, 255))
				_put(px, w, h, x0 + 1, y0 + dy, (40, 90, 160, 255))
		elif name == "badge":
			x0, y0 = cx - 2, int(h * 0.40)
			for dx in range(-2, 3):
				for dy in range(-2, 3):
					if abs(dx) + abs(dy) <= 3:
						_put(px, w, h, x0 + dx, y0 + dy, (200, 200, 210, 255))
		elif name == "bandanna":
			y0 = int(h * 0.30)
			for dx in range(-5, 6):
				_put(px, w, h, cx + dx, y0, (180, 40, 40, 255))
		elif name == "crystal_edge":
			for y in range(int(h * 0.25), int(h * 0.75)):
				_put(px, w, h, min(w - 1, int(w * 0.82)), y, (140, 230, 255, 220))
		elif name == "frost_rim":
			for x in range(w):
				for y in range(h):
					idx = y * w + x
					r, g, b, a = px[idx]
					if a < 40:
						continue
					# Brighten rim pixels lightly toward ice.
					if x <= 1 or y <= 1 or x >= w - 2 or y >= h - 2 or (r + g + b) > 500:
						px[idx] = (
							min(255, int(r * 0.55 + 140)),
							min(255, int(g * 0.55 + 180)),
							min(255, int(b * 0.55 + 220)),
							a,
						)
		elif name == "ash_dust":
			for y in range(int(h * 0.55), h):
				for x in range(0, w, 2):
					idx = y * w + x
					r, g, b, a = px[idx]
					if a > 40:
						px[idx] = (min(255, r + 18), min(255, g + 14), min(255, b + 10), a)

	img.putdata(px)
	return img


def fit_tile(im: Image.Image, size: int = TILE) -> Image.Image:
	canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
	# Checker underlay baked into a separate layer at contact-sheet time; keep transparent here.
	copy = im.copy()
	scale = min((size - 12) / copy.width, (size - 12) / copy.height)
	nw = max(1, int(round(copy.width * scale)))
	nh = max(1, int(round(copy.height * scale)))
	copy = copy.resize((nw, nh), Image.Resampling.NEAREST)
	ox = (size - nw) // 2
	oy = (size - nh) // 2
	canvas.paste(copy, (ox, oy), copy)
	return canvas


def checker_tile(size: int = TILE) -> Image.Image:
	tile = Image.new("RGBA", (size, size), (28, 32, 38, 255))
	draw = ImageDraw.Draw(tile)
	step = 8
	for y in range(0, size, step):
		for x in range(0, size, step):
			if ((x // step) + (y // step)) % 2 == 0:
				draw.rectangle((x, y, x + step - 1, y + step - 1), fill=(36, 42, 50, 255))
	return tile


def draw_label(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str) -> None:
	try:
		font = ImageFont.truetype("segoeui.ttf", 12)
	except OSError:
		font = ImageFont.load_default()
	draw.text(xy, text, fill=(235, 235, 235, 255), font=font)


def edit_sprite(source: Image.Image, option: dict) -> Image.Image:
	"""Material-class remap only. Pixel stamps were too crude at sprite scale."""
	materials = option.get("materials") or {}
	return material_remap(source, materials)


def generate_gallery(gallery: dict, out_dir: pathlib.Path) -> dict:
	lab_sid = str(gallery["fromLabSid"])
	source_path = standing_frame_path(lab_sid)
	source = crop_sprite(Image.open(source_path))

	slug = gallery_slug(gallery)
	line_dir = out_dir / slug
	line_dir.mkdir(parents=True, exist_ok=True)

	# Keep a native-resolution crop for inspection.
	native_path = line_dir / "00_source_native.png"
	source.save(native_path)

	tiles: list[Image.Image] = []
	labels: list[str] = []
	option_rows: list[dict] = []
	underlay = checker_tile()

	def compose(tile_sprite: Image.Image) -> Image.Image:
		base = underlay.copy()
		base.alpha_composite(tile_sprite)
		return base

	src_tile = compose(fit_tile(source))
	src_path = line_dir / "00_source_upgrade.png"
	src_tile.save(src_path)
	tiles.append(src_tile)
	labels.append("SRC " + str(gallery.get("upgradeSid")))
	option_rows.append(
		{
			"optionId": "SRC",
			"name": str(gallery.get("upgradeSid")),
			"role": "HotA upgraded battle standing frame (not an alt option)",
			"previewPath": src_path.relative_to(ROOT).as_posix(),
			"nativePath": native_path.relative_to(ROOT).as_posix(),
			"sourceFrame": source_path.relative_to(ROOT).as_posix(),
			"locked": False,
		}
	)

	for opt in gallery.get("options") or []:
		if not isinstance(opt, dict):
			continue
		edited = edit_sprite(source, opt)
		tile = compose(fit_tile(edited))
		option_id = str(opt.get("optionId") or "?")
		name = str(opt.get("name") or option_id)
		safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_").lower()
		path = line_dir / f"{option_id}_{safe}.png"
		native_opt = line_dir / f"{option_id}_{safe}_native.png"
		edited.save(native_opt)
		tile.save(path)
		tiles.append(tile)
		labels.append(f"{option_id}: {name}")
		option_rows.append(
			{
				"optionId": option_id,
				"name": name,
				"role": str(opt.get("role") or ""),
				"materials": opt.get("materials") or {},
				"accents": list(opt.get("accents") or []),
				"previewPath": path.relative_to(ROOT).as_posix(),
				"nativePath": native_opt.relative_to(ROOT).as_posix(),
				"selected": False,
			}
		)

	sheet_w = PAD + len(tiles) * (TILE + PAD)
	sheet_h = PAD + TILE + LABEL_H + PAD
	sheet = Image.new("RGBA", (sheet_w, sheet_h), (18, 20, 24, 255))
	draw = ImageDraw.Draw(sheet)
	for i, tile in enumerate(tiles):
		x = PAD + i * (TILE + PAD)
		y = PAD
		sheet.paste(tile, (x, y), tile)
		draw_label(draw, (x + 4, y + TILE + 8), labels[i][:28])
	sheet_path = line_dir / "contact_sheet.png"
	sheet.save(sheet_path)

	meta = {
		"faction": gallery.get("faction"),
		"tier": gallery.get("tier"),
		"line": gallery.get("line"),
		"baseSid": gallery.get("baseSid"),
		"upgradeSid": gallery.get("upgradeSid"),
		"fromLabSid": lab_sid,
		"gameAltSid": gallery.get("gameAltSid"),
		"lineRole": gallery.get("role"),
		"selectionStatus": "awaiting_user_choice",
		"selectedOptionId": None,
		"contactSheet": sheet_path.relative_to(ROOT).as_posix(),
		"options": option_rows,
		"evidenceLevel": "generated_sprite_edit_from_battle_standing_frame",
		"sourceSurface": "battle_animation_group_2_first_frame",
	}
	(line_dir / "gallery.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
	return meta


def write_index(metas: list[dict], out_dir: pathlib.Path) -> pathlib.Path:
	lines = [
		"# Factory / Bulwark Alternate Upgrade Sprite-Edit Gallery",
		"",
		"Evidence level: **generated material-class sprite edits** from HotA battle standing frames",
		"(animation group 2), not portrait icons and not a global color filter.",
		"",
		"No option is locked. Pick an `optionId` per line before wiring a final `_upg_alt`.",
		"",
		"Open [`index.html`](index.html) in a browser for the review UI.",
		"",
	]
	for meta in metas:
		title = f"{meta.get('faction')} T{meta.get('tier')} — `{meta.get('baseSid')}` → alt for `{meta.get('upgradeSid')}`"
		if meta.get("line"):
			title += f" (line `{meta['line']}`)"
		lines.extend(
			[
				f"## {title}",
				"",
				f"- Game alt SID placeholder: `{meta.get('gameAltSid')}`",
				f"- Line role: {meta.get('lineRole')}",
				f"- Source lab SID: `{meta.get('fromLabSid')}`",
				f"- Contact sheet: `{meta.get('contactSheet')}`",
				f"- Selection: **{meta.get('selectionStatus')}**",
				"",
				"| Option | Name | Role | Accents | Preview |",
				"| --- | --- | --- | --- | --- |",
			]
		)
		for opt in meta.get("options") or []:
			if opt.get("optionId") == "SRC":
				continue
			accents = ", ".join(opt.get("accents") or []) or "—"
			lines.append(
				f"| {opt.get('optionId')} | {opt.get('name')} | {opt.get('role')} | {accents} | `{opt.get('previewPath')}` |"
			)
		try:
			img_rel = (ROOT / meta["contactSheet"]).resolve().relative_to(out_dir.resolve()).as_posix()
		except Exception:
			img_rel = pathlib.Path(meta["contactSheet"]).name
		lines.extend(["", f"![contact]({img_rel})", ""])

	index_path = out_dir / "README.md"
	index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
	(out_dir / "index.json").write_text(
		json.dumps(
			{
				"selectionStatus": "awaiting_user_choice",
				"evidenceLevel": "generated_sprite_edit_from_battle_standing_frame",
				"galleries": metas,
			},
			indent=2,
		)
		+ "\n",
		encoding="utf-8",
	)
	return index_path


def write_html(metas: list[dict], out_dir: pathlib.Path) -> pathlib.Path:
	parts: list[str] = [
		"<!doctype html>",
		'<html lang="en"><head><meta charset="utf-8">',
		'<meta name="viewport" content="width=device-width,initial-scale=1">',
		"<title>Factory / Bulwark Sprite-Edit Gallery</title>",
		"<style>",
		":root{--bg:#0b0e12;--card:#151a21;--line:#2c3540;--text:#f1f3f5;--muted:#9aa3ad;--accent:#e0b35a}",
		"*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 Segoe UI,Arial,sans-serif}",
		"nav{position:sticky;top:0;z-index:3;display:flex;gap:10px;padding:10px 16px;background:#0d1116f0;border-bottom:1px solid var(--line)}",
		"nav a{color:var(--text);text-decoration:none;background:#1a222b;border:1px solid #3a4653;border-radius:5px;padding:7px 11px}",
		"main{max-width:1400px;margin:0 auto;padding:18px}",
		"h1{font-size:28px;margin:8px 0 6px}.note{color:var(--muted);margin:0 0 18px}",
		".line{margin:0 0 28px;padding:16px;background:var(--card);border:1px solid var(--line);border-radius:8px}",
		".line h2{margin:0 0 4px;font-size:18px}.line p{margin:0 0 12px;color:var(--muted)}",
		".row{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}",
		".tile{background:#0f141a;border:1px solid var(--line);border-radius:6px;padding:8px}",
		".tile img{width:100%;height:180px;object-fit:contain;image-rendering:pixelated;background:repeating-conic-gradient(#1c232b 0 25%,#222a33 0 50%) 0/16px 16px}",
		".tile strong{display:block;margin-top:6px}.tile span{color:var(--muted);font-size:13px}",
		".accents{display:block;color:#c9b27a;font-size:12px;margin-top:2px}",
		"</style></head><body>",
		'<nav><a href="#factory">Factory</a><a href="#bulwark">Bulwark</a></nav>',
		"<main>",
		"<h1>Factory / Bulwark alternate upgrades</h1>",
		'<p class="note">Native battle standing sprites with material-class remaps + pixel accents. '
		"Not portrait icons. Not a global color filter. Nothing locked — pick letters when ready.</p>",
	]

	current_faction = None
	for meta in metas:
		faction = str(meta.get("faction"))
		if faction != current_faction:
			if current_faction is not None:
				parts.append("</section>")
			parts.append(f'<section id="{html.escape(faction)}"><h1>{html.escape(faction.title())}</h1>')
			current_faction = faction
		slug = gallery_slug(meta)
		title = f"T{meta.get('tier')} — {meta.get('upgradeSid')}"
		if meta.get("line"):
			title += f" ({meta['line']})"
		parts.append(f'<article class="line" id="{html.escape(slug)}">')
		parts.append(f"<h2>{html.escape(title)}</h2>")
		parts.append(f"<p>{html.escape(str(meta.get('lineRole') or ''))}</p>")
		parts.append('<div class="row">')
		for opt in meta.get("options") or []:
			rel = pathlib.Path(opt["previewPath"]).name
			# preview lives in slug folder
			src = f"{slug}/{rel}" if opt.get("optionId") != "SRC" or True else rel
			src = f"{slug}/{pathlib.Path(opt['previewPath']).name}"
			label = "Source" if opt.get("optionId") == "SRC" else f"{opt.get('optionId')}. {opt.get('name')}"
			role = opt.get("role") or ""
			accents = ", ".join(opt.get("accents") or [])
			parts.append('<div class="tile">')
			parts.append(f'<img src="{html.escape(src)}" alt="{html.escape(str(label))}">')
			parts.append(f"<strong>{html.escape(str(label))}</strong>")
			parts.append(f"<span>{html.escape(str(role))}</span>")
			if accents:
				parts.append(f'<span class="accents">accents: {html.escape(accents)}</span>')
			parts.append("</div>")
		parts.append("</div></article>")
	if current_faction is not None:
		parts.append("</section>")
	parts.append("</main></body></html>")
	path = out_dir / "index.html"
	path.write_text("\n".join(parts) + "\n", encoding="utf-8")
	return path


def main() -> int:
	ap = argparse.ArgumentParser()
	ap.add_argument("--faction", choices=("factory", "bulwark", "all"), default="all")
	args = ap.parse_args()

	OUT_ROOT.mkdir(parents=True, exist_ok=True)
	metas: list[dict] = []
	for gallery in ALT_RECOLOR_GALLERIES:
		if args.faction != "all" and gallery.get("faction") != args.faction:
			continue
		meta = generate_gallery(gallery, OUT_ROOT)
		metas.append(meta)
		print(f"gallery {gallery_slug(gallery)} -> {len([o for o in gallery.get('options') or [] if isinstance(o, dict)])} options")

	index = write_index(metas, OUT_ROOT)
	# Review HTML is owned by rebuild_recolor_gallery_html_from_concepts.py
	# (battle-sprite AI concepts). Keep a secondary material-remap preview page here.
	html_path = write_html(metas, OUT_ROOT)
	material_html = OUT_ROOT / "material_remap_preview.html"
	html_path.replace(material_html)
	print(f"wrote {len(metas)} galleries; index {index.relative_to(ROOT).as_posix()}")
	print(f"material preview {material_html.relative_to(ROOT).as_posix()}")
	print("concept review HTML: rebuild via rebuild_recolor_gallery_html_from_concepts.py")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
