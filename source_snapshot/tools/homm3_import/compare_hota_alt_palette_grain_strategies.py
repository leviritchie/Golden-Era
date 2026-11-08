#!/usr/bin/env python3
"""Compare programmatic DEF-palette remap strategies for grain reduction.

All strategies operate on the global 256-entry indexed palette (animation-stable).
They are designed to be reusable across HotA unit DEFs, not Plated-Armadillo-only.

Evidence level: generated comparison artifact. Does not claim Golden Era runtime proof.
"""

from __future__ import annotations

import argparse
import colorsys
import html
import json
import math
import pathlib
import shutil
import sys
from collections import Counter, defaultdict
from typing import Callable

from PIL import Image, ImageDraw, ImageFont

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(HERE) not in sys.path:
	sys.path.insert(0, str(HERE))
if str(ROOT / "tools") not in sys.path:
	sys.path.insert(0, str(ROOT / "tools"))

from build_hota_alt_attack_palette_proof import (  # noqa: E402
	PALETTE_OFFSET,
	PALETTE_SIZE,
	checkerboard,
	classify_color,
	composite_on_checker,
	hex_rgb,
	load_json,
	luminance,
	palette_bytes,
	palette_from_def,
	read_zip_member,
	relative_to_root,
	repo_root,
	resolve_repo_path,
)
from hota_alt_palette_strategies import (  # noqa: E402
	STRATEGIES,
	StrategyFn,
	clamp_byte,
	concept_primary_shell_hue_deg,
	rgb_dist,
	soft_class_scores,
	strategy_baseline,
	strategy_cluster_hist_match,
	strategy_cluster_ramp,
	strategy_hue_shift_shell,
	strategy_hybrid_linked_hue,
	strategy_linked_consensus,
	strategy_material_class_hs,
	strategy_multi_seed_hsv,
	strategy_region_ramp,
	strategy_soft_blend,
)



def apply_palette_to_rgba(
	image: Image.Image,
	source_palette: list[tuple[int, int, int]],
	target_palette: list[tuple[int, int, int]],
) -> Image.Image:
	"""Map each opaque pixel to nearest source palette entry, then to target RGB."""
	rgba = image.convert("RGBA")
	# Exact map first for speed.
	exact = {rgb: i for i, rgb in enumerate(source_palette)}
	pixels = list(rgba.getdata())
	out: list[tuple[int, int, int, int]] = []
	cache: dict[tuple[int, int, int], int] = {}
	for r, g, b, a in pixels:
		if a < 8:
			out.append((r, g, b, a))
			continue
		key = (r, g, b)
		idx = exact.get(key)
		if idx is None:
			idx = cache.get(key)
			if idx is None:
				best = 0
				best_d = 1e18
				for i, (pr, pg, pb) in enumerate(source_palette):
					d = (pr - r) * (pr - r) + (pg - g) * (pg - g) + (pb - b) * (pb - b)
					if d < best_d:
						best_d = d
						best = i
						if d == 0:
							break
				idx = best
				cache[key] = idx
		tr, tg, tb = target_palette[idx]
		out.append((tr, tg, tb, a))
	result = Image.new("RGBA", rgba.size)
	result.putdata(out)
	return result


def speckle_score(image: Image.Image, radius: int = 1) -> float:
	rgba = image.convert("RGBA")
	bbox = rgba.getchannel("A").getbbox()
	if not bbox:
		return 0.0
	l, t, r, b = bbox
	px = rgba.load()
	diffs: list[float] = []
	for y in range(t + radius, b - radius):
		for x in range(l + radius, r - radius):
			r0, g0, b0, a0 = px[x, y]
			if a0 < 200:
				continue
			rs = gs = bs = n = 0
			for dy in range(-radius, radius + 1):
				for dx in range(-radius, radius + 1):
					rr, gg, bb, aa = px[x + dx, y + dy]
					if aa < 200:
						continue
					rs += rr
					gs += gg
					bs += bb
					n += 1
			if n < 4:
				continue
			mr, mg, mb = rs / n, gs / n, bs / n
			diffs.append(abs(r0 - mr) + abs(g0 - mg) + abs(b0 - mb))
	return sum(diffs) / len(diffs) if diffs else 0.0


def abrupt_adjacent_jumps(
	source_palette: list[tuple[int, int, int]],
	target_palette: list[tuple[int, int, int]],
	rows: list[dict],
) -> int:
	count = 0
	for i in range(8, len(source_palette) - 1):
		src_d = sum(abs(a - b) for a, b in zip(source_palette[i], source_palette[i + 1]))
		tgt_d = sum(abs(a - b) for a, b in zip(target_palette[i], target_palette[i + 1]))
		if src_d <= 12 and tgt_d >= 80 and (rows[i]["changed"] or rows[i + 1]["changed"]):
			count += 1
	return count


def mean_delta_e_proxy(source: Image.Image, target: Image.Image) -> float:
	"""Cheap mean RGB L1 on opaque pixels (not CIEDE2000, but stable for ranking)."""
	s = source.convert("RGBA")
	t = target.convert("RGBA")
	sp, tp = s.load(), t.load()
	w, h = s.size
	acc = 0.0
	n = 0
	for y in range(h):
		for x in range(w):
			r, g, b, a = sp[x, y]
			if a < 200:
				continue
			r2, g2, b2, a2 = tp[x, y]
			acc += abs(r - r2) + abs(g - g2) + abs(b - b2)
			n += 1
	return acc / max(n, 1)


def crop_subject(image: Image.Image, pad: int = 4, scale: int = 3) -> Image.Image:
	rgba = image.convert("RGBA")
	bbox = rgba.getchannel("A").getbbox()
	if not bbox:
		return rgba
	l, t, r, b = bbox
	cropped = rgba.crop((max(0, l - pad), max(0, t - pad), min(rgba.width, r + pad), min(rgba.height, b + pad)))
	return cropped.resize((cropped.width * scale, cropped.height * scale), Image.Resampling.NEAREST)


def opaque_union_bbox(
	frames: list[Image.Image],
	*,
	pad: int = 4,
	alpha_threshold: int = 8,
) -> tuple[int, int, int, int] | None:
	"""Shared opaque bbox across frames, expanded by pad and clamped to canvas."""
	union: list[int] | None = None
	width = height = 0
	for frame in frames:
		rgba = frame.convert("RGBA")
		width, height = rgba.size
		# Threshold soft edges so near-transparent noise does not inflate the box.
		mask = rgba.getchannel("A").point(lambda a, t=alpha_threshold: 255 if a >= t else 0)
		bbox = mask.getbbox()
		if not bbox:
			continue
		if union is None:
			union = list(bbox)
		else:
			union[0] = min(union[0], bbox[0])
			union[1] = min(union[1], bbox[1])
			union[2] = max(union[2], bbox[2])
			union[3] = max(union[3], bbox[3])
	if union is None or width <= 0 or height <= 0:
		return None
	l, t, r, b = union
	return (
		max(0, l - pad),
		max(0, t - pad),
		min(width, r + pad),
		min(height, b + pad),
	)


def _opaque_bbox(frame: Image.Image, *, alpha_threshold: int = 8) -> tuple[int, int, int, int] | None:
	rgba = frame.convert("RGBA")
	mask = rgba.getchannel("A").point(lambda a, t=alpha_threshold: 255 if a >= t else 0)
	return mask.getbbox()


def crop_frames_to_bbox(
	frames: list[Image.Image],
	bbox: tuple[int, int, int, int],
	*,
	scale: int = 3,
) -> list[Image.Image]:
	"""Crop every frame to the same box, then nearest-neighbor scale (stable animation)."""
	out: list[Image.Image] = []
	for frame in frames:
		cropped = frame.crop(bbox)
		if scale != 1:
			cropped = cropped.resize(
				(cropped.width * scale, cropped.height * scale),
				Image.Resampling.NEAREST,
			)
		out.append(cropped)
	return out


def crop_frames_subject_centered(
	frames: list[Image.Image],
	*,
	guide_frames: list[Image.Image] | None = None,
	pad: int = 4,
	scale: int = 3,
	alpha_threshold: int = 8,
) -> list[Image.Image]:
	"""Per-frame opaque crops pasted onto a shared max-size canvas (bottom-centered).

	Union-of-positions crops leave quiet frames tiny inside a wide motion hull.
	Centering each subject into max(w)×max(h) keeps the creature large in the picker.
	``guide_frames`` supply alpha when ``frames`` are already checker-composited RGB.
	"""
	guides = guide_frames if guide_frames is not None else frames
	if len(guides) != len(frames):
		raise ValueError(f"guide/frame count mismatch: {len(guides)} vs {len(frames)}")
	boxes: list[tuple[int, int, int, int]] = []
	for guide in guides:
		bbox = _opaque_bbox(guide, alpha_threshold=alpha_threshold)
		if bbox is None:
			raise ValueError("frame has no opaque subject for display crop")
		boxes.append(bbox)
	max_w = max(r - l for l, t, r, b in boxes)
	max_h = max(b - t for l, t, r, b in boxes)
	canvas_w = max_w + 2 * pad
	canvas_h = max_h + 2 * pad
	out: list[Image.Image] = []
	for frame, (l, t, r, b) in zip(frames, boxes):
		subject = frame.crop((l, t, r, b))
		# Preserve RGBA when present so write_gif can checker-composite; RGB for refresh path.
		if subject.mode == "RGBA":
			canvas: Image.Image = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
			x = (canvas_w - subject.width) // 2
			y = canvas_h - pad - subject.height
			canvas.paste(subject, (x, y), subject)
		else:
			canvas = checkerboard((canvas_w, canvas_h)).convert("RGB")
			x = (canvas_w - subject.width) // 2
			y = canvas_h - pad - subject.height
			canvas.paste(subject.convert("RGB"), (x, y))
		if scale != 1:
			canvas = canvas.resize(
				(canvas.width * scale, canvas.height * scale),
				Image.Resampling.NEAREST,
			)
		out.append(canvas)
	return out


def write_gif(path: pathlib.Path, frames: list[Image.Image], fps: float) -> None:
	if not frames:
		raise ValueError("no frames")
	duration = max(20, int(round(1000.0 / fps)))
	converted = [composite_on_checker(frame) for frame in frames]
	converted[0].save(
		path,
		save_all=True,
		append_images=converted[1:],
		duration=duration,
		loop=0,
		optimize=False,
	)


def write_rgb_gif(path: pathlib.Path, frames: list[Image.Image], fps: float) -> None:
	"""Write already-composited RGB frames (e.g. cropped from an existing attack.gif)."""
	if not frames:
		raise ValueError("no frames")
	duration = max(20, int(round(1000.0 / fps)))
	converted = [frame.convert("RGB") for frame in frames]
	converted[0].save(
		path,
		save_all=True,
		append_images=converted[1:],
		duration=duration,
		loop=0,
		optimize=False,
	)


def load_gif_frames(path: pathlib.Path) -> list[Image.Image]:
	im = Image.open(path)
	frames: list[Image.Image] = []
	while True:
		frames.append(im.convert("RGB"))
		try:
			im.seek(im.tell() + 1)
		except EOFError:
			break
	return frames


def run_comparison(profile_path: pathlib.Path, out_dir: pathlib.Path, strategies: list[str]) -> dict:
	profile = load_json(profile_path)
	source_frames_dir = resolve_repo_path(profile["outputDir"]) / "source_frames"
	if not source_frames_dir.is_dir():
		raise FileNotFoundError(
			f"missing source_frames under {profile['outputDir']}; "
			"run build_hota_alt_attack_palette_proof.py first"
		)
	group = int(profile["group"])
	frame_paths = sorted(source_frames_dir.glob(f"{group:02d}_*.png"))
	if len(frame_paths) != int(profile["expectedFrameCount"]):
		raise ValueError(
			f"expected {profile['expectedFrameCount']} source frames, found {len(frame_paths)}"
		)

	source_def = read_zip_member(resolve_repo_path(profile["sourceZipPath"]), profile["sourceZipMember"])
	source_palette = palette_from_def(source_def)
	source_images = [Image.open(path).convert("RGBA") for path in frame_paths]
	mid = source_images[len(source_images) // 2]
	fps = float(profile["expectedFps"])

	out_dir.mkdir(parents=True, exist_ok=True)
	results: list[dict] = []

	# Source reference metrics.
	source_speckle = speckle_score(mid)
	source_tile = crop_subject(mid)
	source_tile.save(out_dir / "00_source_mid.png")

	for name in strategies:
		fn = STRATEGIES[name]
		target_palette, rows = fn(source_palette, profile)
		remapped = [apply_palette_to_rgba(frame, source_palette, target_palette) for frame in source_images]
		mid_remapped = remapped[len(remapped) // 2]
		speckle = speckle_score(mid_remapped)
		abrupt = abrupt_adjacent_jumps(source_palette, target_palette, rows)
		delta = mean_delta_e_proxy(mid, mid_remapped)
		changed = sum(1 for row in rows if row["changed"])

		strategy_dir = out_dir / name
		strategy_dir.mkdir(parents=True, exist_ok=True)
		(strategy_dir / "palette_map.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
		crop_subject(mid_remapped).save(strategy_dir / "mid_crop.png")
		write_gif(strategy_dir / "attack.gif", remapped, fps)
		# Side-by-side mid frame
		left = crop_subject(mid)
		right = crop_subject(mid_remapped)
		pair = Image.new("RGBA", (left.width + right.width + 12, max(left.height, right.height) + 28), (18, 20, 24, 255))
		pair.paste(left, (0, 20), left)
		pair.paste(right, (left.width + 12, 20), right)
		draw = ImageDraw.Draw(pair)
		try:
			font = ImageFont.truetype("segoeui.ttf", 14)
		except OSError:
			font = ImageFont.load_default()
		draw.text((4, 2), "source", fill=(220, 220, 220, 255), font=font)
		draw.text((left.width + 16, 2), name, fill=(220, 220, 220, 255), font=font)
		pair.save(strategy_dir / "mid_pair.png")

		# Also emit a patched DEF for the winner-candidate path.
		patched = bytearray(source_def)
		patched[PALETTE_OFFSET : PALETTE_OFFSET + PALETTE_SIZE] = palette_bytes(target_palette)
		(strategy_dir / f"patched_{name}.def").write_bytes(bytes(patched))

		grain_ratio = speckle / max(source_speckle, 1e-6)
		results.append(
			{
				"strategy": name,
				"speckleScore": round(speckle, 4),
				"sourceSpeckleScore": round(source_speckle, 4),
				"grainRatio": round(grain_ratio, 4),
				"abruptAdjacentJumps": abrupt,
				"meanOpaqueRgbL1": round(delta, 4),
				"changedPaletteEntries": changed,
				"midPair": relative_to_root(strategy_dir / "mid_pair.png"),
				"midCrop": relative_to_root(strategy_dir / "mid_crop.png"),
				"attackGif": relative_to_root(strategy_dir / "attack.gif"),
				"patchedDef": relative_to_root(strategy_dir / f"patched_{name}.def"),
			}
		)

	# Rank for grain first, but require meaningful remap (palette-only no-ops lose).
	# Visual plated identity needs some opaque RGB movement; grain-only winners that
	# barely change the sprite are reported separately.
	meaningful = [row for row in results if row["meanOpaqueRgbL1"] >= 20.0]
	grain_only = sorted(results, key=lambda row: (row["grainRatio"], row["abruptAdjacentJumps"]))
	balanced = sorted(
		meaningful or results,
		key=lambda row: (row["grainRatio"], row["abruptAdjacentJumps"], -row["meanOpaqueRgbL1"]),
	)
	for index, row in enumerate(balanced):
		row["rank"] = index + 1
	# Keep non-balanced rows after with worse ranks for the table.
	seen = {row["strategy"] for row in balanced}
	extra = [row for row in grain_only if row["strategy"] not in seen]
	for index, row in enumerate(extra, start=len(balanced) + 1):
		row["rank"] = index
	ranked = balanced + extra

	report = {
		"schemaVersion": 1,
		"profile": relative_to_root(profile_path),
		"concept": profile.get("conceptName"),
		"sourceUnitSid": profile.get("sourceUnitSid"),
		"evidenceLevel": "generated_strategy_comparison",
		"proofBoundary": "Palette-index strategies only. Not bundle/runtime proven.",
		"sourceSpeckleScore": round(source_speckle, 4),
		"rankingNote": (
			"Primary recommendation prefers strategies with meanOpaqueRgbL1>=20 "
			"(visible remap) then lowest grainRatio/abrupt jumps. "
			"Near-noop low-grain strategies are listed but not preferred for plated look."
		),
		"strategies": ranked,
		"recommended": balanced[0]["strategy"] if balanced else None,
		"lowestGrain": grain_only[0]["strategy"] if grain_only else None,
	}
	(out_dir / "comparison_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
	write_comparison_html(report, out_dir)
	write_contact_sheet(out_dir, ranked, source_tile)
	return report


def write_contact_sheet(out_dir: pathlib.Path, ranked: list[dict], source_tile: Image.Image) -> None:
	tiles = [("source", source_tile)]
	for row in ranked:
		tiles.append((row["strategy"], Image.open(ROOT / row["midCrop"]).convert("RGBA")))
	tile_w = max(im.width for _, im in tiles)
	tile_h = max(im.height for _, im in tiles)
	label_h = 36
	pad = 10
	cols = len(tiles)
	sheet = Image.new("RGB", (pad + cols * (tile_w + pad), pad + tile_h + label_h + pad), (14, 16, 20))
	draw = ImageDraw.Draw(sheet)
	try:
		font = ImageFont.truetype("segoeui.ttf", 13)
	except OSError:
		font = ImageFont.load_default()
	for i, (label, im) in enumerate(tiles):
		x = pad + i * (tile_w + pad)
		y = pad
		canvas = Image.new("RGBA", (tile_w, tile_h), (0, 0, 0, 0))
		canvas.paste(im, ((tile_w - im.width) // 2, (tile_h - im.height) // 2), im)
		sheet.paste(composite_on_checker(canvas), (x, y))
		draw.text((x + 4, y + tile_h + 8), label[:22], fill=(230, 230, 230), font=font)
	sheet.save(out_dir / "comparison_contact_sheet.png")


def write_comparison_html(report: dict, out_dir: pathlib.Path) -> None:
	rows = report["strategies"]
	parts = [
		"<!doctype html><html><head><meta charset='utf-8'>",
		"<title>Palette grain strategy comparison</title>",
		"<style>",
		"body{font:14px/1.45 Segoe UI,Arial,sans-serif;background:#0b0e12;color:#eef1f4;margin:0;padding:18px}",
		"table{border-collapse:collapse;width:100%;margin:12px 0 24px}",
		"th,td{border:1px solid #2c3540;padding:8px;text-align:left}",
		"th{background:#151a21}",
		".best{outline:2px solid #e0b35a}",
		"img{image-rendering:pixelated;max-width:100%;background:#111}",
		".grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}",
		".card{background:#151a21;border:1px solid #2c3540;border-radius:8px;padding:10px}",
		".muted{color:#9aa3ad}",
		"</style></head><body>",
		f"<h1>Palette grain strategies — {html.escape(str(report.get('concept')))}</h1>",
		f"<p class='muted'>Source speckle={report['sourceSpeckleScore']}. "
		f"Recommended (visible remap): <strong>{html.escape(str(report.get('recommended')))}</strong>. "
		f"Lowest grain overall: <strong>{html.escape(str(report.get('lowestGrain')))}</strong>. "
		f"{html.escape(str(report.get('rankingNote') or ''))} "
		"Evidence: generated comparison only.</p>",
		"<table><tr><th>Rank</th><th>Strategy</th><th>grainRatio</th><th>speckle</th>"
		"<th>abrupt jumps</th><th>mean RGB L1</th><th>changed entries</th></tr>",
	]
	for row in rows:
		klass = " class='best'" if row["strategy"] == report.get("recommended") else ""
		parts.append(
			f"<tr{klass}><td>{row['rank']}</td><td>{html.escape(row['strategy'])}</td>"
			f"<td>{row['grainRatio']}</td><td>{row['speckleScore']}</td>"
			f"<td>{row['abruptAdjacentJumps']}</td><td>{row['meanOpaqueRgbL1']}</td>"
			f"<td>{row['changedPaletteEntries']}</td></tr>"
		)
	parts.append("</table><div class='grid'>")
	parts.append(
		"<div class='card'><strong>source</strong><br>"
		"<img src='00_source_mid.png' alt='source'></div>"
	)
	for row in rows:
		rel_gif = pathlib.Path(row["attackGif"]).name
		# gif is nested
		rel_gif = f"{row['strategy']}/attack.gif"
		rel_pair = f"{row['strategy']}/mid_pair.png"
		parts.append(
			f"<div class='card'><strong>{html.escape(row['strategy'])}</strong> "
			f"(rank {row['rank']})<br>"
			f"<img src='{html.escape(rel_pair)}' alt='{html.escape(row['strategy'])}'><br>"
			f"<img src='{html.escape(rel_gif)}' alt='gif'></div>"
		)
	parts.append("</div></body></html>")
	(out_dir / "index.html").write_text("\n".join(parts) + "\n", encoding="utf-8")


def main() -> int:
	ap = argparse.ArgumentParser(description=__doc__)
	ap.add_argument(
		"--profile",
		type=pathlib.Path,
		default=ROOT
		/ "tools/homm3_import/alternate_upgrade_concepts/factory__t3__h3_armadillo/animation_proof/plated_armadillo_attack_profile.json",
	)
	ap.add_argument(
		"--out",
		type=pathlib.Path,
		default=None,
		help="Output directory (default: <profile outputDir>/grain_strategy_comparison)",
	)
	ap.add_argument(
		"--strategies",
		nargs="+",
		choices=sorted(STRATEGIES.keys()),
		default=sorted(STRATEGIES.keys()),
	)
	args = ap.parse_args()
	profile = load_json(resolve_repo_path(args.profile))
	out_dir = (
		resolve_repo_path(args.out)
		if args.out
		else resolve_repo_path(profile["outputDir"]) / "grain_strategy_comparison"
	)
	if out_dir.exists():
		shutil.rmtree(out_dir)
	report = run_comparison(resolve_repo_path(args.profile), out_dir, list(args.strategies))
	print(f"recommended={report['recommended']}")
	for row in report["strategies"]:
		print(
			f"{row['rank']}. {row['strategy']}: grainRatio={row['grainRatio']} "
			f"speckle={row['speckleScore']} abrupt={row['abruptAdjacentJumps']} "
			f"l1={row['meanOpaqueRgbL1']}"
		)
	print(f"html {relative_to_root(out_dir / 'index.html')}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
