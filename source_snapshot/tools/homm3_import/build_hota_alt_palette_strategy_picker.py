#!/usr/bin/env python3
"""Batch palette-strategy comparisons for Factory/Bulwark material-remap alts + picker UI.

Baseline subject: material_remap_preview sprites (HotA standing-frame material-class
remaps under recolor_galleries/), NOT ultra-detailed AI concept mockups.

For each material-remap option (A–D) per Factory/Bulwark line:
  1) extract the preferred attack sequence once per source unit
  2) sample ramps / seeds from the material-remap native sprite
  3) run curated palette strategies (incl. material_class_hs / region_ramp / multi_seed)
  4) emit a master HTML picker that copies selections to the clipboard

Evidence: generated strategy comparison only. Not Golden Era runtime-proven.
"""

from __future__ import annotations

import argparse
import colorsys
import html
import json
import pathlib
import re
import shutil
import sys

from PIL import Image

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(HERE) not in sys.path:
	sys.path.insert(0, str(HERE))
if str(ROOT / "tools") not in sys.path:
	sys.path.insert(0, str(ROOT / "tools"))

from build_hota_alt_attack_palette_proof import (  # noqa: E402
	PALETTE_ENTRY_COUNT,
	composite_on_checker,
	load_json,
	palette_from_def,
	read_zip_member,
	relative_to_root,
	resolve_repo_path,
)
from compare_hota_alt_palette_grain_strategies import (  # noqa: E402
	apply_palette_to_rgba,
	abrupt_adjacent_jumps,
	crop_frames_subject_centered,
	crop_subject,
	load_gif_frames,
	mean_delta_e_proxy,
	opaque_union_bbox,
	speckle_score,
	write_gif,
	write_rgb_gif,
)
from hota_alt_palette_strategies import (  # noqa: E402
	PICKER_STRATEGIES,
	STRATEGIES,
	build_region_ramps_from_image,
)
from hota_zip_unit_prep import ALL_HOTA_ZIP_UNITS, faction_zip_rel  # noqa: E402
from audit_unit_animation_frames import (  # noqa: E402
	GROUP_ATTACK_FRONT,
	GROUP_SHOOT_FRONT,
	group_counts,
	preferred_attack_family,
)

MATERIAL_GALLERIES_ROOT = ROOT / "tools/homm3_import/recolor_galleries"
MATERIAL_INDEX = MATERIAL_GALLERIES_ROOT / "index.json"
OUT_ROOT = ROOT / "tools/homm3_import/alternate_upgrade_concepts/palette_strategy_picker"
FRAME_CACHE = OUT_ROOT / "_source_attack_frames"


def slug_text(value: str) -> str:
	return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def line_slug(gallery: dict) -> str:
	parts = [str(gallery["faction"]), f"t{gallery['tier']}", str(gallery["baseSid"])]
	if gallery.get("line"):
		parts.append(str(gallery["line"]))
	return "__".join(parts)


def load_material_galleries() -> list[dict]:
	"""Load Factory+Bulwark material-remap galleries.

	Prefer on-disk gallery.json folders (authoritative per-line artifacts). Fall back to
	index.json only when no gallery.json files exist. Rebuilds index.json when folders
	are richer than the index (e.g. Bulwark present on disk but missing from index).
	"""
	from_disk: list[dict] = []
	for path in sorted(MATERIAL_GALLERIES_ROOT.glob("*/gallery.json")):
		meta = load_json(path)
		if not meta.get("fromLabSid"):
			raise ValueError(f"{path}: missing fromLabSid")
		if not material_options(meta):
			raise ValueError(f"{path}: no alt options")
		from_disk.append(meta)

	if from_disk:
		# Keep faction then tier then line stable for picker navigation.
		from_disk.sort(
			key=lambda g: (
				0 if g.get("faction") == "factory" else 1,
				int(g.get("tier") or 0),
				str(g.get("line") or ""),
				str(g.get("baseSid") or ""),
			)
		)
		MATERIAL_INDEX.write_text(
			json.dumps(
				{
					"selectionStatus": "awaiting_user_choice",
					"evidenceLevel": "generated_sprite_edit_from_battle_standing_frame",
					"galleries": from_disk,
				},
				indent=2,
			)
			+ "\n",
			encoding="utf-8",
		)
		return from_disk

	if not MATERIAL_INDEX.is_file():
		raise FileNotFoundError(
			f"no material galleries under {MATERIAL_GALLERIES_ROOT} and missing {MATERIAL_INDEX}"
		)
	return list(load_json(MATERIAL_INDEX)["galleries"])


def lab_sid_from_gallery(gallery: dict) -> str:
	if gallery.get("fromLabSid"):
		return str(gallery["fromLabSid"])
	# Legacy AI-concept index fallback: .../homm3_lab/<labSid>/extracted_battle/...
	parts = pathlib.PurePosixPath(str(gallery["sourceFramePath"]).replace("\\", "/")).parts
	if "homm3_lab" not in parts:
		raise ValueError(f"cannot derive lab sid from gallery {gallery.get('baseSid')}")
	return parts[parts.index("homm3_lab") + 1]


def material_options(gallery: dict) -> list[dict]:
	"""Alt letters only (skip SRC standing-frame tile)."""
	return [opt for opt in (gallery.get("options") or []) if str(opt.get("optionId")) != "SRC"]


def source_option(gallery: dict) -> dict:
	for opt in gallery.get("options") or []:
		if str(opt.get("optionId")) == "SRC":
			return opt
	raise KeyError(f"{line_slug(gallery)}: missing SRC option in material gallery")


def unit_spec_for_lab(lab_sid: str):
	for spec in ALL_HOTA_ZIP_UNITS:
		if spec.sid == lab_sid:
			return spec
	raise KeyError(f"no HotaZipUnitSpec for {lab_sid}")


def sample_ramps_from_concept(concept: pathlib.Path) -> dict[str, list[str]]:
	im = Image.open(concept).convert("RGBA")
	buckets = {"darks": [], "blues": [], "violets": [], "cyans": [], "golds": [], "reds": []}
	pixels = im.load()
	width, height = im.size
	for y in range(height):
		for x in range(width):
			r, g, b, a = pixels[x, y]
			if a < 200 or max(r, g, b) < 16:
				continue
			h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
			hdeg = h * 360.0
			item = (r, g, b, v)
			if v < 0.22:
				buckets["darks"].append(item)
			if 190 <= hdeg <= 255 and s >= 0.08:
				buckets["blues"].append(item)
			if 260 <= hdeg <= 320 and s >= 0.15:
				buckets["violets"].append(item)
			if 160 <= hdeg < 190 and s >= 0.15:
				buckets["cyans"].append(item)
			if 25 <= hdeg <= 55 and s >= 0.25 and v >= 0.35:
				buckets["golds"].append(item)
			if (hdeg <= 25 or hdeg >= 340) and s >= 0.25:
				buckets["reds"].append(item)

	def ramp(samples, fallback):
		if not samples:
			return list(fallback)
		samples = sorted(samples, key=lambda t: t[3])
		out: list[str] = []
		for i in range(5):
			idx = int(round(i * (len(samples) - 1) / 4))
			r, g, b, _ = samples[idx]
			color = f"#{r:02x}{g:02x}{b:02x}"
			if color not in out:
				out.append(color)
		for color in fallback:
			if len(out) >= 3:
				break
			if color not in out:
				out.append(color)
		return out

	primary = (
		ramp(buckets["blues"], [])
		or ramp(buckets["violets"], [])
		or ramp(buckets["reds"], ["#393b40", "#52586a", "#6a7388", "#828ca0", "#91a5bf"])
	)
	return {
		"soot": ramp(buckets["darks"], ["#0b0707", "#181112", "#221b1a", "#322a27", "#4b352b"]),
		"crimson": primary,
		"copper": ramp(buckets["golds"], ["#5a3a18", "#7a5420", "#9a7030", "#c09048", "#e0b060"]),
		"ember": ramp(buckets["cyans"] + buckets["golds"] + buckets["reds"], ["#7f0000", "#aa5500", "#ffaa00", "#ffaa55"]),
	}


def palette_from_rgba_frames(frame_paths: list[pathlib.Path]) -> list[tuple[int, int, int]]:
	"""Build a 256-entry palette from opaque frame colors when no DEF exists in the zip.

	Some HotA Factory units (Olgoi, Juggernaut, etc.) ship as PNG sequences, not DEFs.
	"""
	from collections import Counter

	counts: Counter[tuple[int, int, int]] = Counter()
	for path in frame_paths:
		im = Image.open(path).convert("RGBA")
		pixels = im.load()
		width, height = im.size
		for y in range(height):
			for x in range(width):
				r, g, b, a = pixels[x, y]
				if a < 200:
					continue
				counts[(r, g, b)] += 1
	# Keep special slots 0..7 empty/black (matches DEF special-slot convention).
	palette: list[tuple[int, int, int]] = [(0, 0, 0)] * 8
	# Prefer frequent colors, then darker-first for stable ramp-like ordering.
	ordered = sorted(counts.items(), key=lambda item: (-item[1], sum(item[0]), item[0]))
	for rgb, _ in ordered:
		if len(palette) >= PALETTE_ENTRY_COUNT:
			break
		if rgb == (0, 0, 0):
			continue
		palette.append(rgb)
	while len(palette) < PALETTE_ENTRY_COUNT:
		palette.append((0, 0, 0))
	return palette


def load_cached_source_palette(lab_sid: str) -> list[tuple[int, int, int]]:
	cache_dir = FRAME_CACHE / lab_sid
	def_path = cache_dir / "source.def"
	if def_path.is_file() and def_path.stat().st_size > 0:
		return palette_from_def(def_path.read_bytes())
	pal_path = cache_dir / "source_palette.json"
	if not pal_path.is_file():
		raise FileNotFoundError(f"no source.def or source_palette.json for {lab_sid}")
	data = load_json(pal_path)
	palette = [tuple(int(v) for v in rgb) for rgb in data["palette"]]
	if len(palette) != PALETTE_ENTRY_COUNT:
		raise ValueError(f"{lab_sid}: expected {PALETTE_ENTRY_COUNT} palette entries, got {len(palette)}")
	return palette


def _copy_group_frames_from_dir(
	*,
	lab_sid: str,
	src_dir: pathlib.Path,
	frames_dir: pathlib.Path,
	group: int,
	frame_count: int,
	frame_names: list[str] | None = None,
) -> None:
	if frames_dir.exists():
		shutil.rmtree(frames_dir)
	frames_dir.mkdir(parents=True)
	if frame_names is None:
		for index in range(frame_count):
			name = f"{group:02d}_{index:02d}.png"
			src = src_dir / name
			if not src.is_file():
				raise FileNotFoundError(f"{lab_sid}: missing extracted {name}")
			shutil.copy2(src, frames_dir / name)
		return
	if len(frame_names) != frame_count:
		raise ValueError(f"{lab_sid}: expected {frame_count} frame names, got {len(frame_names)}")
	for index, rel in enumerate(frame_names):
		src = src_dir / pathlib.Path(str(rel).replace("\\", "/"))
		if not src.is_file():
			raise FileNotFoundError(f"{lab_sid}: missing lab frame {src}")
		shutil.copy2(src, frames_dir / f"{group:02d}_{index:02d}.png")


def ensure_attack_frames(lab_sid: str, faction: str) -> dict:
	"""Extract preferred attack frames once per lab unit into the shared cache."""
	cache_dir = FRAME_CACHE / lab_sid
	meta_path = cache_dir / "meta.json"
	if meta_path.is_file():
		return load_json(meta_path)

	spec = unit_spec_for_lab(lab_sid)
	lab = ROOT / "oldenera_factions" / "Assets" / "CustomUnits" / "homm3_lab" / lab_sid
	extract_root = lab / "extracted_battle"
	manifest_path = next(extract_root.glob("*.json"))
	authoring = load_json(lab / "authoring.json")
	manifest = load_json(manifest_path)
	counts = group_counts(manifest)
	family, preferred = preferred_attack_family(authoring, counts)
	if family.startswith("shoot"):
		group = GROUP_SHOOT_FRONT
		attack_family = "shoot"
	else:
		group = GROUP_ATTACK_FRONT
		attack_family = "melee"
	if counts.get(group, 0) <= 0:
		raise RuntimeError(f"{lab_sid}: preferred attack group {group} has no frames")

	zip_path = ROOT / pathlib.Path(str(faction_zip_rel(faction)))
	member = f"sprites/hota/{faction}/creatures/battle/{spec.battle_stem}.def"
	cache_dir.mkdir(parents=True, exist_ok=True)
	frames_dir = cache_dir / "frames"
	frame_count = counts[group]
	source_mode = "def"

	try:
		source_def = read_zip_member(zip_path, member)
	except FileNotFoundError:
		source_def = None

	if source_def is None:
		# JSON+PNG HotA units (e.g. COLGOIX / CJUGGER) have no battle DEF.
		# Do NOT reconstruct a palette from RGBA lab frames — that path is
		# preview-broken for production. Use shared mode-P lab palette instead.
		source_mode = "lab_shared_p_palette"
		member = f"sprites/hota/{faction}/creatures/battle/{spec.battle_stem}.json"
		sequence = next(
			(item for item in (manifest.get("sequences") or []) if int(item.get("group", -1)) == group),
			None,
		)
		if sequence is None:
			raise RuntimeError(f"{lab_sid}: manifest missing group {group}")
		frame_names = [str(value) for value in (sequence.get("frames") or [])]
		_copy_group_frames_from_dir(
			lab_sid=lab_sid,
			src_dir=extract_root,
			frames_dir=frames_dir,
			group=group,
			frame_count=frame_count,
			frame_names=frame_names,
		)
		frame_paths = [frames_dir / f"{group:02d}_{index:02d}.png" for index in range(frame_count)]
		# Prefer original mode-P files from the production extract dir (shared palette).
		p_sources = []
		for name in frame_names:
			src = extract_root / pathlib.PureWindowsPath(name).name
			if not src.is_file():
				# frame path may include basename.dir\file
				src = extract_root.joinpath(*pathlib.PureWindowsPath(name).parts)
			if not src.is_file():
				raise FileNotFoundError(f"{lab_sid}: missing production frame {name}")
			p_sources.append(src)
		modes = {Image.open(path).mode for path in p_sources}
		if modes != {"P"}:
			raise RuntimeError(
				f"{lab_sid}: JSON+PNG production frames must be shared mode-P; got {sorted(modes)}. "
				"Refusing lab_png_palette RGBA reconstruction (preview-only, not production-safe)."
			)
		raw_palettes = {bytes((Image.open(path).getpalette() or b"")[: 256 * 3]) for path in p_sources}
		if len(raw_palettes) != 1:
			raise RuntimeError(
				f"{lab_sid}: expected one shared 256-color palette across attack frames, "
				f"found {len(raw_palettes)}"
			)
		raw = next(iter(raw_palettes))
		palette = [(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, len(raw), 3)]
		if len(palette) != 256:
			raise RuntimeError(f"{lab_sid}: shared palette length {len(palette)} != 256")
		# Rewrite cache frames from indexed sources for stable palette application.
		for index, src in enumerate(p_sources):
			shutil.copy2(src, frames_dir / f"{group:02d}_{index:02d}.png")
		(cache_dir / "source_palette.json").write_text(
			json.dumps(
				{
					"labSid": lab_sid,
					"sourceMode": source_mode,
					"note": "Shared mode-P palette from production extract_creature lab frames (not RGBA reconstruction).",
					"palette": [list(rgb) for rgb in palette],
				},
				indent=2,
			)
			+ "\n",
			encoding="utf-8",
		)
	else:
		from defextract_py3 import extract_def

		work = cache_dir / ".work"
		if work.exists():
			shutil.rmtree(work)
		work.mkdir()
		def_path = work / f"{spec.battle_stem}.def"
		def_path.write_bytes(source_def)
		extract_tmp = work / "extract"
		extract_tmp.mkdir()
		if not extract_def(str(def_path), str(extract_tmp)):
			raise RuntimeError(f"defextract failed for {lab_sid}")
		extracted_dir = next(extract_tmp.glob("*.dir"))
		_copy_group_frames_from_dir(
			lab_sid=lab_sid,
			src_dir=extracted_dir,
			frames_dir=frames_dir,
			group=group,
			frame_count=frame_count,
		)
		shutil.rmtree(work)
		(cache_dir / "source.def").write_bytes(source_def)

	meta = {
		"labSid": lab_sid,
		"faction": faction,
		"attackFamily": attack_family,
		"familyAuto": family,
		"group": group,
		"frameCount": frame_count,
		"fps": float(authoring.get("flipBookFps") or 12.0),
		"zipPath": relative_to_root(zip_path),
		"zipMember": member,
		"sourceMode": source_mode,
		"framesDir": relative_to_root(frames_dir),
		"sourcePaletteSha256": None,
		"sourcePalette": None,
	}
	meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
	return meta


def compare_concept(
	gallery: dict,
	concept: dict,
	frame_meta: dict,
) -> dict:
	frames_dir = resolve_repo_path(frame_meta["framesDir"])
	frame_paths = sorted(frames_dir.glob(f"{int(frame_meta['group']):02d}_*.png"))
	if len(frame_paths) != int(frame_meta["frameCount"]):
		raise ValueError(f"{frame_meta['labSid']}: expected {frame_meta['frameCount']} frames, found {len(frame_paths)}")

	source_palette = load_cached_source_palette(frame_meta["labSid"])
	source_images = [Image.open(path).convert("RGBA") for path in frame_paths]
	mid = source_images[len(source_images) // 2]
	fps = float(frame_meta["fps"])
	source_speckle = speckle_score(mid)

	# Material-remap native sprite is the color target (not AI mockup).
	concept_native = resolve_repo_path(concept["nativePath"])
	if not concept_native.is_file():
		raise FileNotFoundError(f"missing material-remap native: {concept_native}")
	ramps = sample_ramps_from_concept(concept_native)
	region_ramps = build_region_ramps_from_image(concept_native)
	# Merge region aliases into paletteRamps so soft_blend/baseline stay concept-grounded.
	merged_ramps = dict(ramps)
	for key in ("soot", "crimson", "copper", "ember"):
		if key in region_ramps and region_ramps[key]:
			merged_ramps[key] = region_ramps[key]

	profile = {
		"specialPaletteSlotCount": 8,
		"paletteRamps": merged_ramps,
		"regionRamps": region_ramps,
		"materialShifts": concept.get("materials") or {},
		"conceptNativePath": str(concept_native),
		"classOverrides": {"preserve": [], "soot": [], "crimson": [], "copper": [], "ember": []},
	}

	out_dir = OUT_ROOT / "comparisons" / line_slug(gallery) / concept["optionId"]
	if out_dir.exists():
		shutil.rmtree(out_dir)
	out_dir.mkdir(parents=True, exist_ok=True)
	crop_subject(mid).save(out_dir / "00_source_mid.png")
	subject_bbox = opaque_union_bbox(source_images, pad=4)
	if subject_bbox is None:
		raise RuntimeError(f"{frame_meta['labSid']}: no opaque subject bbox in attack frames")

	src_opt = source_option(gallery)
	source_preview = resolve_repo_path(src_opt.get("nativePath") or src_opt["previewPath"])
	concept_preview = concept_native
	crop_subject(Image.open(source_preview)).save(out_dir / "source_ref_crop.png")
	crop_subject(Image.open(concept_preview)).save(out_dir / "concept_ref_crop.png")

	results: list[dict] = []
	for name in PICKER_STRATEGIES:
		fn = STRATEGIES[name]
		target_palette, rows = fn(source_palette, profile)
		remapped = [apply_palette_to_rgba(frame, source_palette, target_palette) for frame in source_images]
		mid_r = remapped[len(remapped) // 2]
		strategy_dir = out_dir / name
		strategy_dir.mkdir(parents=True, exist_ok=True)
		crop_subject(mid_r).save(strategy_dir / "mid_crop.png")
		write_gif(strategy_dir / "attack.gif", remapped, fps)
		write_gif(
			strategy_dir / "attack_crop.gif",
			crop_frames_subject_centered(remapped, pad=4, scale=3),
			fps,
		)
		left = crop_subject(mid)
		right = crop_subject(mid_r)
		pair = Image.new("RGBA", (left.width + right.width + 12, max(left.height, right.height)), (0, 0, 0, 0))
		pair.paste(left, (0, 0), left)
		pair.paste(right, (left.width + 12, 0), right)
		composite_on_checker(pair).save(strategy_dir / "mid_pair.png")
		speckle = speckle_score(mid_r)
		cid = concept["optionId"]
		slug = line_slug(gallery)
		row = {
			"strategy": name,
			"speckleScore": round(speckle, 4),
			"sourceSpeckleScore": round(source_speckle, 4),
			"grainRatio": round(speckle / max(source_speckle, 1e-6), 4),
			"abruptAdjacentJumps": abrupt_adjacent_jumps(source_palette, target_palette, rows),
			"meanOpaqueRgbL1": round(mean_delta_e_proxy(mid, mid_r), 4),
			"changedPaletteEntries": sum(1 for r in rows if r["changed"]),
			"midPair": f"comparisons/{slug}/{cid}/{name}/mid_pair.png",
			"attackGif": f"comparisons/{slug}/{cid}/{name}/attack.gif",
			"attackCropGif": f"comparisons/{slug}/{cid}/{name}/attack_crop.gif",
			"midCrop": f"comparisons/{slug}/{cid}/{name}/mid_crop.png",
		}
		results.append(row)

	meaningful = [row for row in results if row["meanOpaqueRgbL1"] >= 20.0]
	balanced = sorted(
		meaningful or results,
		key=lambda row: (row["grainRatio"], row["abruptAdjacentJumps"], -row["meanOpaqueRgbL1"]),
	)
	for index, row in enumerate(balanced):
		row["rank"] = index + 1
	seen = {row["strategy"] for row in balanced}
	extra = sorted(
		[row for row in results if row["strategy"] not in seen],
		key=lambda row: (row["grainRatio"], row["abruptAdjacentJumps"]),
	)
	for index, row in enumerate(extra, start=len(balanced) + 1):
		row["rank"] = index
	ranked = balanced + extra

	cid = concept["optionId"]
	slug = line_slug(gallery)
	report = {
		"lineSlug": slug,
		"faction": gallery["faction"],
		"tier": gallery["tier"],
		"line": gallery.get("line"),
		"baseSid": gallery["baseSid"],
		"upgradeSid": gallery["upgradeSid"],
		"gameAltSid": gallery["gameAltSid"],
		"sourceName": gallery.get("upgradeSid"),
		"conceptId": cid,
		"conceptName": concept["name"],
		"gameplayIdentity": concept.get("role"),
		"baselineKind": "material_remap_native",
		"conceptPreview": relative_to_root(concept_native),
		"sourcePreview": relative_to_root(source_preview),
		"sourceRefCrop": f"comparisons/{slug}/{cid}/source_ref_crop.png",
		"conceptRefCrop": f"comparisons/{slug}/{cid}/concept_ref_crop.png",
		"subjectBbox": list(subject_bbox),
		"attackFamily": frame_meta["attackFamily"],
		"group": frame_meta["group"],
		"frameCount": frame_meta["frameCount"],
		"sourceSpeckleScore": round(source_speckle, 4),
		"recommended": balanced[0]["strategy"] if balanced else None,
		"strategies": ranked,
	}
	(out_dir / "comparison_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
	return report


def _preview_href(repo_relative: str) -> str:
	"""HTML href from picker root to a recolor_galleries or concepts asset."""
	rel = pathlib.PurePosixPath(str(repo_relative).replace("\\", "/"))
	for prefix in (
		pathlib.PurePosixPath("tools/homm3_import/recolor_galleries"),
		pathlib.PurePosixPath("tools/homm3_import/alternate_upgrade_concepts"),
	):
		try:
			under = rel.relative_to(prefix)
			if prefix.name == "recolor_galleries":
				return (pathlib.PurePosixPath("../../recolor_galleries") / under).as_posix()
			return (pathlib.PurePosixPath("..") / under).as_posix()
		except ValueError:
			continue
	raise ValueError(f"preview path not under known gallery roots: {repo_relative}")


def write_picker_html(reports: list[dict], out_dir: pathlib.Path) -> pathlib.Path:
	# Group by line; preserve factory-then-bulwark, tier, line order from reports.
	by_line: dict[str, list[dict]] = {}
	for report in reports:
		by_line.setdefault(report["lineSlug"], []).append(report)

	parts = [
		"<!doctype html><html lang='en'><head><meta charset='utf-8'>",
		"<meta name='viewport' content='width=device-width,initial-scale=1'>",
		"<title>Factory / Bulwark Palette Strategy Picker</title>",
		"<style>",
		":root{--bg:#0b0e12;--card:#151a21;--line:#2c3540;--text:#eef1f4;--muted:#9aa3ad;--accent:#e0b35a;--ok:#6bcf8e}",
		"*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 Segoe UI,Arial,sans-serif}",
		"nav{position:sticky;top:0;z-index:5;display:flex;gap:10px;flex-wrap:wrap;align-items:center;padding:10px 16px;background:#0d1116f2;border-bottom:1px solid var(--line)}",
		"nav button,nav a{background:#1a222b;color:var(--text);border:1px solid #3a4653;border-radius:6px;padding:8px 12px;cursor:pointer;text-decoration:none}",
		"nav button.primary{background:#3a2f14;border-color:var(--accent);color:#ffe6a8}",
		"main{max-width:1500px;margin:0 auto;padding:18px}",
		"h1{margin:8px 0 6px}.note{color:var(--muted);margin:0 0 18px}",
		".line{margin:0 0 28px;padding:16px;background:var(--card);border:1px solid var(--line);border-radius:10px}",
		".line h2{margin:0 0 4px;font-size:18px}.line .role{color:var(--muted);margin:0 0 12px}",
		".concept{margin:14px 0 0;padding:12px;border:1px solid #243040;border-radius:8px;background:#10161c}",
		".concept h3{margin:0 0 8px;font-size:15px}",
		".refs{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 10px}",
		".refs figure{margin:0;width:160px}.refs img{width:160px;height:160px;object-fit:contain;image-rendering:pixelated;background:#0a0d11;border:1px solid #2a3340}",
		".refs figcaption{color:var(--muted);font-size:12px;margin-top:4px}",
		".strategies{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}",
		"label.strat{display:block;position:relative;padding:8px;border:1px solid #2c3540;border-radius:8px;background:#0f141a;cursor:pointer}",
		"label.strat:has(input:checked){border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}",
		"label.strat.recommended{outline:1px dashed var(--ok)}",
		"label.strat input{position:absolute;right:8px;top:8px;z-index:1}",
		"label.strat .preview-box{width:100%;height:180px;display:flex;align-items:center;justify-content:center;background:#0a0d11;overflow:hidden}",
		"label.strat img.preview{max-width:100%;max-height:100%;width:auto;height:auto;object-fit:contain;image-rendering:pixelated}",
		"label.strat strong{display:block;margin-top:6px}label.strat span{display:block;color:var(--muted);font-size:12px}",
		"#toast{display:none;margin-left:auto;color:var(--ok)}",
		"</style></head><body>",
		"<nav>",
		"<a href='#factory'>Factory</a><a href='#bulwark'>Bulwark</a>",
		"<button type='button' id='fillRecs'>Use metric recommendations</button>",
		"<button type='button' class='primary' id='copyBtn'>Copy selections</button>",
		"<span id='toast'>Copied</span>",
		"</nav><main>",
		"<h1>Factory / Bulwark palette strategy picker</h1>",
		"<p class='note'>Baseline: material_remap_preview HotA standing-frame remaps (not AI mockups). "
		"Pick one palette strategy per alt letter. Each card plays a subject-cropped attack_crop.gif "
		"(full-canvas attack.gif kept for inspection). "
		"New options: material_class_hs (authored class HSV), region_ramp, multi_seed_hsv, cluster_hist_match. "
		"Metrics recommend a default; visual judgment wins. Copy dumps a paste-ready block. "
		"Evidence: generated strategy comparison only — palette-global, no new silhouette geometry.</p>",
	]

	current_faction = None
	for line_slug_key, line_reports in by_line.items():
		line_reports = sorted(line_reports, key=lambda r: r["conceptId"])
		head = line_reports[0]
		faction = head["faction"]
		if faction != current_faction:
			if current_faction is not None:
				parts.append("</section>")
			parts.append(f"<section id='{html.escape(faction)}'><h1>{html.escape(faction.title())}</h1>")
			current_faction = faction
		parts.append(f"<article class='line' id='{html.escape(line_slug_key)}'>")
		title = f"T{head['tier']} — {head['sourceName']}"
		if head.get("line"):
			title += f" ({head['line']})"
		parts.append(f"<h2>{html.escape(title)}</h2>")
		parts.append(
			f"<p class='role'>{html.escape(head['upgradeSid'])} · {html.escape(head['attackFamily'])} "
			f"group {head['group']} · {head['frameCount']} frames · alt `{html.escape(head['gameAltSid'])}`</p>"
		)
		for report in line_reports:
			field = f"{report['lineSlug']}::{report['conceptId']}"
			parts.append(f"<div class='concept' data-field='{html.escape(field)}'>")
			parts.append(
				f"<h3>{html.escape(report['conceptId'])}. {html.escape(report['conceptName'])} "
				f"<span style='color:#9aa3ad;font-weight:400'>— {html.escape(str(report.get('gameplayIdentity') or ''))}</span></h3>"
			)
			source_href = report.get("sourceRefCrop") or _preview_href(report["sourcePreview"])
			concept_href = report.get("conceptRefCrop") or _preview_href(report["conceptPreview"])
			parts.append("<div class='refs'>")
			parts.append(
				f"<figure><img src='{html.escape(source_href)}' alt='source'>"
				f"<figcaption>Source</figcaption></figure>"
			)
			parts.append(
				f"<figure><img src='{html.escape(concept_href)}' alt='material remap'>"
				f"<figcaption>Material remap target</figcaption></figure>"
			)
			parts.append("</div><div class='strategies'>")
			for strat in report["strategies"]:
				rec = strat["strategy"] == report.get("recommended")
				checked = " checked" if rec else ""
				klass = "strat recommended" if rec else "strat"
				preview = strat.get("attackCropGif") or strat["attackGif"]
				parts.append(
					f"<label class='{klass}'><input type='radio' name='{html.escape(field)}' "
					f"value='{html.escape(strat['strategy'])}' data-concept-name='{html.escape(report['conceptName'])}' "
					f"data-line='{html.escape(report['lineSlug'])}' data-concept-id='{html.escape(report['conceptId'])}' "
					f"data-game-alt='{html.escape(report['gameAltSid'])}'{checked}>"
					f"<div class='preview-box'><img class='preview' src='{html.escape(preview)}' "
					f"alt='{html.escape(strat['strategy'])} attack'></div>"
					f"<strong>{html.escape(strat['strategy'])}"
					f"{' ★' if rec else ''}</strong>"
					f"<span>rank {strat['rank']} · grain {strat['grainRatio']} · "
					f"abrupt {strat['abruptAdjacentJumps']} · L1 {strat['meanOpaqueRgbL1']}</span>"
					f"<span><a href='{html.escape(strat['midPair'])}' target='_blank'>mid pair</a>"
					f" · <a href='{html.escape(strat['attackGif'])}' target='_blank'>full gif</a></span>"
					f"</label>"
				)
			parts.append("</div></div>")
		parts.append("</article>")
	if current_faction is not None:
		parts.append("</section>")

	parts.append(
		"""
<script>
const toast = document.getElementById('toast');
function flash(){toast.style.display='inline'; setTimeout(()=>toast.style.display='none',1200)}
function selections(){
  const lines = [];
  document.querySelectorAll("input[type=radio]:checked").forEach(el=>{
    lines.push(`${el.dataset.line} ${el.dataset.conceptId} (${el.dataset.conceptName}) => ${el.value}  [${el.dataset.gameAlt}]`);
  });
  return lines;
}
document.getElementById('copyBtn').addEventListener('click', async ()=>{
  const lines = selections();
  const text = lines.length
    ? ['Palette strategy selections:', ...lines].join('\\n')
    : 'No selections';
  await navigator.clipboard.writeText(text);
  flash();
});
document.getElementById('fillRecs').addEventListener('click', ()=>{
  document.querySelectorAll('label.strat.recommended input').forEach(el=>{el.checked=true});
});
</script>
</main></body></html>
"""
	)
	path = out_dir / "index.html"
	path.write_text("\n".join(parts), encoding="utf-8")
	return path


def refresh_display_crops(reports: list[dict], gallery_by_line: dict[str, dict]) -> int:
	"""Fast path: crop existing full-canvas attack.gif + write ref crops without remapping."""
	guides_by_lab: dict[str, list[Image.Image]] = {}
	fps_by_lab: dict[str, float] = {}
	bbox_by_lab: dict[str, tuple[int, int, int, int]] = {}
	updated = 0
	for report in reports:
		gallery = gallery_by_line.get(report["lineSlug"])
		if gallery is None:
			raise KeyError(f"no gallery for line {report['lineSlug']}")
		lab_sid = lab_sid_from_gallery(gallery)
		if lab_sid not in guides_by_lab:
			frame_meta = ensure_attack_frames(lab_sid, gallery["faction"])
			frames_dir = resolve_repo_path(frame_meta["framesDir"])
			source_images = [
				Image.open(path).convert("RGBA")
				for path in sorted(frames_dir.glob(f"{int(frame_meta['group']):02d}_*.png"))
			]
			bbox = opaque_union_bbox(source_images, pad=4)
			if bbox is None:
				raise RuntimeError(f"{lab_sid}: no opaque subject bbox")
			guides_by_lab[lab_sid] = source_images
			bbox_by_lab[lab_sid] = bbox
			fps_by_lab[lab_sid] = float(frame_meta["fps"])

		out_dir = OUT_ROOT / "comparisons" / report["lineSlug"] / report["conceptId"]
		source_preview = resolve_repo_path(report["sourcePreview"])
		concept_preview = resolve_repo_path(report["conceptPreview"])
		crop_subject(Image.open(source_preview)).save(out_dir / "source_ref_crop.png")
		crop_subject(Image.open(concept_preview)).save(out_dir / "concept_ref_crop.png")
		report["sourceRefCrop"] = f"comparisons/{report['lineSlug']}/{report['conceptId']}/source_ref_crop.png"
		report["conceptRefCrop"] = f"comparisons/{report['lineSlug']}/{report['conceptId']}/concept_ref_crop.png"
		report["subjectBbox"] = list(bbox_by_lab[lab_sid])
		report["displayCropMode"] = "subject_centered_max_canvas"

		guides = guides_by_lab[lab_sid]
		fps = fps_by_lab[lab_sid]
		for strat in report["strategies"]:
			strategy_dir = out_dir / strat["strategy"]
			full_gif = strategy_dir / "attack.gif"
			if not full_gif.is_file():
				raise FileNotFoundError(full_gif)
			gif_frames = load_gif_frames(full_gif)
			if len(gif_frames) != len(guides):
				raise ValueError(
					f"{report['lineSlug']} {report['conceptId']} {strat['strategy']}: "
					f"gif frames {len(gif_frames)} != source {len(guides)}"
				)
			cropped = crop_frames_subject_centered(
				gif_frames,
				guide_frames=guides,
				pad=4,
				scale=3,
			)
			crop_path = strategy_dir / "attack_crop.gif"
			write_rgb_gif(crop_path, cropped, fps)
			strat["attackCropGif"] = (
				f"comparisons/{report['lineSlug']}/{report['conceptId']}/{strat['strategy']}/attack_crop.gif"
			)
			updated += 1
		(out_dir / "comparison_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
		print(f"  display {report['lineSlug']} {report['conceptId']}", flush=True)
	return updated


def main() -> int:
	ap = argparse.ArgumentParser(description=__doc__)
	ap.add_argument("--faction", choices=("factory", "bulwark", "all"), default="all")
	ap.add_argument("--limit", type=int, default=0, help="optional cap for smoke tests")
	ap.add_argument(
		"--force",
		action="store_true",
		help="rebuild comparisons even when comparison_report.json already exists",
	)
	ap.add_argument(
		"--refresh-display",
		action="store_true",
		help="only regenerate subject-cropped attack_crop.gif + ref thumbs from existing assets, then rewrite HTML",
	)
	args = ap.parse_args()

	galleries = load_material_galleries()
	OUT_ROOT.mkdir(parents=True, exist_ok=True)
	FRAME_CACHE.mkdir(parents=True, exist_ok=True)

	gallery_by_line = {line_slug(g): g for g in galleries}

	if args.refresh_display:
		reports: list[dict] = []
		for gallery in galleries:
			if args.faction != "all" and gallery["faction"] != args.faction:
				continue
			for concept in material_options(gallery):
				report_path = (
					OUT_ROOT / "comparisons" / line_slug(gallery) / concept["optionId"] / "comparison_report.json"
				)
				if not report_path.is_file():
					print(f"  skip missing {line_slug(gallery)} {concept['optionId']}", flush=True)
					continue
				reports.append(load_json(report_path))
				if args.limit and len(reports) >= args.limit:
					break
			if args.limit and len(reports) >= args.limit:
				break
		print(f"refresh-display for {len(reports)} concepts ...", flush=True)
		n = refresh_display_crops(reports, gallery_by_line)
		index_path = OUT_ROOT / "picker_index.json"
		index_path.write_text(
			json.dumps(
				{
					"schemaVersion": 2,
					"evidenceLevel": "generated_strategy_comparison",
					"baselineKind": "material_remap_native",
					"count": len(reports),
					"failureCount": 0,
					"strategies": list(PICKER_STRATEGIES),
					"reports": reports,
					"failures": [],
					"displayCrop": True,
				},
				indent=2,
			)
			+ "\n",
			encoding="utf-8",
		)
		html_path = write_picker_html(reports, OUT_ROOT)
		print(f"wrote {n} attack_crop.gif previews")
		print(f"picker {relative_to_root(html_path)}")
		return 0

	reports = []
	failures: list[dict] = []
	count = 0
	for gallery in galleries:
		if args.faction != "all" and gallery["faction"] != args.faction:
			continue
		lab_sid = lab_sid_from_gallery(gallery)
		print(f"frames {lab_sid} ...", flush=True)
		opts = material_options(gallery)
		try:
			frame_meta = ensure_attack_frames(lab_sid, gallery["faction"])
		except Exception as exc:  # noqa: BLE001 — batch must continue; record failure
			print(f"  FAIL frames {lab_sid}: {exc}", flush=True)
			for concept in opts:
				failures.append(
					{
						"lineSlug": line_slug(gallery),
						"conceptId": concept["optionId"],
						"conceptName": concept["name"],
						"gameAltSid": gallery["gameAltSid"],
						"stage": "ensure_attack_frames",
						"error": str(exc),
					}
				)
				count += 1
				if args.limit and count >= args.limit:
					break
			if args.limit and count >= args.limit:
				break
			continue
		for concept in opts:
			report_path = (
				OUT_ROOT / "comparisons" / line_slug(gallery) / concept["optionId"] / "comparison_report.json"
			)
			if report_path.is_file() and not args.force:
				print(f"  skip {line_slug(gallery)} {concept['optionId']} (existing report)", flush=True)
				reports.append(load_json(report_path))
				count += 1
				if args.limit and count >= args.limit:
					break
				continue
			print(
				f"  compare {line_slug(gallery)} {concept['optionId']} {concept['name']} ...",
				flush=True,
			)
			try:
				report = compare_concept(gallery, concept, frame_meta)
				reports.append(report)
			except Exception as exc:  # noqa: BLE001 — batch must continue; record failure
				print(f"  FAIL {line_slug(gallery)} {concept['optionId']}: {exc}", flush=True)
				failures.append(
					{
						"lineSlug": line_slug(gallery),
						"conceptId": concept["optionId"],
						"conceptName": concept["name"],
						"gameAltSid": gallery["gameAltSid"],
						"stage": "compare_concept",
						"error": str(exc),
					}
				)
			count += 1
			if args.limit and count >= args.limit:
				break
		if args.limit and count >= args.limit:
			break

	index_path = OUT_ROOT / "picker_index.json"
	index_path.write_text(
		json.dumps(
			{
				"schemaVersion": 2,
				"evidenceLevel": "generated_strategy_comparison",
				"baselineKind": "material_remap_native",
				"count": len(reports),
				"failureCount": len(failures),
				"strategies": list(PICKER_STRATEGIES),
				"reports": reports,
				"failures": failures,
			},
			indent=2,
		)
		+ "\n",
		encoding="utf-8",
	)
	html_path = write_picker_html(reports, OUT_ROOT)
	print(f"wrote {len(reports)} concept comparisons ({len(failures)} failures)")
	print(f"picker {relative_to_root(html_path)}")
	return 1 if failures and not reports else 0


if __name__ == "__main__":
	raise SystemExit(main())
