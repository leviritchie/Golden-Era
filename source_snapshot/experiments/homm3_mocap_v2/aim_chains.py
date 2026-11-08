"""Named rest-length aim chains. Hubs with several children are not aimed."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

import numpy as np


def load_aim_chains(path: Path, raw_names: Sequence[str]) -> list[list[int]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw = payload.get("aimChains")
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{path} must contain a non-empty aimChains list")
    index_by_name = {str(name): index for index, name in enumerate(raw_names)}
    chains: list[list[int]] = []
    for chain in raw:
        if not isinstance(chain, list) or len(chain) < 2:
            raise ValueError("each aim chain must name at least two joints")
        resolved: list[int] = []
        for bone in chain:
            if not isinstance(bone, str) or bone not in index_by_name:
                raise ValueError(f"aim chain bone {bone!r} is not in the bind skeleton")
            resolved.append(index_by_name[bone])
        chains.append(resolved)
    return chains


def aim_child_index(
    chains: Sequence[Sequence[int]],
    parents: Sequence[int] | np.ndarray,
) -> dict[int, int]:
    parent = np.asarray(parents, dtype=np.int64)
    aim: dict[int, int] = {}
    for chain in chains:
        if len(chain) < 2:
            raise ValueError("each aim chain must contain at least two joints")
        for start, child in zip(chain[:-1], chain[1:]):
            start_i = int(start)
            child_i = int(child)
            if int(parent[child_i]) != start_i:
                raise ValueError(
                    f"aim chain breaks the parent tree: joint {child_i} parent is "
                    f"{int(parent[child_i])}, not {start_i}"
                )
            previous = aim.get(start_i)
            if previous is not None and previous != child_i:
                raise ValueError(
                    f"joint {start_i} would aim at both {previous} and {child_i}; "
                    "split the hub and aim each child chain separately"
                )
            aim[start_i] = child_i
    return aim


def chain_root_tips(
    chains: Sequence[Sequence[int]],
    parents: Sequence[int] | np.ndarray,
) -> dict[int, int]:
    """Each chain aims only at its tip. Intermediate joints keep rest shape."""
    aim_child_index(chains, parents)
    roots: dict[int, int] = {}
    for chain in chains:
        root = int(chain[0])
        tip = int(chain[-1])
        if root in roots and roots[root] != tip:
            raise ValueError(f"chain root {root} already aims at tip {roots[root]}, not {tip}")
        roots[root] = tip
    return roots


def idle_bookend_worlds(clip_worlds: np.ndarray, rest_world: np.ndarray) -> np.ndarray:
    clip = np.asarray(clip_worlds, dtype=np.float64)
    rest = np.asarray(rest_world, dtype=np.float64)
    if clip.ndim != 4 or clip.shape[-2:] != (4, 4):
        raise ValueError(f"clip worlds must be [T,J,4,4], got {clip.shape}")
    if rest.shape != clip.shape[1:] or rest.shape[-2:] != (4, 4):
        raise ValueError(f"rest world must be [J,4,4] matching clip, got {rest.shape}")
    if clip.shape[0] < 1:
        raise ValueError("clip worlds must contain at least one frame")
    return np.concatenate([rest[None], clip, rest[None]], axis=0)
