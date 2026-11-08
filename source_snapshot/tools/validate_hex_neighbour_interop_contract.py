#!/usr/bin/env python3
"""Fail closed if GameSymbols Hex neighbour slots drift from live Hex.dll metadata."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

EXPECTED = [
    "_cfqh_k__BackingField",
    "_cfqi_k__BackingField",
    "_cfqj_k__BackingField",
    "_cfqk_k__BackingField",
    "_cfql_k__BackingField",
    "_cfqm_k__BackingField",
]


def fail(message: str) -> None:
    print(f"hex-neighbour-interop: {message}", file=sys.stderr)
    raise SystemExit(1)


def extract_hex_neighbour_field_members(symbols_text: str) -> list[str]:
    match = re.search(
        r"HexNeighbourFieldMembers\s*=\s*\{(.*?)\};",
        symbols_text,
        flags=re.DOTALL,
    )
    if not match:
        fail("GameSymbols.DirectStateLaws.HexNeighbourFieldMembers not found")
    names = re.findall(r'"([^"]+)"', match.group(1))
    if not names:
        fail("HexNeighbourFieldMembers is empty")
    return names


def extract_current_hex_neighbour_field_members(current_text: str) -> list[str] | None:
    """Current-port names from the generated GameSymbolScope.Members pin (owner Hex.Session.Battle.Hex)."""
    match = re.search(
        r'HexNeighbourFieldMembers\s*=\s*GameSymbolScope\.Members\("DirectStateLaws\.HexNeighbourFieldMembers",'
        r'\s*HexNeighbourFieldMembers,\s*0x[0-9A-Fa-f]+u,\s*new string\[\]\s*\{([^}]*)\},\s*"Hex\.Session\.Battle\.Hex"\);',
        current_text,
    )
    if not match:
        return None
    names = re.findall(r'"([^"]+)"', match.group(1))
    return names if len(names) == len(EXPECTED) else None


def native_field_needles(name: str) -> tuple[str, str]:
    native = "NativeFieldInfoPtr_" + name
    # Il2CppInterop emits NativeFieldInfoPtr__cfqh_k__BackingField for _cfqh_…
    alt = "NativeFieldInfoPtr__" + name.lstrip("_")
    if name.startswith("_") and name.endswith("_k__BackingField"):
        inner = name[1 : -len("_k__BackingField")]
        alt = f"NativeFieldInfoPtr__{inner}_k__BackingField"
    return native, alt


def missing_scope_names(data: bytes, names: list[str]) -> list[str]:
    missing = []
    for name in names:
        native, alt = native_field_needles(name)
        if not dll_has_utf16_or_ascii(data, native) and not dll_has_utf16_or_ascii(data, alt):
            missing.append(f"native field metadata for {name} ({native} / {alt})")
        elif not dll_has_utf16_or_ascii(data, name):
            missing.append(f"logical neighbour property name {name}")
    return missing


def dll_has_utf16_or_ascii(data: bytes, text: str) -> bool:
    ascii_needle = text.encode("ascii", errors="ignore")
    if ascii_needle and ascii_needle in data:
        return True
    utf16 = text.encode("utf-16-le")
    return utf16 in data


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument(
        "--hex-dll",
        default="",
        help="Path to live BepInEx interop Hex.dll (defaults under GameRoot/BepInEx/interop)",
    )
    parser.add_argument(
        "--game-root",
        default="",
        help="Active Golden Era install root used to locate Hex.dll when --hex-dll is omitted",
    )
    args = parser.parse_args()
    repo = Path(args.repo_root).resolve()
    symbols_path = (
        repo
        / "Heroes of Might & Magic Olden Era Playtest"
        / "OfflineUnlockMod"
        / "GameSymbols.cs"
    )
    if not symbols_path.is_file():
        fail(f"missing GameSymbols.cs: {symbols_path}")

    names = extract_hex_neighbour_field_members(symbols_path.read_text(encoding="utf-8"))
    if names != EXPECTED:
        fail(
            "HexNeighbourFieldMembers must be exactly live Hex.dll ring order "
            + str(EXPECTED)
            + f"; got {names}"
        )

    hex_dll = Path(args.hex_dll) if args.hex_dll else None
    if hex_dll is None or str(hex_dll) == ".":
        game_root = Path(args.game_root) if args.game_root else None
        if game_root is None or not game_root.is_dir():
            fail("--hex-dll or --game-root with BepInEx/interop/Hex.dll is required")
        hex_dll = game_root / "BepInEx" / "interop" / "Hex.dll"
    hex_dll = hex_dll.resolve()
    if not hex_dll.is_file():
        fail(f"missing Hex.dll: {hex_dll}")

    current_path = symbols_path.with_name("GameSymbolsCurrent.g.cs")
    if not current_path.is_file():
        fail(f"missing GameSymbolsCurrent.g.cs: {current_path}")
    current_names = extract_current_hex_neighbour_field_members(current_path.read_text(encoding="utf-8"))
    if current_names is None:
        fail("GameSymbolsCurrent.g.cs has no six-slot DirectStateLaws.HexNeighbourFieldMembers pin on Hex.Session.Battle.Hex")

    data = hex_dll.read_bytes()
    # Golden Era base slots live in GameSymbols.cs; the current port remaps them in the generated
    # scope. The live Hex.dll must carry one complete set, in ring order.
    scopes = {"base": EXPECTED, "current": current_names}
    missing_by_scope = {}
    matched_scope = None
    for scope, scope_names in scopes.items():
        missing = missing_scope_names(data, scope_names)
        if not missing:
            matched_scope = scope
            break
        missing_by_scope[scope] = missing
    if matched_scope is None:
        fail(
            "Hex.dll matches neither the Golden Era nor the current-port neighbour slots: "
            + "; ".join(f"{scope} scope missing {missing[0]}" for scope, missing in missing_by_scope.items())
        )

    # Guard against reintroducing dump.cs neighbour names into the live DLL expectation set.
    for banned in ("<cfnv>k__BackingField", "<cfnw>k__BackingField", "cfnv"):
        if banned in names:
            fail(f"banned dump.cs neighbour name in GameSymbols: {banned}")

    type_token = "Hex.Session.Battle.Hex"
    if not dll_has_utf16_or_ascii(data, type_token):
        # IL metadata often stores namespace and type name separately.
        if not (
            dll_has_utf16_or_ascii(data, "Hex.Session.Battle")
            and dll_has_utf16_or_ascii(data, native_field_needles(scopes[matched_scope][0])[1])
        ):
            fail(
                f"Hex.dll missing type evidence for {type_token} "
                "(full name or Hex.Session.Battle + the first neighbour slot's NativeFieldInfoPtr)"
            )

    print(f"validated hex neighbour interop against {hex_dll} ({matched_scope} scope slots)")


if __name__ == "__main__":
    main()
