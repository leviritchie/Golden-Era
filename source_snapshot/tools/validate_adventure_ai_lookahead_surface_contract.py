#!/usr/bin/env python3
"""Fail-closed static contract for adventure AI lookahead surface (mark-centric v1).

Validates symbols, fork DTO, read-only OnStartDay probe, Plugin wiring, and docs.
Runtime observation still requires homm3_adventure_ai_decision_probe.flag on Golden Era.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOD_DIR = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
GAMESYMBOLS = MOD_DIR / "GameSymbols.cs"
PROBE = MOD_DIR / "Homm3AdventureAiDecisionProbe.cs"
STATE = MOD_DIR / "Homm3AdventureLookaheadState.cs"
PLUGIN = MOD_DIR / "Plugin.cs"
DOC_LOOKAHEAD = ROOT / "docs" / "ai_lookahead_requirements.md"
DOC_SURFACE = ROOT / "docs" / "ai_decision_logic_surface.md"
DUMMY_FJL = ROOT / "tmp" / "ai_lookahead_decomp" / "fjl.cs"
DUMMY_SIDE_AI = ROOT / "tmp" / "ai_lookahead_decomp" / "SideAiData.cs"
FLAG = "homm3_adventure_ai_decision_probe.flag"


def read(path: Path) -> str:
    if not path.exists():
        raise AssertionError(f"required file missing: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def extract_class_block(text: str, class_name: str) -> str:
    match = re.search(
        rf"internal static (?:partial )?class {re.escape(class_name)}\s*\{{",
        text,
    )
    require(match is not None, f"GameSymbols.{class_name} missing")
    start = match.end()
    depth = 1
    i = start
    while i < len(text) and depth > 0:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        i += 1
    require(depth == 0, f"GameSymbols.{class_name} brace mismatch")
    return text[start : i - 1]


def require_method_symbol(block: str, field_name: str, *required_hints: str) -> None:
    match = re.search(
        rf"MethodSymbol {re.escape(field_name)}\s*=\s*new\s*\((.*?)\);",
        block,
        flags=re.S,
    )
    require(match is not None, f"MethodSymbol {field_name} missing")
    body = match.group(1)
    for hint in required_hints:
        require(
            re.search(rf'"{re.escape(hint)}"', body) is not None,
            f"MethodSymbol {field_name} missing required hint {hint!r}",
        )


def validate_gamesymbols() -> None:
    text = read(GAMESYMBOLS)
    adventure = extract_class_block(text, "AdventureAiDecision")
    require('"fjl"' in adventure, "AdventureAiDecision day controller must include fjl")
    require('"fhk"' in adventure, "AdventureAiDecision locator hints must include fhk")
    require('"aiData"' in adventure, "AdventureAiDecision must hint Side.aiData")
    require('"markedCity"' in adventure, "AdventureAiDecision must hint markedCity")
    require('"makredEnemyCity"' in adventure, "AdventureAiDecision must keep engine typo makredEnemyCity")
    require('"cjwk"' in adventure, "AdventureAiDecision must hint day index cjwk")
    require('"cjwo"' in adventure, "AdventureAiDecision must hint strategy config cjwo")
    require_method_symbol(adventure, "OnStartDay", "OnStartDay", "hvs", "bro")


def validate_state() -> None:
    text = read(STATE)
    require("homm3.adventure.lookahead_state.v1" in text, "state schema version missing")
    require("Homm3AdventureMarkSnapshot" in text, "mark snapshot type missing")
    require("Clone()" in text, "state must be Clone-able")
    require("TryCaptureFromLiveSide" in text, "state must support live Side capture")
    require("TryFromLiveAiData" in text, "marks capture must fail closed via TryFromLiveAiData")
    require("visibilityMap" not in text, "omniscient v1 must not copy fog visibilityMap")
    require("SetValue(" not in text, "state capture must not mutate live fields via SetValue")
    require("no SideAiData mark fields resolved" in text, "marks capture must fail when zero fields resolve")


def validate_probe() -> None:
    text = read(PROBE)
    require(
        f'DiagnosticFlag = "{FLAG}"' in text or f'DiagnosticFlag = @"{FLAG}"' in text,
        f"probe flag must be {FLAG}",
    )
    require("PostfixOnStartDay" in text, "probe must define PostfixOnStartDay")
    require("TryRegister" in text, "probe must define TryRegister")
    require("FAILED_CLOSED" in text, "probe must fail closed when unresolved")
    require("Homm3AdventureLookaheadState.TryCaptureFromLiveSide" in text, "probe must capture mark-centric state")
    registered_assigns = [m.start() for m in re.finditer(r"_registered\s*=\s*true\s*;", text)]
    require(len(registered_assigns) == 1, "probe must assign _registered=true exactly once")
    success_idx = text.find("RUNTIME_HOOK_REGISTERED")
    require(success_idx > 0, "probe must emit RUNTIME_HOOK_REGISTERED")
    require(
        registered_assigns[0] < success_idx
        and registered_assigns[0] > text.rfind("_patched = patched", 0, success_idx),
        "probe must set _registered=true only after successful patch count",
    )
    postfix = re.search(r"private static void PostfixOnStartDay\([\s\S]*?\n\t\}", text)
    require(postfix is not None, "PostfixOnStartDay body not found")
    body = postfix.group(0)
    require("SetValue(" not in body, "probe must not mutate live fields")
    require("__result" not in body, "OnStartDay postfix must not touch __result")
    require("harmony.Patch" in text and "postfix:" in text, "probe must Harmony postfix only")
    require(
        re.search(r"harmony\.Patch\([^)]*prefix\s*:", text, flags=re.I) is None,
        "probe must not use Harmony prefix for policy",
    )
    require(
        "refusing silent patch" in text,
        "probe must refuse unhinted OnStartDay patches",
    )


def validate_plugin_wiring() -> None:
    text = read(PLUGIN)
    require(
        "Homm3AdventureAiDecisionProbe.TryRegister" in text,
        "Plugin.cs must register Homm3AdventureAiDecisionProbe",
    )


def validate_docs() -> None:
    lookahead = read(DOC_LOOKAHEAD)
    require("Mark-centric + omniscient" in lookahead or "mark-centric" in lookahead.lower(),
            "lookahead doc must lock mark-centric omniscient")
    require(FLAG in lookahead or "adventure_ai_decision_probe" in lookahead,
            "lookahead doc must mention adventure probe flag or probe name")
    surface = read(DOC_SURFACE)
    require("fjl.OnStartDay" in surface or "fjl" in surface, "surface doc must name fjl")
    require("Homm3AdventureAiDecisionProbe" in surface or FLAG in surface
            or "adventure" in surface.lower(),
            "surface doc must mention adventure probe surface")


def validate_dummydll() -> None:
    fjl = read(DUMMY_FJL)
    require("OnStartDay" in fjl, "DummyDll fjl.cs must declare OnStartDay")
    require("fhk cjwl" in fjl or "cjwl" in fjl, "DummyDll fjl.cs must hold locator field cjwl")
    side_ai = read(DUMMY_SIDE_AI)
    require("markedCity" in side_ai, "DummyDll SideAiData must declare markedCity")
    require("makredEnemyCity" in side_ai, "DummyDll SideAiData must keep makredEnemyCity typo")


def main() -> int:
    try:
        validate_gamesymbols()
        validate_state()
        validate_probe()
        validate_plugin_wiring()
        validate_docs()
        validate_dummydll()
    except AssertionError as ex:
        print(f"FAIL: {ex}", file=sys.stderr)
        return 1
    print("OK: adventure AI lookahead surface contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
