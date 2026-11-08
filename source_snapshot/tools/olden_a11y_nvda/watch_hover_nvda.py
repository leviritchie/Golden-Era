#!/usr/bin/env python3
"""Watch AI driver focus_latest.json (preferred) or hover_latest.json and speak via NVDA.

SR consumer only — does not read screen_dump.
Fails closed when NVDA / nvdaControllerClient.dll is unavailable.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
import time
from pathlib import Path


def load_nvda(dll_path: Path):
    if not dll_path.is_file():
        raise FileNotFoundError(f"nvdaControllerClient.dll missing: {dll_path}")
    dll = ctypes.WinDLL(str(dll_path))
    dll.nvdaController_speakText.argtypes = [ctypes.c_wchar_p]
    dll.nvdaController_speakText.restype = ctypes.c_ulong
    dll.nvdaController_testIfRunning.argtypes = []
    dll.nvdaController_testIfRunning.restype = ctypes.c_ulong
    return dll


def speak(dll, text: str) -> None:
    code = dll.nvdaController_testIfRunning()
    if code != 0:
        raise RuntimeError(f"NVDA not running (testIfRunning={code})")
    speak_code = dll.nvdaController_speakText(text)
    if speak_code != 0:
        raise RuntimeError(f"nvdaController_speakText failed ({speak_code})")


def focus_utterance(payload: dict) -> tuple[str, str]:
    """Return (fingerprint, text). Prefer speechSafe utterance."""
    if payload.get("speechSafe") is True:
        utterance = (payload.get("utterance") or "").strip()
        if utterance:
            return ("focus|" + utterance, utterance)
    # Nested focus envelope: { focus: { utterance, speechSafe, hover } }
    inner = payload.get("focus")
    if isinstance(inner, dict):
        return focus_utterance(inner)
    # Legacy hover path
    utterance = (payload.get("utterance") or "").strip()
    if utterance and payload.get("speechSafe") is not False:
        return ("utterance|" + utterance, utterance)
    hover = payload.get("hover") or {}
    label = (hover.get("label") or "").strip()
    if label and label.lower() not in ("new text", "text"):
        return (hover.get("fingerprint") or ("label|" + label), label)
    path = (hover.get("path") or "").strip()
    if path:
        return (hover.get("fingerprint") or ("path|" + path), path)
    lane = hover.get("lane") or "none"
    node = hover.get("node")
    if lane == "map" and node is not None:
        text = f"map node {node}"
        return (hover.get("fingerprint") or text, text)
    return ("", "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bridge-dir",
        required=True,
        help="Path to ai_driver_bridge (contains focus_latest.json / hover_latest.json)",
    )
    parser.add_argument(
        "--nvda-dll",
        default="",
        help="Path to nvdaControllerClient.dll (defaults to common NVDA install locations)",
    )
    parser.add_argument("--poll-ms", type=int, default=200)
    args = parser.parse_args()

    bridge = Path(args.bridge_dir)
    focus_path = bridge / "focus_latest.json"
    hover_path = bridge / "hover_latest.json"
    dll_candidates = []
    if args.nvda_dll:
        dll_candidates.append(Path(args.nvda_dll))
    dll_candidates.extend(
        [
            Path(r"C:\Program Files (x86)\NVDA\nvdaControllerClient64.dll"),
            Path(r"C:\Program Files (x86)\NVDA\nvdaControllerClient.dll"),
            Path(r"C:\Program Files\NVDA\nvdaControllerClient64.dll"),
            Path.cwd() / "nvdaControllerClient64.dll",
            Path.cwd() / "nvdaControllerClient.dll",
        ]
    )
    dll_path = next((p for p in dll_candidates if p.is_file()), None)
    if dll_path is None:
        print("FAIL: nvdaControllerClient.dll not found. Pass --nvda-dll.", file=sys.stderr)
        return 2

    try:
        dll = load_nvda(dll_path)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: could not load NVDA controller: {exc}", file=sys.stderr)
        return 2

    print(f"Watching {focus_path} (fallback {hover_path}) via {dll_path}")
    last_fp = None
    while True:
        path = focus_path if focus_path.is_file() else hover_path
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                time.sleep(args.poll_ms / 1000.0)
                continue
            fp, text = focus_utterance(payload)
            if fp and fp != last_fp and text:
                try:
                    speak(dll, text)
                    print(f"spoke: {text}")
                except Exception as exc:  # noqa: BLE001
                    print(f"speak failed closed: {exc}", file=sys.stderr)
                    return 3
                last_fp = fp
        time.sleep(args.poll_ms / 1000.0)


if __name__ == "__main__":
    raise SystemExit(main())
