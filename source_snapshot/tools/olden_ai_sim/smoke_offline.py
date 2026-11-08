#!/usr/bin/env python3
"""Offline smoke: build OldenAiSim, run unit tests, run contract validators.

Golden Era runtime apply remains a manual checklist (see docs/ai_external_sim_weight_bridge.md).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIM = ROOT / "tools" / "olden_ai_sim"
TESTS = SIM / "tests" / "OldenAiSim.Tests.csproj"
GUI = SIM / "gui" / "OldenAiSim.Gui.csproj"


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.check_call(cmd, cwd=str(ROOT))


def main() -> int:
    run(["dotnet", "build", str(SIM / "OldenAiSim.csproj"), "-c", "Release"])
    run(["dotnet", "test", str(TESTS), "-c", "Release", "--no-restore"])
    run(["dotnet", "build", str(GUI), "-c", "Release"])
    run(["python", str(ROOT / "tools" / "validate_olden_ai_sim_contract.py")])
    run(["python", str(ROOT / "tools" / "validate_adventure_ai_lookahead_surface_contract.py")])
    print("OK: offline olden AI sim smoke (library + tests + GUI)")
    print("GUI: dotnet run --project tools/olden_ai_sim/gui/OldenAiSim.Gui.csproj")
    print("GE checklist: deploy plugin + OldenAiSim.dll; touch")
    print("  homm3_adventure_ai_weight_bridge.flag")
    print("  (optional) homm3_adventure_ai_weight_apply.flag")
    print("then load a match with AI sides and inspect BepInEx log for")
    print("  'HoMM3 adventure AI weight bridge day'")
    print("  'HoMM3 adventure AI weight bridge score'")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as ex:
        print(f"FAIL: {ex}", file=sys.stderr)
        raise SystemExit(ex.returncode or 1)
