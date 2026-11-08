#!/usr/bin/env python3
"""Recolor Factory/Bulwark material_class_hs alt-upgrade interface portraits.

HotA iconsLarge portraits for a faction share one background. Alternate upgrades
reuse the upgraded-line portrait art, so a full material_class_hs remap would
also tint that shared backdrop. This bake:

1. Builds a shared-background mask from that faction's upgrade portraits on
   DIFFERENT lines (pixels identical in color+position on >=2 lines).
2. Applies the same material_class_hs / material_remap HSV path used for battle
   sprites, but only to non-mask (subject) pixels.
3. Writes OfflineUnlockMod/homm3_portraits/<gameAltSid>.png.

Fail-closed on mask coverage that is suspiciously low or high.
Evidence: generated + deployed-payload after plugin deploy; not runtime-proven.
"""

from __future__ import annotations

import argparse
import io
import json
import pathlib
import sys

from PIL import Image

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PORTRAITS = (
	ROOT
	/ "Heroes of Might & Magic Olden Era Playtest"
	/ "OfflineUnlockMod"
	/ "homm3_portraits"
)
GALLERY_INDEX = HERE / "recolor_galleries" / "index.json"
DEFAULT_SELECTIONS = HERE / "alternate_upgrade_concepts" / "material_class_hs_selections.json"
SPOTCHECK_ROOT = HERE / "alternate_upgrade_concepts" / "material_class_hs_portrait_spotcheck"
REPORT_DIR = HERE / "alternate_upgrade_concepts"

SUPPORTED_FACTIONS = ("factory", "bulwark")

# Fail-closed bounds for shared-background coverage on 58x64 HotA icons.
# Factory ~57%; Bulwark ~61% with all distinct upgrade lines.
MASK_COVERAGE_MIN = 0.25
MASK_COVERAGE_MAX = 0.72
MIN_LINES_FOR_MASK = 4


def load_json(path: pathlib.Path) -> dict:
	return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: pathlib.Path, data: dict) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def relative_to_root(path: pathlib.Path) -> str:
	resolved = path.resolve()
	root = ROOT.resolve()
	try:
		return resolved.relative_to(root).as_posix()
	except ValueError:
		return resolved.as_posix()


def spotcheck_dir_for(faction: str) -> pathlib.Path:
	return SPOTCHECK_ROOT / faction


def report_path_for(faction: str) -> pathlib.Path:
	return REPORT_DIR / f"material_class_hs_portrait_bake_report_{faction}.json"


def gallery_option_materials(faction: str, base_sid: str, option_id: str, line: str | None) -> dict:
	index = load_json(GALLERY_INDEX)
	for gallery in index.get("galleries") or []:
		if gallery.get("faction") != faction or gallery.get("baseSid") != base_sid:
			continue
		if (gallery.get("line") or None) != (line or None):
			continue
		for option in gallery.get("options") or []:
			if option.get("optionId") == option_id:
				materials = option.get("materials")
				if not isinstance(materials, dict) or not materials:
					raise ValueError(f"{base_sid}/{option_id}: missing materials")
				return materials
	raise KeyError(f"gallery option not found: {faction} {base_sid} {option_id} line={line!r}")


def line_key(selection: dict) -> str:
	"""Stable per-line identity so same-tier Couatl/Dreadnought stay distinct."""
	line = selection.get("line")
	if line:
		return f"{selection['baseSid']}__{line}"
	return str(selection["baseSid"])


def faction_selections(selections_path: pathlib.Path, faction: str) -> list[dict]:
	if faction not in SUPPORTED_FACTIONS:
		raise ValueError(f"unsupported faction {faction!r}; expected one of {SUPPORTED_FACTIONS}")
	payload = load_json(selections_path)
	rows = []
	for row in payload.get("selections") or []:
		if row.get("faction") != faction:
			continue
		if row.get("strategy") != "material_class_hs":
			raise ValueError(f"{row.get('displayName')}: expected strategy material_class_hs")
		rows.append(row)
	if not rows:
		raise RuntimeError(f"{selections_path}: no {faction} material_class_hs selections")
	return rows


def load_rgba(path: pathlib.Path) -> Image.Image:
	if not path.is_file():
		raise FileNotFoundError(path)
	return Image.open(path).convert("RGBA")


def build_shared_background_mask(
	images: list[Image.Image],
	*,
	line_labels: list[str],
	faction: str,
) -> tuple[Image.Image, dict]:
	"""True pixels in the returned mask are shared background (preserve)."""
	if len(images) < 2:
		raise RuntimeError(f"shared-background mask requires >=2 different {faction} lines")
	if len(images) != len(line_labels):
		raise RuntimeError("images/line_labels length mismatch")
	if len(set(line_labels)) != len(line_labels):
		raise RuntimeError(f"mask corpus must use unique lines; got {line_labels}")

	size = images[0].size
	for image, label in zip(images, line_labels):
		if image.size != size:
			raise RuntimeError(f"{label}: portrait size {image.size} != {size}")
		if image.mode != "RGBA":
			raise RuntimeError(f"{label}: expected RGBA, got {image.mode}")

	width, height = size
	pixels = [list(image.getdata()) for image in images]
	mask_flags: list[int] = []
	shared = 0
	for index in range(width * height):
		counts: dict[tuple[int, int, int, int], int] = {}
		for row in pixels:
			color = row[index]
			counts[color] = counts.get(color, 0) + 1
		is_shared = any(count >= 2 for count in counts.values())
		mask_flags.append(255 if is_shared else 0)
		if is_shared:
			shared += 1

	total = width * height
	coverage = shared / total if total else 0.0
	if coverage < MASK_COVERAGE_MIN or coverage > MASK_COVERAGE_MAX:
		raise RuntimeError(
			f"{faction} shared-background mask coverage {coverage:.3f} outside fail-closed bounds "
			f"[{MASK_COVERAGE_MIN:.2f}, {MASK_COVERAGE_MAX:.2f}] "
			f"(shared={shared}/{total}, lines={len(images)})"
		)

	mask = Image.new("L", size)
	mask.putdata(mask_flags)
	stats = {
		"lineCount": len(images),
		"lines": list(line_labels),
		"size": [width, height],
		"totalPixels": total,
		"sharedBackgroundPixels": shared,
		"subjectPixels": total - shared,
		"sharedBackgroundCoverage": round(coverage, 6),
		"subjectCoverage": round(1.0 - coverage, 6),
		"method": f"identical_rgba_at_position_on_ge2_different_{faction}_lines",
		"coverageBounds": [MASK_COVERAGE_MIN, MASK_COVERAGE_MAX],
	}
	return mask, stats


def recolor_subject_pixels(source: Image.Image, materials: dict, background_mask: Image.Image) -> Image.Image:
	from generate_hota_alt_recolor_gallery import material_remap

	if source.size != background_mask.size:
		raise RuntimeError(f"mask size {background_mask.size} != portrait size {source.size}")
	remapped = material_remap(source, materials)
	src_px = list(source.convert("RGBA").getdata())
	dst_px = list(remapped.convert("RGBA").getdata())
	mask_px = list(background_mask.convert("L").getdata())
	out: list[tuple[int, int, int, int]] = []
	changed = 0
	for src, dst, flag in zip(src_px, dst_px, mask_px):
		if flag >= 128:
			out.append(src)
			continue
		out.append(dst)
		if dst != src:
			changed += 1
	image = Image.new("RGBA", source.size)
	image.putdata(out)
	image.info["subjectPixelsChanged"] = changed
	return image


def write_png_if_changed(path: pathlib.Path, image: Image.Image) -> bool:
	path.parent.mkdir(parents=True, exist_ok=True)
	buf = io.BytesIO()
	image.save(buf, "PNG", optimize=True)
	data = buf.getvalue()
	if path.exists() and path.read_bytes() == data:
		return False
	path.write_bytes(data)
	return True


def write_spotchecks(
	selection: dict,
	source: Image.Image,
	recolored: Image.Image,
	background_mask: Image.Image,
	*,
	spotcheck_dir: pathlib.Path,
) -> dict:
	spotcheck_dir.mkdir(parents=True, exist_ok=True)
	sid = selection["gameAltSid"]
	width, height = source.size
	pair = Image.new("RGBA", (width * 2 + 8, height), (18, 20, 24, 255))
	pair.paste(source, (0, 0))
	pair.paste(recolored, (width + 8, 0))
	pair_path = spotcheck_dir / f"{sid}_before_after.png"
	pair.save(pair_path)

	# Green = preserved background, red = subject recolor region.
	overlay = source.copy()
	src_px = list(source.getdata())
	mask_px = list(background_mask.getdata())
	out = []
	for (r, g, b, a), flag in zip(src_px, mask_px):
		if flag >= 128:
			out.append((r // 2, min(255, g // 2 + 120), b // 2, 255))
		else:
			out.append((min(255, r // 2 + 120), g // 2, b // 2, 255))
	overlay.putdata(out)
	overlay_path = spotcheck_dir / f"{sid}_mask_overlay.png"
	overlay.save(overlay_path)

	mask_path = spotcheck_dir / "shared_background_mask.png"
	background_mask.save(mask_path)

	return {
		"beforeAfter": relative_to_root(pair_path),
		"maskOverlay": relative_to_root(overlay_path),
		"sharedMask": relative_to_root(mask_path),
	}


def write_background_parity_spotcheck(
	images: list[Image.Image],
	labels: list[str],
	*,
	spotcheck_dir: pathlib.Path,
) -> str:
	"""Confirm two different lines share background under the mask."""
	if len(images) < 2:
		raise RuntimeError("need >=2 lines for background parity spotcheck")
	a, b = images[0], images[1]
	width, height = a.size
	gap = 8
	sheet = Image.new("RGBA", (width * 2 + gap, height), (18, 20, 24, 255))
	sheet.paste(a, (0, 0))
	sheet.paste(b, (width + gap, 0))
	path = spotcheck_dir / f"background_parity__{labels[0]}__vs__{labels[1]}.png"
	spotcheck_dir.mkdir(parents=True, exist_ok=True)
	sheet.save(path)
	return relative_to_root(path)


def bake_faction_alt_portraits(
	faction: str,
	*,
	selections_path: pathlib.Path = DEFAULT_SELECTIONS,
	portraits_dir: pathlib.Path = PORTRAITS,
	write_spotcheck: bool = True,
) -> dict:
	selections = faction_selections(selections_path, faction)
	if len(selections) < MIN_LINES_FOR_MASK:
		raise RuntimeError(
			f"need >= {MIN_LINES_FOR_MASK} {faction} lines for robust mask; got {len(selections)}"
		)

	# One upgrade portrait per distinct line (never pair base/upgrade of same line).
	by_line: dict[str, dict] = {}
	for selection in selections:
		key = line_key(selection)
		if key in by_line:
			raise RuntimeError(f"duplicate {faction} line key in selections: {key}")
		by_line[key] = selection

	mask_images: list[Image.Image] = []
	mask_labels: list[str] = []
	upgrade_paths: dict[str, str] = {}
	for key, selection in by_line.items():
		upgrade_sid = selection["upgradeSid"]
		path = portraits_dir / f"{upgrade_sid}.png"
		image = load_rgba(path)
		mask_images.append(image)
		mask_labels.append(key)
		upgrade_paths[key] = relative_to_root(path)

	background_mask, mask_stats = build_shared_background_mask(
		mask_images,
		line_labels=mask_labels,
		faction=faction,
	)
	mask_stats["upgradePortraitPaths"] = upgrade_paths

	spot_dir = spotcheck_dir_for(faction)
	results = []
	changed = 0
	for selection in selections:
		materials = gallery_option_materials(
			selection["faction"],
			selection["baseSid"],
			selection["optionId"],
			selection.get("line"),
		)
		upgrade_sid = selection["upgradeSid"]
		alt_sid = selection["gameAltSid"]
		source = load_rgba(portraits_dir / f"{upgrade_sid}.png")
		recolored = recolor_subject_pixels(source, materials, background_mask)
		subject_changed = int(recolored.info.get("subjectPixelsChanged") or 0)
		if subject_changed <= 0:
			raise RuntimeError(
				f"{alt_sid}: material_class_hs produced zero subject pixel changes "
				f"(optionId={selection['optionId']}); refusing no-op bake"
			)
		out_path = portraits_dir / f"{alt_sid}.png"
		did_change = write_png_if_changed(out_path, recolored)
		changed += int(did_change)
		row = {
			"displayName": selection["displayName"],
			"gameAltSid": alt_sid,
			"upgradeSid": upgrade_sid,
			"optionId": selection["optionId"],
			"line": selection.get("line"),
			"portraitPath": relative_to_root(out_path),
			"subjectPixelsChanged": subject_changed,
			"wrote": did_change,
		}
		if write_spotcheck:
			row["spotcheck"] = write_spotchecks(
				selection,
				source,
				recolored,
				background_mask,
				spotcheck_dir=spot_dir,
			)
		results.append(row)

	parity_path = None
	report_path = report_path_for(faction)
	if write_spotcheck:
		parity_path = write_background_parity_spotcheck(
			mask_images[:2],
			mask_labels[:2],
			spotcheck_dir=spot_dir,
		)
		mask_path = spot_dir / "shared_background_mask.png"
		background_mask.save(mask_path)

	report = {
		"schemaVersion": 1,
		"strategy": "material_class_hs",
		"faction": faction,
		"evidenceLevel": "generated_portrait_edit_from_interface_iconsLarge",
		"mask": mask_stats,
		"backgroundParitySpotcheck": parity_path,
		"altPortraits": results,
		"changedCount": changed,
		"notes": [
			f"Background = pixels identical in RGBA+position on >=2 different {faction.title()} lines.",
			"Subject = remaining pixels; remapped with gallery material_class_hs materials.",
			"Unique per-portrait background decorations may be falsely treated as subject.",
			"Subject colors that coincidentally match another line at the same pixel are preserved.",
		],
	}
	write_json(report_path, report)
	report["reportPath"] = relative_to_root(report_path)
	return report


def bake_factory_alt_portraits(
	*,
	selections_path: pathlib.Path = DEFAULT_SELECTIONS,
	portraits_dir: pathlib.Path = PORTRAITS,
	write_spotcheck: bool = True,
) -> dict:
	"""Backward-compatible Factory entry point."""
	return bake_faction_alt_portraits(
		"factory",
		selections_path=selections_path,
		portraits_dir=portraits_dir,
		write_spotcheck=write_spotcheck,
	)


def bake_bulwark_alt_portraits(
	*,
	selections_path: pathlib.Path = DEFAULT_SELECTIONS,
	portraits_dir: pathlib.Path = PORTRAITS,
	write_spotcheck: bool = True,
) -> dict:
	"""Bulwark entry point (same path as Factory)."""
	return bake_faction_alt_portraits(
		"bulwark",
		selections_path=selections_path,
		portraits_dir=portraits_dir,
		write_spotcheck=write_spotcheck,
	)


def update_portrait_manifest_sources(
	report: dict,
	portraits_dir: pathlib.Path = PORTRAITS,
	*,
	faction: str | None = None,
) -> bool:
	"""Annotate interfacePortraitSources so alt portraits cite the recolor bake."""
	manifest_path = portraits_dir / "manifest.json"
	if not manifest_path.is_file():
		return False
	manifest = load_json(manifest_path)
	sources = manifest.get("interfacePortraitSources")
	if not isinstance(sources, dict):
		sources = {}
	faction_name = faction or str(report.get("faction") or "factory")
	for row in report.get("altPortraits") or []:
		sid = row["gameAltSid"]
		upgrade = row["upgradeSid"]
		option = row["optionId"]
		prev = sources.get(sid) or f"homm3_portraits/{upgrade}.png"
		sources[sid] = (
			f"{prev} | material_class_hs subject-only recolor "
			f"(optionId={option}; shared {faction_name.title()} background mask)"
		)
	manifest["interfacePortraitSources"] = dict(sorted(sources.items()))
	key = f"{faction_name}AltPortraitRecolor"
	manifest[key] = {
		"strategy": "material_class_hs",
		"maskMethod": report.get("mask", {}).get("method"),
		"sharedBackgroundCoverage": report.get("mask", {}).get("sharedBackgroundCoverage"),
		"lineCount": report.get("mask", {}).get("lineCount"),
		"reportPath": report.get("reportPath"),
		"generatedBy": "tools/homm3_import/bake_factory_alt_portraits_material_class_hs.py",
	}
	text = json.dumps(manifest, indent=4) + "\n"
	if manifest_path.read_text(encoding="utf-8") == text:
		return False
	manifest_path.write_text(text, encoding="utf-8")
	return True


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument(
		"--faction",
		choices=SUPPORTED_FACTIONS,
		default="factory",
		help="Faction whose material_class_hs alt portraits to bake",
	)
	parser.add_argument("--selections", type=pathlib.Path, default=DEFAULT_SELECTIONS)
	parser.add_argument("--portraits-dir", type=pathlib.Path, default=PORTRAITS)
	parser.add_argument("--skip-spotcheck", action="store_true")
	parser.add_argument("--skip-manifest-update", action="store_true")
	args = parser.parse_args(argv)

	# Ensure homm3_import is importable for material_remap.
	if str(HERE) not in sys.path:
		sys.path.insert(0, str(HERE))

	report = bake_faction_alt_portraits(
		args.faction,
		selections_path=args.selections,
		portraits_dir=args.portraits_dir,
		write_spotcheck=not args.skip_spotcheck,
	)
	manifest_changed = False
	if not args.skip_manifest_update:
		manifest_changed = update_portrait_manifest_sources(
			report,
			args.portraits_dir,
			faction=args.faction,
		)
	print(
		f"{args.faction.title()} alt portraits recolored: {len(report['altPortraits'])} "
		f"(changed={report['changedCount']}, manifestChanged={manifest_changed})"
	)
	print(
		f"Mask lines={report['mask']['lineCount']} "
		f"sharedCoverage={report['mask']['sharedBackgroundCoverage']:.3f} "
		f"subjectCoverage={report['mask']['subjectCoverage']:.3f}"
	)
	print(f"Report: {report['reportPath']}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
