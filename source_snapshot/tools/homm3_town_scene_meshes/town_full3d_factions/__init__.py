"""Per-faction profiles of the full-3D town lane (the stronghold_full3d_* tools; docs/homm3_town_depth_building_solids.md).

The tools are faction-generic code; everything that describes ONE HoMM3 town painting (its file, output names, the
hand-measured horizon / floor polygon / scale, the biome's vanilla filler assets, per-building tuning rows, the
animated-building effects module) lives in town_full3d_factions/<key>.py.

The active faction is TOWN_FULL3D_FACTION; a --faction <key> on the command line sets it when this package is first
imported (stronghold_full3d_common imports it, so before any lane module reads a profile value). It must
be set explicitly for any faction other than 'stronghold', the lane's original faction, which stays the default so the
existing Stronghold commands rebuild byte-identically. A profile that lacks a field fails with AttributeError when a
stage needs it: there is no fallback to another faction's values.
"""
from __future__ import annotations

import importlib
import os
import sys

ENV = "TOWN_FULL3D_FACTION"
DEFAULT = "stronghold"


def set_from_argv(argv: list[str] | None = None) -> str:
    """Read --faction <key> / --faction=<key> from argv (before the lane modules are imported) into TOWN_FULL3D_FACTION.
    Leaves argv untouched: each CLI also declares --faction so argparse accepts it."""
    argv = sys.argv if argv is None else argv
    for i, a in enumerate(argv):
        if a == "--faction" and i + 1 < len(argv):
            os.environ[ENV] = argv[i + 1]
        elif a.startswith("--faction="):
            os.environ[ENV] = a.split("=", 1)[1]
    return key()


def key() -> str:
    return os.environ.get(ENV, DEFAULT).strip() or DEFAULT


def _load():
    k = key()
    try:
        return importlib.import_module(f"town_full3d_factions.{k}")
    except ModuleNotFoundError as e:
        if e.name == f"town_full3d_factions.{k}":
            raise SystemExit(f"town_full3d_factions: no profile for faction '{k}' "
                             f"(tools/homm3_town_scene_meshes/town_full3d_factions/{k}.py)") from None
        raise


set_from_argv()
P = _load()
KEY = key()
