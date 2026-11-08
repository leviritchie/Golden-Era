#!/usr/bin/env python3
"""Fail-closed: AB/SoD VIDEO_INDEX_TO_CLIP must match CmpMovie.txt + NWC stem rules.

Pins the fw/pf abbreviation trap (Foolhardy Waywardness=fw, Playing with Fire=pf)
and HackAndSlash HSb stand-in without shifting later HS stems.
"""
from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "campaign_port_poc"))

from ab_sod_video_map import (  # noqa: E402
    HUB_STRIP_STEMS,
    VIDEO_INDEX_TO_CLIP,
    VIDEO_STEM_STANDINS,
    resolve_video_stem_for_clip,
)

DEFAULT_LOD = ROOT / "HoMM 3 Complete" / "Data" / "H3bitmap.lod"


def fail(msg: str) -> None:
    raise SystemExit(f"ab/sod video index map validation failed: {msg}")


def extract_cmpmovie(lod_path: Path) -> list[str]:
    data = lod_path.read_bytes()
    if data[:3] != b"LOD":
        fail(f"not a LOD archive: {lod_path}")
    count = struct.unpack_from("<I", data, 8)[0]
    base = 0x5C
    for i in range(count):
        off = base + i * 32
        name = data[off : off + 16].split(b"\x00", 1)[0].decode("latin1", "replace")
        offset, size, _ = struct.unpack_from("<III", data, off + 16)
        if name.lower() == "cmpmovie.txt":
            blob = data[offset : offset + size]
            text = zlib.decompress(blob).decode("latin1")
            return [ln.strip() for ln in text.splitlines() if ln.strip()]
    fail(f"CmpMovie.txt missing in {lod_path}")


def letter_index(ch: str) -> int:
    return ord(ch.lower()) - ord("a") + 1


def expected_clip_for_label(label: str) -> tuple[str, str] | None:
    """Return (clip_key, narration_snd_key) for AB/SoD CmpMovie labels, else None."""
    rules: list[tuple[str, object]] = [
        ("ArmageddonsBlade_", "ab"),
        ("DragonsBlood_", "db"),
        ("DragonSlayer_", "ds"),
        ("FestivalOfLife_", "fl"),
        ("FoolhardyWaywardness_", "fw"),
        ("PlayingWithFire_", "pf"),
    ]
    for prefix, code in rules:
        if not label.startswith(prefix):
            continue
        suf = label[len(prefix) :]
        if suf == "end":
            # End cards are not required mission pins; leave unmapped unless present.
            return None
        n = letter_index(suf)
        return (f"H3AB{code}{n}", f"ABVO{code.upper()}{n}")

    sod = [
        ("BirthOfABarbarian_", "BB", "H3X2BB"),
        ("ElixirOfLife_", "EL", "H3X2EL"),
        ("HackAndSlash_", "HS", "H3X2HS"),
        ("NewBeginning_", "NB", "H3X2NB"),
        ("RiseOfTheNecromancer_", "RN", "H3X2RN"),
        ("UnholyAlliance_", "UA", "H3X2UA"),
    ]
    for prefix, letters, snd_prefix in sod:
        if not label.startswith(prefix):
            continue
        suf = label[len(prefix) :]
        end_map = {
            "BirthOfABarbarian_end": ("H3x2_BBf", "H3X2BBF"),
            "ElixirOfLife_end": ("H3x2_ELe", "H3X2ELE"),
            "HackAndSlash_end": ("H3x2_HSe", "H3X2HSE"),
            "NewBeginning_end": ("H3x2_NBe", "H3X2NBE"),
            "RiseOfTheNecromancer_end": ("H3x2_RNe1", "H3X2RNE"),
            "UnholyAlliance_end": ("H3x2_UAm", "H3X2UAM"),
        }
        if suf == "end":
            return end_map.get(label)
        # VIDEO.VID uses lowercase trailing letter (H3x2_BBa); SND uses uppercase (H3X2BBA).
        clip_letter = suf.lower() if len(suf) == 1 else suf
        snd_letter = suf.upper() if len(suf) == 1 else suf.upper()
        if label.startswith("UnholyAlliance_") and suf.lower() == "i":
            # CmpMovie uses UnholyAlliance_I; VID stem is H3x2_UAi.
            clip_letter = "i"
            snd_letter = "I"
        clip = f"H3x2_{letters}{clip_letter}"
        snd = f"{snd_prefix}{snd_letter}"
        return (clip, snd)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lod", type=Path, default=DEFAULT_LOD)
    args = parser.parse_args()
    if not args.lod.is_file():
        fail(f"missing LOD {args.lod}")

    movies = extract_cmpmovie(args.lod)
    errors: list[str] = []

    # Abbreviation contract (the fire/fool swap root cause).
    if HUB_STRIP_STEMS.get("fire") != "C1pf2":
        errors.append(
            f"HUB_STRIP_STEMS['fire'] must be C1pf2 (Playing with Fire); "
            f"got {HUB_STRIP_STEMS.get('fire')!r}"
        )
    if HUB_STRIP_STEMS.get("fool") != "C1fw1":
        errors.append(
            f"HUB_STRIP_STEMS['fool'] must be C1fw1 (Foolhardy Waywardness); "
            f"got {HUB_STRIP_STEMS.get('fool')!r}"
        )
    if VIDEO_STEM_STANDINS.get("H3x2_HSb") != "H3x2_HSc":
        errors.append("VIDEO_STEM_STANDINS must map H3x2_HSb → H3x2_HSc")
    if resolve_video_stem_for_clip("H3x2_HSb") != "H3x2_HSc":
        errors.append("resolve_video_stem_for_clip(H3x2_HSb) must return H3x2_HSc")
    if resolve_video_stem_for_clip("H3x2_HSc") != "H3x2_HSc":
        errors.append("H3x2_HSc must not be remapped through stand-ins")

    # Spot-check CmpMovie indices that previously swapped.
    checks = {
        48: ("H3ABfw1", "ABVOFW1"),  # FoolhardyWaywardness_a
        53: ("H3ABpf1", "ABVOPF1"),  # PlayingWithFire_a
        68: ("H3x2_HSa", "H3X2HSA"),
        69: ("H3x2_HSb", "H3X2HSB"),
        70: ("H3x2_HSc", "H3X2HSC"),
        71: ("H3x2_HSd", "H3X2HSD"),
    }
    for idx, want in checks.items():
        label = movies[idx] if idx < len(movies) else None
        got = VIDEO_INDEX_TO_CLIP.get(idx)
        if got != want:
            errors.append(
                f"index {idx} ({label}): map={got} want={want}"
            )

    # Full AB/SoD range: every mapped index must match CmpMovie-derived expectation.
    for idx, label in enumerate(movies):
        if idx < 24:
            continue
        if label.startswith("SpectreOfPower_"):
            # Not in our delivered mission set; may be unmapped.
            continue
        expected = expected_clip_for_label(label)
        got = VIDEO_INDEX_TO_CLIP.get(idx)
        if expected is None:
            continue
        if got is None:
            # End cards optional except HackAndSlash_end which we map for completeness.
            if label.endswith("_end") and label != "HackAndSlash_end":
                continue
            errors.append(f"index {idx} ({label}): unmapped; expected {expected}")
            continue
        if got != expected:
            errors.append(f"index {idx} ({label}): map={got} expected={expected}")

    if errors:
        fail("; ".join(errors[:12]) + (f" … (+{len(errors) - 12} more)" if len(errors) > 12 else ""))

    print(
        json_dumps_ok(
            {
                "ok": True,
                "cmpMovieCount": len(movies),
                "mappedIndexes": len(VIDEO_INDEX_TO_CLIP),
                "hubFireStrip": HUB_STRIP_STEMS["fire"],
                "hubFoolStrip": HUB_STRIP_STEMS["fool"],
                "hsbStandin": VIDEO_STEM_STANDINS["H3x2_HSb"],
            }
        )
    )
    return 0


def json_dumps_ok(payload: dict) -> str:
    import json

    return json.dumps(payload, indent=2)


if __name__ == "__main__":
    raise SystemExit(main())
