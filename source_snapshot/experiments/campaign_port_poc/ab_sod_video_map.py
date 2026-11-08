#!/usr/bin/env python3
"""AB/SoD campaign video index map (H3C prolog.video → VIDEO.VID stem + Heroes3.snd).

prolog.video is a global Complete-edition media index from CmpMovie.txt (H3bitmap.lod).
Mission cutscene slots used by the 12 AB/SoD hubs begin at 24 (after RoE 0–23).

NWC stem abbreviations (verified against VIDEO.VID pixel content + CmpMovie labels):
  ab=Armageddon's Blade, db=Dragon's Blood, ds=Dragon Slayer, fl=Festival of Life,
  fw=Foolhardy Waywardness, pf=Playing with Fire.

HSb.smk is absent from VIDEO.VID; clip key H3x2_HSb keeps H3X2HSB narration and
uses VIDEO_STEM_STANDINS → H3x2_HSc for the video file only (do not shift later
HackAndSlash stems).
"""
from __future__ import annotations

from typing import Final

# (clip_key / video stem, narration_snd_key)
VIDEO_INDEX_TO_CLIP: Final[dict[int, tuple[str, str]]] = {}

# Logical clip key → on-disk VIDEO.VID stem when the named file is missing.
VIDEO_STEM_STANDINS: Final[dict[str, str]] = {
    "H3x2_HSb": "H3x2_HSc",
}


def _fill(start: int, stems_and_snd: list[tuple[str, str]]) -> None:
    for i, pair in enumerate(stems_and_snd):
        VIDEO_INDEX_TO_CLIP[start + i] = pair


_fill(
    24,
    [(f"H3ABab{i}", f"ABVOAB{i}") for i in range(1, 10)],
)
_fill(
    33,
    [(f"H3ABdb{i}", f"ABVODB{i}") for i in range(1, 6)],
)
_fill(
    38,
    [(f"H3ABds{i}", f"ABVODS{i}") for i in range(1, 6)],
)
_fill(
    43,
    [(f"H3ABfl{i}", f"ABVOFL{i}") for i in range(1, 6)],
)
# Foolhardy Waywardness (fw) precedes Playing with Fire (pf) in CmpMovie.
_fill(
    48,
    [(f"H3ABfw{i}", f"ABVOFW{i}") for i in range(1, 5)],
)
# 52 = FoolhardyWaywardness_end (no mission pin in our set).
# Playing with Fire missions use 53–55 (PlayingWithFire_end at 56 unused).
_fill(
    53,
    [(f"H3ABpf{i}", f"ABVOPF{i}") for i in range(1, 4)],
)
_fill(
    57,
    [
        ("H3x2_BBa", "H3X2BBA"),
        ("H3x2_BBb", "H3X2BBB"),
        ("H3x2_BBc", "H3X2BBC"),
        ("H3x2_BBd", "H3X2BBD"),
        ("H3x2_BBe", "H3X2BBE"),
        ("H3x2_BBf", "H3X2BBF"),
    ],
)
_fill(
    63,
    [
        ("H3x2_ELa", "H3X2ELA"),
        ("H3x2_ELb", "H3X2ELB"),
        ("H3x2_ELc", "H3X2ELC"),
        ("H3x2_ELd", "H3X2ELD"),
        ("H3x2_ELe", "H3X2ELE"),
    ],
)
# Crag/Hack: HSb.smk missing — clip key stays HSb; file stand-in is HSc.
VIDEO_INDEX_TO_CLIP[68] = ("H3x2_HSa", "H3X2HSA")
VIDEO_INDEX_TO_CLIP[69] = ("H3x2_HSb", "H3X2HSB")
VIDEO_INDEX_TO_CLIP[70] = ("H3x2_HSc", "H3X2HSC")
VIDEO_INDEX_TO_CLIP[71] = ("H3x2_HSd", "H3X2HSD")
# 72 = HackAndSlash_end → H3x2_HSe (no mission pin in our set).
VIDEO_INDEX_TO_CLIP[72] = ("H3x2_HSe", "H3X2HSE")
_fill(
    73,
    [
        ("H3x2_NBa", "H3X2NBA"),
        ("H3x2_NBb", "H3X2NBB"),
        ("H3x2_NBc", "H3X2NBC"),
        ("H3x2_NBd", "H3X2NBD"),
        ("H3x2_NBe", "H3X2NBE"),
    ],
)
_fill(
    78,
    [
        ("H3x2_RNa", "H3X2RNA"),
        ("H3x2_RNb", "H3X2RNB"),
        ("H3x2_RNc", "H3X2RNC"),
        ("H3x2_RNd", "H3X2RND"),
        ("H3x2_RNe1", "H3X2RNE"),
    ],
)
_fill(
    88,
    [
        ("H3x2_UAa", "H3X2UAA"),
        ("H3x2_UAb", "H3X2UAB"),
        ("H3x2_UAc", "H3X2UAC"),
        ("H3x2_UAd", "H3X2UAD"),
        ("H3x2_UAe", "H3X2UAE"),
        ("H3x2_UAf", "H3X2UAF"),
        ("H3x2_UAg", "H3X2UAG"),
        ("H3x2_UAh", "H3X2UAH"),
        ("H3x2_UAi", "H3X2UAI"),
        ("H3x2_UAj", "H3X2UAJ"),
        ("H3x2_UAk", "H3X2UAK"),
        ("H3x2_UAl", "H3X2UAL"),
        ("H3x2_UAm", "H3X2UAM"),
    ],
)

# Hub → hover-strip stem (selection still only; not composed).
# C1fw* = Foolhardy Waywardness; C1pf* = Playing with Fire (Complete H3ab_ahd.vid).
HUB_STRIP_STEMS: Final[dict[str, str]] = {
    "ab": "C1ab7",
    "blood": "C1db2",
    "slayer": "C1ds1",
    "festival": "C1fl3",
    "fire": "C1pf2",
    "fool": "C1fw1",
    "yog": "Birth",
    "gelu": "elixir",
    "crag": "hack",
    "gem": "new",
    "sandro": "rise",
    "final": "unholy",
}

AB_SOD_CAMPAIGN_LODS: Final[dict[str, str]] = {
    "ab.h3c": "H3ab_bmp.lod",
    "blood.h3c": "H3ab_bmp.lod",
    "slayer.h3c": "H3ab_bmp.lod",
    "festival.h3c": "H3ab_bmp.lod",
    "fire.h3c": "H3ab_bmp.lod",
    "fool.h3c": "H3ab_bmp.lod",
    "Sandro.h3c": "H3bitmap.lod",
    "Crag.h3c": "H3bitmap.lod",
    "Yog.h3c": "H3bitmap.lod",
    "Gem.h3c": "H3bitmap.lod",
    "Gelu.h3c": "H3bitmap.lod",
    "Final.h3c": "H3bitmap.lod",
}


def precon_byte_count(scenario_count: int) -> int:
    if scenario_count <= 0:
        raise ValueError("scenario_count must be positive")
    return (scenario_count + 7) // 8


def resolve_clip_for_video_index(video_index: int) -> tuple[str, str]:
    pair = VIDEO_INDEX_TO_CLIP.get(video_index)
    if pair is None:
        raise KeyError(f"unmapped H3C prolog.video index {video_index}")
    return pair


def resolve_video_stem_for_clip(clip_key: str) -> str:
    """On-disk VIDEO.VID / extract stem (may differ from clip_key for stand-ins)."""
    return VIDEO_STEM_STANDINS.get(clip_key, clip_key)
