#!/usr/bin/env python3
"""Assemble the current mocap exports into a Unity test-only delivery.

Selection entries name raw GLB and lighting inputs. The explicit approved style
derives hash-pinned motion from those raw exports before texture replacement,
animation naming, and the delivery wrapper. Baseline export remains unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "homm3_silhouette_pose_fit"
if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))
from gpu_cascade_delivery import _read_glb, _write_glb, extract_glb_hexlit_pbr_maps, contract_name_for_group, contract_prefix_for_unit, SKIPPED_DEF_GROUPS  # noqa: E402
from showcase_prebaked_clip import write_glb_with_basecolor  # noqa: E402
from deliberate_motion_contract import lifecycle_role_for_clip_name  # noqa: E402
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from experiments.homm3_mocap_v2.delivery_style import MOTION_GAIN, PROFILE, derive, validate_derived
from experiments.homm3_mocap_v2.measure_move_stride import measure_move_stride

ORIENTATION = (0.0, -0.7071067811865476, 0.0, 0.7071067811865476)
SOURCE_ONLY_GROUPS = frozenset(SKIPPED_DEF_GROUPS | {6, 9, 10, 17, 18, 19})
SOURCE_ONLY_REASON = "raw DEF source evidence; no selected OE native clip contract"


def native_contract_for_raw_group(group_id: str, prefix: str = "Unit") -> str | None:
    if len(group_id) < 4 or group_id[0] != "g" or not group_id[1:3].isdigit() or group_id[3] != "_":
        raise ValueError(f"malformed raw group ID {group_id!r}")
    number = int(group_id[1:3])
    if number in SOURCE_ONLY_GROUPS:
        return None
    try:
        return contract_name_for_group(number, prefix)
    except KeyError as exc:
        raise ValueError(f"unknown raw group ID {group_id}") from exc


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _resolve(value: Any, base: Path, label: str) -> Path:
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ValueError(f"{label} must be a non-empty path")
    path = Path(value)
    if not path.is_absolute():
        path = base / path
        if not path.is_file() and (ROOT / str(value)).is_file():
            path = ROOT / str(value)
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} does not exist: {path}")
    return path


def _lighting_inputs(manifest: Path, base: Path) -> tuple[Path, Path]:
    data = _load(manifest)
    if not isinstance(data, dict):
        raise ValueError(f"lighting manifest is not an object: {manifest}")
    source = data.get("source")
    png = data.get("bakedTexture")
    if not png or not source:
        raise ValueError(f"{manifest}: requires exact source and bakedTexture fields")
    source_path = _resolve(source, manifest.parent, "lighting source mesh")
    png_path = _resolve(png, manifest.parent, "baked PNG")
    if data.get("sourceSha256") != sha256(source_path):
        raise ValueError(f"{manifest}: sourceSha256 mismatch")
    if data.get("bakedTextureSha256") != sha256(png_path):
        raise ValueError(f"{manifest}: bakedTextureSha256 mismatch")
    return source_path, png_path


def _attribute_signature(path: Path) -> tuple[Any, ...]:
    doc, blob = _read_glb(path)
    rows = []
    for mesh in doc.get("meshes") or []:
        for primitive in mesh.get("primitives") or []:
            attrs = primitive.get("attributes") or {}
            if "TEXCOORD_0" not in attrs:
                raise ValueError(f"{path}: primitive lacks TEXCOORD_0")
            acc = doc["accessors"][int(attrs["TEXCOORD_0"])]
            view = doc["bufferViews"][int(acc["bufferView"])]
            start = int(view.get("byteOffset", 0)) + int(acc.get("byteOffset", 0))
            stride = int(view.get("byteStride", 8))
            uv = tuple(struct.unpack_from("<2f", blob, start + i * stride) for i in range(int(acc["count"])))
            indices = tuple(range(len(uv)))
            if "indices" in primitive:
                acc = doc["accessors"][int(primitive["indices"])]
                view = doc["bufferViews"][int(acc["bufferView"])]
                start = int(view.get("byteOffset", 0)) + int(acc.get("byteOffset", 0))
                fmt = {5121: "B", 5123: "H", 5125: "I"}[int(acc["componentType"])]
                width = struct.calcsize(fmt)
                indices = tuple(struct.unpack_from("<" + fmt, blob, start + i * width)[0] for i in range(int(acc["count"])))
            if any(index >= len(uv) for index in indices):
                raise ValueError(f"{path}: UV/index accessor mismatch")
            rows.append(("triangleCornerUV", tuple(uv[index] for index in indices)))
    return tuple(rows)


def _wrap_orientation(path: Path) -> None:
    doc, blob = _read_glb(path)
    nodes = doc.get("nodes")
    scenes = doc.get("scenes")
    if not isinstance(nodes, list) or not scenes or not isinstance(scenes[0], dict):
        raise ValueError(f"{path}: malformed scene graph")
    if any(node.get("name") in {"Orientation", "MocapDeliveryRoot"} for node in nodes):
        raise ValueError(f"{path}: delivery wrapper already exists")
    old_roots = [int(v) for v in scenes[0].get("nodes") or []]
    if not old_roots:
        raise ValueError(f"{path}: scene has no roots")
    orientation = len(nodes)
    nodes.append({"name": "Orientation", "rotation": list(ORIENTATION), "children": old_roots})
    outer = len(nodes)
    nodes.append({"name": "MocapDeliveryRoot", "children": [orientation]})
    scenes[0]["nodes"] = [outer]
    _write_glb(path, doc, blob)


def _rename_single_animation(path: Path, name: str, *, static: bool = False) -> None:
    doc, blob = _read_glb(path)
    animations = doc.get("animations") or []
    if static:
        if len(animations) != 1:
            raise ValueError(f"{path}: idle source must contain exactly one animation")
        doc["animations"] = []
    else:
        if len(animations) != 1:
            raise ValueError(f"{path}: expected exactly one animation, got {len(animations)}")
        animations[0]["name"] = name
    _write_glb(path, doc, blob)


def _clip_rows(row: dict[str, Any]) -> list[dict[str, Any]]:
    clips = row.get("rawClips") or row.get("clips")
    if not isinstance(clips, list) or not clips:
        raise ValueError(f"{row.get('labSid')}: rawClips is required")
    out = []
    for clip in clips:
        if not isinstance(clip, dict):
            raise ValueError("clip row is not an object")
        source = clip.get("rawSourceGlb") or clip.get("sourceGlb") or clip.get("path")
        name = clip.get("contractName")
        if not isinstance(name, str) or not source:
            raise ValueError("each raw clip requires contractName and rawSourceGlb")
        out.append({**clip, "contractName": name, "rawSourceGlb": source})
    return out


def _assert_current_raw(path: Path, label: str) -> None:
    lowered = str(path).replace("\\", "/").lower()
    for token in ("prebaked", "fused_push", "engine_material"):
        if token in lowered:
            raise ValueError(f"{label} resolves to forbidden legacy/fused output: {path}")


def _resume_manifest_is_current(manifest: dict[str, Any], sid: str, selected: dict[str, Any],
    raw_manifest_path: Path, side_row: dict[str, Any], side_source: Path,
                                lighting_path: Path, lighting_source: Path, baked_png: Path) -> bool:
    """Trust an existing unit only when all current provenance still matches."""
    provenance = manifest.get("provenance") or {}
    if manifest.get("labSid") != sid or provenance.get("motionAuthority") != "current_mocap_v2":
        return False
    if str(provenance.get("sourceReportSha256") or "").lower() != str(selected.get("sourceReportSha256") or "").lower():
        return False
    if str(manifest.get("rawManifestSha256") or "").lower() != sha256(raw_manifest_path).lower():
        return False
    if str(provenance.get("lightingSourceGlbSha256") or "").lower() != sha256(lighting_source).lower():
        return False
    if str(provenance.get("bakedTextureSha256") or "").lower() != sha256(baked_png).lower():
        return False
    weights = manifest.get("skinWeights")
    if not isinstance(weights, dict):
        return False
    weight_path = Path(str(weights.get("path") or ""))
    if not weight_path.is_absolute() or not weight_path.is_file() or str(weights.get("sha256") or "").lower() != sha256(weight_path).lower():
        return False
    expected_side = side_source
    if not expected_side.is_file():
        return False
    if sha256(weight_path) != sha256(expected_side):
        return False
    if not Path(str(lighting_path)).is_file():
        return False
    for clip in manifest.get("clips") or []:
        output = Path(str(clip.get("output") or ""))
        raw = Path(str(clip.get("rawSourceGlb") or ""))
        if not output.is_absolute() or not output.is_file() or not raw.is_file():
            return False
        if str(clip.get("rawSourceGlbSha256") or "").lower() != sha256(raw).lower():
            return False
        if provenance.get("styleProfile"):
            try:
                validate_derived(raw, clip["contractName"], clip["motionStyle"])
            except (ValueError, KeyError, OSError):
                return False
            if provenance.get("motionGain") != MOTION_GAIN:
                return False
    stride = manifest.get("battleMoveStride") or {}
    if not isinstance(stride, dict) or float(stride.get("strideBindUnits") or 0) <= 0 or float(stride.get("cycleSeconds") or 0) <= 0:
        return False
    return True


def assemble(selection_path: Path, output: Path, *, artifact_root: Path | None = None,
             style_profile: str | None = None, lighting_root: Path | None = None) -> dict[str, Any]:
    if style_profile not in {None, PROFILE}:
        raise ValueError(f"unknown style profile {style_profile!r}")
    if output.exists() and not output.is_dir():
        raise FileExistsError(f"refusing to overwrite non-directory {output}")
    selection = _load(selection_path)
    if not isinstance(selection, dict) or selection.get("accepted") is not False:
        raise ValueError("selection must explicitly have accepted=false")
    units = selection.get("units")
    if not isinstance(units, list) or not units:
        raise ValueError("selection has no units")
    output.mkdir(parents=True, exist_ok=True)
    base = selection_path.parent
    artifact_base = (artifact_root or ROOT / "artifacts/homm3_mocap_v2/stronghold_ingame_test_v1").resolve()
    lighting_base = lighting_root.resolve() if lighting_root is not None else artifact_base
    raw_root = artifact_base / "raw"
    side_root = artifact_base / "skin_sidecars"
    raw_manifest_path = raw_root / "manifest.json"
    side_manifest_path = side_root / "manifest.json"
    raw_manifest = _load(raw_manifest_path)
    side_manifest = _load(side_manifest_path)
    raw_by_game = {str(item["gameSid"]): item for item in raw_manifest["units"]}
    side_by_game = {str(item["gameSid"]): item for item in side_manifest["sidecars"]}
    assembled = []
    try:
        for row in units:
            sid = str(row.get("labSid") or "")
            if not sid:
                raise ValueError("unit missing labSid")
            unit_dir = output / "units" / sid
            unit_dir.mkdir(parents=True, exist_ok=True)
            if sid in {str(item.get("labSid")) for item in assembled}:
                raise ValueError(f"duplicate assembled labSid {sid}")
            raw_row = raw_by_game.get(str(row.get("gameSid")))
            side_row = side_by_game.get(str(row.get("gameSid")))
            if raw_row is None or side_row is None:
                raise ValueError(f"{sid}: raw export and skin sidecar are required")
            lighting_value = row.get("lightingManifest")
            if lighting_root is not None and lighting_value:
                raise ValueError(f"{sid}: choose either lighting-root or explicit per-unit lightingManifest")
            lighting = (_resolve(lighting_value, base, f"{sid} lighting manifest") if lighting_value else _resolve(f"units/{sid}/lighting_manifest.json", lighting_base, f"{sid} lighting manifest"))
            lighting_source, baked_png = _lighting_inputs(lighting, base)
            if _load(lighting).get("styleProfile") != style_profile:
                raise ValueError(f"{sid}: lighting profile differs from requested delivery style")
            if style_profile:
                from experiments.homm3_mocap_v2.prepare_ingame_lighting import validate_styled_lighting
                validate_styled_lighting(_load(lighting))
            side_source = _resolve(side_root / str(side_row["path"]), base, f"{sid} skin sidecar")
            completed_manifest = unit_dir / "delivery_manifest.json"
            if completed_manifest.is_file():
                previous = _load(completed_manifest)
                clips_ok = all(Path(str(item.get("output", ""))).is_absolute() for item in previous.get("clips", []))
                master_ok = isinstance(previous.get("master"), dict) and Path(str(previous["master"].get("master", ""))).is_absolute()
                if previous.get("provenance", {}).get("styleProfile") == style_profile and isinstance(previous.get("skinWeights"), dict) and clips_ok and master_ok and _resume_manifest_is_current(previous, sid, row, raw_manifest_path, side_row, side_source, lighting, lighting_source, baked_png):
                    assembled.append(previous)
                    continue
                raise ValueError(f"{sid}: existing delivery_manifest.json is not current; refusing overwrite during active Unity run")
            prefix = contract_prefix_for_unit(sid)
            groups = raw_row.get("groups")
            if not isinstance(groups, list) or not groups:
                raise ValueError(f"{sid}: raw manifest has no groups")
            clips = []
            source_only = []
            for group in groups:
                gid = str(group.get("groupId") or "")
                name = native_contract_for_raw_group(gid, prefix)
                if name is None:
                    raw_source = _resolve(raw_root / str(group["glb"]), base, f"{sid} source-only raw group")
                    source_only.append({"groupId": gid, "reason": SOURCE_ONLY_REASON,
                                        "rawSourceGlb": str(raw_source), "rawSourceGlbSha256": sha256(raw_source)})
                    continue
                clips.append({"contractName": name, "rawSourceGlb": str(raw_root / str(group["glb"])), "frameCount": int(group["structuralCheck"]["frameCount"]), "fps": 12.0, "lifecycleRole": lifecycle_role_for_clip_name(name)})
            if not clips:
                raise ValueError(f"{sid}: raw manifest has no chosen contract groups")
            idle = next((c for c in clips if c["contractName"].endswith("_Idle")), None)
            if idle is None:
                raise ValueError(f"{sid}: raw manifest has no idle group")
            master_source = _resolve(idle["rawSourceGlb"], base, f"{sid} raw idle/master")
            _assert_current_raw(master_source, f"{sid} raw idle/master")
            if _attribute_signature(master_source) != _attribute_signature(lighting_source):
                raise ValueError(f"{sid}: lighting source triangle-corner UV/index attributes do not match raw master")
            if side_row.get("sourceGlbSha256") != sha256(master_source):
                raise ValueError(f"{sid}: sidecar source hash does not match raw idle")
            if side_row.get("sourceReportSha256") != row.get("sourceReportSha256"):
                raise ValueError(f"{sid}: sidecar/source report hash mismatch")
            copied_sidecar = unit_dir / "skin_weights.json"
            if copied_sidecar.exists():
                if sha256(copied_sidecar) != sha256(side_source):
                    raise FileExistsError(f"refusing to overwrite mismatched {copied_sidecar}")
            else:
                shutil.copyfile(side_source, copied_sidecar)
            clip_manifest = []
            for clip in clips:
                source = _resolve(clip["rawSourceGlb"], base, f"{sid} raw clip")
                _assert_current_raw(source, f"{sid} raw clip")
                if _attribute_signature(source) != _attribute_signature(master_source):
                    raise ValueError(f"{sid}: clip mesh/UV attributes differ from raw master")
                dest = unit_dir / f"{clip['contractName']}.glb"
                style = derive(source, unit_dir / "styled" / source.name, clip["contractName"]) if style_profile else None
                delivery_source = Path(style["derivedSourceGlb"]) if style else source
                write_glb_with_basecolor(delivery_source, dest, baked_png, neutralize_pbr=True)
                _rename_single_animation(dest, clip["contractName"])
                _wrap_orientation(dest)
                clip_manifest.append({
                    "contractName": clip["contractName"], "output": str(dest.resolve()),
                    "rawSourceGlb": str(source), "rawSourceGlbSha256": sha256(source),
                    "frameCount": int(clip.get("frameCount") or 0), "fps": float(clip.get("fps") or 0) / (style["durationMultiplier"] if style else 1.0),
                    "lifecycleRole": str(clip.get("lifecycleRole") or "cycle"),
                    **({"motionStyle": style} if style else {}),
                })
            move_rows = [row for row in clip_manifest if str(row.get("contractName") or "").endswith("_Move")]
            if len(move_rows) != 1:
                raise ValueError(f"{sid}: expected exactly one Move clip to measure stride, got {len(move_rows)}")
            battle_stride = measure_move_stride(Path(move_rows[0]["output"]))
            master = unit_dir / f"{sid}_master.glb"
            write_glb_with_basecolor(master_source, master, baked_png, neutralize_pbr=True)
            _rename_single_animation(master, f"{sid}_Idle", static=True)
            _wrap_orientation(master)
            pbr = extract_glb_hexlit_pbr_maps(master, unit_dir / "pbr", allow_missing_pbr_maps=False)
            assembled.append({
                "labSid": sid,
                "master": {"master": str(master.resolve()), "rawSourceGlb": str(master_source), "rawSourceGlbSha256": sha256(master_source)},
                "skinWeights": {"path": str(copied_sidecar.resolve()), "sha256": sha256(copied_sidecar)},
                "rawManifest": str(raw_manifest_path),
                "rawManifestSha256": sha256(raw_manifest_path),
                "pbr": {key: (str(Path(value.get("output")).resolve()) if isinstance(value, dict) and value.get("output") else str(value)) for key, value in pbr.items()},
                "clips": clip_manifest,
                "battleMoveStride": battle_stride,
                "sourceOnlyGroups": source_only,
                "provenance": {
                    "schema": "homm3_mocap_v2_delivery_provenance.v1", "motionAuthority": "current_mocap_v2",
                    **({"styleProfile": style_profile, "motionGain": MOTION_GAIN,
                        "derivedMotionAuthority": "approved-style-from-current-mocap-v2",
                        "lightingManifest": str(lighting), "lightingManifestSha256": sha256(lighting)} if style_profile else {}),
                    "motionInjected": False, "physicsSmoothApplied": False,
                    "sourceReport": row.get("sourceReport"), "sourceReportSha256": row.get("sourceReportSha256"),
                    "corpus": row.get("corpus"), "corpusSha256": row.get("corpusSha256"),
                    "selection": str(selection_path), "selectionSha256": sha256(selection_path),
                    "rawSourcePolicy": "explicit current raw exports only",
                    "lightingSourceGlb": str(lighting_source), "lightingSourceGlbSha256": sha256(lighting_source),
                    "bakedTexture": str(baked_png), "bakedTextureSha256": sha256(baked_png),
                    "skinWeights": str(copied_sidecar.resolve()), "skinWeightsSha256": sha256(copied_sidecar),
                    "warnings": list(row.get("qualityWarnings") or []),
                    "testDisposition": "user_requested_ingame_test; generated-artifact only; acceptance false",
                },
            })
    except Exception:
        raise
    manifests = []
    for item in assembled:
        path = output / "units" / item["labSid"] / "delivery_manifest.json"
        path.write_text(json.dumps(item, indent=2) + "\n", encoding="utf-8")
        manifests.append(str(path.relative_to(output)).replace("\\", "/"))
    fit_plan = selection.get("fitPlan") or selection.get("fit_plan")
    if not isinstance(fit_plan, dict):
        plan_rows = []
        for selected, item in zip(units, assembled):
            # Reconstruct group numbers from the raw manifest and the same
            # per-unit prefix used during clip assembly.  Do not infer them
            # from clip names with a hard-coded ``Unit`` prefix: Crusader and
            # future owned units may have a distinct contract namespace.
            raw_row = raw_by_game.get(str(selected.get("gameSid"))) or {}
            prefix = contract_prefix_for_unit(str(selected.get("labSid") or ""))
            groups = []
            for raw_group in raw_row.get("groups") or []:
                gid = str(raw_group.get("groupId") or "")
                if len(gid) >= 3 and gid[1:3].isdigit():
                    number = int(gid[1:3])
                    try:
                        if native_contract_for_raw_group(gid, prefix) is not None:
                            groups.append(number)
                    except ValueError:
                        raise
            if not groups:
                raise ValueError(f"{selected.get('labSid')}: no chosen groups for fit plan")
            plan_rows.append({"labSid": selected["labSid"], "choices": [{"groups": groups}], "source": "raw/manifest.json"})
        fit_plan = {"schema": "homm3_mocap_v2_ingame_delivery_fit_plan.v1", "accepted": False, "plan": plan_rows}
    (output / "fit_plan.json").write_text(json.dumps(fit_plan, indent=2) + "\n", encoding="utf-8")
    (output / "status.json").write_text(json.dumps({"schema": "stronghold-current-mocap-ingame-delivery-status-v1", "selection": str(selection_path), "selectionSha256": sha256(selection_path), "accepted": False, "units": [{"labSid": item["labSid"], "meshRole": "own_glb"} for item in assembled], "disposition": "user_requested_ingame_test"}, indent=2) + "\n", encoding="utf-8")
    (output / "assembly_report.json").write_text(json.dumps({"schema": "homm3_mocap_v2_ingame_delivery.v1", "accepted": False, "units": manifests, "warnings": ["candidate delivery only; no acceptance or runtime proof"]}, indent=2) + "\n", encoding="utf-8")
    return {"output": str(output), "units": len(assembled), "accepted": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--lighting-root", type=Path, help="Independent lighting preparation root; incompatible with per-unit lightingManifest")
    parser.add_argument("--style-profile", choices=[PROFILE])
    args = parser.parse_args()
    print(json.dumps(assemble(args.selection.resolve(), args.output.resolve(), artifact_root=args.artifact_root,
                              style_profile=args.style_profile, lighting_root=args.lighting_root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
