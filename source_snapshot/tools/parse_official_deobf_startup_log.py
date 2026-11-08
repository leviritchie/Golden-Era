#!/usr/bin/env python3
"""Parse BepInEx LogOutput.log for Golden Era startup gate failures."""
import re
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: parse_official_deobf_startup_log.py <LogOutput.log> <report.txt>", file=sys.stderr)
        return 1

    log_path = Path(sys.argv[1])
    report_path = Path(sys.argv[2])
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
    lines = text.splitlines()

    patterns = [
        ("PLUGIN_LOAD_ERROR", re.compile(r"Error loading \[HeroesOE Offline Unlock", re.I)),
        ("LOG_FATAL", re.compile(r"(?:Log(?:Fatal|Error)|\.LogFatal)\(|failed during startup", re.I)),
        ("GAME_MEMBER_MISS", re.compile(r"GameMember MISS:", re.I)),
        ("REGISTER_REQUIRED_FAIL", re.compile(r"RegisterRequired.*failed|Could not resolve required", re.I)),
        ("PORT_SMOKE", re.compile(r"Port-smoke profile active", re.I)),
        ("CHAINLOADER_OK", re.compile(r"Chainloader startup complete", re.I)),
        ("AUTO_LAUNCH_OK", re.compile(r"Started configured (?:single-player|hotseat) match", re.I)),
        ("AUTO_LAUNCH_FAIL", re.compile(r"TryStartConfiguredNewGame returned false|Failed to start configured new game", re.I)),
        ("MAP_LOAD", re.compile(r"Session: OnScenesLoaded|loadingScene", re.I)),
        ("STALE_HINT", re.compile(r"GameMember stale-hints:", re.I)),
    ]

    report: list[str] = []
    plugin_loaded = any("Loading [HeroesOE Offline Unlock" in ln for ln in lines)
    plugin_crashed = False

    for name, pat in patterns:
        hits = [ln for ln in lines if pat.search(ln)]
        if name in {"PLUGIN_LOAD_ERROR", "LOG_FATAL", "GAME_MEMBER_MISS", "REGISTER_REQUIRED_FAIL"} and hits:
            plugin_crashed = True
        report.append(f"[{name}] {len(hits)} hit(s)")
        for ln in hits[:8]:
            report.append("  " + ln.strip())
        if len(hits) > 8:
            report.append(f"  ... +{len(hits) - 8} more")

    summary = "STARTUP_OK" if plugin_loaded and not plugin_crashed else "STARTUP_FAIL"
    report.insert(0, summary)
    report.insert(1, f"log={log_path}")
    report_path.write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))
    return 0 if summary == "STARTUP_OK" else 2


if __name__ == "__main__":
    raise SystemExit(main())
