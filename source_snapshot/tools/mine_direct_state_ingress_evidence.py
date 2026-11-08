#!/usr/bin/env python3
"""Thin read-only wrapper: request direct_state_ingress_evidence from the live probe bridge."""

from __future__ import annotations

import argparse
import json
import time
import uuid
from pathlib import Path
import sys


def fail(message: str) -> None:
    print(f"direct-state-ingress-mine: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--bridge-dir",
        type=Path,
        default=Path(
            r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
            r"\BepInEx\plugins\OfflineUnlockMod\live_probe_bridge"
        ),
    )
    parser.add_argument("--timeout-ms", type=int, default=15000)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("artifacts") / "direct_state_ingress_mining" / "latest_evidence_envelope.json",
    )
    args = parser.parse_args()
    bridge = args.bridge_dir
    token_path = bridge / "token.txt"
    status_path = bridge / "status.json"
    if not token_path.is_file() or not status_path.is_file():
        fail(f"bridge not ready under {bridge}")
    token = token_path.read_text(encoding="utf-8").strip()
    status = json.loads(status_path.read_text(encoding="utf-8-sig"))
    if not status.get("ok"):
        fail("bridge status not ok")
    req_id = str(uuid.uuid4())
    request = {
        "id": req_id,
        "token": token,
        "command": "direct_state_ingress_evidence",
    }
    inbox = bridge / "inbox"
    outbox = bridge / "outbox"
    inbox.mkdir(parents=True, exist_ok=True)
    request_path = inbox / f"{req_id}.json"
    response_path = outbox / f"{req_id}.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    deadline = time.time() + (args.timeout_ms / 1000.0)
    while time.time() < deadline:
        if response_path.is_file():
            payload = json.loads(response_path.read_text(encoding="utf-8-sig"))
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"ok": bool(payload.get("ok")), "out": str(args.out)}, indent=2))
            if not payload.get("ok"):
                raise SystemExit(1)
            return
        time.sleep(0.1)
    fail(f"timed out waiting for {response_path}")


if __name__ == "__main__":
    main()
