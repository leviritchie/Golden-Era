#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_DIR = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"

DIRECT_LAW_RUNTIME_RE = re.compile(r"\bHomm3CustomFactionLawRuntime\.TryResolveActiveKnownCustomLaw\b")
DIRECT_PACKET_GATE_RE = re.compile(r"\bHomm3CustomLawPacketGate\.(?:IsGameplayAllowed|IsLawIndexGameplayAllowed)\b")
COMBINED_GUARD_RE = re.compile(r"\bHomm3CustomLawRuntimeGuard\.TryResolve(?:Allowed|Candidate)ActiveLaw\b")
HANDLER_ENTRY_RE = re.compile(r"\bHomm3CustomLawHandlerRegistry\.Try(?:Enter|Probe)Handler\b")

ALLOWED_INFRASTRUCTURE_FILES = {
    "Homm3CustomFactionLawRuntime.cs",
    "Homm3CustomLawPacketGate.cs",
    "Homm3CustomLawRuntimeGuard.cs",
    "Homm3CustomLawHandlerRegistry.cs",
    # Startup registration audit is infrastructure: it reports packet gates; it does not resolve active law context or mutate gameplay.
    "Homm3CustomLawGameplayRegistrationAudit.cs",
}

ALLOWED_DIAGNOSTIC_ONLY_FILES = {
    # Historical diagnostic hook name predates the stricter Diagnostics.cs suffix convention.
    # Keep this explicit so future gameplay hooks named *Hook.cs are still audited.
    "Homm3CounterstrokeDoctrineHook.cs",
    # Prefix-only battle-result diagnostic: it logs candidate active-law context for
    # runtime proof and does not authorize packet gameplay.
    "Homm3BattleResultSafeLawProbe.cs",
    # Registration-only owner cache infrastructure used by packet diagnostics/runtime gates.
    "Homm3BattleUnitLawOwnerRegistry.cs",
    # Brute-force committed-damage pilot owns packet-gate startup registration before active-law handler entry.
    "Homm3TrainingDamageLawRuntime.cs",
}


def is_allowed_diagnostic_or_infra(path: Path) -> bool:
    name = path.name
    if name in ALLOWED_INFRASTRUCTURE_FILES:
        return True
    if name in ALLOWED_DIAGNOSTIC_ONLY_FILES:
        return True
    if name.endswith("Diagnostics.cs"):
        return True
    if "Diagnostic" in name:
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audit custom law C# sources for direct active-law or packet-gate usage. "
            "Gameplay hooks should use Homm3CustomLawHandlerRegistry.TryEnterHandler when a named slot exists, "
            "or Homm3CustomLawRuntimeGuard.TryResolveAllowedActiveLaw only as a documented temporary bridge."
        )
    )
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []
    if not args.source_dir.exists():
        print(f"errors: ['missing source dir: {args.source_dir}']")
        return 1

    for path in sorted(args.source_dir.glob("*.cs")):
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        direct_law_runtime = bool(DIRECT_LAW_RUNTIME_RE.search(text))
        direct_packet_gate = bool(DIRECT_PACKET_GATE_RE.search(text))
        combined_guard = bool(COMBINED_GUARD_RE.search(text))
        handler_entry = bool(HANDLER_ENTRY_RE.search(text))
        if combined_guard and not handler_entry and not is_allowed_diagnostic_or_infra(path):
            warnings.append(
                f"{path.relative_to(ROOT)} uses Homm3CustomLawRuntimeGuard.TryResolveAllowedActiveLaw directly; prefer Homm3CustomLawHandlerRegistry.TryEnterHandler or document the missing handler slot"
            )
        if not direct_law_runtime and not direct_packet_gate:
            continue
        if is_allowed_diagnostic_or_infra(path):
            continue
        if not combined_guard:
            errors.append(
                f"{path.relative_to(ROOT)} uses direct law runtime/packet gate APIs without Homm3CustomLawRuntimeGuard.TryResolveAllowedActiveLaw"
            )
        else:
            warnings.append(
                f"{path.relative_to(ROOT)} uses direct law runtime/packet gate APIs; verify this is diagnostic-only or necessary alongside the combined guard"
            )

    print(f"errors: {errors}")
    if warnings:
        print(f"warnings: {warnings}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
