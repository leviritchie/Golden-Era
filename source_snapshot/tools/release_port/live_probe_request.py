#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
import uuid
from pathlib import Path
from typing import Any


DEFAULT_BRIDGE = (
    Path("V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era")
    / "BepInEx"
    / "plugins"
    / "OfflineUnlockMod"
    / "live_probe_bridge"
)


def load_json_object(text: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{label}: invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"{label}: JSON must be an object")
    return value


def load_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {"command": args.command}
    if args.payload:
        payload.update(load_json_object(args.payload, "--payload"))
    if args.payload_file:
        payload.update(load_json_object(args.payload_file.read_text(encoding="utf-8-sig"), "--payload-file"))
    for item in args.set:
        if "=" not in item:
            raise SystemExit(f"--set value must be key=jsonValue, got {item!r}")
        key, raw_value = item.split("=", 1)
        if not key:
            raise SystemExit("--set key cannot be empty")
        try:
            payload[key] = json.loads(raw_value)
        except json.JSONDecodeError:
            payload[key] = raw_value
    return payload


def request_bridge(bridge: Path, payload: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
    token_path = bridge / "token.txt"
    inbox = bridge / "inbox"
    outbox = bridge / "outbox"
    if not token_path.exists():
        raise SystemExit(f"missing bridge token: {token_path}")
    if not inbox.is_dir():
        raise SystemExit(f"missing bridge inbox: {inbox}")
    if not outbox.is_dir():
        raise SystemExit(f"missing bridge outbox: {outbox}")

    request_id = str(uuid.uuid4())
    request = dict(payload)
    request["id"] = request_id
    request["token"] = token_path.read_text(encoding="utf-8-sig").strip()

    request_path = inbox / f"{request_id}.json"
    response_path = outbox / f"{request_id}.json"
    request_path.write_text(json.dumps(request, separators=(",", ":")), encoding="utf-8")

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if response_path.exists():
            return load_json_object(response_path.read_text(encoding="utf-8-sig"), str(response_path))
        time.sleep(0.1)
    try:
        request_path.unlink(missing_ok=True)
    except OSError as exc:
        raise SystemExit(f"timed out waiting for bridge response: {response_path}; failed to remove stale request {request_path}: {exc}") from exc
    raise SystemExit(f"timed out waiting for bridge response: {response_path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Send one exact request to the Golden Era live_probe_bridge. "
            "This is a request helper only; it does not compile probes, launch the game, or mutate state by itself."
        )
    )
    parser.add_argument("command", help="Bridge command, for example status, town_ui_state, or method_signatures.")
    parser.add_argument("--bridge", type=Path, default=DEFAULT_BRIDGE)
    parser.add_argument("--payload", default="", help="JSON object merged into the request.")
    parser.add_argument("--payload-file", type=Path, default=None, help="JSON object file merged into the request.")
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="KEY=JSON",
        help="Set one request field. Values are parsed as JSON when possible, otherwise kept as strings.",
    )
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args()

    response = request_bridge(args.bridge, load_payload(args), args.timeout)
    print(json.dumps(response, indent=2, sort_keys=True))
    return 0 if response.get("ok") is not False else 1


if __name__ == "__main__":
    raise SystemExit(main())
