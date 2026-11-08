#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from analyze_construction_law_capture import analyze as analyze_log
from analyze_construction_law_capture import read_log
from live_probe_request import DEFAULT_BRIDGE, request_bridge
from preflight_construction_law_capture import analyze as analyze_preflight


DEFAULT_GAME_ROOT = Path("V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era")


def now_label() -> str:
    return time.strftime("%H:%M:%S")


def run_preflight(bridge: Path, request_timeout: float) -> tuple[bool, dict[str, Any]]:
    status_response = request_bridge(bridge, {"command": "status"}, request_timeout)
    town_response = request_bridge(bridge, {"command": "town_ui_state"}, request_timeout)
    errors, notes = analyze_preflight(status_response, town_response)
    return not errors, {
        "readyForConstructionCapture": not errors,
        "errors": errors,
        "notes": notes,
        "status": status_response.get("status"),
        "townUi": town_response.get("townUi"),
    }


def emit_status(prefix: str, payload: dict[str, Any], json_mode: bool) -> None:
    if json_mode:
        print(json.dumps({"time": now_label(), "phase": prefix, **payload}, sort_keys=True), flush=True)
        return
    print(f"[{now_label()}] {prefix}", flush=True)
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        print("  blocking: " + "; ".join(str(error) for error in errors[:3]), flush=True)
    gaps = payload.get("proofGaps")
    if isinstance(gaps, list) and gaps:
        print("  gaps: " + "; ".join(str(gap) for gap in gaps[:3]), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only live monitor for construction-law packet capture. "
            "It waits for bridge/town readiness, then watches LogOutput.log for the construction packet checklist."
        )
    )
    parser.add_argument("--bridge", type=Path, default=DEFAULT_BRIDGE)
    parser.add_argument("--game-root", type=Path, default=DEFAULT_GAME_ROOT)
    parser.add_argument("--log", type=Path, default=None, help="Override LogOutput.log path or capture directory.")
    parser.add_argument("--wait-preflight-seconds", type=float, default=300.0)
    parser.add_argument("--wait-evidence-seconds", type=float, default=300.0)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--request-timeout", type=float, default=8.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    log_path = args.log if args.log is not None else args.game_root / "BepInEx" / "LogOutput.log"
    poll_seconds = max(args.poll_seconds, 0.25)

    preflight_deadline = time.monotonic() + max(args.wait_preflight_seconds, 0.0)
    last_preflight: dict[str, Any] = {}
    while True:
        ready, last_preflight = run_preflight(args.bridge, args.request_timeout)
        if ready:
            emit_status("preflight-ready", last_preflight, args.json)
            break
        emit_status("preflight-waiting", last_preflight, args.json)
        if time.monotonic() >= preflight_deadline:
            emit_status("preflight-timeout", last_preflight, args.json)
            return 1
        time.sleep(poll_seconds)

    evidence_deadline = time.monotonic() + max(args.wait_evidence_seconds, 0.0)
    last_analysis: dict[str, Any] = {}
    while True:
        last_analysis = analyze_log(read_log(log_path))
        if last_analysis.get("packetPromotionReady") is True:
            emit_status("evidence-ready", last_analysis, args.json)
            print("Construction packet mechanical checklist is satisfied. Human review is still required.", flush=True)
            return 0
        emit_status("evidence-waiting", last_analysis, args.json)
        if time.monotonic() >= evidence_deadline:
            emit_status("evidence-timeout", last_analysis, args.json)
            return 2
        time.sleep(poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
