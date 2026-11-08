#!/usr/bin/env python3
"""Shared GenerateImage prompt contract for dense bone overlays."""
from __future__ import annotations

from constants import JOINT_ORDER

# Exact spellings the model must print next to each joint dot.
JOINT_LABELS = list(JOINT_ORDER)

OVERLAY_LEGEND_LINES = [
    "Bright cyan sticks + dots: spine/head chain Nose -> Neck -> chest -> MidHip",
    "Bright lime sticks + dots: STRIKE arm (arm nearer orange mace tip) RShoulder -> RElbow -> RWrist",
    "Bright magenta sticks + dots: support arm LShoulder -> LElbow -> LWrist",
    "Bright yellow sticks + dots: hips + legs MidHip -> RHip -> RKnee -> RAnkle and MidHip -> LHip -> LKnee -> LAnkle",
    "Bright orange stick + LARGE tip dot: mace shaft ending at WeaponTip",
]


def joint_label_block() -> str:
    names = ", ".join(JOINT_LABELS)
    return (
        "LABEL EVERY JOINT with a small readable text tag next to its dot, using EXACTLY these names:\n"
        f"  {names}\n"
        "Rules for labels:\n"
        "- One label per joint; spelling must match the list exactly (including WeaponTip, MidHip, R/L prefixes).\n"
        "- Place each label next to its joint dot (slightly offset so it stays readable).\n"
        "- Use small high-contrast text (white or yellow with a dark outline).\n"
        "- Do not invent extra joint names; do not omit any listed joint that is visible."
    )


def build_overlay_prompt(*, camera: str, has_prev_overlay: bool) -> str:
    chain = ""
    if has_prev_overlay:
        chain = (
            "Consistency lock: a previous overlay is attached. Keep the SAME character identity, "
            "clothing, mace style, neon stick colors/weights, and joint LABEL style/names as that "
            "previous overlay. Only change camera/pose to match THIS frame's sprite reference.\n\n"
        )
    legend = "\n".join(f"- {line}" for line in OVERLAY_LEGEND_LINES)
    return (
        f"{chain}"
        "Faithful painted redraw of the HoMM3 Stronghold hobgoblin attack sprite. "
        "Match the EXACT pose from the NN-upscaled sprite reference (limb bends, mace, stance). "
        "Do not invent a new pose or a different creature.\n\n"
        f"Camera: {camera}\n\n"
        "Character: olive/moss green skin (not neon chroma green), bronze bowl helmet and pauldrons, "
        "baggy brown trousers, bare feet, wooden-haft spiked morningstar. "
        "Simple dark solid background. Large clear sprite-like game art.\n\n"
        "ADD a vivid neon stick-skeleton OVERLAY on top (high saturation, thick lines, white outline):\n"
        f"{legend}\n\n"
        f"{joint_label_block()}\n"
    )
