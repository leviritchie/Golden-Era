#!/usr/bin/env python3
"""Rebuild the mod's Core.zip from a VANILLA Core.zip (port phase 4).

vanilla COPY -> Core-writing layers in the order the installed Golden Era Core
was produced -> StoryHub video dependency closure -> --out. Layer order and the
reason each layer sits where it does are pinned by
tools/validate_core_rebuild_layer_order_contract.py; see
docs/port_to_current_game_version.md "Phase 4 status".

Safety contract (fail closed, no fallbacks):
- never writes to a game install: --out and --work may not sit under
  steamapps/common, and every layer runs against a staged game root under --work;
- --vanilla-core must be an unmodded Core (no mod-owned marker members) and is
  only ever read (its sha256 is re-checked after the run);
- --work must be new or empty and --out must not exist;
- a layer that exits non-zero stops the run; Core-writing layers must change the
  Core, while only the final video dependency layer may leave it unchanged. The
  report JSON records every layer run and the one that failed.

Proof tier of a successful run: generated artifact.  A rebuilt Core is not an
installed, startup, runtime or gameplay proof.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_SRC = REPO_ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
TOOLS = REPO_ROOT / "tools"
STAGED_CORE_REL = Path("HeroesOldenEra_Data") / "StreamingAssets" / "Core.zip"
STAGED_MAPS_REL = Path("HeroesOldenEra_Data") / "StreamingAssets" / "maps"
REPORT_SCHEMA = "homm3.port.core_rebuild_from_vanilla.v1"

# Members only the mod writes. Any of them in --vanilla-core means it is not vanilla.
MOD_MARKER_MEMBERS = (
    "DB/fractions/7_homm3_stronghold.json",
    "DB/fractions/10_homm3_tower.json",
    "DB/info/info_script_unit/units_homm3_stronghold.script",
    "DB/h3_campaign_placed_heroes_catalog.json",
)


@dataclasses.dataclass(frozen=True)
class Layer:
    name: str
    script: Path
    args: tuple[str, ...]  # {core} {game_root} {work} {repo} {video_source} {seven_zip} are substituted
    why: str
    core_change_required: bool = True


LAYERS: tuple[Layer, ...] = (
    Layer(
        "stronghold_city",
        PLUGIN_SRC / "generate_homm3_stronghold_city.py",
        ("--core", "{core}", "--core-only"),
        "Clones the dungeon faction into homm3_stronghold; owns units_homm3_stronghold.script and "
        "units_buffs_homm3_stronghold.json, which the release overlay never generates.",
    ),
    Layer(
        "stronghold_heroes",
        PLUGIN_SRC / "generate_homm3_stronghold_heroes.py",
        ("--core", "{core}", "--core-only"),
        "Owns the Warcries skill/ability rows the release overlay requires (it fails without them).",
    ),
    Layer(
        "tower_overlay",
        TOOLS / "apply_homm3_tower_overlay.py",
        ("--core", "{core}", "--core-lang"),
        "Seeds homm3_tower unit/city rows; the release overlay preserves tower quality-pass rows and "
        "reads tower unit views (death fade), so they must exist first. --core-lang puts the Tower Lang "
        "overlay into Core (the Golden Era Core got it from the overlay's old tower import).",
    ),
    Layer(
        "release_core_overlay",
        TOOLS / "release_port" / "apply_release_core_overlay.py",
        (
            "--release-core", "{core}",
            "--work-dir", "{work}/core_overlay_work",
            "--release-plugin-root", "{work}/staged_plugin_root",
            # Target-pinned readbacks (neutral tier bands) use the live 25672315 values (option A).
            "--game-target", "steam_25672315",
        ),
        "The custom-faction release overlay (neutrals, reward units, artifacts, biome pack) with its "
        "candidate validation.",
    ),
    Layer(
        "homecoming_raw_translation",
        TOOLS / "install_homecoming_raw_translation_map.py",
        ("--repo-root", "{repo}", "--game-root", "{game_root}"),
        "Homecoming raw_translation map Core overlay + DB/quickStart.json + homecoming_* manifests.",
    ),
    Layer(
        "brine_bell_scenario",
        TOOLS / "install_brine_bell_scenario.py",
        ("--repo-root", "{repo}", "--game-root", "{game_root}"),
        "BrineBell custom map squads/dialogs.",
    ),
    Layer(
        "emberwatch_signal_scenario",
        TOOLS / "install_emberwatch_signal_scenario.py",
        ("--repo-root", "{repo}", "--game-root", "{game_root}"),
        "EmberwatchSignal custom map squads/dialogs.",
    ),
    Layer(
        "floodgate_gambit_scenario",
        TOOLS / "install_floodgate_gambit_scenario.py",
        ("--repo-root", "{repo}", "--game-root", "{game_root}"),
        "FloodgateGambit custom map squads/dialogs.",
    ),
    Layer(
        "event_runtime_probe_map",
        TOOLS / "install_event_runtime_probe_map.py",
        ("--repo-root", "{repo}", "--game-root", "{game_root}"),
        "EventRuntimeProbe map squads/dialogs (present in the installed Golden Era Core).",
    ),
    Layer(
        "vanilla_stock_twins_event_dialogs",
        TOOLS / "install_vanilla_stock_event_dialog_overlay.py",
        (
            "--overlay-dir", "{repo}/artifacts/campaign_port_poc/vanilla_stock/twins/optional_core_overlay_for_events",
            "--core-zip", "{core}",
        ),
        "Twins event dialogs; the installed Golden Era Core carries only the twins set.",
    ),
    Layer(
        "roe_castle_continuity_weave",
        TOOLS / "install_roe_castle_continuity_weave.py",
        (
            "--repo-root", "{repo}", "--game-root", "{game_root}",
            "--all-hubs", "--skip-regenerate", "--no-mark-installed",
            # One hub at a time: bounds peak RAM (the 2026-09-30 merged run died with MemoryError).
            "--jobs", "1",
        ),
        "Last: all 20 StoryHub campaigns (Griffin Cliff included: install_griffin_cliff_custom_map.py "
        "refuses to displace the Good1 Story_maps mission, so it is not a layer), campaign squads/dialogs/heroes, placed-heroes catalog and "
        "map-load preflight members (seer hut, camp-fire aliases); it merges into the finished Core.",
    ),
    Layer(
        "campaign_video_dependencies",
        TOOLS / "port_current" / "stage_campaign_video_dependencies.py",
        (
            "--source-game-root", "{video_source}",
            "--game-root", "{game_root}",
            "--work", "{work}/campaign_video_dependencies",
            "--report", "{work}/campaign_video_dependencies.json",
            "--seven-zip", "{seven_zip}",
        ),
        "Stages the exact media and subtitle/locale inputs reached by target StoryHub PlayVideo closures, "
        "merging only required clip and English locale rows into Core.zip and copying existing files without encoding.",
        core_change_required=False,
    ),
)
LAYER_ORDER: tuple[str, ...] = tuple(layer.name for layer in LAYERS)


class RebuildError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_under_game_install(path: Path) -> bool:
    return "steamapps/common/" in str(path.resolve()).replace("\\", "/").lower()


def require_safe_output_paths(out: Path, work: Path) -> None:
    for label, path in (("--out", out), ("--work", work)):
        if is_under_game_install(path):
            raise RebuildError(f"{label} {path} is inside a Steam game install; the rebuild never writes there")
    repo = REPO_ROOT.resolve()
    if work.resolve() == repo or work.resolve() in repo.parents:
        raise RebuildError(f"--work {work} would contain the repo")
    if out.exists():
        raise RebuildError(f"--out {out} already exists; choose a new path")
    if work.exists() and any(work.iterdir()):
        raise RebuildError(f"--work {work} is not empty; choose a new or empty directory")


def require_vanilla_core(core: Path) -> None:
    if not core.is_file():
        raise RebuildError(f"--vanilla-core {core} does not exist")
    try:
        with zipfile.ZipFile(core) as zf:
            names = {n.replace("\\", "/") for n in zf.namelist()}
    except zipfile.BadZipFile as ex:
        raise RebuildError(f"--vanilla-core {core} is not a zip: {ex}") from ex
    if "DB/data.json" not in names:
        raise RebuildError(f"--vanilla-core {core} has no DB/data.json; not a Core.zip")
    found = [m for m in MOD_MARKER_MEMBERS if m in names]
    if found:
        raise RebuildError(f"--vanilla-core {core} is already modded (mod-owned members: {found})")


def layer_argv(layer: Layer, subst: dict[str, str]) -> list[str]:
    if not layer.script.is_file():
        raise RebuildError(f"layer {layer.name}: script missing: {layer.script}")
    return [sys.executable, str(layer.script)] + [a.format(**subst) for a in layer.args]


def run_layers(
    layers: tuple[Layer, ...],
    *,
    core: Path,
    game_root: Path,
    work: Path,
    report: dict[str, Any],
    video_source: Path | None = None,
    seven_zip: Path | None = None,
) -> None:
    """Run layers in order against the staged core. Raises RebuildError on the first failure."""
    subst = {"core": str(core), "game_root": str(game_root), "work": str(work), "repo": str(REPO_ROOT)}
    needs_video_source = any("{video_source}" in arg for layer in layers for arg in layer.args)
    if needs_video_source and video_source is None:
        raise RebuildError("campaign_video_dependencies requires explicit --campaign-video-source-root")
    needs_seven_zip = any("{seven_zip}" in arg for layer in layers for arg in layer.args)
    if needs_seven_zip and seven_zip is None:
        raise RebuildError("campaign_video_dependencies requires explicit --campaign-video-seven-zip")
    if video_source is not None:
        subst["video_source"] = str(video_source.resolve())
    if seven_zip is not None:
        subst["seven_zip"] = str(seven_zip.resolve())
    logs = work / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    for index, layer in enumerate(layers, 1):
        argv = layer_argv(layer, subst)
        before = sha256_file(core)
        log_path = logs / f"{index:02d}_{layer.name}.log"
        t0 = time.perf_counter()
        print(f"[rebuild] {index:02d}/{len(layers)} {layer.name}", flush=True)
        with log_path.open("w", encoding="utf-8") as log:
            proc = subprocess.run(argv, cwd=str(REPO_ROOT), env=env, stdout=log, stderr=subprocess.STDOUT)
        after = sha256_file(core) if core.is_file() else None
        row = {
            "layer": layer.name,
            "argv": argv,
            "returnCode": proc.returncode,
            "coreSha256Before": before,
            "coreSha256After": after,
            "coreChangeRequired": layer.core_change_required,
            "elapsedSec": round(time.perf_counter() - t0, 3),
            "log": str(log_path),
        }
        report["layers"].append(row)
        if proc.returncode != 0:
            row["status"] = "failed"
            raise RebuildError(f"layer {layer.name} exited {proc.returncode}; see {log_path}")
        if after is None:
            row["status"] = "failed"
            raise RebuildError(f"layer {layer.name} removed the staged Core.zip")
        if after == before and layer.core_change_required:
            row["status"] = "failed"
            raise RebuildError(f"layer {layer.name} exited 0 but left Core.zip unchanged; see {log_path}")
        row["status"] = "passed"


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vanilla-core", type=Path, required=True, help="Unmodded Core.zip (read only; copied).")
    ap.add_argument("--out", type=Path, required=True, help="Rebuilt Core.zip to write (must not exist).")
    ap.add_argument("--work", type=Path, required=True, help="New or empty scratch dir (staged game root, logs).")
    ap.add_argument(
        "--campaign-video-source-root",
        type=Path,
        help="Prepared, read-only donor game root containing Core.zip and source StoryHub video inputs.",
    )
    ap.add_argument(
        "--campaign-video-seven-zip",
        type=Path,
        help="Explicit 7-Zip executable for incremental Core-member updates; no default or download is used.",
    )
    ap.add_argument(
        "--resume-from",
        choices=LAYER_ORDER,
        help=(
            "Diagnostic only: start at this layer with --resume-core as its input instead of the vanilla "
            "copy. The report is marked diagnosticResume and is not a rebuild from vanilla."
        ),
    )
    ap.add_argument("--resume-core", type=Path, help="Input Core for --resume-from (read only; copied).")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    vanilla = args.vanilla_core.resolve()
    out = args.out.resolve()
    work = args.work.resolve()
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "vanillaCore": str(vanilla),
        "out": str(out),
        "work": str(work),
        "layerOrder": list(LAYER_ORDER),
        "layers": [],
        "proofTier": "generated artifact",
    }
    report_path: Path | None = None
    try:
        if (args.resume_from is None) != (args.resume_core is None):
            raise RebuildError("--resume-from and --resume-core go together")
        require_safe_output_paths(out, work)
        require_vanilla_core(vanilla)
        vanilla_sha = sha256_file(vanilla)
        report["vanillaCoreSha256"] = vanilla_sha
        layers = LAYERS
        source = vanilla
        if args.resume_from is not None:
            start = LAYER_ORDER.index(args.resume_from)
            layers = LAYERS[start:]
            source = args.resume_core.resolve()
            if not source.is_file():
                raise RebuildError(f"--resume-core {source} does not exist")
            report["diagnosticResume"] = {"from": args.resume_from, "inputCore": str(source),
                                          "inputCoreSha256": sha256_file(source)}
        needs_video_source = any(
            "{video_source}" in arg for layer in layers for arg in layer.args
        )
        video_source: Path | None = None
        if needs_video_source:
            if args.campaign_video_source_root is None:
                raise RebuildError(
                    "--campaign-video-source-root is required when campaign_video_dependencies is included"
                )
            video_source = args.campaign_video_source_root.resolve()
            source_core = video_source / STAGED_CORE_REL
            if not video_source.is_dir():
                raise RebuildError(f"--campaign-video-source-root {video_source} does not exist or is not a directory")
            if not source_core.is_file():
                raise RebuildError(
                    f"--campaign-video-source-root {video_source} has no prepared Core.zip at {source_core}"
                )
            try:
                with zipfile.ZipFile(source_core) as zf:
                    zf.getinfo("DB/clips_info.json")
            except zipfile.BadZipFile as ex:
                raise RebuildError(f"prepared source Core {source_core} is not a zip: {ex}") from ex
            except KeyError:
                raise RebuildError(
                    f"prepared source Core {source_core} has no DB/clips_info.json for StoryHub video closure"
                ) from None
            report["campaignVideoSourceRoot"] = str(video_source)
            report["campaignVideoSourceCore"] = str(source_core)
            if args.campaign_video_seven_zip is None:
                raise RebuildError(
                    "--campaign-video-seven-zip is required when campaign_video_dependencies is included"
                )
            seven_zip = args.campaign_video_seven_zip.resolve()
            if not seven_zip.is_file():
                raise RebuildError(
                    f"--campaign-video-seven-zip {seven_zip} does not exist or is not a file"
                )
            report["campaignVideoSevenZip"] = str(seven_zip)
        else:
            seven_zip = None
        work.mkdir(parents=True, exist_ok=True)
        report_path = work / "rebuild_report.json"
        game_root = work / "staged_game_root"
        core = game_root / STAGED_CORE_REL
        core.parent.mkdir(parents=True)
        (game_root / STAGED_MAPS_REL / "Story_maps").mkdir(parents=True)
        # release_core_overlay copies its plugin-side assets (biome runtime, law icons,
        # artifact icons) into --release-plugin-root after replacing the Core; the rebuild
        # only keeps the Core, so that root is scratch under --work.
        (work / "staged_plugin_root").mkdir(parents=True)
        shutil.copyfile(source, core)
        report["stagedGameRoot"] = str(game_root)
        run_layers(
            layers,
            core=core,
            game_root=game_root,
            work=work,
            report=report,
            video_source=video_source,
            seven_zip=seven_zip,
        )
        if sha256_file(vanilla) != vanilla_sha:
            raise RebuildError(f"--vanilla-core {vanilla} changed during the run")
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(core, out)
        report["outSha256"] = sha256_file(out)
        report["ok"] = True
        print(f"[rebuild] OK -> {out}")
        return 0
    except RebuildError as ex:
        report["ok"] = False
        report["error"] = str(ex)
        print(f"[rebuild] FAILED: {ex}", file=sys.stderr)
        return 1
    finally:
        if report_path is not None:
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(f"[rebuild] report: {report_path}")


if __name__ == "__main__":
    raise SystemExit(main())
