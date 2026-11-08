#!/usr/bin/env python3
"""Build raw_translation maps for campaign batch missions (profile-driven).

Regenerates raw_translation profiles from the batch manifest (centralized defaults +
per-mission rawTranslation overrides), then emits each map through the shared
raw_translation generator.

Performance knobs:
- ``--manifest`` is repeatable: every mission of every manifest goes through one worker
  pool, largest first (by the previous build's wall time), so no manifest waits on
  another's slowest mission.
- ``--jobs N``: parallel mission workers. Default: one per mission, capped by logical
  CPUs and by free RAM (memgate's 5 GB reserve, ~1.5 GB per worker). When ``N>1`` a
  frozen Core.zip snapshot is used so workers never race the live install zip, and the
  profile refresh runs in the same pool.
- ``--frozen-core``: always emit against a copied Core.zip snapshot (even with 1 job).
- ``--skip-unchanged``: skip missions whose input stamp and recorded read closure both
  match the prior emit (see campaign_raw_translation_batch_worker).

A failed mission stops the batch (or, with ``--continue-on-error``, is listed and the batch
exits non-zero). Nothing is retried or skipped silently.

Emit-side speedups (always on): process Core.zip JSON/object-config cache, deepcopy
instead of json round-trips, deterministic ``.map`` gzip (``mtime=0`` + sorted keys),
Lang overlay skip-unchanged writes, and ``phaseTimingsSec`` on the emit report.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

_POC = Path(__file__).resolve().parent
_RAW = _POC / "raw_translation"
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))
if str(_RAW) not in sys.path:
    sys.path.insert(0, str(_RAW))

import campaign_raw_translation_batch_worker as batch_worker  # noqa: E402

# Before any emitter import, so --skip-unchanged's read closure sees data read at import.
batch_worker.ensure_read_audit()

import generate_campaign_raw_translation_profile as raw_profile  # noqa: E402
import port_homecoming_poc as poc  # noqa: E402
from campaign_mission import (  # noqa: E402
    default_batch_manifest_path,
    load_batch_manifest,
)
from scenario_profile import load_scenario_profile  # noqa: E402
from h3c_mission_source import resolve_h3c_lod_path  # noqa: E402

# memgate (tools/homm3_def_retarget/memgate.py) keeps 5 GB free for other agents; a worker
# peaked at 1.15 GB RSS in the 2026-09-26 profile of the 87-mission batch.
MEMGATE_RESERVE_GB = 5.0
WORKER_RAM_BUDGET_GB = 1.5


def prepare_frozen_core_zip(*, live_core: Path, dest_dir: Path) -> Path:
    """Copy and validate Core.zip into dest_dir for read-only parallel emit."""
    if not live_core.is_file():
        raise FileNotFoundError(f"live Core.zip missing: {live_core}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "Core.zip"
    shutil.copy2(live_core, dest)
    with zipfile.ZipFile(dest, "r") as zf:
        names = zf.namelist()
    if not names:
        raise ValueError(f"frozen Core.zip is empty: {dest}")
    return dest.resolve()


def _configure_process_core_zip(core_zip: Path | None) -> None:
    if core_zip is None:
        return
    resolved = core_zip.resolve()
    os.environ[poc._OLDEN_CORE_ZIP_ENV] = str(resolved)
    poc.OLDEN_CORE_ZIP = resolved


def _auto_jobs(mission_count: int) -> tuple[int, dict[str, Any]]:
    try:
        import psutil
    except ImportError as exc:
        raise SystemExit("--jobs auto needs psutil to read free RAM; pass --jobs N explicitly") from exc
    free_gb = psutil.virtual_memory().available / 2**30
    cpus = os.cpu_count() or 1
    by_ram = int((free_gb - MEMGATE_RESERVE_GB) // WORKER_RAM_BUDGET_GB)
    if by_ram < 1:
        raise SystemExit(
            f"free RAM {free_gb:.1f} GB leaves no room for a worker above memgate's "
            f"{MEMGATE_RESERVE_GB} GB reserve; wait (memgate --wait) or pass --jobs 1"
        )
    jobs = max(1, min(cpus, by_ram, mission_count))
    return jobs, {"cpus": cpus, "freeRamGb": round(free_gb, 1), "jobsByRam": by_ram, "missions": mission_count}


def _resolve_jobs(raw_jobs: int | None, mission_count: int) -> tuple[int, dict[str, Any]]:
    if raw_jobs is None:
        return _auto_jobs(mission_count)
    if raw_jobs < 0:
        raise ValueError(f"--jobs must be >= 0, got {raw_jobs}")
    if raw_jobs == 0:
        return max(1, os.cpu_count() or 1), {"explicit": 0}
    return raw_jobs, {"explicit": raw_jobs}


def _select_missions(manifests: list[Path], wanted: list[str] | None) -> list[tuple[Path, Any]]:
    """(manifest, mission) in manifest order; mission ids must be unique across manifests."""
    selected: list[tuple[Path, Any]] = []
    seen: dict[str, Path] = {}
    for manifest in manifests:
        batch = load_batch_manifest(manifest)
        for mission in batch.missions:
            if mission.mission_id in seen:
                raise ValueError(
                    f"mission {mission.mission_id} is in both {seen[mission.mission_id]} and {manifest}"
                )
            seen[mission.mission_id] = manifest
            selected.append((manifest, mission))
    if wanted:
        missing = sorted(set(wanted) - set(seen))
        if missing:
            raise ValueError(f"unknown missionId values: {missing}")
        order = {mission_id: index for index, mission_id in enumerate(wanted)}
        selected = sorted(
            (row for row in selected if row[1].mission_id in order),
            key=lambda row: order[row[1].mission_id],
        )
    return selected


def main() -> int:
    t_start = time.perf_counter()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--manifest",
        type=Path,
        action="append",
        dest="manifests",
        help="Campaign batch manifest; repeat for several (default: Castle Good1+Good2).",
    )
    parser.add_argument(
        "--mission",
        action="append",
        dest="missions",
        help="missionId values to build (default: all missions in the manifests).",
    )
    parser.add_argument(
        "--skip-profile-refresh",
        action="store_true",
        help="Use on-disk raw_translation profiles without regenerating them.",
    )
    parser.add_argument(
        "--skip-alignment-refresh",
        action="store_true",
        help="Use on-disk olden_storage_alignment without rebuilding story/eventPolicy.",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Build remaining missions after a failure; exit non-zero if any failed.",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=None,
        help="Parallel mission workers (default: auto from CPUs and free RAM; 0 = CPU count).",
    )
    parser.add_argument(
        "--frozen-core",
        action="store_true",
        help="Emit against a copied Core.zip snapshot (implied when --jobs > 1).",
    )
    parser.add_argument(
        "--enable-homm3-footprint-compatibility",
        action="store_true",
        help="Run the isolated H3-versus-Olden footprint repair pass for candidate maps.",
    )
    parser.add_argument(
        "--enable-homm3-bank-remapping",
        action="store_true",
        help=(
            "Run the isolated HoMM3 creature-bank/Den remapping pass before "
            "footprint repair and visual scenery randomization."
        ),
    )
    parser.add_argument(
        "--skip-unchanged",
        action="store_true",
        help="Skip missions whose input stamp and read closure match the prior successful emit.",
    )
    args = parser.parse_args()
    manifests = [path.resolve() for path in (args.manifests or [default_batch_manifest_path()])]
    selected = _select_missions(manifests, args.missions)
    jobs, jobs_basis = _resolve_jobs(args.jobs, len(selected))
    use_frozen = bool(args.frozen_core or jobs > 1)
    print(f"raw_translation: {len(selected)} missions from {len(manifests)} manifest(s), jobs={jobs} {jobs_basis}")

    frozen_core: Path | None = None
    frozen_dir: Path | None = None
    pool: ProcessPoolExecutor | None = None
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    timings: dict[str, Any] = {}
    skipped = 0
    try:
        if use_frozen:
            live_core = poc.resolve_olden_core_zip()
            artifact_tmp = (_POC.parents[1] / "artifacts" / "campaign_port_poc").resolve()
            artifact_tmp.mkdir(parents=True, exist_ok=True)
            frozen_dir = Path(tempfile.mkdtemp(prefix="olden_frozen_core_", dir=str(artifact_tmp)))
            frozen_core = prepare_frozen_core_zip(live_core=live_core, dest_dir=frozen_dir)
            _configure_process_core_zip(frozen_core)
            print(f"raw_translation frozen Core.zip: {frozen_core} (jobs={jobs})")
        if jobs > 1:
            pool = ProcessPoolExecutor(
                max_workers=jobs,
                initializer=batch_worker.init_worker,
                initargs=(str(_POC), str(frozen_core) if frozen_core is not None else None),
            )

        t0 = time.perf_counter()
        if not args.skip_profile_refresh:
            if pool is None:
                refreshed = [
                    batch_worker.refresh_profile_job(str(manifest), mission.mission_id)
                    for manifest, mission in selected
                ]
            else:
                refreshed = list(
                    pool.map(
                        batch_worker.refresh_profile_job,
                        [str(manifest) for manifest, _ in selected],
                        [mission.mission_id for _, mission in selected],
                    )
                )
            for out_path in refreshed:
                print(f"raw_translation profile refreshed: {out_path}")
        timings["profileRefreshSec"] = round(time.perf_counter() - t0, 2)

        t0 = time.perf_counter()
        core_zip_for_stamp = (frozen_core or poc.resolve_olden_core_zip()).resolve()
        sibling_roots = [str(mission.artifact_root) for _, mission in selected]
        work_items: list[dict[str, Any]] = []
        for manifest, mission in selected:
            profile_path = raw_profile.raw_profile_path_for_mission(mission)
            source_lod_path = resolve_h3c_lod_path(mission.campaign_entry)
            stamp = batch_worker.compute_mission_input_stamp(
                poc_root=_POC,
                mission=mission,
                profile_path=profile_path,
                manifest_path=manifest,
                source_lod_path=source_lod_path,
                core_zip_path=core_zip_for_stamp,
                enable_homm3_footprint_compatibility=bool(args.enable_homm3_footprint_compatibility),
                enable_homm3_bank_remapping=bool(args.enable_homm3_bank_remapping),
            )
            work_items.append(
                {
                    "pocRoot": str(_POC),
                    "sourceLod": str(source_lod_path),
                    "manifest": str(manifest),
                    "missionId": mission.mission_id,
                    "profilePath": str(profile_path),
                    "inputStamp": stamp,
                    "skipAlignmentRefresh": bool(args.skip_alignment_refresh),
                    "skipUnchanged": bool(args.skip_unchanged),
                    "enableHomm3FootprintCompatibility": bool(args.enable_homm3_footprint_compatibility),
                    "enableHomm3BankRemapping": bool(args.enable_homm3_bank_remapping),
                    "frozenCore": str(frozen_core) if frozen_core is not None else None,
                    "siblingArtifactRoots": sibling_roots,
                    "priorWallSec": batch_worker.prior_build_wall_sec(mission),
                }
            )
        # Largest first: the longest mission starts at once instead of ending the batch alone.
        # Unknown cost sorts first too (it may be the largest); ties keep manifest order.
        work_items.sort(
            key=lambda item: -(item["priorWallSec"] if item["priorWallSec"] is not None else float("inf"))
        )
        timings["stampSec"] = round(time.perf_counter() - t0, 2)
        timings["prePoolSec"] = round(time.perf_counter() - t_start, 2)

        def record(item: dict[str, Any], row: dict[str, Any]) -> None:
            nonlocal skipped
            mission_id = item["missionId"]
            if row.get("skipped"):
                skipped += 1
                print(f"raw_translation SKIPPED {mission_id}: {row.get('reason')}")
                return
            print(f"raw_translation ok {mission_id}: {row.get('mapSid')} ({row.get('jobWallSec')}s)")
            results.append(
                {
                    "missionId": mission_id,
                    "scenarioId": row["scenarioId"],
                    "mapSid": row["mapSid"],
                    "output": row.get("output"),
                    "gateFaceRotation": row.get("gateFaceRotation"),
                    "envelopePaddingVoid": row.get("envelopePaddingVoid"),
                    "jobWallSec": row.get("jobWallSec"),
                    "workerPid": row.get("workerPid"),
                }
            )

        def fail(item: dict[str, Any], exc: BaseException) -> None:
            mission_id = item["missionId"]
            profile = load_scenario_profile(Path(item["profilePath"]))
            failures.append(
                {"missionId": mission_id, "mapSid": profile.map_sid, "error": f"{type(exc).__name__}: {exc}"}
            )
            print(f"raw_translation FAILED {mission_id}: {type(exc).__name__}: {exc}")

        t_pool = time.perf_counter()
        if pool is None:
            for item in work_items:
                print(f"raw_translation: building {item['missionId']}")
                try:
                    row = batch_worker.build_mission_job(item)
                except Exception as exc:
                    if not args.continue_on_error:
                        raise
                    fail(item, exc)
                    continue
                record(item, row)
        else:
            print(f"raw_translation: parallel emit jobs={jobs} missions={len(work_items)}")
            futures = {pool.submit(batch_worker.build_mission_job, item): item for item in work_items}
            for fut in as_completed(futures):
                item = futures[fut]
                try:
                    row = fut.result()
                except Exception as exc:
                    if not args.continue_on_error:
                        for pending in futures:
                            pending.cancel()
                        raise
                    fail(item, exc)
                    continue
                record(item, row)
        pool_wall = time.perf_counter() - t_pool
        busy = sum(float(row.get("jobWallSec") or 0.0) for row in results)
        timings["emitSec"] = round(pool_wall, 2)
        timings["workerUtilisation"] = round(busy / (pool_wall * jobs), 3) if pool_wall > 0 else None
    finally:
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)
        if frozen_dir is not None:
            shutil.rmtree(frozen_dir, ignore_errors=True)
    timings["totalSec"] = round(time.perf_counter() - t_start, 2)

    payload = {
        "ok": not failures,
        "jobs": jobs,
        "jobsBasis": jobs_basis,
        "frozenCore": use_frozen,
        "manifests": [str(path) for path in manifests],
        "skippedUnchanged": skipped,
        "timings": timings,
        "missions": results,
        "failures": failures,
    }
    print(json.dumps(payload, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
