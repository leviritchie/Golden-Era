#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILES = ROOT / "custom_factions" / "custom_law_diag_profiles.json"


def load_profiles(path: Path) -> dict[str, list[str]]:
    doc = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(doc, dict) or doc.get("schemaVersion") != 1:
        raise ValueError(f"{path} must be a schemaVersion 1 profile document")
    profiles = doc.get("profiles")
    if not isinstance(profiles, dict):
        raise ValueError(f"{path} profiles must be an object")
    result: dict[str, list[str]] = {}
    for name, flags in sorted(profiles.items()):
        if not isinstance(name, str) or not name:
            raise ValueError("profile names must be non-empty strings")
        if not isinstance(flags, list) or any(not isinstance(flag, str) or not flag.endswith(".flag") for flag in flags):
            raise ValueError(f"profile {name!r} must contain only .flag strings")
        result[name] = sorted(set(flags))
    return result


def all_flags(profiles: dict[str, list[str]]) -> set[str]:
    flags: set[str] = set()
    for values in profiles.values():
        flags.update(values)
    return flags


def resolve_flags(profiles: dict[str, list[str]], profile_names: list[str]) -> set[str]:
    resolved: set[str] = set()
    for name in profile_names:
        if name not in profiles:
            raise ValueError(f"unknown profile {name!r}; available: {', '.join(sorted(profiles))}")
        resolved.update(profiles[name])
    return resolved


def apply_flags(plugin_root: Path, flags: set[str]) -> None:
    plugin_root.mkdir(parents=True, exist_ok=True)
    for flag in sorted(flags):
        (plugin_root / flag).write_text("", encoding="utf-8")


def clear_flags(plugin_root: Path, flags: set[str]) -> None:
    for flag in sorted(flags):
        path = plugin_root / flag
        if path.exists():
            path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("list", "apply", "clear"))
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--plugin-root", type=Path, help="OfflineUnlockMod plugin directory containing .flag files")
    parser.add_argument("--profile", action="append", default=[], help="Profile name. May be repeated.")
    parser.add_argument("--all-known", action="store_true", help="With clear, remove every known custom-law diagnostic flag.")
    args = parser.parse_args()

    profiles = load_profiles(args.profiles)
    if args.action == "list":
        for name, flags in sorted(profiles.items()):
            print(f"{name}: {', '.join(flags)}")
        return 0

    if args.plugin_root is None:
        print("error: --plugin-root is required for apply/clear", file=sys.stderr)
        return 1

    if args.all_known:
        if args.action != "clear":
            print("error: --all-known is only valid with clear", file=sys.stderr)
            return 1
        flags = all_flags(profiles)
    else:
        if not args.profile:
            print("error: at least one --profile is required unless using clear --all-known", file=sys.stderr)
            return 1
        flags = resolve_flags(profiles, args.profile)

    if args.action == "apply":
        apply_flags(args.plugin_root, flags)
        print(f"applied {len(flags)} flag(s) to {args.plugin_root}")
        return 0

    clear_flags(args.plugin_root, flags)
    print(f"cleared {len(flags)} known flag(s) from {args.plugin_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
