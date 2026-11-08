#!/usr/bin/env python3
"""Worker helpers for parallel raw_translation batch emit (Windows-spawn safe).

Incremental builds (``--skip-unchanged``) compare two things against the prior emit:

* the input stamp: tracked inputs (profile, manifest, source LOD, IR, alignment, substitution
  map, catalogs, Core.zip) and the emitter modules, hashed in the parent;
* the read closure: every repo file this worker process opened for reading while building
  (an audit hook installed before the emitter modules are imported) plus every repo module
  it imported, recorded per mission with its content digest. A file read through a
  process-level cache by an earlier mission of the same worker is still in the set, so the
  closure over-approximates; other missions' artifact roots are excluded so one mission's
  rebuild does not invalidate the rest.

A mission is skipped only when both match and the prior map exists; anything else rebuilds.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

_POC = Path(__file__).resolve().parent
_REPO_ROOT = _POC.parents[1]
EMIT_CONTRACT_ID = "raw_translation_emit_contract_v6_entrance_occupancy"
_EMITTER_STAMP_FILES = (
    "campaign_ocean.py",
    "campaign_placed_hero_payloads.py",
    "campaign_runtime_script.py",
    "campaign_victory.py",
    "campaign_starting_bonus.py",
    "core_zip_cache.py",
    "port_homecoming_poc.py",
    "exact_homm3_footprint.py",
    "build_homecoming_entity_substitution_map.py",
    "functional_emit_reservation.py",
    "homecoming_localization.py",
    "raw_translation/build_raw_translation_map.py",
    "raw_translation/visual_scenery_canon_postpass.py",
    "raw_translation/entrance_occupancy.py",
    "raw_translation/homm3_footprint_compatibility.py",
    "raw_translation/homm3_bank_remapping.py",
    "native_footprint_model.py",
    "raw_translation/gate_face_rotation.py",
    "approach_cell/surface_emit.py",
)
_INPUT_STAMP_NAME = "raw_translation_input_stamp.json"
_STAMP_SCHEMA = "homm3.raw_translation_input_stamp.v3"
_CORE_ZIP_ENV = "OLDEN_ERA_CORE_ZIP"

# (normcased absolute path) -> ((mtime_ns, size), sha256 hex). Per process.
_DIGEST_MEMO: dict[str, tuple[tuple[int, int], str]] = {}
_READ_PATHS: set[str] = set()
_READ_AUDIT_INSTALLED = False


def file_digest(path: Path) -> str | None:
    """sha256 of a file's bytes, memoised on (mtime_ns, size); None when missing."""
    key = os.path.normcase(os.path.abspath(path))
    try:
        stat = os.stat(key)
    except OSError:
        return None
    ident = (int(stat.st_mtime_ns), int(stat.st_size))
    cached = _DIGEST_MEMO.get(key)
    if cached is not None and cached[0] == ident:
        return cached[1]
    hasher = hashlib.sha256()
    with open(key, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(block)
    digest = hasher.hexdigest()
    _DIGEST_MEMO[key] = (ident, digest)
    return digest


def _read_audit(event: str, args: tuple[Any, ...]) -> None:
    if event != "open" or not args:
        return
    path, mode = args[0], (args[1] if len(args) > 1 else None)
    if isinstance(mode, str) and any(flag in mode for flag in "wax+"):
        return
    if isinstance(path, bytes):
        path = os.fsdecode(path)
    if isinstance(path, str):
        _READ_PATHS.add(os.path.normcase(os.path.abspath(path)))


def ensure_read_audit() -> None:
    """Record every file this process opens for reading (once per process)."""
    global _READ_AUDIT_INSTALLED
    if not _READ_AUDIT_INSTALLED:
        sys.addaudithook(_read_audit)
        _READ_AUDIT_INSTALLED = True


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("\\/") + os.sep)


def read_closure(*, own_root: Path, sibling_roots: list[str], exclude_roots: list[str]) -> dict[str, str]:
    """Repo files read or imported by this process, minus other missions' outputs."""
    repo = os.path.normcase(str(_REPO_ROOT))
    own = os.path.normcase(os.path.abspath(own_root))
    excluded = [os.path.normcase(os.path.abspath(r)) for r in exclude_roots if r]
    siblings = [os.path.normcase(os.path.abspath(r)) for r in sibling_roots]
    for root in siblings:
        if root != own and (_under(own, root) or _under(root, own)):
            raise ValueError(f"mission artifact roots nest: {own} / {root}")
    candidates = set(_READ_PATHS)
    for module in list(sys.modules.values()):
        module_file = getattr(module, "__file__", None)
        if isinstance(module_file, str) and module_file.endswith(".py"):
            candidates.add(os.path.normcase(os.path.abspath(module_file)))
    closure: dict[str, str] = {}
    for path in sorted(candidates):
        if not _under(path, repo) or "__pycache__" in path:
            continue
        if any(_under(path, root) for root in excluded):
            continue
        if any(root != own and _under(path, root) for root in siblings):
            continue
        if path.endswith(_INPUT_STAMP_NAME) or not os.path.isfile(path):
            continue
        digest = file_digest(Path(path))
        if digest is not None:
            closure[os.path.relpath(path, repo).replace(os.sep, "/")] = digest
    return closure


def closure_mismatch(closure: Any) -> str | None:
    """First recorded closure file whose content changed (or went missing); None when all match."""
    if not isinstance(closure, dict) or not closure:
        return "no read closure recorded"
    for rel, digest in closure.items():
        if file_digest(_REPO_ROOT / rel) != digest:
            return rel
    return None


def _hash_file(hasher: Any, path: Path, *, logical_name: str) -> None:
    hasher.update(b"\0")
    hasher.update(logical_name.encode("utf-8"))
    hasher.update(b"\0")
    digest = file_digest(path) if path.is_file() else None
    hasher.update(digest.encode("ascii") if digest else b"MISSING")


def compute_mission_input_stamp(
    *,
    poc_root: Path,
    mission: Any,
    profile_path: Path,
    manifest_path: Path | None = None,
    source_lod_path: Path | None = None,
    core_zip_path: Path | None = None,
    enable_homm3_footprint_compatibility: bool = False,
    enable_homm3_bank_remapping: bool = False,
) -> str:
    hasher = hashlib.sha256()
    hasher.update(EMIT_CONTRACT_ID.encode("utf-8"))
    hasher.update((
        "homm3_footprint_compatibility="
        + ("enabled" if enable_homm3_footprint_compatibility else "disabled")
    ).encode("ascii"))
    hasher.update((
        "homm3_bank_remapping="
        + ("enabled" if enable_homm3_bank_remapping else "disabled")
    ).encode("ascii"))
    tracked: list[tuple[str, Path]] = [("profile", profile_path)]
    if manifest_path is not None:
        tracked.append(("manifest", manifest_path))
    if source_lod_path is not None:
        tracked.append(("source-lod", source_lod_path))
    tracked.extend(
        (
            ("object-walk", mission.object_walk_path),
            ("object-port-manifest", mission.object_port_manifest_path),
            ("layered-ir", mission.layered_ir_path),
            ("alignment", mission.alignment_path),
            ("substitution-map", mission.substitution_path),
            ("core-catalog", mission.core_catalog_path),
            ("template-map", mission.template_map_path),
        )
    )
    if core_zip_path is not None:
        tracked.append(("core-zip", core_zip_path))
    for logical_name, path in tracked:
        _hash_file(hasher, path, logical_name=logical_name)
    for rel in _EMITTER_STAMP_FILES:
        _hash_file(hasher, poc_root / rel, logical_name=f"emitter:{rel}")
    return hasher.hexdigest()


def stamp_path_for_mission(mission: Any) -> Path:
    return mission.artifact_root / "raw_translation_map" / _INPUT_STAMP_NAME


def read_prior_stamp(mission: Any) -> dict[str, Any] | None:
    path = stamp_path_for_mission(mission)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def write_stamp(
    mission: Any,
    stamp: str,
    *,
    map_sid: str,
    closure: dict[str, str],
    build_wall_sec: float,
) -> None:
    path = stamp_path_for_mission(mission)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": _STAMP_SCHEMA,
                "missionId": mission.mission_id,
                "scenarioId": getattr(mission, "scenario_id", None),
                "mapSid": map_sid,
                "emitContractId": EMIT_CONTRACT_ID,
                "sha256": stamp,
                # Scheduling hint only (largest-first ordering); never part of the stamp.
                "buildWallSec": round(build_wall_sec, 2),
                "readClosure": closure,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def prior_build_wall_sec(mission: Any) -> float | None:
    """Wall time of the last build (stamp), else the emit report's phase total."""
    prior = read_prior_stamp(mission)
    if isinstance(prior, dict) and isinstance(prior.get("buildWallSec"), (int, float)):
        return float(prior["buildWallSec"])
    report = mission.artifact_root / "raw_translation_map" / "raw_translation_report.json"
    try:
        total = (json.loads(report.read_text(encoding="utf-8")).get("phaseTimingsSec") or {}).get("total")
    except (OSError, json.JSONDecodeError):
        return None
    return float(total) if isinstance(total, (int, float)) else None


def init_worker(poc_root: str, frozen_core: str | None) -> None:
    """Pool initializer: audit reads, bind Core, import the emitter once per process."""
    ensure_read_audit()
    for path in (poc_root, str(Path(poc_root) / "raw_translation")):
        if path not in sys.path:
            sys.path.insert(0, path)
    if frozen_core:
        os.environ[_CORE_ZIP_ENV] = str(frozen_core)
    import build_campaign_alignment  # noqa: F401
    import build_raw_translation_map  # noqa: F401
    import generate_campaign_raw_translation_profile  # noqa: F401
    import port_homecoming_poc as poc

    if frozen_core:
        poc.OLDEN_CORE_ZIP = Path(frozen_core)


def refresh_profile_job(manifest: str, mission_id: str) -> str:
    """Regenerate one mission's raw_translation profile; returns the written path."""
    import generate_campaign_raw_translation_profile as raw_profile
    from campaign_mission import load_batch_manifest, mission_by_id

    batch = load_batch_manifest(Path(manifest))
    mission = mission_by_id(batch, mission_id)
    profile = raw_profile.build_raw_translation_profile(batch, mission)
    disk_profile = {key: value for key, value in profile.items() if not str(key).startswith("_")}
    out_path = raw_profile.raw_profile_path_for_mission(mission)
    raw_profile.write_json(out_path, disk_profile)
    return str(out_path)


def _assert_alignment_provenance(mission: Any) -> None:
    path = mission.alignment_path
    if not path.is_file():
        raise ValueError(f"alignment artifact missing for {mission.mission_id}: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read alignment artifact {path}: {exc}") from exc
    source = payload.get("source") if isinstance(payload, dict) else None
    if not isinstance(source, dict):
        raise ValueError(f"alignment artifact {path} has no source provenance")
    from h3c_mission_source import load_h3c_block

    source_block = load_h3c_block(mission.campaign_entry, mission.block_index)
    expected = {
        "missionId": mission.mission_id,
        "campaignEntry": mission.campaign_entry,
        "blockIndex": mission.block_index,
        "sourceLodSha256": hashlib.sha256(source_block.lod_path.read_bytes()).hexdigest(),
        "sourceH3mSha256": source_block.h3m_sha256,
        "layeredIrSha256": hashlib.sha256(mission.layered_ir_path.read_bytes()).hexdigest(),
        "objectManifestSha256": hashlib.sha256(
            mission.object_port_manifest_path.read_bytes()
        ).hexdigest(),
    }
    mismatches = {
        key: (expected_value, source.get(key))
        for key, expected_value in expected.items()
        if source.get(key) != expected_value
    }
    if mismatches:
        raise ValueError(
            f"stale alignment provenance for {mission.mission_id}: {mismatches}"
        )


def _assert_profile_mission_binding(
    *,
    profile: Any,
    profile_path: Path,
    mission: Any,
    manifest_path: Path,
    repo_root: Path,
) -> None:
    expected_profile_path = (
        mission.profile_path
        if getattr(mission, "profile_path", None) is not None
        else repo_root / "scenarios" / mission.scenario_id / "raw_translation.profile.json"
    ).resolve()
    if profile_path.resolve() != expected_profile_path:
        raise ValueError(
            f"profile path {profile_path} is not the manifest profile {expected_profile_path}"
        )
    if profile.scenario_id != mission.scenario_id:
        raise ValueError(
            f"profile scenarioId {profile.scenario_id!r} does not match "
            f"mission {mission.mission_id} scenarioId {mission.scenario_id!r}"
        )
    if profile.map_sid != mission.map_sid:
        raise ValueError(
            f"profile mapSid {profile.map_sid!r} does not match "
            f"mission {mission.mission_id} mapSid {mission.map_sid!r}"
        )
    if profile.output_subdir != "raw_translation_map":
        raise ValueError(
            f"profile {profile_path} must emit raw_translation_map, got "
            f"{profile.output_subdir!r}"
        )
    path_checks = (
        ("artifactRoot", profile.artifact_root, mission.artifact_root),
        ("inputs.alignment", profile.alignment_path, mission.alignment_path),
        ("inputs.substitutionMap", profile.substitution_path, mission.substitution_path),
        ("inputs.coreCatalog", profile.core_catalog_path, mission.core_catalog_path),
        ("inputs.templateMap", profile.template_map_path, mission.template_map_path),
    )
    for label, actual, expected in path_checks:
        if not _same_path(actual, expected):
            raise ValueError(
                f"profile {label} {actual} is not bound to mission value {expected}"
            )
    recorded_manifest = getattr(profile, "batch_manifest_path", None)
    if recorded_manifest is None or not _same_path(recorded_manifest, manifest_path):
        raise ValueError(
            f"profile {profile_path} is not bound to manifest {manifest_path}"
        )


def _same_path(left: Any, right: Any) -> bool:
    """Path identity on Windows is case-insensitive (V:/games and V:/Games are one tree)."""
    return os.path.normcase(str(Path(left).resolve())) == os.path.normcase(str(Path(right).resolve()))


def build_mission_job(job: dict[str, Any]) -> dict[str, Any]:
    """Process entrypoint: build one mission (optionally against frozen Core)."""
    started = time.perf_counter()
    ensure_read_audit()
    poc_root = Path(job["pocRoot"])
    raw_root = poc_root / "raw_translation"
    for path in (str(poc_root), str(raw_root)):
        if path not in sys.path:
            sys.path.insert(0, path)

    frozen = job.get("frozenCore")
    if frozen:
        os.environ[_CORE_ZIP_ENV] = str(frozen)

    import build_campaign_alignment as alignment_builder
    import build_raw_translation_map as raw_builder
    import object_property_namespaces as propns
    import port_homecoming_poc as poc
    from campaign_mission import load_batch_manifest, mission_by_id
    from h3c_mission_source import resolve_h3c_lod_path
    from scenario_profile import load_scenario_profile

    if frozen:
        # The Core cache keys on (path, mtime, size), so a worker that builds several
        # missions reuses one parse of the frozen snapshot and still drops it if the
        # snapshot changes.
        poc.OLDEN_CORE_ZIP = Path(frozen)

    batch = load_batch_manifest(Path(job["manifest"]))
    mission = mission_by_id(batch, job["missionId"])
    profile_path = Path(job["profilePath"]).resolve()
    profile = load_scenario_profile(profile_path)
    manifest_path = Path(job["manifest"]).resolve()
    _assert_profile_mission_binding(
        profile=profile,
        profile_path=profile_path,
        mission=mission,
        manifest_path=manifest_path,
        repo_root=poc.ROOT,
    )
    source_lod_path = resolve_h3c_lod_path(mission.campaign_entry).resolve()
    provided_source_lod = job.get("sourceLod")
    if provided_source_lod and Path(provided_source_lod).resolve() != source_lod_path:
        raise ValueError(
            f"worker sourceLod {provided_source_lod} is not canonical {source_lod_path}"
        )
    core_zip_path = (
        Path(frozen).resolve()
        if frozen
        else Path(poc.resolve_olden_core_zip()).resolve()
    )
    stamp = job.get("inputStamp")
    if not isinstance(stamp, str) or len(stamp) != 64 or any(
        char not in "0123456789abcdef" for char in stamp
    ):
        raise ValueError("worker inputStamp must be a lowercase SHA-256 hex string")
    expected_stamp = compute_mission_input_stamp(
        poc_root=poc_root,
        mission=mission,
        profile_path=profile_path,
        manifest_path=manifest_path,
        source_lod_path=source_lod_path,
        core_zip_path=core_zip_path,
        enable_homm3_footprint_compatibility=bool(
            job.get("enableHomm3FootprintCompatibility")
        ),
        enable_homm3_bank_remapping=bool(job.get("enableHomm3BankRemapping")),
    )
    if stamp != expected_stamp:
        raise ValueError(
            f"worker inputStamp does not match current inputs for {mission.mission_id}"
        )

    if job.get("skipUnchanged"):
        prior = read_prior_stamp(mission)
        _assert_alignment_provenance(mission)
        out_map = (
            mission.artifact_root
            / "raw_translation_map"
            / "maps"
            / f"{profile.map_sid}.map"
        )
        if (
            isinstance(prior, dict)
            and prior.get("schema") == _STAMP_SCHEMA
            and prior.get("missionId") == mission.mission_id
            and prior.get("scenarioId") == profile.scenario_id
            and prior.get("mapSid") == profile.map_sid
            and prior.get("emitContractId") == EMIT_CONTRACT_ID
            and prior.get("sha256") == stamp
            and out_map.is_file()
            and closure_mismatch(prior.get("readClosure")) is None
        ):
            return {
                "ok": True,
                "skipped": True,
                "missionId": mission.mission_id,
                "scenarioId": profile.scenario_id,
                "mapSid": profile.map_sid,
                "reason": "input_stamp_and_read_closure_unchanged",
                "workerPid": os.getpid(),
                "jobWallSec": round(time.perf_counter() - started, 2),
            }

    if not job.get("skipAlignmentRefresh"):
        alignment_builder.build_artifact_for_mission(mission)

    _assert_alignment_provenance(mission)
    manifest = raw_builder.generate_map(
        profile,
        enable_homm3_footprint_compatibility=bool(
            job.get("enableHomm3FootprintCompatibility")
        ),
        enable_homm3_bank_remapping=bool(job.get("enableHomm3BankRemapping")),
    )
    out_map = (Path(poc.ROOT) / manifest["output"]["map"]).resolve()
    container = poc.read_olden_map_container(out_map)
    map_data = container.chunks[1]
    if not isinstance(map_data, dict):
        raise ValueError(f"{manifest['mapSid']}: mapData chunk is not an object")
    propns.assert_marker_property_integrity(
        markers=map_data.get("markers") or [],
        properties=map_data.get("objectsProperties") or {},
        context=str(manifest["mapSid"]),
    )
    closure = read_closure(
        own_root=mission.artifact_root,
        sibling_roots=list(job.get("siblingArtifactRoots") or []),
        exclude_roots=[str(Path(frozen).parent)] if frozen else [],
    )
    wall = time.perf_counter() - started
    write_stamp(
        mission,
        stamp,
        map_sid=str(manifest["mapSid"]),
        closure=closure,
        build_wall_sec=wall,
    )
    return {
        "ok": True,
        "skipped": False,
        "workerPid": os.getpid(),
        "jobWallSec": round(wall, 2),
        "readClosureFiles": len(closure),
        "missionId": mission.mission_id,
        "scenarioId": profile.scenario_id,
        "mapSid": manifest["mapSid"],
        "output": manifest["output"],
        "gateFaceRotation": (manifest.get("postPasses") or {}).get("gateFaceRotation"),
        "envelopePaddingVoid": (manifest.get("envelopePaddingVoid") or {}).get("policy"),
    }
