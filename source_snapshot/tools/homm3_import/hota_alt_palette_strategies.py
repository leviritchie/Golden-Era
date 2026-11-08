#!/usr/bin/env python3
"""Shared HotA alternate-upgrade DEF palette remap strategies.

Animation-stable: all strategies rewrite the global 256-entry palette only.
They do not invent silhouette geometry — only recolor existing indexed colors.

Evidence: generated strategy comparison / palette proof artifacts only.
"""

from __future__ import annotations

import colorsys
import math
import pathlib
import random
from collections import Counter, defaultdict
from typing import Callable

from PIL import Image

from build_hota_alt_attack_palette_proof import (
	build_target_palette,
	classify_color,
	hex_rgb,
	luminance,
	palette_bytes,
	parse_hex,
	sample_ramp,
	sha256_bytes,
)
from generate_hota_alt_recolor_gallery import apply_class_shift, classify_pixel

StrategyFn = Callable[
	[list[tuple[int, int, int]], dict],
	tuple[list[tuple[int, int, int]], list[dict]],
]


def clamp_byte(value: float) -> int:
	return max(0, min(255, int(round(value))))


def rgb_dist(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
	return math.dist(a, b)


def soft_class_scores(rgb: tuple[int, int, int]) -> dict[str, float]:
	"""Continuous membership scores used by soft_blend (not hard thresholds)."""
	r, g, b = rgb
	if max(rgb) == 0:
		return {"soot": 1.0, "crimson": 0.0, "copper": 0.0, "ember": 0.0, "preserve": 0.0}
	h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
	hdeg = h * 360.0
	green_ratio = g / max(r, 1)
	scores = {
		"preserve": 0.0,
		"crimson": 0.0,
		"ember": 0.0,
		"copper": 0.0,
		"soot": 0.15 + (1.0 - s) * 0.35,
	}
	if hdeg <= 40 and 0.08 <= s <= 0.65 and green_ratio >= 0.45:
		scores["preserve"] = 0.35 + green_ratio * 0.5
	if (hdeg <= 25 or hdeg >= 340) and s >= 0.2:
		scores["crimson"] = 0.25 + s * 0.7
	if 12 <= hdeg <= 60 and s >= 0.3 and v >= 0.45:
		scores["ember"] = 0.2 + s * 0.5 + (v - 0.45) * 0.4
	if 7 <= hdeg <= 78 and s >= 0.15 and green_ratio >= 0.3:
		scores["copper"] = 0.2 + s * 0.45
	if v <= 0.22:
		scores["soot"] = max(scores["soot"], 0.7)
	total = sum(scores.values()) or 1.0
	return {key: value / total for key, value in scores.items()}


def concept_primary_shell_hue_deg(profile: dict) -> float:
	"""Target hue for hue_shift_shell from concept palette ramps."""
	if "hueShiftTargetDeg" in profile:
		return float(profile["hueShiftTargetDeg"]) % 360.0

	ramps = profile.get("paletteRamps") or {}
	min_s = 0.20
	min_v = 0.20
	crimson_min_mass = 0.35

	def ramp_samples(colors: list) -> list[tuple[float, float, float]]:
		out: list[tuple[float, float, float]] = []
		for value in colors:
			r, g, b = parse_hex(value)
			h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
			if s < min_s or v < min_v:
				continue
			out.append((h, s, v))
		return out

	def mass(samples: list[tuple[float, float, float]]) -> float:
		return sum(s * v for _, s, v in samples)

	crimson_samples = ramp_samples(ramps.get("crimson") or [])
	copper_samples = ramp_samples(ramps.get("copper") or [])
	ember_samples = ramp_samples(ramps.get("ember") or [])

	if mass(crimson_samples) >= crimson_min_mass:
		best_samples = crimson_samples
		best_name = "crimson"
	else:
		copper_mass = mass(copper_samples)
		ember_mass = mass(ember_samples)
		if copper_mass <= 0.0 and ember_mass <= 0.0:
			raise ValueError(
				"hue_shift_shell: no chromatic shell samples in paletteRamps "
				"(crimson below midtone mass floor; copper/ember empty), "
				"or set hueShiftTargetDeg"
			)
		if ember_mass > copper_mass:
			best_samples = ember_samples
			best_name = "ember"
		else:
			best_samples = copper_samples
			best_name = "copper"

	sin_sum = 0.0
	cos_sum = 0.0
	weight_sum = 0.0
	for h, s, v in best_samples:
		weight = s * v
		angle = h * 2.0 * math.pi
		sin_sum += math.sin(angle) * weight
		cos_sum += math.cos(angle) * weight
		weight_sum += weight
	if weight_sum <= 0.0:
		raise ValueError(f"hue_shift_shell: empty chromatic mass for ramp {best_name!r}")
	return (math.atan2(sin_sum, cos_sum) / (2.0 * math.pi) * 360.0) % 360.0


def strategy_baseline(
	source_palette: list[tuple[int, int, int]],
	profile: dict,
) -> tuple[list[tuple[int, int, int]], list[dict]]:
	return build_target_palette(source_palette, profile)


def strategy_linked_consensus(
	source_palette: list[tuple[int, int, int]],
	profile: dict,
	*,
	link_distance: float = 14.0,
) -> tuple[list[tuple[int, int, int]], list[dict]]:
	"""Union near-duplicate source colors, then majority-vote one class per component."""
	special = int(profile["specialPaletteSlotCount"])
	parent = list(range(len(source_palette)))

	def find(i: int) -> int:
		while parent[i] != i:
			parent[i] = parent[parent[i]]
			i = parent[i]
		return i

	def union(a: int, b: int) -> None:
		ra, rb = find(a), find(b)
		if ra != rb:
			parent[rb] = ra

	hard = [classify_color(i, rgb, profile) for i, rgb in enumerate(source_palette)]
	for i in range(special, len(source_palette)):
		for j in range(i + 1, len(source_palette)):
			if hard[i] == "special" or hard[j] == "special":
				continue
			if rgb_dist(source_palette[i], source_palette[j]) <= link_distance:
				union(i, j)

	components: dict[int, list[int]] = defaultdict(list)
	for i in range(len(source_palette)):
		components[find(i)].append(i)

	consensus: list[str] = list(hard)
	for members in components.values():
		votes = Counter(hard[i] for i in members if hard[i] not in {"special"})
		if not votes:
			continue
		if votes.get("preserve", 0) >= max(1, len(members) // 4):
			winner = "preserve"
		else:
			winner = votes.most_common(1)[0][0]
		for i in members:
			if hard[i] != "special":
				consensus[i] = winner

	patched = dict(profile)
	overrides = {name: [] for name in ("preserve", "soot", "crimson", "copper", "ember")}
	for i, name in enumerate(consensus):
		if name in overrides:
			overrides[name].append(i)
	patched["classOverrides"] = overrides
	return build_target_palette(source_palette, patched)


def strategy_soft_blend(
	source_palette: list[tuple[int, int, int]],
	profile: dict,
) -> tuple[list[tuple[int, int, int]], list[dict]]:
	"""Blend ramp outputs by soft class membership; honor preserve overrides hard."""
	ramps = {
		name: [parse_hex(value) for value in values]
		for name, values in (profile.get("paletteRamps") or {}).items()
	}
	curve = {"soot": 0.72, "crimson": 0.62, "copper": 0.68, "ember": 0.56}
	special = int(profile["specialPaletteSlotCount"])
	override_preserve = {int(v) for v in (profile.get("classOverrides") or {}).get("preserve") or []}
	target: list[tuple[int, int, int]] = []
	rows: list[dict] = []
	for index, source in enumerate(source_palette):
		hard = classify_color(index, source, profile)
		if index < special or hard == "special" or index in override_preserve or hard == "preserve":
			mapped = source
			class_name = "preserve" if index in override_preserve or hard == "preserve" else hard
		else:
			scores = soft_class_scores(source)
			scores[hard] = max(scores.get(hard, 0.0), 0.45)
			scores["preserve"] = 0.0
			total = sum(scores[name] for name in curve) or 1.0
			acc = [0.0, 0.0, 0.0]
			for name in curve:
				weight = scores[name] / total
				position = (luminance(source) / 255.0) ** curve[name]
				sample = sample_ramp(ramps[name], position)
				acc[0] += sample[0] * weight
				acc[1] += sample[1] * weight
				acc[2] += sample[2] * weight
			mapped = (clamp_byte(acc[0]), clamp_byte(acc[1]), clamp_byte(acc[2]))
			class_name = f"soft:{hard}"
		target.append(mapped)
		rows.append(
			{
				"index": index,
				"class": class_name,
				"source": hex_rgb(source),
				"target": hex_rgb(mapped),
				"changed": mapped != source,
			}
		)
	return target, rows


def strategy_cluster_ramp(
	source_palette: list[tuple[int, int, int]],
	profile: dict,
	*,
	clusters: int = 4,
) -> tuple[list[tuple[int, int, int]], list[dict]]:
	"""K-means the remappable palette colors; remap each cluster with one continuous ramp."""
	special = int(profile["specialPaletteSlotCount"])
	hard = [classify_color(i, rgb, profile) for i, rgb in enumerate(source_palette)]
	remap_indices = [i for i in range(special, len(source_palette)) if hard[i] not in {"special", "preserve"}]
	if len(remap_indices) < clusters:
		return build_target_palette(source_palette, profile)

	points = [source_palette[i] for i in remap_indices]
	seed = sha256_bytes(palette_bytes(source_palette))
	rng = random.Random(int(seed[:8], 16))
	centroids = [points[rng.randrange(len(points))] for _ in range(clusters)]
	assign = [0] * len(points)
	for _ in range(20):
		changed = False
		for pi, point in enumerate(points):
			best = min(range(clusters), key=lambda c: rgb_dist(point, centroids[c]))
			if assign[pi] != best:
				assign[pi] = best
				changed = True
		for c in range(clusters):
			members = [points[pi] for pi, a in enumerate(assign) if a == c]
			if not members:
				centroids[c] = points[rng.randrange(len(points))]
				continue
			centroids[c] = (
				int(round(sum(p[0] for p in members) / len(members))),
				int(round(sum(p[1] for p in members) / len(members))),
				int(round(sum(p[2] for p in members) / len(members))),
			)
		if not changed:
			break

	ramps = {
		name: [parse_hex(value) for value in values]
		for name, values in (profile.get("paletteRamps") or {}).items()
	}
	cluster_ramp: dict[int, str] = {}
	for c, centroid in enumerate(centroids):
		h, s, v = colorsys.rgb_to_hsv(centroid[0] / 255.0, centroid[1] / 255.0, centroid[2] / 255.0)
		hdeg = h * 360.0
		if v < 0.22:
			cluster_ramp[c] = "soot"
		elif 12 <= hdeg <= 60 and s >= 0.35 and v >= 0.5:
			cluster_ramp[c] = "ember"
		elif 7 <= hdeg <= 78 and s >= 0.18:
			cluster_ramp[c] = "crimson" if s >= 0.28 else "copper"
		else:
			cluster_ramp[c] = "crimson"

	target = list(source_palette)
	rows: list[dict] = []
	for index, source in enumerate(source_palette):
		if index < special or hard[index] in {"special", "preserve"}:
			mapped = source
			class_name = hard[index]
		else:
			local = remap_indices.index(index)
			c = assign[local]
			members = [remap_indices[pi] for pi, a in enumerate(assign) if a == c]
			members_sorted = sorted(members, key=lambda i: luminance(source_palette[i]))
			rank = members_sorted.index(index)
			position = rank / max(1, len(members_sorted) - 1)
			mapped = sample_ramp(ramps[cluster_ramp[c]], position)
			class_name = f"cluster:{cluster_ramp[c]}"
		target[index] = mapped
		rows.append(
			{
				"index": index,
				"class": class_name,
				"source": hex_rgb(source),
				"target": hex_rgb(mapped),
				"changed": mapped != source,
			}
		)
	return target, rows


def strategy_hue_shift_shell(
	source_palette: list[tuple[int, int, int]],
	profile: dict,
	*,
	target_hue_deg: float | None = None,
) -> tuple[list[tuple[int, int, int]], list[dict]]:
	"""Hue-rotate remappable colors toward the concept's primary shell/body hue."""
	if target_hue_deg is None:
		target_hue_deg = concept_primary_shell_hue_deg(profile)
	else:
		target_hue_deg = float(target_hue_deg) % 360.0

	special = int(profile["specialPaletteSlotCount"])
	new_h = target_hue_deg / 360.0
	target: list[tuple[int, int, int]] = []
	rows: list[dict] = []
	for index, source in enumerate(source_palette):
		hard = classify_color(index, source, profile)
		if index < special or hard in {"special", "preserve"}:
			mapped = source
			class_name = hard
		else:
			r, g, b = [c / 255.0 for c in source]
			h, s, v = colorsys.rgb_to_hsv(r, g, b)
			mixed_h = (h * 0.25 + new_h * 0.75) % 1.0
			new_s = min(1.0, s * 0.85 + 0.08)
			rr, gg, bb = colorsys.hsv_to_rgb(mixed_h, new_s, v)
			mapped = (clamp_byte(rr * 255), clamp_byte(gg * 255), clamp_byte(bb * 255))
			class_name = "hue_shift"
		target.append(mapped)
		rows.append(
			{
				"index": index,
				"class": class_name,
				"source": hex_rgb(source),
				"target": hex_rgb(mapped),
				"changed": mapped != source,
			}
		)
	return target, rows


def strategy_hybrid_linked_hue(
	source_palette: list[tuple[int, int, int]],
	profile: dict,
) -> tuple[list[tuple[int, int, int]], list[dict]]:
	"""Linked class consensus, then hue-shift within remapped classes instead of hard ramps."""
	_linked_palette, linked_rows = strategy_linked_consensus(source_palette, profile)
	preserve = [row["index"] for row in linked_rows if row["class"] == "preserve"]
	patched = dict(profile)
	overrides = dict(profile.get("classOverrides") or {})
	overrides["preserve"] = sorted(set(int(v) for v in (overrides.get("preserve") or [])) | set(preserve))
	patched["classOverrides"] = overrides
	return strategy_hue_shift_shell(source_palette, patched)


def strategy_material_class_hs(
	source_palette: list[tuple[int, int, int]],
	profile: dict,
) -> tuple[list[tuple[int, int, int]], list[dict]]:
	"""Apply authored material-class HSV shifts (same path as material_remap_preview).

	Requires profile.materialShifts with cloth/metal/glow/base hue/sat/val dicts.
	Uses generate_hota_alt_recolor_gallery.classify_pixel + apply_class_shift.
	Animation-stable: global palette rewrite only.
	"""
	materials = profile.get("materialShifts")
	if not isinstance(materials, dict) or not materials:
		raise ValueError("material_class_hs requires non-empty profile.materialShifts")

	special = int(profile["specialPaletteSlotCount"])
	target: list[tuple[int, int, int]] = []
	rows: list[dict] = []
	for index, source in enumerate(source_palette):
		if index < special:
			mapped = source
			class_name = "special"
		else:
			klass = classify_pixel(source[0], source[1], source[2], 255)
			if klass in {"empty", "preserve"}:
				mapped = source
				class_name = "preserve"
			else:
				mapped = apply_class_shift(source, materials.get(klass))
				class_name = f"material:{klass}"
		target.append(mapped)
		rows.append(
			{
				"index": index,
				"class": class_name,
				"source": hex_rgb(source),
				"target": hex_rgb(mapped),
				"changed": mapped != source,
			}
		)
	return target, rows


def _opaque_pixels(path: pathlib.Path) -> list[tuple[int, int, int]]:
	im = Image.open(path).convert("RGBA")
	pixels = im.load()
	width, height = im.size
	out: list[tuple[int, int, int]] = []
	for y in range(height):
		for x in range(width):
			r, g, b, a = pixels[x, y]
			if a < 200 or max(r, g, b) < 8:
				continue
			out.append((r, g, b))
	if not out:
		raise ValueError(f"no opaque pixels in concept image {path}")
	return out


def _luminance_ramp(samples: list[tuple[int, int, int]], *, count: int = 5) -> list[tuple[int, int, int]]:
	ordered = sorted(samples, key=luminance)
	if len(ordered) == 1:
		return [ordered[0]] * count
	out: list[tuple[int, int, int]] = []
	for i in range(count):
		idx = int(round(i * (len(ordered) - 1) / (count - 1)))
		rgb = ordered[idx]
		if not out or out[-1] != rgb:
			out.append(rgb)
	while len(out) < 3:
		out.append(out[-1])
	return out


def build_region_ramps_from_image(concept_path: pathlib.Path) -> dict[str, list[str]]:
	"""Sample per-material-class luminance ramps from a material-remap native sprite."""
	buckets: dict[str, list[tuple[int, int, int]]] = {
		"cloth": [],
		"metal": [],
		"glow": [],
		"base": [],
		"soot": [],
	}
	for rgb in _opaque_pixels(concept_path):
		klass = classify_pixel(rgb[0], rgb[1], rgb[2], 255)
		if klass == "preserve":
			continue
		if klass in buckets:
			buckets[klass].append(rgb)
		if luminance(rgb) < 40:
			buckets["soot"].append(rgb)

	# Fallback chain so every ramp is non-empty.
	all_colors = [c for bucket in buckets.values() for c in bucket] or list(_opaque_pixels(concept_path))
	fallback = _luminance_ramp(all_colors)

	def as_hex(ramp: list[tuple[int, int, int]]) -> list[str]:
		return [hex_rgb(rgb) for rgb in ramp]

	out: dict[str, list[str]] = {}
	for name in ("cloth", "metal", "glow", "base", "soot"):
		samples = buckets[name] or all_colors
		out[name] = as_hex(_luminance_ramp(samples) if samples else fallback)
	# Compatibility aliases for older soot/crimson/copper/ember consumers.
	out["crimson"] = out["cloth"]
	out["copper"] = out["metal"]
	out["ember"] = out["glow"] if buckets["glow"] else out["metal"]
	return out


def strategy_region_ramp(
	source_palette: list[tuple[int, int, int]],
	profile: dict,
) -> tuple[list[tuple[int, int, int]], list[dict]]:
	"""Per-material-region luminance ramps sampled from the material-remap target sprite.

	Classifies each palette entry with classify_pixel (cloth/metal/glow/base/preserve)
	and maps through concept-grounded ramps for that region.
	"""
	region_ramps = profile.get("regionRamps")
	if not region_ramps:
		concept_path = profile.get("conceptNativePath")
		if not concept_path:
			raise ValueError("region_ramp requires profile.regionRamps or profile.conceptNativePath")
		region_ramps = build_region_ramps_from_image(pathlib.Path(str(concept_path)))

	ramps = {
		name: [parse_hex(value) for value in values]
		for name, values in region_ramps.items()
		if values
	}
	curve = {"cloth": 0.62, "metal": 0.68, "glow": 0.56, "base": 0.70, "soot": 0.72}
	special = int(profile["specialPaletteSlotCount"])
	target: list[tuple[int, int, int]] = []
	rows: list[dict] = []
	for index, source in enumerate(source_palette):
		if index < special:
			mapped = source
			class_name = "special"
		else:
			klass = classify_pixel(source[0], source[1], source[2], 255)
			if klass in {"empty", "preserve"}:
				mapped = source
				class_name = "preserve"
			else:
				ramp_name = klass if klass in ramps else ("base" if "base" in ramps else "cloth")
				if ramp_name not in ramps:
					raise ValueError(f"region_ramp missing ramp for class {klass!r}")
				position = (luminance(source) / 255.0) ** curve.get(ramp_name, 0.65)
				mapped = sample_ramp(ramps[ramp_name], position)
				class_name = f"region:{ramp_name}"
		target.append(mapped)
		rows.append(
			{
				"index": index,
				"class": class_name,
				"source": hex_rgb(source),
				"target": hex_rgb(mapped),
				"changed": mapped != source,
			}
		)
	return target, rows


def _kmeans_rgb(
	points: list[tuple[int, int, int]],
	*,
	clusters: int,
	seed: int,
	iters: int = 24,
) -> tuple[list[tuple[int, int, int]], list[int]]:
	if len(points) < clusters:
		clusters = max(1, len(points))
	rng = random.Random(seed)
	centroids = [points[rng.randrange(len(points))] for _ in range(clusters)]
	assign = [0] * len(points)
	for _ in range(iters):
		changed = False
		for pi, point in enumerate(points):
			best = min(range(clusters), key=lambda c: rgb_dist(point, centroids[c]))
			if assign[pi] != best:
				assign[pi] = best
				changed = True
		for c in range(clusters):
			members = [points[pi] for pi, a in enumerate(assign) if a == c]
			if not members:
				centroids[c] = points[rng.randrange(len(points))]
				continue
			centroids[c] = (
				int(round(sum(p[0] for p in members) / len(members))),
				int(round(sum(p[1] for p in members) / len(members))),
				int(round(sum(p[2] for p in members) / len(members))),
			)
		if not changed:
			break
	return centroids, assign


def strategy_multi_seed_hsv(
	source_palette: list[tuple[int, int, int]],
	profile: dict,
	*,
	seeds: int = 6,
) -> tuple[list[tuple[int, int, int]], list[dict]]:
	"""Match each remappable palette color to the nearest concept color seed in HSV.

	Seeds are k-means centroids of opaque pixels from the material-remap target.
	Preserves source value structure while pulling hue/sat toward the matched seed.
	Animation-stable: global palette rewrite only.
	"""
	concept_path = profile.get("conceptNativePath")
	if not concept_path:
		raise ValueError("multi_seed_hsv requires profile.conceptNativePath")
	concept_pixels = _opaque_pixels(pathlib.Path(str(concept_path)))
	seed_key = sha256_bytes(palette_bytes(source_palette))
	centroids, _ = _kmeans_rgb(concept_pixels, clusters=seeds, seed=int(seed_key[:8], 16))

	def hsv_of(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
		return colorsys.rgb_to_hsv(rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0)

	centroid_hsv = [hsv_of(c) for c in centroids]

	def nearest_seed(rgb: tuple[int, int, int]) -> int:
		h, s, v = hsv_of(rgb)
		best_i = 0
		best_d = 1e9
		for i, (ch, cs, cv) in enumerate(centroid_hsv):
			dh = min(abs(h - ch), 1.0 - abs(h - ch)) * 2.0
			d = dh * 2.2 + abs(s - cs) * 1.1 + abs(v - cv) * 0.35
			if d < best_d:
				best_d = d
				best_i = i
		return best_i

	special = int(profile["specialPaletteSlotCount"])
	target: list[tuple[int, int, int]] = []
	rows: list[dict] = []
	for index, source in enumerate(source_palette):
		if index < special:
			mapped = source
			class_name = "special"
		else:
			klass = classify_pixel(source[0], source[1], source[2], 255)
			if klass in {"empty", "preserve"}:
				mapped = source
				class_name = "preserve"
			else:
				si = nearest_seed(source)
				sh, ss, sv = hsv_of(source)
				th, ts, tv = centroid_hsv[si]
				# Keep source value; pull hue hard and sat moderately toward seed.
				mixed_h = (sh * 0.20 + th * 0.80) % 1.0
				mixed_s = max(0.0, min(1.0, ss * 0.35 + ts * 0.65))
				# Slight value nudge toward seed so dark/light bands track concept.
				mixed_v = max(0.0, min(1.0, sv * 0.85 + tv * 0.15))
				rr, gg, bb = colorsys.hsv_to_rgb(mixed_h, mixed_s, mixed_v)
				mapped = (clamp_byte(rr * 255), clamp_byte(gg * 255), clamp_byte(bb * 255))
				class_name = f"seed:{si}"
		target.append(mapped)
		rows.append(
			{
				"index": index,
				"class": class_name,
				"source": hex_rgb(source),
				"target": hex_rgb(mapped),
				"changed": mapped != source,
			}
		)
	return target, rows


def strategy_cluster_hist_match(
	source_palette: list[tuple[int, int, int]],
	profile: dict,
	*,
	clusters: int = 5,
) -> tuple[list[tuple[int, int, int]], list[dict]]:
	"""K-means palette clusters, then luminance-CDF match each cluster to concept colors.

	For each source cluster, concept pixels nearest the cluster centroid in hue/sat
	are sorted by luminance and used as a transfer ramp (histogram matching).
	"""
	concept_path = profile.get("conceptNativePath")
	if not concept_path:
		raise ValueError("cluster_hist_match requires profile.conceptNativePath")
	concept_pixels = _opaque_pixels(pathlib.Path(str(concept_path)))

	special = int(profile["specialPaletteSlotCount"])
	hard = [classify_color(i, rgb, profile) for i, rgb in enumerate(source_palette)]
	# Prefer material-style preserve for skin, but also honor hard preserve.
	remap_indices = []
	for i in range(special, len(source_palette)):
		if hard[i] in {"special", "preserve"}:
			continue
		klass = classify_pixel(*source_palette[i], 255)
		if klass == "preserve":
			continue
		remap_indices.append(i)
	if len(remap_indices) < 2:
		raise ValueError(
			"cluster_hist_match: fewer than 2 remappable palette entries "
			"(refuse silent fallback to another strategy)"
		)

	points = [source_palette[i] for i in remap_indices]
	seed = int(sha256_bytes(palette_bytes(source_palette))[:8], 16)
	centroids, assign = _kmeans_rgb(points, clusters=min(clusters, len(points)), seed=seed)

	def hsv_of(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
		return colorsys.rgb_to_hsv(rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0)

	# Pre-bin concept pixels by nearest centroid (hue/sat emphasis).
	concept_by_cluster: dict[int, list[tuple[int, int, int]]] = defaultdict(list)
	for rgb in concept_pixels:
		h, s, v = hsv_of(rgb)
		best = 0
		best_d = 1e9
		for c, centroid in enumerate(centroids):
			ch, cs, cv = hsv_of(centroid)
			dh = min(abs(h - ch), 1.0 - abs(h - ch))
			d = dh * 2.0 + abs(s - cs) + abs(v - cv) * 0.25
			if d < best_d:
				best_d = d
				best = c
		concept_by_cluster[best].append(rgb)
	# Ensure every cluster has a fallback concept pool.
	all_concept = concept_pixels
	for c in range(len(centroids)):
		if not concept_by_cluster[c]:
			concept_by_cluster[c] = all_concept

	target = list(source_palette)
	rows: list[dict] = []
	local_of = {index: li for li, index in enumerate(remap_indices)}
	for index, source in enumerate(source_palette):
		if index not in local_of:
			mapped = source
			class_name = hard[index] if hard[index] != "special" else "special"
			if index >= special and classify_pixel(*source, 255) == "preserve":
				class_name = "preserve"
		else:
			li = local_of[index]
			c = assign[li]
			members = [remap_indices[pi] for pi, a in enumerate(assign) if a == c]
			members_sorted = sorted(members, key=lambda i: luminance(source_palette[i]))
			rank = members_sorted.index(index)
			position = rank / max(1, len(members_sorted) - 1)
			pool = sorted(concept_by_cluster[c], key=luminance)
			mapped = sample_ramp(pool, position)
			class_name = f"hist:{c}"
		target[index] = mapped
		rows.append(
			{
				"index": index,
				"class": class_name,
				"source": hex_rgb(source),
				"target": hex_rgb(mapped),
				"changed": mapped != source,
			}
		)
	return target, rows


# Full registry (CLI compare + proof baking).
STRATEGIES: dict[str, StrategyFn] = {
	"baseline": strategy_baseline,
	"linked_consensus": strategy_linked_consensus,
	"soft_blend": strategy_soft_blend,
	"cluster_ramp": strategy_cluster_ramp,
	"hue_shift_shell": strategy_hue_shift_shell,
	"hybrid_linked_hue": strategy_hybrid_linked_hue,
	"material_class_hs": strategy_material_class_hs,
	"region_ramp": strategy_region_ramp,
	"multi_seed_hsv": strategy_multi_seed_hsv,
	"cluster_hist_match": strategy_cluster_hist_match,
}

# Curated picker set: 3 stronger remaps + 2 legacy refs that often fail visually.
# Dropped from picker (still in STRATEGIES for CLI compare):
#   cluster_ramp, hybrid_linked_hue, linked_consensus, baseline, multi_seed_hsv
PICKER_STRATEGIES: tuple[str, ...] = (
	"material_class_hs",  # authored cloth/metal/glow/base HSV (material_remap_preview path)
	"region_ramp",  # per-material luminance ramps from material-remap native
	"cluster_hist_match",  # k-means + concept histogram/luminance CDF match
	"soft_blend",  # legacy soft class blend (comparison)
	"hue_shift_shell",  # legacy shell hue rotate (comparison)
)


def resolve_target_palette(
	source_palette: list[tuple[int, int, int]],
	profile: dict,
) -> tuple[list[tuple[int, int, int]], list[dict]]:
	name = str(profile.get("paletteStrategy") or "baseline").strip().lower()
	if name not in STRATEGIES:
		raise ValueError(f"unknown paletteStrategy {name!r}; expected one of {sorted(STRATEGIES)}")
	return STRATEGIES[name](source_palette, profile)
