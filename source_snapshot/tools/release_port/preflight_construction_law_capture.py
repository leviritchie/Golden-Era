#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from live_probe_request import DEFAULT_BRIDGE, request_bridge


CITY_SCENES = {"cityHuman", "cityHuman2"}


def require_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SystemExit(f"{label}: expected object, got {type(value).__name__}")
    return value


def analyze(status_response: dict[str, Any], town_response: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    notes: list[str] = []

    if status_response.get("ok") is not True:
        errors.append("bridge status command did not return ok=true")
        return errors, notes
    if town_response.get("ok") is not True:
        errors.append("town_ui_state command did not return ok=true")
        return errors, notes

    status = require_dict(status_response.get("status"), "status response.status")
    town_ui = require_dict(town_response.get("townUi"), "town_ui_state response.townUi")

    if status.get("state") != "ready":
        errors.append(f"bridge state is {status.get('state')!r}, expected 'ready'")
    if status.get("profile") != "OfficialDeobf":
        errors.append(f"bridge profile is {status.get('profile')!r}, expected 'OfficialDeobf'")

    commands = status.get("commands")
    if not isinstance(commands, list) or "town_ui_state" not in commands:
        errors.append("bridge command list does not include town_ui_state")

    active_scene = town_ui.get("activeScene")
    if active_scene not in CITY_SCENES:
        errors.append(f"activeScene is {active_scene!r}, expected one of {sorted(CITY_SCENES)}")

    current_fraction = town_ui.get("currentFraction")
    cached_fraction = town_ui.get("cachedFraction")
    if not isinstance(current_fraction, str) or not current_fraction:
        errors.append("currentFraction is empty; no custom town faction context is active")
    elif not current_fraction.startswith("homm3_"):
        errors.append(f"currentFraction is {current_fraction!r}; expected a homm3_* custom faction")

    if isinstance(cached_fraction, str) and cached_fraction and cached_fraction != current_fraction:
        notes.append(f"cachedFraction {cached_fraction!r} differs from currentFraction {current_fraction!r}")

    if town_ui.get("cachedWrapperPresent") is not True:
        errors.append("cachedWrapperPresent is not true")
    if town_ui.get("cachedWrapperKnownType") is not True:
        errors.append("cachedWrapperKnownType is not true")
    if town_ui.get("currentCityDataNonNull") is not True:
        errors.append("currentCityDataNonNull is not true")
    if town_ui.get("currentCityConfigNonNull") is not True:
        errors.append("currentCityConfigNonNull is not true")

    layers = town_ui.get("layers")
    if isinstance(layers, dict):
        if layers.get("rootExists") is not True:
            notes.append("town layer root is not present; construction traces may still work, but town-layer visual context is absent")
    else:
        notes.append("town layer state was not an object")

    return errors, notes


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Preflight the live Golden Era bridge for construction-law packet capture readiness. "
            "This is read-only and does not promote packet proof state."
        )
    )
    parser.add_argument("--bridge", type=Path, default=DEFAULT_BRIDGE)
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=0.0,
        help="Poll until ready or until this many seconds elapse. Default is one immediate check.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=1.0,
        help="Delay between polls when --wait-seconds is used.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON instead of text.")
    args = parser.parse_args()

    attempts = 0
    deadline = time.monotonic() + max(args.wait_seconds, 0.0)
    status_response: dict[str, Any] = {}
    town_response: dict[str, Any] = {}
    errors: list[str] = []
    notes: list[str] = []
    while True:
        attempts += 1
        status_response = request_bridge(args.bridge, {"command": "status"}, args.timeout)
        town_response = request_bridge(args.bridge, {"command": "town_ui_state"}, args.timeout)
        errors, notes = analyze(status_response, town_response)
        if not errors:
            break
        if args.wait_seconds <= 0 or time.monotonic() >= deadline:
            break
        time.sleep(max(args.poll_seconds, 0.1))

    result = {
        "readyForConstructionCapture": not errors,
        "attempts": attempts,
        "errors": errors,
        "notes": notes,
        "status": status_response.get("status"),
        "townUi": town_response.get("townUi"),
    }

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("# Construction law capture preflight")
        print("")
        print(f"- Ready for construction capture: `{str(not errors)}`")
        print(f"- Attempts: `{attempts}`")
        if errors:
            print("")
            print("## Blocking errors")
            for error in errors:
                print(f"- {error}")
        if notes:
            print("")
            print("## Notes")
            for note in notes:
                print(f"- {note}")

    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
