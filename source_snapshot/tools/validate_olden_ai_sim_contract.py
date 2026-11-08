#!/usr/bin/env python3
"""Fail-closed contract for OldenAiSim + adventure weight bridge surface."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIM_DIR = ROOT / "tools" / "olden_ai_sim"
SIM_CSPROJ = SIM_DIR / "OldenAiSim.csproj"
MOD_DIR = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
GAMESYMBOLS = MOD_DIR / "GameSymbols.cs"
BRIDGE = MOD_DIR / "Homm3AdventureAiWeightBridge.cs"
LOOKAHEAD = MOD_DIR / "Homm3AdventureLookaheadState.cs"
LIVE_CAPTURE = MOD_DIR / "Homm3AiDriverBridge.AdventureCapture.cs"
PLUGIN = MOD_DIR / "Plugin.cs"
DOC = ROOT / "docs" / "ai_external_sim_weight_bridge.md"
MOD_CSPROJ = MOD_DIR / "OfflineUnlockMod.csproj"
FLAG_BRIDGE = "homm3_adventure_ai_weight_bridge.flag"
FLAG_APPLY = "homm3_adventure_ai_weight_apply.flag"
FORBIDDEN = ("HarmonyLib", "UnityEngine", "BepInEx", "Il2CppInterop", "using Hex")


def read(path: Path) -> str:
    if not path.exists():
        raise AssertionError(f"required file missing: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def require(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def validate_sim_isolation() -> None:
    require(SIM_CSPROJ.exists(), "OldenAiSim.csproj missing")
    skip_parts = {"tests", "gui", "tmp_gen_fixture"}
    cs_files = [p for p in SIM_DIR.rglob("*.cs") if not skip_parts.intersection(p.parts)]
    require(any(p.name == "AdventureSimulator.cs" for p in cs_files), "AdventureSimulator.cs missing")
    require(any(p.name == "AdventureSimModels.cs" for p in cs_files), "AdventureSimModels.cs missing")
    require(any(p.name == "AdventureSimScenarios.cs" for p in cs_files), "AdventureSimScenarios.cs missing")
    require(any(p.name == "AdventureSimStepper.cs" for p in cs_files), "AdventureSimStepper.cs missing")
    require(any(p.name == "OldenTileMp.cs" for p in cs_files), "OldenTileMp.cs missing")
    for path in cs_files:
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN:
            require(token not in text, f"{path.relative_to(ROOT)} must not reference {token}")
    models = read(SIM_DIR / "AdventureSimModels.cs")
    require("homm3.adventure.sim_state.v1" in models, "sim state schema missing")
    require("class AdventureSimResult" in models, "AdventureSimResult missing")
    require("class AdventureSimKnobs" in models, "AdventureSimKnobs missing")
    require("class AdventureSimTerrain" in models, "AdventureSimTerrain missing")
    require("AdventureSimActionKind" in models, "AdventureSimActionKind missing")
    require("HeroPowerMultiplier" in models, "fight knobs missing")
    require("ValuesVsMobsMultiplier" in models, "mob knobs missing")
    sim = read(SIM_DIR / "AdventureSimulator.cs")
    require("Evaluate(" in sim, "AdventureSimulator.Evaluate missing")
    stepper = read(SIM_DIR / "AdventureSimStepper.cs")
    require("TryStepForward" in stepper, "stepper TryStepForward missing")
    require("TryStepBack" in stepper, "stepper TryStepBack missing")
    require("WorldAt" in stepper, "stepper WorldAt missing")
    pathfinder = read(SIM_DIR / "AdventurePathfinder.cs")
    require("MoveCostIsAuthority" in pathfinder, "MoveCost authority missing")
    require("AddPortal" in pathfinder, "portal support missing")
    data = SIM_DIR / "data"
    require((data / "olden_tile_mp.v1.json").exists(), "committed tile MP snapshot missing")
    require((data / "olden_road_mp.v1.json").exists(), "committed road MP snapshot missing")
    require((data / "ai_world_sid_vocab.v1.json").exists(), "SID vocab reference missing")
    require((data / "clipped_fixture.aisim").exists(), "clipped fixture missing")
    vocab = read(data / "ai_world_sid_vocab.v1.json")
    compact = vocab.replace(" ", "").replace("\n", "").replace("\r", "")
    require('"wiredToBeam":false' in compact, "SID vocab must declare wiredToBeam false")
    gui_csproj = SIM_DIR / "gui" / "OldenAiSim.Gui.csproj"
    require(gui_csproj.exists(), "OldenAiSim.Gui.csproj missing")
    gui = read(gui_csproj)
    require("UseWindowsForms" in gui, "GUI must enable WinForms")
    require("OldenAiSim.csproj" in gui, "GUI must reference OldenAiSim")
    main = read(SIM_DIR / "gui" / "MainForm.cs")
    require("StepForward" in main, "GUI must support step forward")
    require("AdventureSimStepper" in main, "GUI must use AdventureSimStepper")
    csproj = read(SIM_CSPROJ)
    require("gui\\" in csproj or "gui/" in csproj, "library csproj must exclude gui")


def validate_mod_bridge() -> None:
    text = read(BRIDGE)
    lookahead = read(LOOKAHEAD)
    live_capture = read(LIVE_CAPTURE)
    require(FLAG_BRIDGE in text, f"bridge must mention {FLAG_BRIDGE}")
    require(FLAG_APPLY in text, f"bridge must mention {FLAG_APPLY}")
    require("AdventureSimulator.Evaluate" in text, "bridge must call AdventureSimulator.Evaluate")
    require("PostfixScoreTask" in text or "bjsj" in text, "bridge must hook task score")
    require("FAILED_CLOSED" in text, "bridge must fail closed")
    require("__result" in text, "bridge must be able to adjust score result when apply enabled")
    require("TryCaptureAdventureLiveWorld" in text, "weight bridge must invoke live world capture")
    require("TryValidateForSimulation" in text, "weight bridge must gate simulation on capture readiness")
    require("ClearBiases" in text, "weight bridge must clear stale biases on capture failure")
    require("MoveCostProvisional" in text, "weight bridge must expose provisional move-cost gate")
    require("EnsureHeroForSim" not in text, "placeholder hero injection is forbidden")
    require("WeightApplyFlag" in text or FLAG_APPLY in text, "apply gate required")
    registered = list(re.finditer(r"_registered\s*=\s*true\s*;", text))
    require(len(registered) == 1, "bridge must set _registered=true exactly once")
    gs = read(GAMESYMBOLS)
    require("TaskScorerTypeHints" in gs or '"ffe"' in gs, "GameSymbols must hint ffe task scorer")
    require("ScoreTask" in gs or "bjsj" in gs, "GameSymbols must hint bjsj")
    require("LiveMapSizeXMembers" in gs and "LiveMapTilesMembers" in gs, "GameSymbols must centralize live map members")
    require("LiveMapVoidTerrainTileCode" in gs, "GameSymbols must pin void terrain policy")
    require("DataObjectsAllMembers" in gs and "DataSquadsAllMembers" in gs, "GameSymbols must centralize session occupancy members")
    require("TryCaptureAdventureLiveWorld" in live_capture, "live capture adapter entry point missing")
    require("SetLiveMap" in lookahead, "lookahead must accept live map arrays")
    require("TryValidateForSimulation" in lookahead, "lookahead readiness validator missing")
    require("LiveOccupancyCaptured" in lookahead, "lookahead must track live occupancy capture")
    require("MoveCostProvisional" in lookahead, "lookahead must label provisional move cost")
    require("Pathable[i] = true" not in lookahead, "synthetic all-pathable fallback is forbidden")
    require("all-pathable" not in lookahead.lower(), "all-pathable fallback wording is forbidden")
    require("placeholder" not in text.lower(), "placeholder simulation data is forbidden")
    plugin = read(PLUGIN)
    require("Homm3AdventureAiWeightBridge.TryRegister" in plugin, "Plugin must register weight bridge")
    csproj = read(MOD_CSPROJ)
    require("OldenAiSim" in csproj, "OfflineUnlockMod must reference OldenAiSim")
    require("ValidateOldenAiSimContract" in csproj, "build must wire OldenAiSim contract validator")
    require("validate_olden_ai_sim_contract.py" in csproj, "build must invoke this validator")


def validate_docs() -> None:
    text = read(DOC)
    live_doc = read(ROOT / "docs" / "ai_sim_live_map_capture_handoff_2026-08-02.md")
    require("ffe.bjsj" in text, "doc must name ffe.bjsj")
    require("OldenAiSim" in text, "doc must name OldenAiSim")
    require("ask" in text.lower(), "doc must keep ask-when-uncertain rule")
    require("provisional" in text.lower(), "doc must label provisional MP/fight")
    require("step" in text.lower(), "doc must describe step-debug GUI")
    require("AdventureSimStepper" in text or "Step forward" in text, "doc must name stepper / step controls")
    require("live" in live_doc.lower() and "map" in live_doc.lower(), "live capture handoff must describe live map")
    require("failed_closed" in live_doc.lower(), "live capture handoff must document failed-closed apply behavior")
    require("provisional" in live_doc.lower(), "live capture handoff must label provisional movement cost")
    require("runtime" in live_doc.lower(), "live capture handoff must preserve runtime proof boundary")


def main() -> int:
    try:
        validate_sim_isolation()
        validate_mod_bridge()
        validate_docs()
    except AssertionError as ex:
        print(f"FAIL: {ex}", file=sys.stderr)
        return 1
    print("OK: olden AI sim + weight bridge contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
