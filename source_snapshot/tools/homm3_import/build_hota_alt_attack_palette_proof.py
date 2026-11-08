#!/usr/bin/env python3
"""Build and validate a temporally stable HoMM3 attack recolor proof.

The source DEF owns one global indexed palette. This tool changes that palette
once, preserves the compressed animation body byte-for-byte, re-extracts the
requested attack group, and fails closed unless geometry, alpha, frame count,
resolution, and playback metadata still match the source contract.

The current attack contract is deliberately shooter-front group 15 / 14.Attack.
Palette classification is a fixed four-class material policy (soot, crimson, copper, ember);
profiles provide ramps and overrides, not a new classifier vocabulary.
"""
from __future__ import annotations

import argparse
import colorsys
import hashlib
import json
import math
import pathlib
import shutil
import sys
import zipfile

from PIL import Image, ImageDraw, ImageFont


PALETTE_OFFSET = 16
PALETTE_ENTRY_COUNT = 256
PALETTE_ENTRY_SIZE = 3
PALETTE_SIZE = PALETTE_ENTRY_COUNT * PALETTE_ENTRY_SIZE


def repo_root() -> pathlib.Path:
	return pathlib.Path(__file__).resolve().parents[2]


def load_json(path: pathlib.Path) -> dict:
	return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256_bytes(data: bytes) -> str:
	return hashlib.sha256(data).hexdigest()


def sha256_file(path: pathlib.Path) -> str:
	return sha256_bytes(path.read_bytes())


def relative_to_root(path: pathlib.Path) -> str:
	return path.resolve().relative_to(repo_root().resolve()).as_posix()


def resolve_repo_path(value: str) -> pathlib.Path:
	path = pathlib.Path(value)
	return path if path.is_absolute() else repo_root() / path


def require_repo_output(path: pathlib.Path) -> pathlib.Path:
	resolved = path.resolve()
	allowed_root = (repo_root() / "tools" / "homm3_import" / "alternate_upgrade_concepts").resolve()
	try:
		relative = resolved.relative_to(allowed_root)
	except ValueError as ex:
		raise ValueError(f"outputDir must remain under {allowed_root}: {resolved}") from ex
	if not (
		(resolved.name == "animation_proof" or resolved.name.startswith("animation_proof_"))
		and len(relative.parts) >= 2
	):
		raise ValueError(f"outputDir must be a concept-owned animation_proof directory: {resolved}")
	return resolved


def require_output_def_name(value: str) -> str:
	path = pathlib.Path(value)
	if path.is_absolute() or path.name != value or path.suffix.lower() != ".def":
		raise ValueError(f"outputDefName must be a basename ending in .def: {value!r}")
	return value


def require_output_file_name(value: str, suffix: str) -> str:
	path = pathlib.Path(value)
	if path.is_absolute() or path.name != value or path.suffix.lower() != suffix.lower():
		raise ValueError(f"preview file must be a basename ending in {suffix}: {value!r}")
	return value


def preview_names(profile: dict) -> dict[str, str]:
	if "previewStem" not in profile:
		raise ValueError("profile must define previewStem for generated preview names")
	stem = str(profile["previewStem"]).strip()
	if not stem or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for character in stem):
		raise ValueError(f"previewStem must be a non-empty filename stem: {stem!r}")
	return {
		"exactApng": require_output_file_name(f"{stem}.png", ".png"),
		"exactGif": require_output_file_name(f"{stem}.gif", ".gif"),
		"detailComparisonGif": require_output_file_name(
			str(profile.get("detailPreviewName", f"original_vs_{stem}_detail.gif")), ".gif"
		),
		"contactSheet": require_output_file_name(
			str(profile.get("contactSheetName", "attack_contact_sheet.png")), ".png"
		),
	}


def read_zip_member(zip_path: pathlib.Path, member: str) -> bytes:
	want = member.replace("\\", "/")
	with zipfile.ZipFile(zip_path) as archive:
		by_lower = {name.replace("\\", "/").lower(): name for name in archive.namelist()}
		resolved = by_lower.get(want.lower())
		if resolved is None:
			raise FileNotFoundError(f"{member!r} is not present in {zip_path}")
		return archive.read(resolved)


def palette_from_def(data: bytes) -> list[tuple[int, int, int]]:
	end = PALETTE_OFFSET + PALETTE_SIZE
	if len(data) < end:
		raise ValueError(f"DEF is too short for a 256-entry palette: {len(data)} bytes")
	return [
		tuple(data[PALETTE_OFFSET + index * 3 : PALETTE_OFFSET + index * 3 + 3])
		for index in range(PALETTE_ENTRY_COUNT)
	]


def palette_bytes(palette: list[tuple[int, int, int]]) -> bytes:
	if len(palette) != PALETTE_ENTRY_COUNT:
		raise ValueError(f"expected {PALETTE_ENTRY_COUNT} palette entries, got {len(palette)}")
	return bytes(channel for rgb in palette for channel in rgb)


def def_body_without_palette(data: bytes) -> bytes:
	return data[:PALETTE_OFFSET] + data[PALETTE_OFFSET + PALETTE_SIZE :]


def parse_hex(value: str) -> tuple[int, int, int]:
	text = value.strip().lstrip("#")
	if len(text) != 6:
		raise ValueError(f"expected RRGGBB color, got {value!r}")
	return tuple(int(text[index : index + 2], 16) for index in (0, 2, 4))


def hex_rgb(rgb: tuple[int, int, int]) -> str:
	return "#" + "".join(f"{channel:02x}" for channel in rgb)


def luminance(rgb: tuple[int, int, int]) -> float:
	r, g, b = rgb
	return 0.2126 * r + 0.7152 * g + 0.0722 * b


def sample_ramp(ramp: list[tuple[int, int, int]], position: float) -> tuple[int, int, int]:
	position = max(0.0, min(1.0, position))
	if len(ramp) == 1:
		return ramp[0]
	scaled = position * (len(ramp) - 1)
	left = min(int(math.floor(scaled)), len(ramp) - 2)
	amount = scaled - left
	return tuple(
		int(round(ramp[left][channel] * (1.0 - amount) + ramp[left + 1][channel] * amount))
		for channel in range(3)
	)


def classify_color(index: int, rgb: tuple[int, int, int], profile: dict) -> str:
	special_count = int(profile["specialPaletteSlotCount"])
	if index < special_count:
		return "special"

	overrides = profile.get("classOverrides") or {}
	for class_name, indices in overrides.items():
		if index in {int(value) for value in indices}:
			return str(class_name)

	r, g, b = rgb
	if max(rgb) == 0:
		return "soot"
	hue, saturation, _ = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
	hue *= 360.0
	green_ratio = g / max(r, 1)
	blue_green_ratio = b / max(g, 1)

	# Skin is deliberately immutable. Ratios separate it from the red waistcoat
	# and the darker brown sling/canister hardware.
	if (
		r >= 72
		and g >= 35
		and b >= 26
		and hue <= 32.0
		and 0.10 <= saturation <= 0.58
		and green_ratio >= 0.55
		and blue_green_ratio >= 0.76
	):
		return "preserve"

	# Saturated red cloth remains the concept's crimson identity cue.
	if (
		r >= 36
		and (hue <= 18.0 or hue >= 345.0)
		and saturation >= 0.34
		and green_ratio < 0.55
	):
		return "crimson"

	# The brightest native gold/spark colors become the incendiary ember ramp.
	if (
		r >= 145
		and 12.0 <= hue <= 58.0
		and saturation >= 0.42
		and g >= 65
		and b <= 82
	):
		return "ember"

	# Warm sling, pouch, hat-band, and trim colors become copper hardware.
	if (
		r >= 28
		and 7.0 <= hue <= 78.0
		and saturation >= 0.18
		and green_ratio >= 0.34
	):
		return "copper"

	# Whites, greys, trousers, and remaining dark material become soot cloth.
	return "soot"


def build_target_palette(
	source_palette: list[tuple[int, int, int]],
	profile: dict,
) -> tuple[list[tuple[int, int, int]], list[dict]]:
	ramps = {
		name: [parse_hex(value) for value in values]
		for name, values in (profile.get("paletteRamps") or {}).items()
	}
	for required in ("soot", "crimson", "copper", "ember"):
		if required not in ramps or not ramps[required]:
			raise ValueError(f"paletteRamps.{required} must contain at least one color")

	curve = {
		"soot": 0.72,
		"crimson": 0.62,
		"copper": 0.68,
		"ember": 0.56,
	}
	target: list[tuple[int, int, int]] = []
	rows: list[dict] = []
	for index, source in enumerate(source_palette):
		class_name = classify_color(index, source, profile)
		if class_name in {"special", "preserve"}:
			mapped = source
		else:
			position = (luminance(source) / 255.0) ** curve[class_name]
			mapped = sample_ramp(ramps[class_name], position)
		target.append(mapped)
		rows.append(
			{
				"index": index,
				"class": class_name,
				"source": hex_rgb(source),
				"target": hex_rgb(mapped),
				"changed": mapped != source,
				"sourceLuminance": round(luminance(source), 4),
				"targetLuminance": round(luminance(mapped), 4),
			}
		)
	return target, rows


def concept_swatch_audit(concept_path: pathlib.Path, profile: dict) -> dict:
	with Image.open(concept_path) as opened:
		concept = opened.convert("RGBA")
	concept_rgba = concept.tobytes()
	pixels = {
		(concept_rgba[offset], concept_rgba[offset + 1], concept_rgba[offset + 2])
		for offset in range(0, len(concept_rgba), 4)
		if concept_rgba[offset + 3] > 0
	}
	if not pixels:
		raise ValueError(f"concept image has no visible pixels: {concept_path}")
	rows: list[dict] = []
	for class_name, values in (profile.get("paletteRamps") or {}).items():
		for value in values:
			rgb = parse_hex(value)
			distance = min(math.dist(rgb, concept_rgb) for concept_rgb in pixels)
			rows.append({"class": class_name, "color": value.lower(), "nearestConceptDistance": round(distance, 4)})
	maximum = max(row["nearestConceptDistance"] for row in rows)
	allowed = float(profile.get("maxConceptSwatchDistance", 16.0))
	if maximum > allowed:
		raise ValueError(f"palette ramp is not concept-grounded: distance {maximum:.3f} exceeds {allowed:.3f}")
	return {"maxDistance": maximum, "allowedDistance": allowed, "swatches": rows}


def source_sequence(profile: dict) -> tuple[list[pathlib.Path], dict, dict]:
	manifest_path = resolve_repo_path(profile["sourceManifestPath"])
	authoring_path = resolve_repo_path(profile["sourceAuthoringPath"])
	manifest = load_json(manifest_path)
	authoring = load_json(authoring_path)
	group = int(profile["group"])
	sequence = next((item for item in manifest.get("sequences") or [] if int(item.get("group", -1)) == group), None)
	if sequence is None:
		raise ValueError(f"source manifest has no group {group}: {manifest_path}")
	paths = [manifest_path.parent / pathlib.Path(str(value).replace("\\", "/")) for value in sequence.get("frames") or []]
	return paths, manifest, authoring


def source_attack_contract(profile: dict, manifest: dict, authoring: dict) -> dict:
	from audit_unit_animation_frames import (
		GROUP_ATTACK_FRONT,
		GROUP_SHOOT_FRONT,
		group_counts,
		preferred_attack_family,
	)

	counts = group_counts(manifest)
	family, preferred_groups = preferred_attack_family(authoring, counts)
	group = int(profile["group"])
	requested = str(profile.get("attackFamily") or "auto").strip().lower()
	if requested == "auto":
		requested = "shoot" if family.startswith("shoot") else "melee"
	errors: list[str] = []
	if requested == "shoot":
		if group != GROUP_SHOOT_FRONT:
			errors.append(f"proof group {group} is not GROUP_SHOOT_FRONT ({GROUP_SHOOT_FRONT})")
		if not family.startswith("shoot"):
			errors.append(f"source resolves to {family}, not the shooter attack family")
	elif requested == "melee":
		if group != GROUP_ATTACK_FRONT:
			errors.append(f"proof group {group} is not GROUP_ATTACK_FRONT ({GROUP_ATTACK_FRONT})")
		if not family.startswith("melee"):
			errors.append(f"source resolves to {family}, not the melee attack family")
	else:
		errors.append(f"attackFamily must be auto|shoot|melee, got {requested!r}")
	if group not in preferred_groups or counts.get(group, 0) <= 0:
		errors.append(f"source preferred attack group {group} has no frames")
	if profile.get("runtimeClip") != "14.Attack":
		errors.append(f"runtimeClip must be 14.Attack, got {profile.get('runtimeClip')!r}")
	if errors:
		raise ValueError("attack contract failed:\n- " + "\n- ".join(errors))
	return {
		"family": family,
		"requestedFamily": requested,
		"group": group,
		"runtimeClip": profile["runtimeClip"],
		"preferredGroups": list(preferred_groups),
		"groupFrameCount": counts[group],
	}

def alpha_bytes(image: Image.Image) -> bytes:
	return image.convert("RGBA").getchannel("A").tobytes()


def alpha_sequence_hash(paths: list[pathlib.Path]) -> str:
	digest = hashlib.sha256()
	for path in paths:
		with Image.open(path) as opened:
			image = opened.convert("RGBA")
		digest.update(alpha_bytes(image))
	return digest.hexdigest()


def checkerboard(size: tuple[int, int], tile: int = 12) -> Image.Image:
	image = Image.new("RGBA", size, (25, 26, 29, 255))
	draw = ImageDraw.Draw(image)
	for y in range(0, size[1], tile):
		for x in range(0, size[0], tile):
			if (x // tile + y // tile) % 2:
				draw.rectangle((x, y, min(x + tile - 1, size[0] - 1), min(y + tile - 1, size[1] - 1)), fill=(39, 41, 45, 255))
	return image


def composite_on_checker(image: Image.Image) -> Image.Image:
	background = checkerboard(image.size)
	background.alpha_composite(image.convert("RGBA"))
	return background.convert("RGB")


def exact_duration_schedule(frame_count: int, fps: float, quantum_ms: int) -> list[int]:
	total_ms = int(round(frame_count * 1000.0 / fps))
	# GIF stores durations in 10 ms units. Round the aggregate duration to a
	# representable value before distributing it, rather than creating a final
	# unrepresentable remainder that Pillow silently truncates.
	representable_total_ms = int(round(total_ms / quantum_ms)) * quantum_ms
	base_units, remainder = divmod(representable_total_ms, quantum_ms * frame_count)
	durations = [base_units * quantum_ms] * frame_count
	extra_units = int(round(remainder / quantum_ms))
	for index in range(extra_units):
		durations[((index + 1) * frame_count // extra_units - 1) if extra_units else 0] += quantum_ms
	return durations


def save_animation(path: pathlib.Path, frames: list[Image.Image], durations: list[int], *, format_name: str) -> None:
	if not frames:
		raise ValueError("cannot save an empty animation")
	first, rest = frames[0], frames[1:]
	if format_name == "GIF":
		converted = [frame.convert("P", palette=Image.Palette.ADAPTIVE, colors=256) for frame in frames]
		converted[0].save(
			path,
			format="GIF",
			save_all=True,
			append_images=converted[1:],
			duration=durations,
			loop=0,
			disposal=2,
			optimize=False,
		)
		return
	first.save(
		path,
		format="PNG",
		save_all=True,
		append_images=rest,
		duration=durations,
		loop=0,
		disposal=0,
		blend=0,
	)


def union_alpha_bbox(frames: list[Image.Image]) -> tuple[int, int, int, int]:
	boxes = [frame.convert("RGBA").getchannel("A").getbbox() for frame in frames]
	visible = [box for box in boxes if box]
	if not visible:
		raise ValueError("sequence has no visible pixels")
	return (
		min(box[0] for box in visible),
		min(box[1] for box in visible),
		max(box[2] for box in visible),
		max(box[3] for box in visible),
	)


def expanded_bbox(box: tuple[int, int, int, int], size: tuple[int, int], margin: int = 8) -> tuple[int, int, int, int]:
	return (
		max(0, box[0] - margin),
		max(0, box[1] - margin),
		min(size[0], box[2] + margin),
		min(size[1], box[3] + margin),
	)


def load_rgba_frames(paths: list[pathlib.Path]) -> list[Image.Image]:
	result: list[Image.Image] = []
	for path in paths:
		with Image.open(path) as opened:
			result.append(opened.convert("RGBA"))
	return result


def make_detail_comparison_frames(
	source_frames: list[Image.Image],
	target_frames: list[Image.Image],
	box: tuple[int, int, int, int],
	scale: int,
	group: int,
	source_label: str,
	target_label: str,
) -> list[Image.Image]:
	font = ImageFont.load_default()
	result: list[Image.Image] = []
	for index, (source, target) in enumerate(zip(source_frames, target_frames, strict=True)):
		left = composite_on_checker(source.crop(box)).resize(
			((box[2] - box[0]) * scale, (box[3] - box[1]) * scale), Image.Resampling.NEAREST
		)
		right = composite_on_checker(target.crop(box)).resize(left.size, Image.Resampling.NEAREST)
		canvas = Image.new("RGB", (left.width * 2 + 20, left.height + 30), (16, 17, 19))
		canvas.paste(left, (0, 30))
		canvas.paste(right, (left.width + 20, 30))
		draw = ImageDraw.Draw(canvas)
		draw.text((6, 8), f"{source_label}  {group:02d}_{index:02d}", fill=(224, 226, 229), font=font)
		draw.text((left.width + 26, 8), f"{target_label}  {group:02d}_{index:02d}", fill=(255, 170, 93), font=font)
		result.append(canvas)
	return result

def make_previews(
	source_frames: list[Image.Image],
	target_frames: list[Image.Image],
	output_dir: pathlib.Path,
	fps: float,
	profile: dict,
) -> dict:
	frame_count = len(target_frames)
	apng_durations = exact_duration_schedule(frame_count, fps, 1)
	gif_durations = exact_duration_schedule(frame_count, fps, 10)

	names = preview_names(profile)
	group = int(profile["group"])
	source_label = str(profile.get("sourceLabel", profile["sourceUnitSid"]))
	target_label = str(profile.get("targetLabel", profile["conceptName"]))

	exact_apng = output_dir / names["exactApng"]
	save_animation(exact_apng, target_frames, apng_durations, format_name="PNG")

	exact_gif = output_dir / names["exactGif"]
	save_animation(exact_gif, [composite_on_checker(frame) for frame in target_frames], gif_durations, format_name="GIF")

	box = union_alpha_bbox(source_frames + target_frames)
	box = expanded_bbox(box, source_frames[0].size, margin=8)
	scale = 4
	detail_frames = make_detail_comparison_frames(source_frames, target_frames, box, scale, group, source_label, target_label)
	detail_gif = output_dir / names["detailComparisonGif"]
	save_animation(detail_gif, detail_frames, gif_durations, format_name="GIF")

	columns = 6
	font = ImageFont.load_default()
	rows = math.ceil(frame_count / columns)
	thumb_scale = 2
	crop_width = (box[2] - box[0]) * thumb_scale
	crop_height = (box[3] - box[1]) * thumb_scale
	cell_width = crop_width * 2 + 12
	cell_height = crop_height + 24
	sheet = Image.new("RGB", (columns * cell_width, rows * cell_height), (16, 17, 19))
	draw = ImageDraw.Draw(sheet)
	for index, (source, target) in enumerate(zip(source_frames, target_frames, strict=True)):
		x = (index % columns) * cell_width
		y = (index // columns) * cell_height
		left = composite_on_checker(source.crop(box)).resize((crop_width, crop_height), Image.Resampling.NEAREST)
		right = composite_on_checker(target.crop(box)).resize((crop_width, crop_height), Image.Resampling.NEAREST)
		sheet.paste(left, (x, y + 24))
		sheet.paste(right, (x + crop_width + 12, y + 24))
		draw.text((x + 4, y + 6), f"{group:02d}_{index:02d}  {source_label} | {target_label}", fill=(226, 228, 231), font=font)
	contact_sheet = output_dir / names["contactSheet"]
	sheet.save(contact_sheet)

	return {
		"exactApng": relative_to_root(exact_apng),
		"exactGif": relative_to_root(exact_gif),
		"detailComparisonGif": relative_to_root(detail_gif),
		"contactSheet": relative_to_root(contact_sheet),
		"cropBox": list(box),
		"detailScale": scale,
		"apngDurationsMs": apng_durations,
		"gifDurationsMs": gif_durations,
	}


def animation_audit(path: pathlib.Path) -> dict:
	with Image.open(path) as opened:
		frame_count = int(getattr(opened, "n_frames", 1))
		size = list(opened.size)
		loop = opened.info.get("loop")
		durations: list[float] = []
		frame_hashes: list[str] = []
		for index in range(frame_count):
			opened.seek(index)
			durations.append(float(opened.info.get("duration", 0.0)))
			frame_hashes.append(sha256_bytes(opened.convert("RGBA").tobytes()))
	return {
		"frameCount": frame_count,
		"size": size,
		"loop": loop,
		"durationMs": sum(durations),
		"frameDurationsMs": durations,
		"frameRgbaSha256": frame_hashes,
	}


def quantized_gif_frames(frames: list[Image.Image]) -> list[Image.Image]:
	return [
		frame.convert("P", palette=Image.Palette.ADAPTIVE, colors=256).convert("RGBA")
		for frame in frames
	]


def validate_previews(
	profile: dict,
	previews: dict,
	source_paths: list[pathlib.Path],
	target_paths: list[pathlib.Path],
) -> tuple[dict, list[str]]:
	errors: list[str] = []
	audits: dict[str, dict] = {}
	expected_count = int(profile["expectedFrameCount"])
	expected_size = [int(value) for value in profile["expectedSize"]]
	fps = float(profile["expectedFps"])
	apng_durations = [float(value) for value in exact_duration_schedule(expected_count, fps, 1)]
	gif_durations = [float(value) for value in exact_duration_schedule(expected_count, fps, 10)]
	source_frames = load_rgba_frames(source_paths)
	target_frames = load_rgba_frames(target_paths)
	detail_frames = make_detail_comparison_frames(
		source_frames,
		target_frames,
		tuple(int(value) for value in previews["cropBox"]),
		int(previews["detailScale"]),
		int(profile["group"]),
		str(profile.get("sourceLabel", profile["sourceUnitSid"])),
		str(profile.get("targetLabel", profile["conceptName"])),
	)
	expected_frames = {
		"exactApng": target_frames,
		"exactGif": quantized_gif_frames([composite_on_checker(frame) for frame in target_frames]),
		"detailComparisonGif": quantized_gif_frames(detail_frames),
	}
	expected_durations = {
		"exactApng": apng_durations,
		"exactGif": gif_durations,
		"detailComparisonGif": gif_durations,
	}
	expected_names = preview_names(profile)
	for key in ("exactApng", "exactGif", "detailComparisonGif"):
		if pathlib.PurePosixPath(str(previews[key])).name != expected_names[key]:
			errors.append(f"{key} path does not match the profile preview name")
		path = resolve_repo_path(previews[key])
		audit = animation_audit(path)
		audits[key] = audit
		if audit["frameCount"] != expected_count:
			errors.append(f"{key} frame count {audit['frameCount']} != {expected_count}")
		if audit["loop"] != 0:
			errors.append(f"{key} loop metadata {audit['loop']!r} != 0")
		if audit["frameDurationsMs"] != expected_durations[key]:
			errors.append(f"{key} per-frame cadence differs from the exact schedule")
		expected_hashes = [sha256_bytes(frame.convert("RGBA").tobytes()) for frame in expected_frames[key]]
		if audit["frameRgbaSha256"] != expected_hashes:
			errors.append(f"{key} decoded frame content differs from the generated sequence")
	for key in ("exactApng", "exactGif"):
		if audits[key]["size"] != expected_size:
			errors.append(f"{key} size {audits[key]['size']} != {expected_size}")
	return audits, errors

def validate_frames(
	profile: dict,
	source_paths: list[pathlib.Path],
	target_paths: list[pathlib.Path],
) -> tuple[list[dict], list[str]]:
	errors: list[str] = []
	rows: list[dict] = []
	expected_count = int(profile["expectedFrameCount"])
	expected_size = tuple(int(value) for value in profile["expectedSize"])
	group = int(profile["group"])
	expected_names = [f"{group:02d}_{index:02d}.png" for index in range(expected_count)]
	if len(source_paths) != expected_count:
		errors.append(f"source frame count {len(source_paths)} != {expected_count}")
	if [path.name for path in source_paths] != expected_names:
		errors.append("source frame names/order do not match the exact group contract")
	if [path.name for path in target_paths] != expected_names:
		errors.append("target frame names/order do not match the exact group contract")
	for index, (source_path, target_path) in enumerate(zip(source_paths, target_paths)):
		with Image.open(source_path) as opened:
			source = opened.convert("RGBA")
			source_mode = opened.mode
		with Image.open(target_path) as opened:
			target = opened.convert("RGBA")
			target_mode = opened.mode
		if source_mode != "RGBA":
			errors.append(f"{source_path.name}: source mode {source_mode} != RGBA")
		if target_mode != "RGBA":
			errors.append(f"{target_path.name}: target mode {target_mode} != RGBA")
		if source.size != expected_size or target.size != expected_size:
			errors.append(f"{source_path.name}: size source={source.size} target={target.size} expected={expected_size}")
		source_alpha = alpha_bytes(source)
		target_alpha = alpha_bytes(target)
		alpha_equal = source_alpha == target_alpha
		if not alpha_equal:
			errors.append(f"{source_path.name}: alpha plane changed")
		source_bbox = source.getchannel("A").getbbox()
		target_bbox = target.getchannel("A").getbbox()
		if source_bbox != target_bbox:
			errors.append(f"{source_path.name}: alpha bbox changed {source_bbox} -> {target_bbox}")
		source_rgba = source.tobytes()
		target_rgba = target.tobytes()
		visible_rgb_changed = sum(
			1
			for offset in range(0, len(source_rgba), 4)
			if source_rgba[offset + 3] > 0
			and source_rgba[offset : offset + 3] != target_rgba[offset : offset + 3]
		)
		rows.append(
			{
				"frame": f"{group:02d}_{index:02d}",
				"size": list(target.size),
				"sourceAlphaSha256": sha256_bytes(source_alpha),
				"targetAlphaSha256": sha256_bytes(target_alpha),
				"alphaEqual": alpha_equal,
				"sourceAlphaBbox": list(source_bbox) if source_bbox else None,
				"targetAlphaBbox": list(target_bbox) if target_bbox else None,
				"sourceRgbaSha256": sha256_bytes(source_rgba),
				"targetRgbaSha256": sha256_bytes(target_rgba),
				"visibleRgbChangedPixelCount": visible_rgb_changed,
			}
		)
	return rows, errors


def write_readme(profile_path: pathlib.Path, output_dir: pathlib.Path, report: dict) -> None:
	command = f"python tools/homm3_import/build_hota_alt_attack_palette_proof.py --profile {relative_to_root(profile_path)}"
	concept_name = report["concept"]["name"]
	source = report["source"]
	sequence = report["sequence"]
	source_label = str(report.get("sourceLabel", source["unitSid"]))
	target_label = str(report.get("targetLabel", concept_name))
	ramp_names = ", ".join(str(name) for name in (report.get("paletteClasses") or []))
	fence = chr(96) * 3
	text = f"""# {concept_name} Attack Pipeline Proof

This proof applies one profile-defined global palette rewrite to the native indexed DEF for {source_label} ({source["unitSid"]}), then re-extracts runtime clip {sequence["runtimeClip"]} group {sequence["group"]}.

- Contract: {sequence["frameCount"]} frames, {sequence["size"][0]}x{sequence["size"][1]} RGBA, {sequence["fps"]:g} FPS.
- Stability mechanism: the DEF body is byte-identical; only its single global palette changes.
- Geometry proof: every output alpha plane and bounding box is byte-identical to its matching source frame.
- Palette authoring: {ramp_names or "profile-defined ramps"} drive the {target_label} material treatment.
- Scope: palette/material propagation only; it does not prove arbitrary geometry transfer or new equipment silhouettes.
- Attack contract scope: shooter-front group 15 or melee-front group 12 with runtime clip 14.Attack (profile attackFamily: shoot|melee|auto).
- Palette strategy: {report.get("paletteStrategy") or "baseline"}.
- Palette taxonomy: the classifier uses fixed soot, crimson, copper, and ember material classes; a different class vocabulary requires a mapper extension.
- Evidence boundary: generated artifact validated. This has not been built into an Olden Era bundle or runtime-tested.

Rebuild and validate:

{fence}powershell
{command}
{fence}

Run the same fail-closed checks without rebuilding:

{fence}powershell
{command} --validate-only
{fence}
"""
	(output_dir / "README.md").write_text(text, encoding="utf-8")

def build(profile_path: pathlib.Path) -> dict:
	profile = load_json(profile_path)
	output_dir = require_repo_output(resolve_repo_path(profile["outputDir"]))
	output_dir.mkdir(parents=True, exist_ok=True)

	concept_path = resolve_repo_path(profile["conceptImagePath"])
	zip_path = resolve_repo_path(profile["sourceZipPath"])
	source_def = read_zip_member(zip_path, profile["sourceZipMember"])
	source_palette = palette_from_def(source_def)
	from hota_alt_palette_strategies import resolve_target_palette

	target_palette, palette_rows = resolve_target_palette(source_palette, profile)
	concept_audit = concept_swatch_audit(concept_path, profile)
	source_paths, source_manifest, authoring = source_sequence(profile)
	attack_contract = source_attack_contract(profile, source_manifest, authoring)
	expected_fps = float(profile["expectedFps"])
	actual_fps = float(authoring.get("flipBookFps"))
	if actual_fps != expected_fps:
		raise ValueError(f"authoring flipBookFps {actual_fps} != expected {expected_fps}")

	patched_def = bytearray(source_def)
	patched_def[PALETTE_OFFSET : PALETTE_OFFSET + PALETTE_SIZE] = palette_bytes(target_palette)
	patched_def_bytes = bytes(patched_def)
	patched_def_path = output_dir / require_output_def_name(profile["outputDefName"])
	build_marker = output_dir / ".build_in_progress"
	build_marker.write_text(sha256_file(profile_path) + "\n", encoding="ascii")
	patched_def_path.write_bytes(patched_def_bytes)


	tools_dir = repo_root() / "tools"
	if str(tools_dir) not in sys.path:
		sys.path.insert(0, str(tools_dir))
	from defextract_py3 import extract_def

	# Keep transient extraction in a fixed, marker-owned directory. tempfile's
	# 0700 creation mode is rejected by this workspace's restricted-token ACL.
	work_root = output_dir / ".work"
	work_marker = work_root / ".owned_by_alt_attack_palette_proof"
	if work_root.exists():
		if work_root.parent != output_dir or work_root.name != ".work" or not work_marker.is_file():
			raise ValueError(f"refusing to clear unowned work directory: {work_root}")
		shutil.rmtree(work_root)
	work_root.mkdir()
	work_marker.write_text("owned\n", encoding="ascii")
	source_def_name = pathlib.Path(profile["sourceZipMember"]).stem + "_SOURCE.def"
	source_def_path = work_root / source_def_name
	source_def_path.write_bytes(source_def)
	source_extract_root = work_root / "source_extract"
	target_extract_root = work_root / "target_extract"
	source_extract_root.mkdir()
	target_extract_root.mkdir()
	try:
		if not extract_def(str(source_def_path), str(source_extract_root)):
			raise RuntimeError("defextract_py3 rejected the source DEF")
		if not extract_def(str(patched_def_path), str(target_extract_root)):
			raise RuntimeError("defextract_py3 rejected the patched DEF")
		source_extracted_dir = source_extract_root / f"{source_def_path.stem.lower()}.dir"
		target_extracted_dir = target_extract_root / f"{patched_def_path.stem.lower()}.dir"
		source_frames_dir = output_dir / "source_frames"
		frames_dir = output_dir / "frames"
		source_frames_dir.mkdir(exist_ok=True)
		frames_dir.mkdir(exist_ok=True)
		for directory in (source_frames_dir, frames_dir):
			for stale in directory.glob(f"{int(profile['group']):02d}_*.png"):
				stale.unlink()
		extracted_source_paths: list[pathlib.Path] = []
		target_paths: list[pathlib.Path] = []
		for index in range(int(profile["expectedFrameCount"])):
			name = f"{int(profile['group']):02d}_{index:02d}.png"
			source = source_extracted_dir / name
			target_source = target_extracted_dir / name
			if not source.is_file() or not target_source.is_file():
				raise FileNotFoundError(f"DEF extraction omitted {name}")
			source_target = source_frames_dir / name
			target = frames_dir / name
			shutil.copy2(source, source_target)
			shutil.copy2(target_source, target)
			extracted_source_paths.append(source_target)
			target_paths.append(target)
	finally:
		if not work_marker.is_file():
			raise RuntimeError(f"work-directory ownership marker disappeared: {work_marker}")
		shutil.rmtree(work_root)
	source_images = load_rgba_frames(extracted_source_paths)
	target_images = load_rgba_frames(target_paths)
	previews = make_previews(source_images, target_images, output_dir, expected_fps, profile)
	frame_rows, errors = validate_frames(profile, extracted_source_paths, target_paths)
	manifest_rows, manifest_errors = validate_frames(profile, source_paths, extracted_source_paths)
	errors.extend(manifest_errors)
	for row in manifest_rows:
		if row["sourceRgbaSha256"] != row["targetRgbaSha256"]:
			errors.append(f"{row['frame']}: checked-in source frame differs from the current source DEF")
	visible_rgb_changed = sum(row["visibleRgbChangedPixelCount"] for row in frame_rows)
	if visible_rgb_changed <= 0:
		errors.append("palette transform changed no visible pixels in the requested sequence")

	special_bytes = int(profile["specialPaletteSlotCount"]) * PALETTE_ENTRY_SIZE
	source_body_hash = sha256_bytes(def_body_without_palette(source_def))
	target_body_hash = sha256_bytes(def_body_without_palette(patched_def_bytes))
	body_equal = def_body_without_palette(source_def) == def_body_without_palette(patched_def_bytes)
	special_equal = (
		source_def[PALETTE_OFFSET : PALETTE_OFFSET + special_bytes]
		== patched_def_bytes[PALETTE_OFFSET : PALETTE_OFFSET + special_bytes]
	)
	if not body_equal:
		errors.append("patched DEF body differs outside the global palette")
	if not special_equal:
		errors.append("special transparency/shadow palette slots changed")
	if not any(row["changed"] for row in palette_rows[int(profile["specialPaletteSlotCount"]) :]):
		errors.append("palette transform changed no visible palette slots")

	profile_hash = sha256_file(profile_path)
	palette_map_path = output_dir / "palette_map.json"
	palette_map = {
		"schemaVersion": 1,
		"profileSha256": profile_hash,
		"sourcePaletteSha256": sha256_bytes(palette_bytes(source_palette)),
		"targetPaletteSha256": sha256_bytes(palette_bytes(target_palette)),
		"entries": palette_rows,
	}
	palette_map_path.write_text(json.dumps(palette_map, indent=2) + "\n", encoding="utf-8")

	preview_audits, preview_errors = validate_previews(profile, previews, extracted_source_paths, target_paths)
	errors.extend(preview_errors)
	previews["audits"] = preview_audits

	report = {
		"schemaVersion": 1,
		"sourceLabel": str(profile.get("sourceLabel", profile["sourceUnitSid"])),
		"targetLabel": str(profile.get("targetLabel", profile["conceptName"])),
		"paletteStrategy": str(profile.get("paletteStrategy") or "baseline"),
		"paletteClasses": list((profile.get("paletteRamps") or {}).keys()),
		"status": "passed" if not errors else "failed",
		"proofBoundary": "generated_artifact_validated" if not errors else "generated_artifact_failed_validation",
		"concept": {
			"name": profile["conceptName"],
			"image": relative_to_root(concept_path),
			"imageSha256": sha256_file(concept_path),
			"swatchAudit": concept_audit,
		},
		"source": {
			"unitSid": profile["sourceUnitSid"],
			"zipPath": relative_to_root(zip_path),
			"zipMember": profile["sourceZipMember"],
			"defSha256": sha256_bytes(source_def),
			"paletteSha256": sha256_bytes(palette_bytes(source_palette)),
			"bodyWithoutPaletteSha256": source_body_hash,
			"attackContract": attack_contract,
		},
		"output": {
			"patchedDef": relative_to_root(patched_def_path),
			"patchedDefSha256": sha256_bytes(patched_def_bytes),
			"paletteSha256": sha256_bytes(palette_bytes(target_palette)),
			"bodyWithoutPaletteSha256": target_body_hash,
			"paletteMap": relative_to_root(palette_map_path),
			"sourceFramesDir": relative_to_root(extracted_source_paths[0].parent),
			"framesDir": relative_to_root(target_paths[0].parent),
		},
		"sequence": {
			"group": int(profile["group"]),
			"runtimeClip": profile["runtimeClip"],
			"frameCount": len(target_paths),
			"size": list(target_images[0].size),
			"mode": "RGBA",
			"fps": expected_fps,
			"nominalDurationSeconds": len(target_paths) / expected_fps,
			"sourceAlphaSequenceSha256": alpha_sequence_hash(extracted_source_paths),
			"targetAlphaSequenceSha256": alpha_sequence_hash(target_paths),
		},
		"stability": {
			"singleGlobalPaletteTransform": True,
			"defBodyByteIdentical": body_equal,
			"specialPaletteSlotsUnchanged": special_equal,
			"alphaPlanesByteIdentical": all(row["alphaEqual"] for row in frame_rows),
			"alphaBoundingBoxesIdentical": all(row["sourceAlphaBbox"] == row["targetAlphaBbox"] for row in frame_rows),
			"resizedOrInterpolatedFrames": False,
			"changedPaletteEntryCount": sum(1 for row in palette_rows if row["changed"]),
			"visibleRgbChangedPixelCount": visible_rgb_changed,
		},
		"previews": previews,
		"frames": frame_rows,
		"validationErrors": errors,
	}
	report_path = output_dir / "report.json"
	report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
	write_readme(profile_path, output_dir, report)
	if errors:
		raise RuntimeError("proof validation failed:\n- " + "\n- ".join(errors))
	build_marker.unlink()
	return report


def validate_only(profile_path: pathlib.Path) -> dict:
	profile = load_json(profile_path)
	output_dir = require_repo_output(resolve_repo_path(profile["outputDir"]))
	build_marker = output_dir / ".build_in_progress"
	if build_marker.exists():
		raise RuntimeError(f"proof build is incomplete while marker exists: {build_marker}")
	report_path = output_dir / "report.json"
	if not report_path.is_file():
		raise FileNotFoundError(f"build report is missing: {report_path}")
	report = load_json(report_path)
	source_def = read_zip_member(resolve_repo_path(profile["sourceZipPath"]), profile["sourceZipMember"])
	patched_path = resolve_repo_path(report["output"]["patchedDef"])
	patched_def = patched_path.read_bytes()
	manifest_paths, source_manifest, authoring = source_sequence(profile)
	attack_contract = source_attack_contract(profile, source_manifest, authoring)
	source_frames_dir = resolve_repo_path(report["output"]["sourceFramesDir"])
	frames_dir = resolve_repo_path(report["output"]["framesDir"])
	extracted_source_paths = [
		source_frames_dir / f"{int(profile['group']):02d}_{index:02d}.png"
		for index in range(int(profile["expectedFrameCount"]))
	]
	target_paths = [
		frames_dir / f"{int(profile['group']):02d}_{index:02d}.png"
		for index in range(int(profile["expectedFrameCount"]))
	]
	frame_rows, errors = validate_frames(profile, extracted_source_paths, target_paths)
	if attack_contract != report["source"]["attackContract"]:
		errors.append("source attack contract no longer matches the saved report")
	manifest_rows, manifest_errors = validate_frames(profile, manifest_paths, extracted_source_paths)
	errors.extend(manifest_errors)
	for row in manifest_rows:
		if row["sourceRgbaSha256"] != row["targetRgbaSha256"]:
			errors.append(f"{row['frame']}: checked-in source frame differs from the current source DEF")

	source_palette = palette_from_def(source_def)
	expected_target_palette, _ = build_target_palette(source_palette, profile)
	if palette_from_def(patched_def) != expected_target_palette:
		errors.append("patched DEF palette no longer matches the concept profile")
	if sha256_bytes(source_def) != report["source"]["defSha256"]:
		errors.append("source DEF hash no longer matches the saved report")
	if sha256_bytes(patched_def) != report["output"]["patchedDefSha256"]:
		errors.append("patched DEF hash no longer matches the saved report")
	palette_map = load_json(resolve_repo_path(report["output"]["paletteMap"]))
	if sha256_file(profile_path) != palette_map.get("profileSha256"):
		errors.append("profile hash no longer matches the palette map")
	if palette_map.get("targetPaletteSha256") != sha256_bytes(palette_bytes(expected_target_palette)):
		errors.append("palette-map hash no longer matches the concept profile")
	concept_path = resolve_repo_path(profile["conceptImagePath"])
	if sha256_file(concept_path) != report["concept"]["imageSha256"]:
		errors.append("concept image hash no longer matches the saved report")

	saved_frames = {row["frame"]: row for row in report.get("frames") or []}
	for row in frame_rows:
		saved = saved_frames.get(row["frame"])
		if not saved or saved.get("sourceRgbaSha256") != row["sourceRgbaSha256"]:
			errors.append(f"{row['frame']}: source RGBA hash no longer matches the saved report")
		if not saved or saved.get("targetRgbaSha256") != row["targetRgbaSha256"]:
			errors.append(f"{row['frame']}: target RGBA hash no longer matches the saved report")
	if sum(row["visibleRgbChangedPixelCount"] for row in frame_rows) <= 0:
		errors.append("palette transform changed no visible pixels in the requested sequence")
	_, preview_errors = validate_previews(profile, report["previews"], extracted_source_paths, target_paths)
	errors.extend(preview_errors)

	if def_body_without_palette(source_def) != def_body_without_palette(patched_def):
		errors.append("patched DEF body differs outside the global palette")
	special_bytes = int(profile["specialPaletteSlotCount"]) * PALETTE_ENTRY_SIZE
	if source_def[PALETTE_OFFSET : PALETTE_OFFSET + special_bytes] != patched_def[PALETTE_OFFSET : PALETTE_OFFSET + special_bytes]:
		errors.append("special transparency/shadow palette slots changed")
	if float(authoring.get("flipBookFps")) != float(profile["expectedFps"]):
		errors.append("authoring FPS no longer matches the profile")
	if alpha_sequence_hash(extracted_source_paths) != alpha_sequence_hash(target_paths):
		errors.append("alpha-sequence hash mismatch")
	if report.get("status") != "passed":
		errors.append("saved report status is not passed")
	if errors:
		raise RuntimeError("proof validation failed:\n- " + "\n- ".join(errors))
	return {"status": "passed", "frames": len(frame_rows), "group": int(profile["group"])}

def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--profile", type=pathlib.Path, required=True)
	parser.add_argument("--validate-only", action="store_true")
	args = parser.parse_args()
	profile_path = args.profile if args.profile.is_absolute() else repo_root() / args.profile
	try:
		result = validate_only(profile_path) if args.validate_only else build(profile_path)
	except Exception as ex:
		print(f"ERROR: {ex}", file=sys.stderr)
		return 1
	print(
		f"proof {result['status']}: group={result.get('sequence', result).get('group')} "
		f"frames={result.get('sequence', result).get('frameCount', result.get('frames'))}"
	)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
