"""Resolve StoryHub campaignHeroSid / factionSid for a mission id.

Carry-policy ``campaign.missionSpawns`` (fallback ``defaultSpawn``) is the
authoritative per-mission spawn. Installer ``HUB_CONFIGS.campaignHeroSid`` remains
the hub primary (must appear in weave ``heroes.json``). Raw_translation profiles
must emit the same ``spawn.heroSid`` so map ``propHeroes`` matches weave
``fixedHeroesSet``.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

_HERO_SID_RE = re.compile(r"^(homm3_[a-z]+)_hero_\d+$")

# Artifact folder names that differ from batch missionId.
_MISSION_ID_ALIASES = {
    "homecoming_poc": "homecoming",
}

_POLICY_GLOBS = (
    ROOT / "scenarios" / "roe_castle_campaign" / "continuity_carry_policy*.json",
    ROOT / "scenarios" / "ab_sod_campaigns" / "continuity_carry_policy_*.json",
)


def faction_sid_from_hero_sid(hero_sid: str) -> str:
    match = _HERO_SID_RE.fullmatch(str(hero_sid).strip())
    if not match:
        raise ValueError(f"campaign hero SID has unexpected shape: {hero_sid!r}")
    return match.group(1)


def mission_id_from_map_install_artifact(artifact: Path | str) -> str:
    art = Path(artifact)
    if art.name != "maps" or art.parent.name != "raw_translation_map":
        raise ValueError(
            f"mapInstall artifact must end with raw_translation_map/maps; got {art.as_posix()}"
        )
    folder = art.parent.parent.name
    return _MISSION_ID_ALIASES.get(folder, folder)


def _load_hub_configs() -> dict[str, dict[str, Any]]:
    tools_dir = str(ROOT / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    from install_roe_castle_continuity_weave import HUB_CONFIGS  # noqa: WPS433

    return HUB_CONFIGS


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _iter_carry_policy_paths(repo_root: Path) -> list[Path]:
    paths: list[Path] = []
    for pattern in (
        repo_root / "scenarios" / "roe_castle_campaign" / "continuity_carry_policy*.json",
        repo_root / "scenarios" / "ab_sod_campaigns" / "continuity_carry_policy_*.json",
    ):
        paths.extend(sorted(pattern.parent.glob(pattern.name)))
    # Deduplicate while preserving order (good1 policy has no hub suffix).
    seen: set[Path] = set()
    out: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        out.append(path)
    return out


def _hub_key_for_hub_sid(hub_sid: str, hub_configs: dict[str, dict[str, Any]]) -> str | None:
    for hub_key, hub_cfg in hub_configs.items():
        if str(hub_cfg.get("hubSid") or "") == hub_sid:
            return str(hub_key)
    return None


def _spawns_from_policy(policy: dict[str, Any]) -> dict[str, dict[str, str]]:
    campaign = policy.get("campaign") if isinstance(policy.get("campaign"), dict) else {}
    default = campaign.get("defaultSpawn") if isinstance(campaign.get("defaultSpawn"), dict) else {}
    default_hero = str(default.get("heroSid") or "").strip()
    default_faction = str(default.get("factionSid") or "").strip()
    raw = campaign.get("missionSpawns") if isinstance(campaign.get("missionSpawns"), dict) else {}
    chain = list(policy.get("missionChain") or [])
    out: dict[str, dict[str, str]] = {}
    for mission_id in chain:
        mid = str(mission_id)
        override = raw.get(mid) if isinstance(raw.get(mid), dict) else None
        if override is not None:
            hero = str(override.get("heroSid") or "").strip()
            faction = str(override.get("factionSid") or "").strip()
            if not hero or not faction:
                raise ValueError(
                    f"campaign.missionSpawns[{mid!r}] requires non-empty heroSid and factionSid"
                )
            out[mid] = {"heroSid": hero, "factionSid": faction}
        elif default_hero and default_faction:
            out[mid] = {"heroSid": default_hero, "factionSid": default_faction}
    return out


def campaign_hub_spawn_by_mission(
    *,
    repo_root: Path | None = None,
) -> dict[str, dict[str, str]]:
    """Map missionId → {heroSid, factionSid, hubKey} from carry policies + HUB_CONFIGS."""

    root = (repo_root or ROOT).resolve()
    hub_configs = _load_hub_configs()
    by_mission: dict[str, dict[str, str]] = {}

    # Prefer carry-policy missionSpawns / defaultSpawn (supports multi-hero hubs).
    for policy_path in _iter_carry_policy_paths(root):
        policy = _load_json(policy_path)
        if policy.get("schema") != "homm3.olden_campaign_continuity_carry_policy.v1":
            continue
        campaign = policy.get("campaign") if isinstance(policy.get("campaign"), dict) else {}
        hub_sid = str(campaign.get("hubSid") or "").strip()
        hub_key = _hub_key_for_hub_sid(hub_sid, hub_configs) or ""
        for mission_id, spawn in _spawns_from_policy(policy).items():
            row = {
                "heroSid": spawn["heroSid"],
                "factionSid": spawn["factionSid"],
                "hubKey": hub_key,
            }
            prior = by_mission.get(mission_id)
            if prior is not None and (
                prior["heroSid"] != row["heroSid"] or prior["factionSid"] != row["factionSid"]
            ):
                raise ValueError(
                    f"mission {mission_id!r} maps to conflicting policy spawns: "
                    f"{prior} vs {row} ({policy_path})"
                )
            by_mission[mission_id] = row

    # Fill any installer missions missing from policies (should be rare).
    for hub_key, hub_cfg in hub_configs.items():
        hero_sid = str(hub_cfg.get("campaignHeroSid") or "").strip()
        if not hero_sid:
            raise ValueError(f"hub {hub_key!r} missing campaignHeroSid")
        faction_sid = faction_sid_from_hero_sid(hero_sid)
        missions = list(hub_cfg.get("missions") or ())
        installs = list(hub_cfg.get("mapInstalls") or [])
        if len(missions) != len(installs):
            raise ValueError(
                f"hub {hub_key!r} missions/mapInstalls length mismatch: "
                f"{len(missions)} vs {len(installs)}"
            )
        for _filename, install in zip(missions, installs):
            if not isinstance(install, dict) or "artifact" not in install:
                raise ValueError(f"hub {hub_key!r} mapInstall missing artifact")
            mission_id = mission_id_from_map_install_artifact(install["artifact"])
            if mission_id in by_mission:
                continue
            by_mission[mission_id] = {
                "heroSid": hero_sid,
                "factionSid": faction_sid,
                "hubKey": str(hub_key),
            }
    return by_mission


def resolve_campaign_hub_spawn(mission_id: str) -> dict[str, str] | None:
    return campaign_hub_spawn_by_mission().get(str(mission_id))
