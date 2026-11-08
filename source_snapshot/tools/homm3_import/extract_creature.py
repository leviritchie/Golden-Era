#!/usr/bin/env python3
"""Extract one creature from HoMM3 LOD or loose .def into Unity homm3_lab folders (defextract PNG + JSON)."""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import zipfile


def _absolute_no_resolve(path: pathlib.Path) -> pathlib.Path:
	return pathlib.Path(os.path.abspath(path))


def _repo_root() -> pathlib.Path:
	# This file lives at <repo>/tools/homm3_import/extract_creature.py
	return pathlib.Path(__file__).resolve().parents[2]


def _repo_relative(path_s: str) -> pathlib.Path:
	"""Resolve large local source assets from this worktree or its main checkout."""
	path = pathlib.Path(path_s).expanduser()
	if path.is_absolute():
		return path
	root = _repo_root()
	candidates = [root / path]
	if root.parent.name.lower() == "worktrees":
		candidates.append(root.parent.parent / path)
	for candidate in candidates:
		if candidate.is_file():
			return candidate
	return candidates[0]


def _load_inventory(path: pathlib.Path) -> dict:
	return json.loads(path.read_text(encoding="utf-8-sig"))


def _resolve_lod(inv: dict, lod_name: str) -> pathlib.Path | None:
	root = _repo_root()
	for key in ("homm3LodRoot", "fallbackLodRoot"):
		rel = inv.get(key)
		if not rel:
			continue
		candidate = (root / pathlib.Path(rel) / lod_name).resolve()
		if candidate.is_file():
			return candidate
	return None


def _run(py: list[str]) -> None:
	r = subprocess.run(py, cwd=str(_repo_root()))
	if r.returncode != 0:
		raise SystemExit(r.returncode)


def _prune_stale_extracts(root: pathlib.Path, keep_basename: str, *, clear_rife_done: bool = False) -> None:
	keep = {
		f"{keep_basename}.dir".lower(),
		f"{keep_basename}.dir.meta".lower(),
		f"{keep_basename}.json".lower(),
		f"{keep_basename}.json.meta".lower(),
	}
	if not root.is_dir():
		return
	for child in root.iterdir():
		name = child.name.lower()
		if clear_rife_done and name == ".rife120_done.json" and child.is_file():
			child.unlink()
			continue
		if name in keep or name.startswith(".") or name == "manifest.json":
			continue
		if child.is_dir() and name.endswith(".dir"):
			shutil.rmtree(child)
		elif child.is_file() and (name.endswith(".json") or name.endswith(".dir.meta") or name.endswith(".json.meta")):
			child.unlink()


def _zip_resolve_member(zf: zipfile.ZipFile, member_s: str) -> str:
	"""Resolve zip members with case-insensitive fallback for HotA archives."""
	want = member_s.replace("\\", "/")
	names = [n.replace("\\", "/") for n in zf.namelist()]
	if want in names:
		return want
	lower = {n.lower(): n for n in names}
	hit = lower.get(want.lower())
	if hit is None:
		raise KeyError(member_s)
	return hit


def _copy_or_extract_zip_member(row: dict, *, path_key: str, zip_key: str, member_key: str, dest: pathlib.Path) -> bool:
	"""Copy a loose file or extract a zip member described by inventory keys."""
	if row.get(path_key):
		src = pathlib.Path(row[path_key]).expanduser()
		if not src.is_file():
			print(f"{path_key} not found: {src}", file=sys.stderr)
			raise SystemExit(1)
		shutil.copy2(src, dest)
		return True

	zip_path_s = (row.get(zip_key) or "").strip()
	member_s = (row.get(member_key) or "").strip()
	if not zip_path_s and not member_s:
		return False
	if not zip_path_s or not member_s:
		print(f"inventory row needs both {zip_key} and {member_key}", file=sys.stderr)
		raise SystemExit(1)

	zip_path = _repo_relative(zip_path_s)
	if not zip_path.is_file():
		print(f"{zip_key} not found: {zip_path}", file=sys.stderr)
		raise SystemExit(1)

	try:
		with zipfile.ZipFile(zip_path) as zf:
			resolved = _zip_resolve_member(zf, member_s)
			with zf.open(resolved) as src, dest.open("wb") as out:
				shutil.copyfileobj(src, out)
	except KeyError:
		print(f"{member_key} not found in {zip_path}: {member_s}", file=sys.stderr)
		raise SystemExit(1)
	except zipfile.BadZipFile as ex:
		print(f"bad zip file {zip_path}: {ex}", file=sys.stderr)
		raise SystemExit(1)
	return True


def _copy_vcmi_json_animation(
	row: dict,
	*,
	zip_key: str,
	json_member_key: str,
	dir_prefix_key: str,
	out_root: pathlib.Path,
	basename: str,
) -> bool:
	"""Copy a VCMI JSON+PNG animation from a zip into defextract-like layout."""
	zip_path_s = (row.get(zip_key) or "").strip()
	json_member = (row.get(json_member_key) or "").strip()
	dir_prefix = (row.get(dir_prefix_key) or "").strip()
	if not json_member and not dir_prefix:
		return False
	if not zip_path_s or not json_member or not dir_prefix:
		print(f"inventory row needs {zip_key}, {json_member_key}, and {dir_prefix_key}", file=sys.stderr)
		raise SystemExit(1)

	zip_path = _repo_relative(zip_path_s)
	if not zip_path.is_file():
		print(f"{zip_key} not found: {zip_path}", file=sys.stderr)
		raise SystemExit(1)

	dest_dir = out_root / f"{basename}.dir"
	dest_json = out_root / f"{basename}.json"
	if dest_dir.exists():
		shutil.rmtree(dest_dir)
	dest_dir.mkdir(parents=True, exist_ok=True)

	try:
		with zipfile.ZipFile(zip_path) as zf:
			json_resolved = _zip_resolve_member(zf, json_member)
			prefix_resolved = _zip_resolve_member(zf, dir_prefix.rstrip("/") + "/") if False else dir_prefix.rstrip("/")
			# Resolve dir prefix case-insensitively against namelist.
			names_ci = {n.replace("\\", "/").lower(): n.replace("\\", "/") for n in zf.namelist()}
			prefix_key = dir_prefix.replace("\\", "/").rstrip("/").lower() + "/"
			# Find any member under the prefix to recover canonical casing.
			canonical_prefix = None
			for low, real in names_ci.items():
				if low.startswith(prefix_key):
					canonical_prefix = real[: len(real) - len(real.split("/")[-1])].rstrip("/")
					# Better: take the directory portion matching prefix depth
					parts = real.split("/")
					want_parts = dir_prefix.replace("\\", "/").rstrip("/").split("/")
					canonical_prefix = "/".join(parts[: len(want_parts)])
					break
			if canonical_prefix is None:
				# allow exact json sibling directory even if empty listing quirk
				canonical_prefix = dir_prefix.replace("\\", "/").rstrip("/")
			vcmi_manifest = json.loads(zf.read(json_resolved).decode("utf-8-sig"))
			images = vcmi_manifest.get("images") or []
			by_group: dict[int, list[tuple[int, str]]] = {}
			for image_index, image in enumerate(images):
				if not isinstance(image, dict):
					continue
				group = int(image.get("group"))
				frame = int(image.get("frame"))
				file_name = str(image.get("file") or "").replace("\\", "/")
				if not file_name:
					continue
				member = canonical_prefix.rstrip("/") + "/" + file_name
				member = names_ci.get(member.lower(), member)
				# Some VCMI manifests reuse the same basename in different groups.
				# Keep every source image unique until the final GG_FF rename; using
				# the basename directly silently overwrote one of those frames.
				source_name = f"__source_{image_index:06d}_{pathlib.PurePosixPath(file_name).name}"
				with zf.open(member) as src, (dest_dir / source_name).open("wb") as out:
					shutil.copyfileobj(src, out)
				by_group.setdefault(group, []).append((frame, source_name))
	except KeyError as ex:
		print(f"missing VCMI animation member in {zip_path}: {ex}", file=sys.stderr)
		raise SystemExit(1)
	except zipfile.BadZipFile as ex:
		print(f"bad zip file {zip_path}: {ex}", file=sys.stderr)
		raise SystemExit(1)

	# HotA JSON+PNG frames are shared mode-P with special-slot keyed transparency
	# (often cyan @ index 0) and usually no tRNS. Convert to RGBA like defextract
	# so RIFE/Unity never see an opaque cyan plate. Palette remaps for alt bakes
	# always re-read mode-P from the HotA zip (see bake_hota_alt_material_class_hs_units).
	_tools = pathlib.Path(__file__).resolve().parent
	if str(_tools) not in sys.path:
		sys.path.insert(0, str(_tools))
	from homm3_vcmi_png_alpha import (  # noqa: WPS433 — local import after path setup
		assert_rgba_transparency_contract,
		mode_p_to_rgba_special_slots,
	)
	from PIL import Image

	# Decode HotA/VCMI mode-P plates to RGBA, then rename onto authentic
	# GG_FF.png keys (group/frame). Pose-fit inventory refuses HotA basenames
	# and four-digit RIFE plates; keep extract output on the same contract as
	# defextract so ToA JSON+PNG alts are immediately selectable.
	decoded: dict[str, pathlib.Path] = {}
	for png in sorted(dest_dir.glob("*.png")):
		with Image.open(png) as image:
			if image.mode == "P":
				rgba = mode_p_to_rgba_special_slots(image)
			elif image.mode == "RGBA":
				# A subset of newer HotA exports is already decoded.  Preserve its
				# alpha channel rather than rejecting a valid source representation.
				rgba = image.copy()
			else:
				raise SystemExit(
					f"{png.name}: VCMI JSON+PNG extract expected P or RGBA, got {image.mode}"
				)
			assert_rgba_transparency_contract(rgba, png.name, allow_empty=True)
			rgba.save(png)
		decoded[png.name] = png

	sequences = []
	kept_names: set[str] = set()
	for group in sorted(by_group):
		ordered = sorted(by_group[group], key=lambda item: item[0])
		frames: list[str] = []
		for frame_index, (_, file_name) in enumerate(ordered):
			src = decoded.get(file_name)
			if src is None:
				raise SystemExit(
					f"{basename}: sequence references missing frame {file_name!r}"
				)
			out_name = f"{int(group):02d}_{int(frame_index):02d}.png"
			dest = dest_dir / out_name
			if src.name != out_name:
				if dest.exists():
					dest.unlink()
				src.replace(dest)
				decoded[out_name] = dest
				decoded.pop(file_name, None)
			kept_names.add(out_name)
			frames.append(f"{basename}.dir\\{out_name}")
		sequences.append({"group": group, "frames": frames})
	for stale in list(dest_dir.glob("*.png")):
		if stale.name not in kept_names:
			stale.unlink()
	dest_json.write_text(json.dumps({"sequences": sequences}, indent=4) + "\n", encoding="utf-8")
	return True


def _extract_map_source(
	row: dict,
	*,
	map_dir: pathlib.Path,
	tmp: pathlib.Path,
	map_basename: str,
	defextract: pathlib.Path,
	lod_extract: pathlib.Path,
	inventory: dict,
) -> bool:
	map_path_str = row.get("mapDefPath") or ""
	map_zip = (row.get("mapZipPath") or "").strip()
	map_zip_member = (row.get("mapZipMember") or "").strip()
	map_json_member = (row.get("mapJsonZipMember") or "").strip()
	map_lod_entry = (row.get("mapLodEntry") or "").strip()
	if not (map_path_str or map_zip or map_zip_member or map_json_member or map_lod_entry):
		return False

	map_dir.mkdir(parents=True, exist_ok=True)
	if _copy_vcmi_json_animation(
		row,
		zip_key="mapZipPath",
		json_member_key="mapJsonZipMember",
		dir_prefix_key="mapJsonDirPrefix",
		out_root=map_dir,
		basename=map_basename,
	):
		_prune_stale_extracts(map_dir, map_basename)
		print(f"OK map -> {map_dir}")
		return True

	map_path = tmp / f"{map_basename}.def"
	if not _copy_or_extract_zip_member(
		row,
		path_key="mapDefPath",
		zip_key="mapZipPath",
		member_key="mapZipMember",
		dest=map_path,
	):
		if not map_lod_entry:
			print("inventory row needs mapDefPath, mapZipPath/mapZipMember, or mapLodEntry", file=sys.stderr)
			raise SystemExit(1)
		lod_name = row.get("mapLod") or row.get("battleLod") or "H3sprite.lod"
		lod_path = _resolve_lod(inventory, str(lod_name))
		if lod_path is None:
			print(f"Could not find {lod_name} for map LOD extraction", file=sys.stderr)
			raise SystemExit(1)
		_run([sys.executable, str(lod_extract), str(lod_path), map_lod_entry, str(map_path)])
	out_map = tmp / "defextract_map"
	out_map.mkdir(parents=True, exist_ok=True)
	_run([sys.executable, str(defextract), str(map_path), str(out_map)])
	m_stem = map_path.stem.lower()
	m_dir = out_map / f"{m_stem}.dir"
	m_json = out_map / f"{m_stem}.json"
	if m_dir.is_dir() and m_json.is_file():
		dest_m_dir = map_dir / f"{map_basename}.dir"
		if dest_m_dir.exists():
			shutil.rmtree(dest_m_dir)
		shutil.copytree(m_dir, dest_m_dir)
		shutil.copy2(m_json, map_dir / f"{map_basename}.json")
		_prune_stale_extracts(map_dir, map_basename)
	else:
		print(f"map defextract output missing: {m_dir} / {m_json}", file=sys.stderr)
		raise SystemExit(1)

	print(f"OK map -> {map_dir}")
	return True


def main() -> int:
	ap = argparse.ArgumentParser(description="HoMM3 creature extract → homm3_lab (lane B).")
	ap.add_argument("--inventory", type=pathlib.Path, default=None, help="units_inventory.json path")
	ap.add_argument("--unit", required=True, help="unitSid in inventory")
	ap.add_argument("--map-only", action="store_true", help="Extract only adventure-map frames into extracted_map.")
	ap.add_argument(
		"--unity-project",
		type=pathlib.Path,
		required=True,
		help="oldenera_factions root (contains Assets/)",
	)
	args = ap.parse_args()
	inv_path = args.inventory or (pathlib.Path(__file__).resolve().parent / "units_inventory.json")
	inv = _load_inventory(inv_path)
	units = inv.get("units") or []
	row = next((u for u in units if u.get("unitSid") == args.unit), None)
	if not row:
		print(f"unitSid '{args.unit}' not found in {inv_path}", file=sys.stderr)
		return 1

	lab_root = _absolute_no_resolve(args.unity_project) / "Assets" / "CustomUnits" / "homm3_lab" / args.unit
	battle_dir = lab_root / "extracted_battle"
	map_dir = lab_root / "extracted_map"
	battle_dir.mkdir(parents=True, exist_ok=True)
	tools = _repo_root() / "tools"
	lod_extract = tools / "lod_extract_entry_py3.py"
	defextract = tools / "defextract_py3.py"
	fix_script = pathlib.Path(__file__).resolve().parent / "fix_defextract_json_paths.py"

	tmp = _repo_root() / "tools" / "build_temp_homm3" / args.unit
	if tmp.exists():
		shutil.rmtree(tmp)
	tmp.mkdir(parents=True)

	basename = row.get("battleExtractBasename") or args.unit
	map_basename = row.get("mapExtractBasename") or f"{basename}_map"

	if args.map_only:
		if _extract_map_source(row, map_dir=map_dir, tmp=tmp, map_basename=map_basename,
								defextract=defextract, lod_extract=lod_extract, inventory=inv):
			return 0
		print("inventory row has no adventure-map source; set mapDefPath/mapZipPath/mapZipMember/mapJsonZipMember/mapLodEntry", file=sys.stderr)
		return 1

	battle_def = tmp / f"{basename}.def"
	battle_from_json = _copy_vcmi_json_animation(
		row,
		zip_key="battleZipPath",
		json_member_key="battleJsonZipMember",
		dir_prefix_key="battleJsonDirPrefix",
		out_root=battle_dir,
		basename=basename,
	)
	if battle_from_json:
		dest_png_dir = battle_dir / f"{basename}.dir"
		dest_json = battle_dir / f"{basename}.json"
		_prune_stale_extracts(battle_dir, basename, clear_rife_done=True)
		map_json_member = (row.get("mapJsonZipMember") or "").strip()
		if map_json_member:
			if not _copy_vcmi_json_animation(
				row,
				zip_key="mapZipPath",
				json_member_key="mapJsonZipMember",
				dir_prefix_key="mapJsonDirPrefix",
				out_root=map_dir,
				basename=map_basename,
			):
				return 1
			print(f"OK map -> {map_dir}")
			print(f"OK battle -> {dest_png_dir} + {dest_json}")
			return 0
	elif not _copy_or_extract_zip_member(
		row,
		path_key="battleDefPath",
		zip_key="battleZipPath",
		member_key="battleZipMember",
		dest=battle_def,
	):
		lod_name = row.get("battleLod") or "H3sprite.lod"
		entry = row.get("battleLodEntry")
		if not entry:
			print("inventory row needs battleLodEntry, battleDefPath, or battleZipPath/battleZipMember", file=sys.stderr)
			return 1
		lod_path = _resolve_lod(inv, lod_name)
		if lod_path is None:
			print(
				"Could not find "
				+ lod_name
				+ " — set homm3LodRoot / fallbackLodRoot in units_inventory.json (relative to repo root).",
				file=sys.stderr,
			)
			return 1
		_run([sys.executable, str(lod_extract), str(lod_path), entry, str(battle_def)])

	if not battle_from_json:
		out_battle = tmp / "defextract_battle"
		out_battle.mkdir(parents=True, exist_ok=True)
		_run([sys.executable, str(defextract), str(battle_def), str(out_battle)])

	# defextract_py3 names output from basename.lower() (see defextract → "%s.dir" % bn).
		stem_lc = battle_def.stem.lower()
		src_png_dir = out_battle / f"{stem_lc}.dir"
		src_json = out_battle / f"{stem_lc}.json"
		if not src_png_dir.is_dir() or not src_json.is_file():
			print(f"defextract output missing: {src_png_dir} / {src_json}", file=sys.stderr)
			return 1

		dest_png_dir = battle_dir / f"{basename}.dir"
		if dest_png_dir.exists():
			shutil.rmtree(dest_png_dir)
		shutil.copytree(src_png_dir, dest_png_dir)

		dest_json = battle_dir / f"{basename}.json"
		shutil.copy2(src_json, dest_json)
		_prune_stale_extracts(battle_dir, basename, clear_rife_done=True)
		rew = row.get("jsonPathRewrite") or {}
		f_p = rew.get("fromDirPrefix")
		t_p = rew.get("toDirPrefix")
		if f_p and t_p:
			_run([sys.executable, str(fix_script), str(dest_json), str(f_p), str(t_p)])

	extracted_map = _extract_map_source(row, map_dir=map_dir, tmp=tmp, map_basename=map_basename,
										defextract=defextract, lod_extract=lod_extract, inventory=inv)

	print(f"OK battle -> {dest_png_dir} + {dest_json}")
	if extracted_map:
		print(f"OK map -> {map_dir}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
