#!/usr/bin/env python3
"""Load HoMM3 campaign H3C blocks from the local Complete LOD archives.

RoE + SoD campaigns live in H3bitmap.lod. AB-only campaigns live in H3ab_bmp.lod.
Resolution is explicit by entry name (no silent cross-LOD fallback). HotA and
H3HD are intentionally out of scope for this loader.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import h3m_format as h3m
import port_homecoming_poc as poc

AB_LOD_PATH = poc.ROOT / "HoMM 3 Complete" / "Data" / "H3ab_bmp.lod"

# Armageddon's Blade campaign entries are absent from H3bitmap.lod.
AB_CAMPAIGN_ENTRIES = frozenset(
    {
        "ab.h3c",
        "blood.h3c",
        "slayer.h3c",
        "festival.h3c",
        "fire.h3c",
        "fool.h3c",
    }
)


@dataclass(frozen=True)
class H3CMissionSource:
    campaign_entry: str
    block_index: int
    campaign_bytes: bytes
    h3m_data: bytes
    h3m_sha256: str
    summary: h3m.H3MShapeSummary
    templates: list[dict[str, Any]]
    lod_path: Path = poc.LOD_PATH


def resolve_h3c_lod_path(campaign_entry: str) -> Path:
    """Return the Complete LOD that owns this campaign entry."""

    if campaign_entry.lower() in AB_CAMPAIGN_ENTRIES:
        if not AB_LOD_PATH.is_file():
            raise FileNotFoundError(f"expected AB LOD at {AB_LOD_PATH}")
        return AB_LOD_PATH
    if not poc.LOD_PATH.is_file():
        raise FileNotFoundError(f"expected Complete bitmap LOD at {poc.LOD_PATH}")
    return poc.LOD_PATH


def load_h3c_block(campaign_entry: str, block_index: int) -> H3CMissionSource:
    if block_index <= 0:
        raise ValueError(f"H3C block index must be positive, got {block_index}")
    lod_path = resolve_h3c_lod_path(campaign_entry)
    compressed_campaign = poc.read_lod_entry(lod_path, campaign_entry)
    h3c_blocks = poc.split_concatenated_gzip_members(compressed_campaign)
    if block_index >= len(h3c_blocks):
        raise ValueError(
            f"{campaign_entry} has {len(h3c_blocks)} blocks; requested block index {block_index} is out of range"
        )
    block = h3c_blocks[block_index]
    if block.index != block_index:
        raise ValueError(f"internal H3C block index mismatch: expected {block_index}, got {block.index}")
    h3m_data = block.payload
    summary = h3m.summarize_h3m_shape(h3m_data)
    _terrain_start, _object_table_offset, _object_count, templates = h3m.locate_h3m_terrain_and_objects(
        h3m_data,
        summary.size,
        summary.layers,
    )
    campaign_bytes = b"".join(member.payload for member in h3c_blocks)
    return H3CMissionSource(
        campaign_entry=campaign_entry,
        block_index=block_index,
        campaign_bytes=campaign_bytes,
        h3m_data=h3m_data,
        h3m_sha256=hashlib.sha256(h3m_data).hexdigest(),
        summary=summary,
        templates=templates,
        lod_path=lod_path,
    )

