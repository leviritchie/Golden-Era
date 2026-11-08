#!/usr/bin/env python3
"""Contract: tools/port_current/rebuild_core_from_vanilla.py (port phase 4).

Pins
- the rebuild layer order (and that every layer script exists);
- that no layer can reach a game install: every layer writes through {core} or a
  staged {game_root}, the overlay scratch is under {work}, and the continuity
  installer runs --skip-regenerate --no-mark-installed;
- the final StoryHub video dependency layer, its explicit prepared source root,
  and its sole exemption from the Core-change requirement;
- that the owning layers still expose the copy-safe modes the driver relies on;
- the driver's fail-closed behaviour, exercised on tiny fake Cores and fake layers:
  refused --out/--work under steamapps/common, refused modded --vanilla-core,
  refused non-empty --work, stop at the first failing layer, and a layer that
  exits 0 without changing Core.zip is a failure.

Static + behavioural (fake layers) only; it does not run the real rebuild.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DRIVER = REPO_ROOT / "tools" / "port_current" / "rebuild_core_from_vanilla.py"

EXPECTED_LAYER_ORDER = (
    "stronghold_city",
    "stronghold_heroes",
    "tower_overlay",
    "release_core_overlay",
    "homecoming_raw_translation",
    "brine_bell_scenario",
    "emberwatch_signal_scenario",
    "floodgate_gambit_scenario",
    "event_runtime_probe_map",
    "vanilla_stock_twins_event_dialogs",
    "roe_castle_continuity_weave",
    "campaign_video_dependencies",
)
CORE_ARG_LAYERS = {
    "stronghold_city", "stronghold_heroes", "tower_overlay", "release_core_overlay",
    "vanilla_stock_twins_event_dialogs",
}
REQUIRED_OWNER_FLAGS = {
    "stronghold_city": ("--core-only",),
    "stronghold_heroes": ("--core-only",),
    "tower_overlay": ("--core-lang",),
    "release_core_overlay": ("--work-dir", "--release-plugin-root", "--game-target"),
    "roe_castle_continuity_weave": ("--no-mark-installed", "--skip-regenerate"),
    "campaign_video_dependencies": (
        "--source-game-root", "--game-root", "--work", "--report", "--seven-zip",
    ),
}


def load_driver():
    spec = importlib.util.spec_from_file_location("rebuild_core_from_vanilla", DRIVER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_zip(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)


def static_checks(drv, errors: list[str]) -> None:
    if tuple(drv.LAYER_ORDER) != EXPECTED_LAYER_ORDER:
        errors.append(f"layer order drifted: {list(drv.LAYER_ORDER)} != {list(EXPECTED_LAYER_ORDER)}")
    no_core_change = [layer.name for layer in drv.LAYERS if not layer.core_change_required]
    if no_core_change != ["campaign_video_dependencies"]:
        errors.append(f"only campaign_video_dependencies may allow an unchanged Core: {no_core_change}")
    if '"--campaign-video-source-root"' not in DRIVER.read_text(encoding="utf-8"):
        errors.append("driver must expose an explicit --campaign-video-source-root option")
    if '"--campaign-video-seven-zip"' not in DRIVER.read_text(encoding="utf-8"):
        errors.append("driver must expose an explicit --campaign-video-seven-zip option")
    for layer in drv.LAYERS:
        if not layer.script.is_file():
            errors.append(f"{layer.name}: script missing {layer.script}")
            continue
        joined = " ".join(layer.args)
        if "steamapps" in joined.lower():
            errors.append(f"{layer.name}: argument names a game install: {joined}")
        if layer.name in CORE_ARG_LAYERS:
            if "{core}" not in layer.args:
                errors.append(f"{layer.name}: must write through {{core}}")
        elif "{game_root}" not in layer.args:
            errors.append(f"{layer.name}: must write through the staged {{game_root}}")
        source = layer.script.read_text(encoding="utf-8", errors="replace")
        for flag in REQUIRED_OWNER_FLAGS.get(layer.name, ()):
            if flag not in layer.args:
                errors.append(f"{layer.name}: driver must pass {flag}")
            if f'"{flag}"' not in source:
                errors.append(f"{layer.name}: owning script {layer.script.name} no longer defines {flag}")
    overlay = next((l for l in drv.LAYERS if l.name == "release_core_overlay"), None)
    if overlay is not None:
        for flag in ("--work-dir", "--release-plugin-root"):
            idx = overlay.args.index(flag) if flag in overlay.args else -1
            if idx < 0 or not overlay.args[idx + 1].startswith("{work}/"):
                errors.append(f"release_core_overlay: {flag} must point under {{work}}")
        # The rebuild is from the port's vanilla Core, so its target-pinned readbacks must be the
        # port build's (option A), never the Golden Era default.
        idx = overlay.args.index("--game-target") if "--game-target" in overlay.args else -1
        if idx < 0 or overlay.args[idx + 1] != "steam_25672315":
            errors.append("release_core_overlay: driver must pass --game-target steam_25672315")
    video = next((layer for layer in drv.LAYERS if layer.name == "campaign_video_dependencies"), None)
    if video is not None:
        expected = (
            "--source-game-root", "{video_source}",
            "--game-root", "{game_root}",
            "--work", "{work}/campaign_video_dependencies",
            "--report", "{work}/campaign_video_dependencies.json",
            "--seven-zip", "{seven_zip}",
        )
        if video.args != expected:
            errors.append(f"campaign_video_dependencies: unsafe or drifted arguments: {video.args}")


def expect_refusal(drv, argv: list[str], needle: str, label: str, errors: list[str]) -> None:
    rc = drv.main(argv)
    if rc == 0:
        errors.append(f"fail-closed: {label} was accepted")
        return
    work = Path(argv[argv.index("--work") + 1])
    report = work / "rebuild_report.json"
    if report.is_file():
        err = json.loads(report.read_text(encoding="utf-8")).get("error", "")
        if needle not in err:
            errors.append(f"fail-closed: {label} refused for the wrong reason: {err}")


def behaviour_checks(drv, errors: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="core_rebuild_contract_") as tmp_s:
        tmp = Path(tmp_s)
        vanilla = tmp / "vanilla.zip"
        write_zip(vanilla, {"DB/data.json": b"{}"})
        modded = tmp / "modded.zip"
        write_zip(modded, {"DB/data.json": b"{}", drv.MOD_MARKER_MEMBERS[0]: b"{}"})

        rc = drv.main(["--vanilla-core", str(vanilla), "--out",
                       "V:/SteamLibrary/steamapps/common/x/Core.zip", "--work", str(tmp / "w0")])
        if rc == 0:
            errors.append("fail-closed: --out under steamapps/common was accepted")
        expect_refusal(drv, ["--vanilla-core", str(modded), "--out", str(tmp / "o1.zip"), "--work", str(tmp / "w1")],
                       "already modded", "modded --vanilla-core", errors)
        busy = tmp / "w2"
        busy.mkdir()
        (busy / "leftover").write_text("x")
        rc = drv.main(["--vanilla-core", str(vanilla), "--out", str(tmp / "o2.zip"), "--work", str(busy)])
        if rc == 0:
            errors.append("fail-closed: non-empty --work was accepted")

        # run_layers with fake layers: change, fail, never-reached.
        scripts = tmp / "scripts"
        scripts.mkdir()
        change = scripts / "change.py"
        change.write_text(
            "import sys, zipfile\n"
            "with zipfile.ZipFile(sys.argv[1], 'a') as z: z.writestr('DB/fake_%s.json' % sys.argv[2], b'{}')\n",
            encoding="utf-8",
        )
        failing = scripts / "fail.py"
        failing.write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
        noop = scripts / "noop.py"
        noop.write_text("pass\n", encoding="utf-8")
        L = drv.Layer
        cases = (
            ("stop at first failure",
             (L("a", change, ("{core}", "a"), ""), L("b", failing, (), ""), L("c", change, ("{core}", "c"), "")),
             ["passed", "failed"]),
            ("unchanged Core is a failure",
             (L("a", change, ("{core}", "a"), ""), L("n", noop, (), ""), L("c", change, ("{core}", "c"), "")),
             ["passed", "failed"]),
        )
        for index, (label, layers, statuses) in enumerate(cases):
            work = tmp / f"run{index}"
            game_root = work / "staged_game_root"
            core = game_root / drv.STAGED_CORE_REL
            core.parent.mkdir(parents=True)
            write_zip(core, {"DB/data.json": b"{}"})
            report = {"layers": []}
            try:
                drv.run_layers(layers, core=core, game_root=game_root, work=work, report=report)
                errors.append(f"fail-closed: {label}: run_layers did not raise")
            except drv.RebuildError:
                pass
            got = [row.get("status") for row in report["layers"]]
            if got != statuses:
                errors.append(f"fail-closed: {label}: layer statuses {got} != {statuses}")

        # The final media-closure layer may validate/stage external dependencies without editing Core.
        video = scripts / "video.py"
        video.write_text(
            "import pathlib, sys\n"
            "args = sys.argv[1:]\n"
            "work = pathlib.Path(args[args.index('--work') + 1])\n"
            "report = pathlib.Path(args[args.index('--report') + 1])\n"
            "work.mkdir(parents=True, exist_ok=True)\n"
            "report.parent.mkdir(parents=True, exist_ok=True)\n"
            "report.write_text('{}', encoding='utf-8')\n",
            encoding="utf-8",
        )
        seven_zip = tmp / "7z.exe"
        seven_zip.write_bytes(b"test fixture placeholder; never executed")
        source_root = tmp / "prepared_source"
        source_core = source_root / drv.STAGED_CORE_REL
        source_core.parent.mkdir(parents=True)
        write_zip(source_core, {"DB/clips_info.json": b"{}"})
        closure = L(
            "campaign_video_dependencies",
            video,
            (
                "--source-game-root", "{video_source}", "--game-root", "{game_root}",
                "--work", "{work}/campaign_video_dependencies",
                "--report", "{work}/campaign_video_dependencies.json",
                "--seven-zip", "{seven_zip}",
            ),
            "test no-Core-change closure",
            core_change_required=False,
        )
        original_layers, original_order = drv.LAYERS, drv.LAYER_ORDER
        try:
            drv.LAYERS = (closure,)
            drv.LAYER_ORDER = (closure.name,)
            out = tmp / "video_out.zip"
            work = tmp / "video_run"
            rc = drv.main([
                "--vanilla-core", str(vanilla), "--out", str(out), "--work", str(work),
                "--campaign-video-source-root", str(source_root),
                "--campaign-video-seven-zip", str(seven_zip),
            ])
            if rc != 0 or not out.is_file():
                errors.append("video closure: a successful no-Core-change layer was rejected")
            rows = json.loads((work / "rebuild_report.json").read_text(encoding="utf-8")).get("layers", [])
            if len(rows) != 1 or rows[0].get("status") != "passed" or rows[0].get("coreChangeRequired") is not False:
                errors.append(f"video closure: report did not record allowed unchanged Core: {rows}")
            report_doc = json.loads((work / "rebuild_report.json").read_text(encoding="utf-8"))
            if report_doc.get("campaignVideoSevenZip") != str(seven_zip.resolve()):
                errors.append("video closure: report did not record the explicit 7-Zip path")

            resume_out = tmp / "video_resume_out.zip"
            resume_work = tmp / "video_resume_run"
            rc = drv.main([
                "--vanilla-core", str(vanilla), "--out", str(resume_out), "--work", str(resume_work),
                "--campaign-video-source-root", str(source_root), "--campaign-video-seven-zip", str(seven_zip),
                "--resume-from", closure.name, "--resume-core", str(vanilla),
            ])
            if rc != 0 or not resume_out.is_file():
                errors.append("diagnostic resume: final video layer rejected explicit source inputs")
            resume_report = json.loads((resume_work / "rebuild_report.json").read_text(encoding="utf-8"))
            if resume_report.get("diagnosticResume", {}).get("from") != closure.name:
                errors.append("diagnostic resume: existing resume marker was not preserved")

            # Missing or unprepared media-source roots must be rejected before any earlier real layer runs.
            marker = tmp / "expensive_layer_ran"
            expensive = scripts / "expensive.py"
            expensive.write_text(
                "from pathlib import Path\n"
                f"Path({str(marker)!r}).write_text('ran')\n",
                encoding="utf-8",
            )
            core_writer = L("expensive_core_layer", expensive, (), "test preflight")
            drv.LAYERS = (core_writer, closure)
            drv.LAYER_ORDER = (core_writer.name, closure.name)
            missing_source_work = tmp / "missing_source_run"
            rc = drv.main([
                "--vanilla-core", str(vanilla), "--out", str(tmp / "missing_source_out.zip"),
                "--work", str(missing_source_work),
            ])
            if rc == 0 or marker.exists():
                errors.append("video source preflight: missing --campaign-video-source-root reached a layer")
            marker.unlink(missing_ok=True)

            unprepared_root = tmp / "unprepared_source"
            unprepared_root.mkdir()
            rc = drv.main([
                "--vanilla-core", str(vanilla), "--out", str(tmp / "unprepared_out.zip"),
                "--work", str(tmp / "unprepared_run"), "--campaign-video-source-root", str(unprepared_root),
                "--campaign-video-seven-zip", str(seven_zip),
            ])
            if rc == 0 or marker.exists():
                errors.append("video source preflight: source without a prepared Core reached a layer")

            missing_seven_zip = tmp / "missing_7z.exe"
            rc = drv.main([
                "--vanilla-core", str(vanilla), "--out", str(tmp / "missing_7z_out.zip"),
                "--work", str(tmp / "missing_7z_run"), "--campaign-video-source-root", str(source_root),
                "--campaign-video-seven-zip", str(missing_seven_zip),
            ])
            if rc == 0 or marker.exists():
                errors.append("video source preflight: missing explicit 7-Zip binary reached a layer")
        finally:
            drv.LAYERS, drv.LAYER_ORDER = original_layers, original_order

        fixture_script = REPO_ROOT / "tools" / "port_current" / "test_campaign_video_dependencies.py"
        if not fixture_script.is_file():
            errors.append(f"campaign video dependency fixtures missing: {fixture_script}")
        else:
            fixture_root = tmp / "campaign_video_dependencies"
            t0 = time.perf_counter()
            try:
                proc = subprocess.run(
                    [
                        sys.executable, str(fixture_script), "--contract-fast",
                        "--scratch-root", str(fixture_root),
                    ],
                    cwd=str(REPO_ROOT),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=60,
                    check=False,
                )
            except subprocess.TimeoutExpired as ex:
                errors.append(f"campaign video dependency fixtures exceeded 60 seconds: {ex}")
            else:
                elapsed = time.perf_counter() - t0
                if proc.returncode != 0:
                    errors.append(
                        f"campaign video dependency fixtures failed after {elapsed:.3f}s:\n{proc.stdout[-12000:]}"
                    )
                else:
                    print(f"campaign video dependency fixtures OK ({elapsed:.3f}s; synthetic, no 7-Zip execution)")


def main() -> int:
    errors: list[str] = []
    if not DRIVER.is_file():
        print(f"core rebuild layer-order contract FAILED: missing {DRIVER}")
        return 1
    drv = load_driver()
    static_checks(drv, errors)
    behaviour_checks(drv, errors)
    if errors:
        print("core rebuild layer-order contract FAILED:")
        for err in errors:
            print("  - " + err)
        return 1
    print(f"core rebuild layer-order contract OK ({len(EXPECTED_LAYER_ORDER)} layers, fail-closed checks passed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
