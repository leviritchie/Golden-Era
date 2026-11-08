#!/usr/bin/env python3
"""Bake Factory/Bulwark alt upgrades with material_class_hs into homm3_lab.

Production rules (fail-closed):
- DEF battle sources: rewrite the global DEF palette once, re-extract all groups.
- JSON+PNG battle sources (e.g. COLGOIX / CJUGGER): require a shared 256-color
  mode-P palette (lab extract or authoritative HotA zip), rewrite that palette on
  every frame, then convert to RGBA via HoMM3 special-slot alpha (index 0 cyan
  key and slots 1-7 shadows). Never leave keyed cyan opaque for RIFE/Unity.
  Never use the picker lab_png_palette reconstructed fallback (preview-only).
- Map DEF sources: same material_class_hs palette rewrite + extract.
"""

from __future__ import annotations

import argparse
import io
import json
import pathlib
import shutil
import sys
import tempfile
import zipfile

from PIL import Image

from homm3_vcmi_png_alpha import (
	assert_rgba_transparency_contract,
	is_opaque_key_cyan,
	mode_p_to_rgba_special_slots,
)

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
UNITY_LAB = ROOT / "oldenera_factions" / "Assets" / "CustomUnits" / "homm3_lab"
INVENTORY = HERE / "units_inventory.json"
MANIFEST = HERE / "homm3_units_manifest.json"
PRESETS = HERE / "presets"
GALLERY_INDEX = HERE / "recolor_galleries" / "index.json"
DEFAULT_SELECTIONS = HERE / "alternate_upgrade_concepts" / "material_class_hs_selections.json"
SPOTCHECK_DIR = HERE / "alternate_upgrade_concepts" / "material_class_hs_bake_spotcheck"
SPECIAL_PALETTE_SLOT_COUNT = 8
PALETTE_OFFSET = 16
PALETTE_ENTRY_COUNT = 256
PALETTE_ENTRY_SIZE = 3
PALETTE_SIZE = PALETTE_ENTRY_COUNT * PALETTE_ENTRY_SIZE


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
		# Unity project may be a junction/symlink outside the repo (oldenera_factions -> V:/homm3_unity_work).
		return resolved.as_posix()


def palette_from_def(data: bytes) -> list[tuple[int, int, int]]:
	chunk = data[PALETTE_OFFSET : PALETTE_OFFSET + PALETTE_SIZE]
	if len(chunk) != PALETTE_SIZE:
		raise ValueError(f"DEF palette truncated: got {len(chunk)} bytes")
	return [
		(chunk[i], chunk[i + 1], chunk[i + 2])
		for i in range(0, PALETTE_SIZE, PALETTE_ENTRY_SIZE)
	]


def palette_bytes(palette: list[tuple[int, int, int]]) -> bytes:
	if len(palette) != PALETTE_ENTRY_COUNT:
		raise ValueError(f"expected {PALETTE_ENTRY_COUNT} palette entries, got {len(palette)}")
	out = bytearray()
	for r, g, b in palette:
		out.extend((r, g, b))
	return bytes(out)


def read_zip_member(zip_path: pathlib.Path, member: str) -> bytes:
	with zipfile.ZipFile(zip_path) as zf:
		names = {n.replace("\\", "/").lower(): n for n in zf.namelist()}
		key = member.replace("\\", "/").lower()
		if key not in names:
			raise FileNotFoundError(f"{zip_path}: missing member {member}")
		return zf.read(names[key])


def inventory_row(unit_sid: str) -> dict:
	inv = load_json(INVENTORY)
	row = next((u for u in (inv.get("units") or []) if u.get("unitSid") == unit_sid), None)
	if not isinstance(row, dict):
		raise KeyError(f"inventory missing unitSid {unit_sid}")
	return row


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


def material_profile(materials: dict) -> dict:
	return {
		"specialPaletteSlotCount": SPECIAL_PALETTE_SLOT_COUNT,
		"materialShifts": materials,
		"paletteStrategy": "material_class_hs",
		"classOverrides": {"preserve": [], "soot": [], "crimson": [], "copper": [], "ember": []},
		"paletteRamps": {"soot": [], "crimson": [], "copper": [], "ember": []},
	}


def resolve_target_palette(source_palette: list[tuple[int, int, int]], materials: dict):
	from hota_alt_palette_strategies import resolve_target_palette as _resolve

	return _resolve(source_palette, material_profile(materials))


def battle_source_kind(row: dict) -> str:
	if (row.get("battleZipMember") or "").strip():
		return "def"
	if (row.get("battleJsonZipMember") or "").strip():
		return "json_png"
	raise ValueError(f"{row.get('unitSid')}: inventory has neither battleZipMember nor battleJsonZipMember")


def map_source_kind(row: dict) -> str | None:
	if (row.get("mapZipMember") or "").strip() or (row.get("mapDefPath") or "").strip():
		return "def"
	if (row.get("mapJsonZipMember") or "").strip():
		return "json_png"
	return None


def require_shared_p_palette(frame_dir: pathlib.Path) -> list[tuple[int, int, int]]:
	frames = sorted(frame_dir.glob("*.png"))
	if not frames:
		raise FileNotFoundError(f"no PNG frames under {frame_dir}")
	palettes: set[bytes] = set()
	source_palette: list[tuple[int, int, int]] | None = None
	for path in frames:
		image = Image.open(path)
		if image.mode != "P":
			raise RuntimeError(
				f"production JSON+PNG bake requires mode-P indexed frames; "
				f"{path.name} is {image.mode}. Refusing picker-style RGBA palette reconstruction."
			)
		raw = bytes(image.getpalette() or b"")
		if len(raw) < PALETTE_SIZE:
			raise RuntimeError(f"{path.name}: palette shorter than 256 RGB entries ({len(raw)} bytes)")
		raw = raw[:PALETTE_SIZE]
		palettes.add(raw)
		if source_palette is None:
			source_palette = [(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, PALETTE_SIZE, 3)]
	if len(palettes) != 1:
		raise RuntimeError(
			f"{frame_dir}: expected one shared palette across all frames, found {len(palettes)} unique palettes"
		)
	assert source_palette is not None
	return source_palette


def _rmtree_retry(path: pathlib.Path) -> None:
	"""Remove a directory tree; tolerate transient Unity/Windows file locks."""
	if not path.exists():
		return
	last_exc: Exception | None = None
	for attempt in range(6):
		try:
			shutil.rmtree(path)
			return
		except OSError as exc:  # noqa: PERF203 — intentional retry on Windows locks
			last_exc = exc
			# Clear read-only bits that block deletes on Windows.
			for child in path.rglob("*"):
				try:
					child.chmod(0o666)
				except OSError:
					pass
			try:
				path.chmod(0o777)
			except OSError:
				pass
			import time

			time.sleep(0.35 * (attempt + 1))
	raise RuntimeError(f"failed to remove {path}: {last_exc}") from last_exc


def write_remapped_json_png_rgba_frames(
	src_dir: pathlib.Path,
	dst_dir: pathlib.Path,
	target_palette: list[tuple[int, int, int]],
) -> int:
	"""Remap shared mode-P palette, then emit RGBA with special-slot alpha.

	HotA JSON+PNG keys transparency by palette index (cyan at slot 0, etc.), not
	PNG tRNS. Leaving mode-P or naive RGBA for RIFE produces an opaque cyan plate.
	"""
	if dst_dir.exists():
		_rmtree_retry(dst_dir)
	dst_dir.mkdir(parents=True)
	flat = []
	for r, g, b in target_palette:
		flat.extend((r, g, b))
	count = 0
	for src in sorted(src_dir.glob("*.png")):
		image = Image.open(src)
		if image.mode != "P":
			raise RuntimeError(f"refusing non-P frame during remap: {src}")
		remapped = image.copy()
		remapped.putpalette(flat)
		rgba = mode_p_to_rgba_special_slots(remapped)
		assert_rgba_transparency_contract(
			rgba, f"{dst_dir.name}/{src.name}", allow_empty=True
		)
		rgba.save(dst_dir / src.name)
		count += 1
	return count


def materialize_json_png_mode_p_frames(
	source_row: dict,
	*,
	basename: str,
	lab_dir: pathlib.Path,
	zip_json_key: str,
	zip_prefix_key: str,
	zip_path_key: str,
) -> tuple[pathlib.Path, pathlib.Path | None]:
	"""Return a mode-P frame directory for palette rewrite.

	Always materialize from the authoritative HotA zip for JSON+PNG units.
	Lab extracted_battle is frequently RIFE-dense RGBA or a partial overwrite,
	so it must not be treated as the shared mode-P production source.
	"""
	del lab_dir  # intentionally unused; zip is authoritative
	zip_path = ROOT / pathlib.Path(source_row[zip_path_key])
	json_member = (source_row.get(zip_json_key) or "").strip()
	dir_prefix = (source_row.get(zip_prefix_key) or "").strip()
	if not zip_path.is_file() or not json_member or not dir_prefix:
		raise RuntimeError(
			f"{basename}: JSON+PNG bake requires {zip_path_key}/{zip_json_key}/{zip_prefix_key}"
		)
	tmp = pathlib.Path(tempfile.mkdtemp(prefix=f"homm3_json_png_{basename}_"))
	frame_dir = tmp / f"{basename}.dir"
	frame_dir.mkdir(parents=True)
	with zipfile.ZipFile(zip_path) as zf:
		names_ci = {n.replace("\\", "/").lower(): n.replace("\\", "/") for n in zf.namelist()}
		key = json_member.replace("\\", "/").lower()
		if key not in names_ci:
			raise FileNotFoundError(f"{zip_path}: missing {json_member}")
		manifest = json.loads(zf.read(names_ci[key]).decode("utf-8-sig"))
		prefix_key = dir_prefix.replace("\\", "/").rstrip("/").lower() + "/"
		canonical_prefix = None
		for low, real in names_ci.items():
			if low.startswith(prefix_key):
				parts = real.split("/")
				want_parts = dir_prefix.replace("\\", "/").rstrip("/").split("/")
				canonical_prefix = "/".join(parts[: len(want_parts)])
				break
		if canonical_prefix is None:
			raise FileNotFoundError(f"{zip_path}: missing prefix {dir_prefix}")
		written = 0
		for image in manifest.get("images") or []:
			if not isinstance(image, dict):
				continue
			file_name = str(image.get("file") or "").replace("\\", "/")
			if not file_name:
				continue
			member = names_ci.get((canonical_prefix.rstrip("/") + "/" + file_name).lower())
			if not member:
				raise FileNotFoundError(f"{zip_path}: missing frame {file_name}")
			out_path = frame_dir / pathlib.PurePosixPath(file_name).name
			out_path.write_bytes(zf.read(member))
			written += 1
		if written < 1:
			raise RuntimeError(f"{basename}: zip manifest has no images")
	require_shared_p_palette(frame_dir)
	return frame_dir, tmp


def extract_def_bytes(def_bytes: bytes, dest_root: pathlib.Path, basename: str) -> tuple[pathlib.Path, pathlib.Path]:
	tools_dir = ROOT / "tools"
	if str(tools_dir) not in sys.path:
		sys.path.insert(0, str(tools_dir))
	from defextract_py3 import extract_def

	work = dest_root / ".def_work"
	if work.exists():
		shutil.rmtree(work)
	work.mkdir(parents=True)
	def_path = work / f"{basename}.def"
	def_path.write_bytes(def_bytes)
	out = work / "extract"
	out.mkdir()
	if not extract_def(str(def_path), str(out)):
		raise RuntimeError(f"defextract failed for {basename}")
	stem_lc = basename.lower()
	src_dir = out / f"{stem_lc}.dir"
	src_json = out / f"{stem_lc}.json"
	if not src_dir.is_dir() or not src_json.is_file():
		raise FileNotFoundError(f"defextract missing outputs for {basename}")
	dest_dir = dest_root / f"{basename}.dir"
	dest_json = dest_root / f"{basename}.json"
	if dest_dir.exists():
		shutil.rmtree(dest_dir)
	shutil.copytree(src_dir, dest_dir)
	shutil.copy2(src_json, dest_json)
	shutil.rmtree(work)
	return dest_dir, dest_json


def prune_rife_marker(extract_root: pathlib.Path) -> None:
	marker = extract_root / ".rife120_done.json"
	if marker.is_file():
		marker.unlink()
	# Stale native backups from a prior cyan-keyed RIFE run must not win over
	# freshly baked RGBA JSON+PNG frames on the next interpolate pass.
	unit_root = extract_root.parent
	for backup_name in ("extracted_battle_source_12fps", "extracted_map_source_10fps"):
		backup = unit_root / backup_name
		if backup.is_dir():
			shutil.rmtree(backup)


def copy_scaffold(from_lab: pathlib.Path, to_lab: pathlib.Path) -> None:
	to_lab.mkdir(parents=True, exist_ok=True)
	pairs = [
		("battle.prefab", False),
		("map.prefab", False),
		("battle_billboard_mesh.mat", False),
	]
	for name, with_meta in pairs:
		src = from_lab / name
		if not src.is_file():
			raise FileNotFoundError(f"missing scaffold {src}")
		shutil.copy2(src, to_lab / name)
		# Do not copy .meta: shared GUIDs across lab units break Unity imports/rebinding.
		if with_meta:
			meta = src.with_name(src.name + ".meta")
			if meta.is_file():
				shutil.copy2(meta, to_lab / (name + ".meta"))
	ref_src = from_lab / "Reference" / "StockEsquireBattle.controller"
	ref_dst = to_lab / "Reference" / "StockEsquireBattle.controller"
	ref_dst.parent.mkdir(parents=True, exist_ok=True)
	if not ref_src.is_file():
		raise FileNotFoundError(f"missing reference controller {ref_src}")
	shutil.copy2(ref_src, ref_dst)
	# Reference controller meta may be shared safely within Reference/, but prefer unique.
	meta = ref_src.with_name(ref_src.name + ".meta")
	if meta.is_file():
		# Still skip copying controller meta to avoid GUID collisions across units.
		pass


def authoring_for_alt(game_alt_sid: str, inv_row: dict) -> dict:
	battle_base = inv_row["battleExtractBasename"]
	map_base = inv_row["mapExtractBasename"]
	sid = game_alt_sid
	return {
		"unitSid": sid,
		"framesFolder": f"Assets/CustomUnits/homm3_lab/{sid}/extracted_battle/{battle_base}.dir",
		"templateMaterialPath": f"Assets/CustomUnits/homm3_lab/{sid}/battle_billboard_mesh.mat",
		"battlePrefabPath": f"Assets/CustomUnits/homm3_lab/{sid}/battle.prefab",
		"mapPrefabPath": f"Assets/CustomUnits/homm3_lab/{sid}/map.prefab",
		"mapFramesFolder": f"Assets/CustomUnits/homm3_lab/{sid}/extracted_map/{map_base}.dir",
		"generatedRoot": f"Assets/CustomUnits/homm3_lab/{sid}/Generated/BillboardAnim",
		"mapGeneratedRoot": f"Assets/CustomUnits/homm3_lab/{sid}/Generated/MapBillboard",
		"mapAnimatorControllerPath": f"Assets/CustomUnits/homm3_lab/{sid}/Generated/MapBillboard/Homm3MapBillboard.controller",
		"referenceControllerPath": f"Assets/CustomUnits/homm3_lab/{sid}/Reference/StockEsquireBattle.controller",
		"overrideOutputPath": f"Assets/CustomUnits/homm3_lab/{sid}/Generated/BillboardAnim/Homm3BattleBillboard.overrideController",
		"legacyFlatControllerPath": f"Assets/CustomUnits/homm3_lab/{sid}/Generated/BillboardAnim/Homm3BattleBillboard.controller",
		"mapFlipBookFps": 10.0,
		"flipBookFps": 12.0,
		"deathClipFps": 10.0,
		"battleQuadLocalScaleX": 13.5,
		"battleQuadLocalScaleY": 12.0,
		"battleQuadLocalScaleZ": 1.0,
		"battleQuadLocalPositionX": 0.75,
		"battleQuadLocalPositionY": 2.01,
		"battleQuadLocalPositionExtraY": 0.0,
		"mapQuadLocalScaleX": 16.0,
		"mapQuadLocalScaleY": 16.0,
		"mapQuadLocalScaleZ": 1.0,
		"mapQuadLocalPositionX": 1.45,
		"mapQuadLocalPositionY": 2.45,
		"generatedClipNamesCsv": "",
		"paletteStrategy": "material_class_hs",
	}


def upsert_inventory_manifest(selection: dict, source_row: dict, battle_kind: str) -> dict:
	game_alt_sid = selection["gameAltSid"]
	faction = selection["faction"]
	inv = load_json(INVENTORY)
	manifest = load_json(MANIFEST)
	inv_units = inv.setdefault("units", [])
	manifest_units = manifest.setdefault("units", [])

	alt_row = {
		"unitSid": game_alt_sid,
		"comment": (
			f"{faction.title()} alt upgrade baked with material_class_hs from {selection['fromLabSid']} "
			f"(option {selection['optionId']}: {selection['displayName']})."
		),
		"battleExtractBasename": source_row["battleExtractBasename"],
		"mapExtractBasename": source_row["mapExtractBasename"],
		"battleZipPath": source_row.get("battleZipPath"),
		"mapZipPath": source_row.get("mapZipPath"),
		"soundPaths": source_row.get("soundPaths"),
		"altBake": {
			"strategy": "material_class_hs",
			"fromLabSid": selection["fromLabSid"],
			"optionId": selection["optionId"],
			"displayName": selection["displayName"],
			"battleSourceKind": battle_kind,
		},
	}
	# Alts are derived lab units; keep source pointers for audit but do not claim raw zip members are the alt art.
	if battle_kind == "def" and source_row.get("battleZipMember"):
		alt_row["battleZipMember"] = source_row["battleZipMember"]
	elif battle_kind == "json_png":
		alt_row["battleJsonZipMember"] = source_row.get("battleJsonZipMember")
		alt_row["battleJsonDirPrefix"] = source_row.get("battleJsonDirPrefix")
	if source_row.get("mapZipMember"):
		alt_row["mapZipMember"] = source_row["mapZipMember"]
	if source_row.get("mapJsonZipMember"):
		alt_row["mapJsonZipMember"] = source_row["mapJsonZipMember"]
		alt_row["mapJsonDirPrefix"] = source_row.get("mapJsonDirPrefix")

	replaced = False
	for i, row in enumerate(inv_units):
		if row.get("unitSid") == game_alt_sid:
			inv_units[i] = alt_row
			replaced = True
			break
	if not replaced:
		inv_units.append(alt_row)

	bundle_name = f"custom_units_{faction}_{game_alt_sid}"
	manifest_row = {
		"unitSid": game_alt_sid,
		"battlePrefabAsset": f"Assets/CustomUnits/homm3_lab/{game_alt_sid}/battle.prefab",
		"mapPrefabAsset": f"Assets/CustomUnits/homm3_lab/{game_alt_sid}/map.prefab",
		"bundleName": bundle_name,
	}
	replaced = False
	for i, row in enumerate(manifest_units):
		if row.get("unitSid") == game_alt_sid:
			manifest_units[i] = manifest_row
			replaced = True
			break
	if not replaced:
		manifest_units.append(manifest_row)

	write_json(INVENTORY, inv)
	write_json(MANIFEST, manifest)
	preset_dir = PRESETS / game_alt_sid
	write_json(preset_dir / "authoring.json", authoring_for_alt(game_alt_sid, alt_row))
	return alt_row


def bake_battle_def(selection: dict, source_row: dict, materials: dict, dest_battle: pathlib.Path) -> dict:
	zip_path = ROOT / pathlib.Path(source_row["battleZipPath"])
	member = source_row["battleZipMember"]
	source_def = read_zip_member(zip_path, member)
	source_palette = palette_from_def(source_def)
	target_palette, rows = resolve_target_palette(source_palette, materials)
	patched = bytearray(source_def)
	patched[PALETTE_OFFSET : PALETTE_OFFSET + PALETTE_SIZE] = palette_bytes(target_palette)
	basename = source_row["battleExtractBasename"]
	if dest_battle.exists():
		shutil.rmtree(dest_battle)
	dest_battle.mkdir(parents=True)
	frame_dir, manifest = extract_def_bytes(bytes(patched), dest_battle, basename)
	prune_rife_marker(dest_battle)
	changed = sum(1 for row in rows if row.get("changed"))
	return {
		"kind": "def",
		"zipMember": member,
		"frameCount": len(list(frame_dir.glob("*.png"))),
		"paletteChangedEntries": changed,
		"manifest": relative_to_root(manifest),
	}


def write_battle_json_from_zip_manifest(
	*,
	zip_path: pathlib.Path,
	json_member: str,
	dir_prefix: str,
	basename: str,
	dest_json: pathlib.Path,
	expected_frame_names: set[str],
) -> None:
	"""Write defextract-like sequences JSON matching the remapped frame filenames."""
	with zipfile.ZipFile(zip_path) as zf:
		names_ci = {n.replace("\\", "/").lower(): n.replace("\\", "/") for n in zf.namelist()}
		key = json_member.replace("\\", "/").lower()
		if key not in names_ci:
			raise FileNotFoundError(f"{zip_path}: missing {json_member}")
		manifest = json.loads(zf.read(names_ci[key]).decode("utf-8-sig"))
	by_group: dict[int, list[tuple[int, str]]] = {}
	for image in manifest.get("images") or []:
		if not isinstance(image, dict):
			continue
		file_name = pathlib.PurePosixPath(str(image.get("file") or "").replace("\\", "/")).name
		if not file_name:
			continue
		if file_name not in expected_frame_names:
			raise RuntimeError(
				f"{basename}: zip frame {file_name} missing from remapped dir "
				f"(expected {len(expected_frame_names)} files)"
			)
		by_group.setdefault(int(image["group"]), []).append((int(image["frame"]), file_name))
	sequences = []
	for group in sorted(by_group):
		frames = [
			f"{basename}.dir\\{file_name}"
			for _, file_name in sorted(by_group[group], key=lambda item: item[0])
		]
		sequences.append({"group": group, "frames": frames})
	if not sequences:
		raise RuntimeError(f"{basename}: zip manifest produced no sequences")
	write_json(dest_json, {"sequences": sequences})


def bake_battle_json_png(selection: dict, source_row: dict, materials: dict, dest_battle: pathlib.Path) -> dict:
	from_lab = UNITY_LAB / selection["fromLabSid"]
	src_battle = from_lab / "extracted_battle"
	basename = source_row["battleExtractBasename"]
	src_dir = src_battle / f"{basename}.dir"
	src_json = src_battle / f"{basename}.json"
	# Refuse any DEF claim when inventory says JSON+PNG.
	zip_path = ROOT / pathlib.Path(source_row["battleZipPath"])
	def_member = f"sprites/hota/{selection['faction']}/creatures/battle/{basename}.def"
	try:
		read_zip_member(zip_path, def_member)
		raise RuntimeError(
			f"{selection['fromLabSid']}: inventory marks JSON+PNG but {def_member} exists in zip; "
			"resolve inventory source kind before baking."
		)
	except FileNotFoundError:
		pass

	mode_p_dir, tmp_cleanup = materialize_json_png_mode_p_frames(
		source_row,
		basename=basename,
		lab_dir=src_dir,
		zip_json_key="battleJsonZipMember",
		zip_prefix_key="battleJsonDirPrefix",
		zip_path_key="battleZipPath",
	)
	try:
		source_palette = require_shared_p_palette(mode_p_dir)
		target_palette, rows = resolve_target_palette(source_palette, materials)
		if dest_battle.exists():
			_rmtree_retry(dest_battle)
		dest_battle.mkdir(parents=True)
		dst_dir = dest_battle / f"{basename}.dir"
		frame_count = write_remapped_json_png_rgba_frames(mode_p_dir, dst_dir, target_palette)
		dest_json = dest_battle / f"{basename}.json"
		frame_names = {p.name for p in dst_dir.glob("*.png")}
		# Lab JSON is often RIFE-rewritten (00_0000.png). Always rebuild from the
		# HotA zip so remapped original filenames stay addressable for standing/RIFE.
		write_battle_json_from_zip_manifest(
			zip_path=zip_path,
			json_member=str(source_row.get("battleJsonZipMember") or ""),
			dir_prefix=str(source_row.get("battleJsonDirPrefix") or ""),
			basename=basename,
			dest_json=dest_json,
			expected_frame_names=frame_names,
		)
		prune_rife_marker(dest_battle)
		changed = sum(1 for row in rows if row.get("changed"))
		return {
			"kind": "json_png_shared_palette_rgba",
			"zipMember": source_row.get("battleJsonZipMember"),
			"frameCount": frame_count,
			"paletteChangedEntries": changed,
			"sourceLabDir": relative_to_root(src_dir) if src_dir.is_dir() else None,
			"modePSource": "zip",
			"manifest": relative_to_root(dest_json),
		}
	finally:
		if tmp_cleanup is not None and tmp_cleanup.exists():
			shutil.rmtree(tmp_cleanup, ignore_errors=True)


def bake_map_def(selection: dict, source_row: dict, materials: dict, dest_map: pathlib.Path) -> dict:
	zip_path = ROOT / pathlib.Path(source_row["mapZipPath"])
	member = source_row.get("mapZipMember")
	if not member:
		raise ValueError(f"{selection['gameAltSid']}: map DEF member missing")
	source_def = read_zip_member(zip_path, member)
	source_palette = palette_from_def(source_def)
	target_palette, rows = resolve_target_palette(source_palette, materials)
	patched = bytearray(source_def)
	patched[PALETTE_OFFSET : PALETTE_OFFSET + PALETTE_SIZE] = palette_bytes(target_palette)
	basename = source_row["mapExtractBasename"]
	if dest_map.exists():
		_rmtree_retry(dest_map)
	dest_map.mkdir(parents=True)
	frame_dir, manifest = extract_def_bytes(bytes(patched), dest_map, basename)
	prune_rife_marker(dest_map)
	changed = sum(1 for row in rows if row.get("changed"))
	return {
		"kind": "def",
		"zipMember": member,
		"frameCount": len(list(frame_dir.glob("*.png"))),
		"paletteChangedEntries": changed,
		"manifest": relative_to_root(manifest),
	}


def bake_map_json_png(selection: dict, source_row: dict, materials: dict, dest_map: pathlib.Path) -> dict:
	from_lab = UNITY_LAB / selection["fromLabSid"]
	src_map = from_lab / "extracted_map"
	basename = source_row["mapExtractBasename"]
	src_dir = src_map / f"{basename}.dir"
	src_json = src_map / f"{basename}.json"
	if not src_json.is_file():
		raise FileNotFoundError(f"missing map extract manifest {src_json}")
	mode_p_dir, tmp_cleanup = materialize_json_png_mode_p_frames(
		source_row,
		basename=basename,
		lab_dir=src_dir,
		zip_json_key="mapJsonZipMember",
		zip_prefix_key="mapJsonDirPrefix",
		zip_path_key="mapZipPath",
	)
	try:
		source_palette = require_shared_p_palette(mode_p_dir)
		target_palette, rows = resolve_target_palette(source_palette, materials)
		if dest_map.exists():
			_rmtree_retry(dest_map)
		dest_map.mkdir(parents=True)
		frame_count = write_remapped_json_png_rgba_frames(
			mode_p_dir, dest_map / f"{basename}.dir", target_palette
		)
		shutil.copy2(src_json, dest_map / f"{basename}.json")
		prune_rife_marker(dest_map)
		changed = sum(1 for row in rows if row.get("changed"))
		return {
			"kind": "json_png_shared_palette_rgba",
			"frameCount": frame_count,
			"paletteChangedEntries": changed,
			"modePSource": "zip",
		}
	finally:
		if tmp_cleanup is not None and tmp_cleanup.exists():
			shutil.rmtree(tmp_cleanup, ignore_errors=True)


def standing_frame(lab_sid: str) -> pathlib.Path:
	extracted = UNITY_LAB / lab_sid / "extracted_battle"
	manifests = sorted(
		p
		for p in extracted.glob("*.json")
		if p.is_file() and not p.name.startswith(".") and p.name.lower() != ".rife120_done.json"
	)
	if not manifests:
		raise FileNotFoundError(f"{lab_sid}: no battle manifest under {extracted}")
	manifest = manifests[0]
	data = load_json(manifest)
	group = next((row for row in (data.get("sequences") or []) if int(row.get("group", -1)) == 2), None)
	if not group or not group.get("frames"):
		raise FileNotFoundError(f"{lab_sid}: no standing group 2 in {manifest.name}")
	rel = pathlib.PureWindowsPath(str(group["frames"][0]))
	path = extracted.joinpath(*rel.parts)
	if not path.is_file():
		raise FileNotFoundError(path)
	return path


def standing_frame_rgba_for_spotcheck(selection: dict, *, alt: bool) -> tuple[Image.Image, str]:
	"""Load standing RGBA for spotcheck; prefer lab, fall back to HotA zip for broken sources."""
	lab_sid = selection["gameAltSid"] if alt else selection["fromLabSid"]
	try:
		path = standing_frame(lab_sid)
		image = Image.open(path)
		if image.mode == "P":
			rgba = mode_p_to_rgba_special_slots(image)
		else:
			rgba = image.convert("RGBA")
		return rgba, relative_to_root(path)
	except FileNotFoundError:
		if alt:
			raise
	# Source lab may be a prior cyan RIFE pass with an emptied manifest. Rebuild
	# standing preview from the authoritative HotA zip for the left-side compare.
	source_row = inventory_row(selection["fromLabSid"])
	zip_path = ROOT / pathlib.Path(source_row["battleZipPath"])
	json_member = str(source_row.get("battleJsonZipMember") or "")
	dir_prefix = str(source_row.get("battleJsonDirPrefix") or "")
	with zipfile.ZipFile(zip_path) as zf:
		names_ci = {n.replace("\\", "/").lower(): n.replace("\\", "/") for n in zf.namelist()}
		manifest = json.loads(zf.read(names_ci[json_member.replace("\\", "/").lower()]).decode("utf-8-sig"))
		standing = next(
			(
				img
				for img in (manifest.get("images") or [])
				if isinstance(img, dict) and int(img.get("group", -1)) == 2 and int(img.get("frame", -1)) == 0
			),
			None,
		)
		if standing is None:
			raise FileNotFoundError(f"{selection['fromLabSid']}: zip missing standing frame")
		file_name = str(standing.get("file") or "").replace("\\", "/")
		prefix_key = dir_prefix.replace("\\", "/").rstrip("/").lower() + "/"
		canonical_prefix = None
		for low, real in names_ci.items():
			if low.startswith(prefix_key):
				parts = real.split("/")
				want_parts = dir_prefix.replace("\\", "/").rstrip("/").split("/")
				canonical_prefix = "/".join(parts[: len(want_parts)])
				break
		if canonical_prefix is None:
			raise FileNotFoundError(dir_prefix)
		member = names_ci[(canonical_prefix.rstrip("/") + "/" + file_name).lower()]
		image = Image.open(io.BytesIO(zf.read(member)))
	if image.mode != "P":
		raise RuntimeError(f"{selection['fromLabSid']}: zip standing is {image.mode}, expected mode-P")
	rgba = mode_p_to_rgba_special_slots(image)
	assert_rgba_transparency_contract(rgba, f"{selection['fromLabSid']} zip standing")
	return rgba, f"{source_row['battleZipPath']}!{dir_prefix}/{file_name}"


def spotcheck(selection: dict) -> dict:
	SPOTCHECK_DIR.mkdir(parents=True, exist_ok=True)
	src_im, src_label = standing_frame_rgba_for_spotcheck(selection, alt=False)
	dst_im, dst_label = standing_frame_rgba_for_spotcheck(selection, alt=True)
	if dst_im.mode != "RGBA":
		dst_im = dst_im.convert("RGBA")
	assert_rgba_transparency_contract(dst_im, f"{selection['gameAltSid']} standing")
	if src_im.size != dst_im.size:
		raise RuntimeError(
			f"{selection['displayName']}: standing size mismatch {src_im.size} vs {dst_im.size}"
		)
	if src_im.size != (450, 400):
		raise RuntimeError(f"{selection['displayName']}: unexpected canvas {src_im.size}, expected 450x400")
	if dst_im.getchannel("A").getbbox() is None:
		raise RuntimeError(f"{selection['displayName']}: remapped standing frame has no opaque pixels")
	cyan_dst = sum(1 for r, g, b, a in dst_im.getdata() if is_opaque_key_cyan(r, g, b, a))
	if cyan_dst:
		raise RuntimeError(f"{selection['displayName']}: alt standing still has {cyan_dst} opaque cyan pixels")
	pair = Image.new("RGBA", (src_im.width * 2 + 16, src_im.height), (18, 20, 24, 255))
	tile = Image.new("RGBA", (16, 16), (28, 32, 38, 255))
	for y in range(0, pair.height, 16):
		for x in range(0, pair.width, 16):
			if ((x // 16) + (y // 16)) % 2 == 0:
				pair.paste(tile, (x, y))
	pair.alpha_composite(src_im.convert("RGBA"), (0, 0))
	pair.alpha_composite(dst_im, (src_im.width + 16, 0))
	out = SPOTCHECK_DIR / f"{selection['gameAltSid']}_standing_pair.png"
	pair.save(out)
	return {
		"sourceStanding": src_label,
		"altStanding": dst_label,
		"pair": relative_to_root(out),
		"size": list(src_im.size),
		"altCyanOpaquePixels": cyan_dst,
	}


def bake_one(selection: dict) -> dict:
	if selection.get("strategy") != "material_class_hs":
		raise ValueError(f"{selection['displayName']}: strategy must be material_class_hs")
	source_row = inventory_row(selection["fromLabSid"])
	materials = gallery_option_materials(
		selection["faction"],
		selection["baseSid"],
		selection["optionId"],
		selection.get("line"),
	)
	from_lab = UNITY_LAB / selection["fromLabSid"]
	if not from_lab.is_dir():
		raise FileNotFoundError(from_lab)
	to_lab = UNITY_LAB / selection["gameAltSid"]
	copy_scaffold(from_lab, to_lab)

	battle_kind = battle_source_kind(source_row)
	dest_battle = to_lab / "extracted_battle"
	if battle_kind == "def":
		battle_meta = bake_battle_def(selection, source_row, materials, dest_battle)
	elif battle_kind == "json_png":
		battle_meta = bake_battle_json_png(selection, source_row, materials, dest_battle)
	else:
		raise RuntimeError(f"unsupported battle kind {battle_kind}")

	map_kind = map_source_kind(source_row)
	dest_map = to_lab / "extracted_map"
	if map_kind == "def":
		map_meta = bake_map_def(selection, source_row, materials, dest_map)
	elif map_kind == "json_png":
		map_meta = bake_map_json_png(selection, source_row, materials, dest_map)
	else:
		map_meta = {"kind": None, "note": "no map source"}

	alt_row = upsert_inventory_manifest(selection, source_row, battle_kind)
	shutil.copy2(PRESETS / selection["gameAltSid"] / "authoring.json", to_lab / "authoring.json")
	check = spotcheck(selection)
	return {
		"displayName": selection["displayName"],
		"gameAltSid": selection["gameAltSid"],
		"fromLabSid": selection["fromLabSid"],
		"optionId": selection["optionId"],
		"battle": battle_meta,
		"map": map_meta,
		"spotcheck": check,
		"lab": relative_to_root(to_lab),
		"inventoryUnitSid": alt_row["unitSid"],
	}


def main() -> int:
	ap = argparse.ArgumentParser(description=__doc__)
	ap.add_argument("--selections", type=pathlib.Path, default=DEFAULT_SELECTIONS)
	ap.add_argument("--only", action="append", default=[], help="optional displayName filter (repeatable)")
	args = ap.parse_args()

	payload = load_json(args.selections)
	selections = payload.get("selections") or []
	if args.only:
		wanted = {name.lower() for name in args.only}
		selections = [s for s in selections if str(s.get("displayName", "")).lower() in wanted]
	if not selections:
		print("no selections to bake", file=sys.stderr)
		return 1

	reports = []
	failures = []
	for selection in selections:
		name = selection.get("displayName")
		print(f"bake {name} -> {selection.get('gameAltSid')} ...", flush=True)
		try:
			report = bake_one(selection)
			reports.append(report)
			print(
				f"  OK battle={report['battle']['kind']} frames={report['battle']['frameCount']} "
				f"paletteChanged={report['battle']['paletteChangedEntries']}",
				flush=True,
			)
		except Exception as exc:  # noqa: BLE001 — batch fail-closed summary
			failures.append({"displayName": name, "gameAltSid": selection.get("gameAltSid"), "error": str(exc)})
			print(f"  FAIL {name}: {exc}", flush=True)

	out = {
		"schemaVersion": 1,
		"strategy": "material_class_hs",
		"evidenceLevel": "generated_lab_units_from_production_extract",
		"count": len(reports),
		"failureCount": len(failures),
		"reports": reports,
		"failures": failures,
	}
	report_path = HERE / "alternate_upgrade_concepts" / "material_class_hs_bake_report.json"
	write_json(report_path, out)
	print(f"wrote {relative_to_root(report_path)} ok={len(reports)} fail={len(failures)}", flush=True)
	return 1 if failures else 0


if __name__ == "__main__":
	raise SystemExit(main())
