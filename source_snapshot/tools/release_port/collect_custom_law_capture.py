#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_ROOT = ROOT / "artifacts" / "custom_law_captures"


def copy_if_exists(source: Path, target_dir: Path, copied: list[dict[str, str]]) -> None:
    if not source.exists():
        copied.append({"source": str(source), "status": "missing"})
        return
    target = target_dir / source.name
    shutil.copy2(source, target)
    copied.append({"source": str(source), "target": str(target), "status": "copied"})


def write_text(path: Path, text: str) -> None:
    path.write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-root", type=Path, required=True, help="Game root containing BepInEx logs.")
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--scenario", required=True, help="Short scenario id, for example construction-cove-harbor-rush.")
    parser.add_argument("--profile", action="append", default=[], help="Diagnostic profile(s) enabled for this capture.")
    parser.add_argument("--notes", default="", help="Short human scenario notes.")
    parser.add_argument("--player-log", type=Path, help="Optional explicit Player.log path.")
    parser.add_argument("--extra-log", type=Path, action="append", default=[], help="Optional extra log/artifact path. May repeat.")
    args = parser.parse_args()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_scenario = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in args.scenario).strip("_")
    capture_dir = args.out_root / f"{timestamp}_{safe_scenario}"
    capture_dir.mkdir(parents=True, exist_ok=False)

    copied: list[dict[str, str]] = []
    bepinex = args.game_root / "BepInEx"
    copy_if_exists(bepinex / "LogOutput.log", capture_dir, copied)
    copy_if_exists(bepinex / "ErrorLog.log", capture_dir, copied)
    if args.player_log is not None:
        copy_if_exists(args.player_log, capture_dir, copied)
    for extra in args.extra_log:
        copy_if_exists(extra, capture_dir, copied)

    write_text(
        capture_dir / "scenario_notes.md",
        "# Custom Law Runtime Capture Notes\n\n"
        f"- Scenario: `{args.scenario}`\n"
        f"- Profiles: {', '.join(args.profile) if args.profile else '(not recorded)'}\n"
        f"- UTC captured: `{timestamp}`\n\n"
        "## Notes\n\n"
        f"{args.notes or '(none supplied)'}\n\n"
        "## Proof status\n\n"
        "- This bundle is raw evidence only.\n"
        "- Do not mark any surface proven until logs are reviewed against the activation packet.\n",
    )

    manifest = {
        "schemaVersion": 1,
        "scenario": args.scenario,
        "profiles": args.profile,
        "utcCaptured": timestamp,
        "gameRoot": str(args.game_root),
        "proofStatus": "raw-unreviewed",
        "copied": copied,
    }
    (capture_dir / "capture_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"custom law capture bundle: {capture_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
