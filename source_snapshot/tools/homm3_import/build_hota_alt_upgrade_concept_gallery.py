#!/usr/bin/env python3
"""Prepare and build Factory/Bulwark alternate-upgrade concept galleries.

The image-generation step is intentionally external: the built-in image_gen tool
edits one representative standing battle frame per candidate. This script owns
the deterministic source normalization, prompt contract, review asset layout,
and gallery metadata. It does not select an option or create production animation
sets.
"""

from __future__ import annotations

import argparse
import html
import json
import pathlib
import re
import textwrap

from PIL import Image, ImageChops, ImageDraw, ImageFont


HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT_ROOT = HERE / "alternate_upgrade_concepts"
BRIEFS = OUT_ROOT / "briefs.json"
UNITY_LAB = ROOT / "oldenera_factions" / "Assets" / "CustomUnits" / "homm3_lab"
KEY_COLOR = "#00ff00"
SOURCE_CANVAS = 1024
TILE_SIZE = 384


def load_json(path: pathlib.Path):
	return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: pathlib.Path, data) -> None:
	path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def slug_text(value: str) -> str:
	return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def line_slug(line: dict) -> str:
	parts = [str(line["faction"]), f"t{line['tier']}", str(line["baseSid"])]
	if line.get("line"):
		parts.append(str(line["line"]))
	return "__".join(parts)


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
	names = ["arialbd.ttf", "segoeuib.ttf"] if bold else ["arial.ttf", "segoeui.ttf"]
	for name in names:
		try:
			return ImageFont.truetype(name, size=size)
		except OSError:
			continue
	raise SystemExit(f"missing deterministic gallery font; install one of: {', '.join(names)}")


def source_frame_path(line: dict) -> pathlib.Path:
	extracted = UNITY_LAB / str(line["sourceLabSid"]) / "extracted_battle"
	manifests = sorted(extracted.glob("*.json"))
	if len(manifests) != 1:
		raise SystemExit(f"{line['sourceLabSid']}: expected one battle manifest, found {len(manifests)}")
	manifest = load_json(manifests[0])
	group = next((row for row in manifest.get("sequences") or [] if int(row.get("group", -1)) == 2), None)
	if not group or not group.get("frames"):
		raise SystemExit(f"{line['sourceLabSid']}: battle animation group 2 has no frames")
	rel = pathlib.PureWindowsPath(str(group["frames"][0]))
	path = extracted.joinpath(*rel.parts)
	if not path.is_file():
		raise SystemExit(f"{line['sourceLabSid']}: missing standing frame {path}")
	return path


def normalize_h3_frame(path: pathlib.Path) -> Image.Image:
	"""Return RGBA while preserving established HoMM3 shadow alpha semantics."""
	with Image.open(path) as source:
		if source.mode != "P":
			return source.convert("RGBA")
		indices = source.copy()
		rgba = source.convert("RGBA")
		# VCMI JSON PNGs retain all eight HoMM3 special palette slots. Unlike
		# defextract output, slots 2/3 can still be magenta shadow keys. Normalize
		# every special slot to neutral black alpha so review art never leaks key
		# colors while still retaining the soft ground-shadow shape.
		alpha_map = {0: 0, 1: 32, 2: 48, 3: 80, 4: 128, 5: 0, 6: 128, 7: 64}
		pixel_indices = indices.get_flattened_data() if hasattr(indices, "get_flattened_data") else indices.getdata()
		pixels = list(rgba.get_flattened_data() if hasattr(rgba, "get_flattened_data") else rgba.getdata())
		normalized = []
		for pixel, index in zip(pixels, pixel_indices):
			if index in alpha_map:
				normalized.append((0, 0, 0, alpha_map[index]))
			else:
				normalized.append(pixel)
		rgba.putdata(normalized)
		return rgba


def alpha_bbox(image: Image.Image, threshold: int = 1) -> tuple[int, int, int, int] | None:
	alpha = image.convert("RGBA").getchannel("A")
	if threshold > 1:
		alpha = alpha.point(lambda value: 255 if value >= threshold else 0)
	return alpha.getbbox()


def fit_sprite(image: Image.Image, canvas_size: int, subject_size: int) -> Image.Image:
	image = image.convert("RGBA")
	bbox = alpha_bbox(image)
	if bbox is None:
		raise SystemExit("sprite has no visible alpha coverage")
	left, top, right, bottom = bbox
	pad = max(2, int(max(right - left, bottom - top) * 0.05))
	crop = image.crop((max(0, left - pad), max(0, top - pad), min(image.width, right + pad), min(image.height, bottom + pad)))
	scale = min(subject_size / crop.width, subject_size / crop.height)
	new_size = (max(1, round(crop.width * scale)), max(1, round(crop.height * scale)))
	resample = Image.Resampling.NEAREST if scale >= 1 else Image.Resampling.LANCZOS
	crop = crop.resize(new_size, resample)
	canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
	x = (canvas_size - crop.width) // 2
	y = canvas_size - crop.height - max(18, canvas_size // 20)
	canvas.alpha_composite(crop, (x, y))
	return canvas


def load_validated_raw_alpha(path: pathlib.Path, label: str) -> Image.Image:
	"""Load a generated master only when its transparency contract is intact."""
	try:
		with Image.open(path) as source:
			source.load()
			if source.format != "PNG":
				raise SystemExit(f"{label}: raw master is not encoded as PNG")
			if source.mode != "RGBA":
				raise SystemExit(f"{label}: raw master mode {source.mode} != RGBA")
			if source.width != source.height or source.width < 512:
				raise SystemExit(
					f"{label}: raw master must be square and at least 512px; got {source.size}"
				)
			alpha = source.getchannel("A")
			if alpha.getextrema() != (0, 255):
				raise SystemExit(f"{label}: raw master needs transparent and opaque pixels")
			width, height = source.size
			border_opaque = (
				any(alpha.getpixel((x, 0)) != 0 for x in range(width))
				or any(alpha.getpixel((x, height - 1)) != 0 for x in range(width))
				or any(alpha.getpixel((0, y)) != 0 for y in range(height))
				or any(alpha.getpixel((width - 1, y)) != 0 for y in range(height))
			)
			if border_opaque:
				raise SystemExit(f"{label}: raw master border must be fully transparent")
			visible_alpha = alpha.point(lambda value: 255 if value >= 12 else 0)
			bbox = visible_alpha.getbbox()
			if bbox is None:
				raise SystemExit(f"{label}: raw master has no visible subject")
			left, top, right, bottom = bbox
			padding = min(left, top, width - right, height - bottom)
			if padding < 16:
				raise SystemExit(
					f"{label}: raw subject padding {padding}px is below the 16px minimum"
				)
			red, green, blue, opacity = source.split()
			near_key = ImageChops.multiply(
				ImageChops.multiply(
					red.point(lambda value: 255 if value <= 24 else 0),
					green.point(lambda value: 255 if value >= 240 else 0),
				),
				ImageChops.multiply(
					blue.point(lambda value: 255 if value <= 24 else 0),
					opacity.point(lambda value: 255 if value >= 16 else 0),
				),
			)
			key_pixels = near_key.histogram()[255]
			if key_pixels:
				raise SystemExit(
					f"{label}: raw master retains {key_pixels} visible near-key pixels"
				)
			return source.copy()
	except (OSError, ValueError) as exc:
		raise SystemExit(f"{label}: unreadable raw alpha PNG: {exc}") from exc


def generation_prompt(line: dict, concept: dict) -> str:
	return "\n".join(
		[
			"Use case: precise-object-edit",
			"Asset type: alternate-upgrade battle sprite concept for a classic isometric fantasy strategy game",
			f"Primary request: Turn the supplied {line['sourceName']} sprite into a distinct alternate upgrade called {concept['name']}.",
			"Input image: edit target. Preserve the exact single-creature identity, facing direction, pose, silhouette, anatomy, and proportions unless the design edit explicitly names a small equipment change.",
			"Style/medium: exceptionally polished hand-authored late-1990s PC strategy-game pixel art; crisp clustered pixels; deliberate one-pixel details; limited material-aware palette; strong readability at game-sprite scale; no smoothing or painterly brushwork.",
			f"Design edit: {concept['artDirection']}",
			f"Gameplay read: {concept['gameplayIdentity']}.",
			"Composition: exactly one full-body creature centered with generous padding, same facing direction as the source, no cropping.",
			f"Background: perfectly flat solid {KEY_COLOR} chroma-key with no shadow, floor, scenery, texture, gradient, reflection, or lighting variation.",
			f"Constraints: one creature only; no text; no border; no UI; no watermark; no photorealism; no 3D render; no extra limbs; do not use {KEY_COLOR} anywhere on the creature.",
		]
	)


def prepare_line(line: dict) -> dict:
	slug = line_slug(line)
	out_dir = OUT_ROOT / slug
	out_dir.mkdir(parents=True, exist_ok=True)
	(out_dir / "raw").mkdir(exist_ok=True)
	source_path = source_frame_path(line)
	source = normalize_h3_frame(source_path)
	if source.size != (450, 400):
		raise SystemExit(f"{line['sourceLabSid']}: standing frame {source.size} != 450x400")

	input_path = out_dir / "source_input.png"
	review_path = out_dir / "source_upgrade.png"
	fit_sprite(source, SOURCE_CANVAS, 700).save(input_path)
	fit_sprite(source, TILE_SIZE, 300).save(review_path)

	concept_rows = []
	for concept in line["concepts"]:
		stem = f"{concept['id']}_{slug_text(concept['name'])}"
		prompt = generation_prompt(line, concept)
		(out_dir / f"prompt_{concept['id']}.txt").write_text(prompt + "\n", encoding="utf-8")
		concept_rows.append(
			{
				**concept,
				"selected": False,
				"promptPath": (out_dir / f"prompt_{concept['id']}.txt").relative_to(ROOT).as_posix(),
				"rawChromaPath": (out_dir / "raw" / f"{stem}_chroma.png").relative_to(ROOT).as_posix(),
				"rawAlphaPath": (out_dir / "raw" / f"{stem}_alpha.png").relative_to(ROOT).as_posix(),
				"previewPath": (out_dir / f"{stem}.png").relative_to(ROOT).as_posix(),
			}
		)

	return {
		"faction": line["faction"],
		"tier": line["tier"],
		"line": line.get("line"),
		"baseSid": line["baseSid"],
		"upgradeSid": line["upgradeSid"],
		"gameAltSid": line["gameAltSid"],
		"sourceName": line["sourceName"],
		"lineRole": line["lineRole"],
		"sourceSurface": "battle_animation_group_2_first_frame",
		"sourceFramePath": source_path.relative_to(ROOT).as_posix(),
		"sourceInputPath": input_path.relative_to(ROOT).as_posix(),
		"sourcePreviewPath": review_path.relative_to(ROOT).as_posix(),
		"selectionStatus": "awaiting_user_choice",
		"selectedOptionId": None,
		"concepts": concept_rows,
	}


def prepare(faction: str) -> pathlib.Path:
	briefs = load_json(BRIEFS)
	rows = [prepare_line(line) for line in briefs["lines"] if faction == "all" or line["faction"] == faction]
	path = OUT_ROOT / ("prepared_index.json" if faction == "all" else f"prepared_index_{faction}.json")
	write_json(
		path,
		{
			"schemaVersion": briefs["schemaVersion"],
			"status": briefs["status"],
			"evidenceLevel": briefs["evidenceLevel"],
			"proofBoundary": briefs["proofBoundary"],
			"generation": briefs["generation"],
			"galleries": rows,
		},
	)
	return path


def draw_wrapped(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, width: int, font_obj, fill, spacing: int = 4) -> int:
	average = max(1, int(width / max(1, draw.textlength("M", font=font_obj))))
	lines = textwrap.wrap(text, width=average, break_long_words=False)
	y = xy[1]
	for line in lines:
		draw.text((xy[0], y), line, font=font_obj, fill=fill)
		y += int(font_obj.size * 1.2) if hasattr(font_obj, "size") else 14
	return y + spacing


def sprite_tile(image_path: pathlib.Path, heading: str, subheading: str, *, source: bool = False) -> Image.Image:
	tile = Image.new("RGB", (392, 474), "#151a20")
	draw = ImageDraw.Draw(tile)
	draw.rounded_rectangle((2, 2, 389, 471), radius=6, outline="#303841", width=2, fill="#151a20")
	sprite = Image.open(image_path).convert("RGBA")
	checker = Image.new("RGB", (360, 360), "#20262d")
	check_draw = ImageDraw.Draw(checker)
	for y in range(0, 360, 24):
		for x in range(0, 360, 24):
			if (x // 24 + y // 24) % 2:
				check_draw.rectangle((x, y, x + 23, y + 23), fill="#252c34")
	checker.paste(sprite, ((360 - sprite.width) // 2, (360 - sprite.height) // 2), sprite)
	tile.paste(checker, (16, 14))
	accent = "#9aa6b2" if source else "#e8b85c"
	draw.text((18, 387), heading, font=font(20, bold=True), fill=accent)
	draw_wrapped(draw, (18, 417), subheading, 354, font(15), "#d5dbe1")
	return tile


def build_contact_sheet(gallery: dict) -> pathlib.Path:
	slug = line_slug(gallery)
	out_dir = OUT_ROOT / slug
	options = gallery["concepts"]
	if len(options) != 3:
		raise SystemExit(f"{slug}: expected exactly three concepts")

	tiles = [
		sprite_tile(ROOT / gallery["sourcePreviewPath"], f"SOURCE: {gallery['sourceName']}", "Canonical upgraded battle sprite", source=True)
	]
	for option in options:
		raw_alpha = ROOT / option["rawAlphaPath"]
		if not raw_alpha.is_file():
			raise SystemExit(f"{slug} {option['id']}: missing {raw_alpha}; generate and remove chroma key first")
		raw = load_validated_raw_alpha(raw_alpha, f"{slug} {option['id']}")
		final = fit_sprite(raw, TILE_SIZE, 320)
		preview = ROOT / option["previewPath"]
		final.save(preview, optimize=True)
		tiles.append(sprite_tile(preview, f"{option['id']}. {option['name']}", option["gameplayIdentity"]))

	width = 1600
	height = 548
	sheet = Image.new("RGB", (width, height), "#0f1318")
	draw = ImageDraw.Draw(sheet)
	line_label = f"{gallery['faction'].title()} T{gallery['tier']} - {gallery['sourceName']} line"
	if gallery.get("line"):
		line_label += f" ({gallery['line']})"
	draw.text((16, 12), line_label, font=font(24, bold=True), fill="#f2f4f6")
	draw.text((16, 42), gallery["lineRole"], font=font(15), fill="#aeb7c0")
	for index, tile in enumerate(tiles):
		sheet.paste(tile, (4 + index * 398, 68))
	path = out_dir / "contact_sheet.png"
	sheet.save(path, optimize=True)
	gallery["contactSheet"] = path.relative_to(ROOT).as_posix()
	return path


def build_overview(faction: str, galleries: list[dict]) -> pathlib.Path:
	paths = [ROOT / row["contactSheet"] for row in galleries if row["faction"] == faction]
	images = [Image.open(path).convert("RGB") for path in paths]
	header = 76
	gap = 12
	height = header + sum(image.height for image in images) + gap * max(0, len(images) - 1)
	overview = Image.new("RGB", (1600, height), "#090c10")
	draw = ImageDraw.Draw(overview)
	draw.text((18, 14), f"{faction.title()} alternate-upgrade concepts", font=font(30, bold=True), fill="#f4f5f7")
	draw.text((18, 50), "Source upgrade plus three unselected standing-sprite candidates per recruit line", font=font(16), fill="#aeb7c0")
	y = header
	for image in images:
		overview.paste(image, (0, y))
		y += image.height + gap
	path = OUT_ROOT / f"{faction}_overview.png"
	overview.save(path, optimize=True)
	for image in images:
		image.close()
	return path


def build_html(index: dict) -> pathlib.Path:
	sections = []
	for faction in ("factory", "bulwark"):
		rows = []
		for gallery in index["galleries"]:
			if gallery["faction"] != faction:
				continue
			options = []
			for option in gallery["concepts"]:
				options.append(
					f'<label class="choice"><input type="radio" name="{html.escape(gallery["gameAltSid"])}" value="{html.escape(option["name"])}">'
					f'<img src="{html.escape(pathlib.Path(option["previewPath"]).relative_to(OUT_ROOT.relative_to(ROOT)).as_posix())}" alt="{html.escape(option["name"])}">'
					f'<strong>{option["id"]}. {html.escape(option["name"])}</strong><span>{html.escape(option["gameplayIdentity"])}</span></label>'
				)
			rows.append(
				f'<section class="line" id="{html.escape(line_slug(gallery))}"><header><h2>T{gallery["tier"]} {html.escape(gallery["sourceName"])} line</h2><p>{html.escape(gallery["lineRole"])}</p></header>'
				f'<div class="compare"><div class="source"><img src="{html.escape(pathlib.Path(gallery["sourcePreviewPath"]).relative_to(OUT_ROOT.relative_to(ROOT)).as_posix())}" alt="Source {html.escape(gallery["sourceName"])}"><strong>Source: {html.escape(gallery["sourceName"])}</strong><span>Canonical upgrade</span></div>{"".join(options)}</div></section>'
			)
		sections.append(f'<main id="{faction}"><h1>{faction.title()}</h1>{"".join(rows)}</main>')

	document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Factory and Bulwark Alternate Upgrades</title>
<style>
:root{{--bg:#090c10;--band:#10151b;--tile:#171d24;--line:#303944;--text:#f2f4f6;--muted:#aeb7c0;--accent:#e8b85c}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 Segoe UI,Arial,sans-serif;letter-spacing:0}}nav{{position:sticky;top:0;z-index:4;display:flex;gap:10px;align-items:center;padding:10px 18px;background:#0d1116ee;border-bottom:1px solid var(--line)}}nav a,button{{color:var(--text);background:#1a222b;border:1px solid #3a4653;border-radius:5px;padding:7px 11px;text-decoration:none;cursor:pointer}}main>h1{{max-width:1600px;margin:28px auto 8px;padding:0 18px;font-size:30px}}.line{{padding:18px max(18px,calc((100vw - 1600px)/2));border-top:1px solid #202832;background:var(--band)}}.line:nth-of-type(even){{background:#0d1217}}header h2{{margin:0 0 3px;font-size:20px}}header p{{margin:0 0 12px;color:var(--muted)}}.compare{{display:grid;grid-template-columns:repeat(4,minmax(210px,1fr));gap:10px}}.choice,.source{{display:grid;grid-template-rows:280px auto auto;gap:5px;position:relative;padding:10px;background:var(--tile);border:1px solid var(--line);border-radius:6px;min-width:0}}.choice:has(input:checked){{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}}.choice input{{position:absolute;right:12px;top:12px;width:18px;height:18px;accent-color:#d6a94e}}img{{width:100%;height:280px;object-fit:contain;image-rendering:pixelated;background:repeating-conic-gradient(#20262d 0 25%,#252c34 0 50%) 0/24px 24px}}strong{{font-size:16px}}span{{color:var(--muted)}}#summary{{margin-left:auto}}@media(max-width:900px){{.compare{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:520px){{.compare{{grid-template-columns:1fr}}nav{{flex-wrap:wrap}}#summary{{margin-left:0}}}}
</style></head><body><nav><a href="#factory">Factory</a><a href="#bulwark">Bulwark</a><button id="summary" type="button">Copy selections</button></nav>{''.join(sections)}
<script>document.querySelector('#summary').addEventListener('click',async()=>{{const picked=[...document.querySelectorAll('input:checked')].map(x=>`${{x.name}}: ${{x.value}}`);const text=picked.length?picked.join('\\n'):'No options selected';await navigator.clipboard.writeText(text);document.querySelector('#summary').textContent='Copied';setTimeout(()=>document.querySelector('#summary').textContent='Copy selections',1200)}});</script></body></html>"""
	path = OUT_ROOT / "index.html"
	path.write_text(document, encoding="utf-8")
	return path


def build(faction: str) -> pathlib.Path:
	prepared_path = OUT_ROOT / ("prepared_index.json" if faction == "all" else f"prepared_index_{faction}.json")
	if not prepared_path.is_file():
		prepared_path = prepare(faction)
	index = load_json(prepared_path)
	for gallery in index["galleries"]:
		build_contact_sheet(gallery)

	if faction == "all":
		index["overviews"] = {
			name: build_overview(name, index["galleries"]).relative_to(ROOT).as_posix()
			for name in ("factory", "bulwark")
		}
	else:
		index["overviews"] = {faction: build_overview(faction, index["galleries"]).relative_to(ROOT).as_posix()}
	index_path = OUT_ROOT / ("index.json" if faction == "all" else f"index_{faction}.json")
	write_json(index_path, index)
	if faction == "all":
		build_html(index)
	return index_path


def main() -> int:
	parser = argparse.ArgumentParser()
	parser.add_argument("--faction", choices=("factory", "bulwark", "all"), default="all")
	parser.add_argument("--prepare", action="store_true", help="Normalize standing sources and write generation prompts.")
	parser.add_argument("--build", action="store_true", help="Build review images from generated alpha candidates.")
	args = parser.parse_args()
	if not args.prepare and not args.build:
		args.prepare = args.build = True
	if args.prepare:
		path = prepare(args.faction)
		print(f"prepared {path.relative_to(ROOT).as_posix()}")
	if args.build:
		path = build(args.faction)
		print(f"built {path.relative_to(ROOT).as_posix()}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
