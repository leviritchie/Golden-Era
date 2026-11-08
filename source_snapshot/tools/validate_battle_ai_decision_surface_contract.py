#!/usr/bin/env python3
"""Fail-closed static contract for battle AI decision surface symbols + probe.

Validates source/static evidence only. Runtime picker observation still requires
homm3_battle_ai_decision_probe.flag on Golden Era.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOD_DIR = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
GAMESYMBOLS = MOD_DIR / "GameSymbols.cs"
PROBE = MOD_DIR / "Homm3BattleAiDecisionProbe.cs"
PLUGIN = MOD_DIR / "Plugin.cs"
DOC = ROOT / "docs" / "ai_decision_logic_surface.md"
DUMMY_DYT = ROOT / "tmp" / "ai_decision_decomp" / "dyt.cs"
DUMMY_ECV = ROOT / "tmp" / "ai_decision_decomp" / "ecv.cs"
DUMMY_DYE = ROOT / "tmp" / "ai_decision_decomp" / "dye.cs"
FLAG = "homm3_battle_ai_decision_probe.flag"


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
    battle = extract_class_block(text, "BattleAiDecision")
    require('"dyt"' in battle, "BattleAiDecision.BrainTypeHints must include dyt")
    require('"dye"' in battle, "BattleAiDecision.ScorerTypeHints must include dye")
    require('"ecv"' in battle, "BattleAiDecision.ExecutorTypeHints must include ecv")
    brain_hints = re.search(r"BrainTypeHints\s*=\s*\{([^}]*)\}", battle, flags=re.S)
    require(brain_hints is not None, "BrainTypeHints missing")
    require('"dyn"' not in brain_hints.group(1), "BrainTypeHints must not include dyn")

    require_method_symbol(
        battle,
        "PickAction",
        "bavi",
        "mla",
        "kkj",
        "Method_Private_BattleAiAction_Unit_List_1_Unit_List_1_Unit_List_1_BattleAiAction_0",
    )
    require_method_symbol(battle, "ScoreUnitTurn", "bavn")
    require_method_symbol(battle, "LoadParams", "bavl")
    require_method_symbol(battle, "ExecuteAction", "bcau", "bcav")

    adventure = extract_class_block(text, "AdventureAiDecision")
    require('"fjl"' in adventure, "AdventureAiDecision day controller must include fjl")
    require_method_symbol(adventure, "OnStartDay", "OnStartDay")


def validate_probe() -> None:
    text = read(PROBE)
    require(
        f'DiagnosticFlag = "{FLAG}"' in text or f'DiagnosticFlag = @"{FLAG}"' in text,
        f"probe flag must be {FLAG}",
    )
    require("PostfixPickAction" in text, "probe must define PostfixPickAction")
    require("TryRegister" in text, "probe must define TryRegister")
    require("FAILED_CLOSED" in text, "probe must fail closed when unresolved")
    require("GameMember.TypesEquivalent" in text, "probe must use GameMember.TypesEquivalent")
    require(
        re.search(r"private static bool TypesEquivalent\s*\(", text) is None,
        "probe must not redefine TypesEquivalent",
    )
    # _registered = true only after RUNTIME_HOOK_REGISTERED success path
    registered_assigns = [
        m.start() for m in re.finditer(r"_registered\s*=\s*true\s*;", text)
    ]
    require(len(registered_assigns) == 1, "probe must assign _registered=true exactly once")
    success_idx = text.find('RUNTIME_HOOK_REGISTERED')
    require(success_idx > 0, "probe must emit RUNTIME_HOOK_REGISTERED")
    require(
        registered_assigns[0] < success_idx
        and registered_assigns[0] > text.rfind("_patched = patched", 0, success_idx),
        "probe must set _registered=true only after successful patch count",
    )
    # Read-only: no __result assignment / no SetValue on action fields in postfix body.
    postfix = re.search(
        r"private static void PostfixPickAction\([\s\S]*?\n\t\}",
        text,
    )
    require(postfix is not None, "PostfixPickAction body not found")
    body = postfix.group(0)
    require("__result =" not in body, "probe must not mutate __result")
    require("SetValue(" not in body, "probe must not mutate action fields")
    require("harmony.Patch" in text and "postfix:" in text, "probe must Harmony postfix only")
    require(
        re.search(r"harmony\.Patch\([^)]*prefix\s*:", text, flags=re.I) is None,
        "probe must not use Harmony prefix for policy",
    )
    require(
        "refusing silent patch without PickAction name hints" in text
        or "unhinted picker" in text,
        "probe must refuse unhinted picker patches",
    )


def validate_plugin_wiring() -> None:
    text = read(PLUGIN)
    require(
        "Homm3BattleAiDecisionProbe.TryRegister" in text,
        "Plugin.cs must register Homm3BattleAiDecisionProbe",
    )


def validate_doc() -> None:
    text = read(DOC)
    require("dyt" in text and "bavi" in text, "surface doc must name dyt.bavi")
    require("dye" in text, "surface doc must name dye scorers")
    require("ecv" in text, "surface doc must name ecv executor")
    require("runtime-unvalidated" in text.lower() or "runtime-unvalidated" in text,
            "surface doc must label runtime as unvalidated")
    require(FLAG in text, f"surface doc must mention {FLAG}")


def validate_dummydll_decomp() -> None:
    dyt = read(DUMMY_DYT)
    require(
        re.search(r"BattleAiAction\s+bavi\s*\(", dyt) is not None
        or re.search(r"\bbavi\b[\s\S]{0,80}BattleAiAction", dyt) is not None
        or "BattleAiAction bavi" in dyt
        or re.search(r"private BattleAiAction bavi\(", dyt) is not None,
        "DummyDll dyt.cs must declare picker bavi returning BattleAiAction",
    )
    require("BattleAiParams" in dyt, "DummyDll dyt.cs must reference BattleAiParams")
    # Signature shape: Unit + three Lists ending in BattleAiAction
    require(
        re.search(
            r"BattleAiAction\s+\w+\s*\(\s*Unit\s+\w+\s*,\s*List<Unit>\s+\w+\s*,\s*List<Unit>\s+\w+\s*,\s*List<BattleAiAction>\s+\w+\s*\)",
            dyt,
        )
        is not None,
        "DummyDll dyt.cs must contain picker signature (Unit, List<Unit>, List<Unit>, List<BattleAiAction>)",
    )

    ecv = read(DUMMY_ECV)
    require("bcau(BattleAiAction" in ecv or "bcau(BattleAiAction a, int b)" in ecv,
            "DummyDll ecv.cs must declare bcau(BattleAiAction, int)")
    dye = read(DUMMY_DYE)
    require("BattleAiParams" in dye, "DummyDll dye.cs must score with BattleAiParams")


def main() -> int:
    try:
        validate_gamesymbols()
        validate_probe()
        validate_plugin_wiring()
        validate_doc()
        validate_dummydll_decomp()
    except AssertionError as ex:
        print(f"FAIL: {ex}", file=sys.stderr)
        return 1
    print("OK: battle AI decision surface contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
