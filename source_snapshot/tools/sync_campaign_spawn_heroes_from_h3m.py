#!/usr/bin/env python3
"""Align StoryHub spawn heroes to H3M-canon playable starts.

Updates carry-policy ``defaultSpawn`` / ``missionSpawns``, AB/SoD ``hub_index``
``heroSid``, installer ``campaignHeroSid`` rows, and raw_translation profile
``spawn`` blocks so they match ``infer_campaign_spawn_hero_sid`` (map hero /
mainCustomHeroId). Campaign-granted missions with no concrete H3M hero keep
their existing policy spawn (or hub default).

Proof boundary: source/static H3M header + alignment only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POC = ROOT / "experiments" / "campaign_port_poc"
if str(POC) not in sys.path:
    sys.path.insert(0, str(POC))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from campaign_hub_spawn import faction_sid_from_hero_sid  # noqa: E402
from campaign_mission import load_batch_manifest, mission_by_id  # noqa: E402
from campaign_profile_derive import infer_campaign_spawn_hero_sid  # noqa: E402


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, doc: Any) -> None:
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _iter_policy_paths() -> list[Path]:
    paths: list[Path] = []
    for pattern in (
        ROOT / "scenarios" / "roe_castle_campaign" / "continuity_carry_policy*.json",
        ROOT / "scenarios" / "ab_sod_campaigns" / "continuity_carry_policy_*.json",
    ):
        paths.extend(sorted(pattern.parent.glob(pattern.name)))
    # Dedupe (good1 policy matched by both globs' parent walks only once here).
    seen: set[Path] = set()
    out: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        out.append(path)
    return out


def _hub_configs_spawn_by_hub_sid() -> dict[str, dict[str, str]]:
    tools_dir = str(ROOT / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    from install_roe_castle_continuity_weave import HUB_CONFIGS  # noqa: WPS433

    out: dict[str, dict[str, str]] = {}
    for hub_cfg in HUB_CONFIGS.values():
        hub_sid = str(hub_cfg.get("hubSid") or "")
        hero = str(hub_cfg.get("campaignHeroSid") or "").strip()
        if not hub_sid or not hero:
            continue
        out[hub_sid] = {
            "heroSid": hero,
            "factionSid": faction_sid_from_hero_sid(hero),
        }
    return out


def _derive_chain_spawns(
    policy: dict[str, Any],
    *,
    hub_fallback: dict[str, dict[str, str]] | None = None,
) -> tuple[dict[str, dict[str, str]], list[str]]:
    campaign = policy.get("campaign") if isinstance(policy.get("campaign"), dict) else {}
    batch_rel = campaign.get("batchManifest")
    chain = [str(mid) for mid in (policy.get("missionChain") or [])]
    notes: list[str] = []
    if not isinstance(batch_rel, str) or not batch_rel.strip() or not chain:
        raise ValueError("policy missing campaign.batchManifest or missionChain")
    batch = load_batch_manifest((ROOT / batch_rel).resolve())
    existing = campaign.get("missionSpawns") if isinstance(campaign.get("missionSpawns"), dict) else {}
    default = campaign.get("defaultSpawn") if isinstance(campaign.get("defaultSpawn"), dict) else {}
    default_hero = str(default.get("heroSid") or "").strip()
    default_faction = str(default.get("factionSid") or "").strip()
    hub_sid = str(campaign.get("hubSid") or "")
    hub_spawn = (hub_fallback or {}).get(hub_sid) or {}
    if not default_hero:
        default_hero = str(hub_spawn.get("heroSid") or "").strip()
    if not default_faction:
        default_faction = str(hub_spawn.get("factionSid") or "").strip()
    out: dict[str, dict[str, str]] = {}
    for mid in chain:
        mission = mission_by_id(batch, mid)
        prior = existing.get(mid) if isinstance(existing.get(mid), dict) else None
        prior_hero = str((prior or {}).get("heroSid") or default_hero or "").strip()
        prior_faction = str((prior or {}).get("factionSid") or default_faction or "").strip()
        try:
            derived = infer_campaign_spawn_hero_sid(mission)
            hero = str(derived["heroSid"])
            faction = faction_sid_from_hero_sid(hero)
            out[mid] = {"heroSid": hero, "factionSid": faction}
            if prior_hero and prior_hero != hero:
                notes.append(
                    f"{mid}: {prior_hero} -> {hero} ({derived.get('evidence')})"
                )
            else:
                notes.append(f"{mid}: {hero} ({derived.get('evidence')})")
        except ValueError:
            if not prior_hero or not prior_faction:
                raise ValueError(
                    f"{mid}: no H3M concrete spawn and no existing policy/hub spawn to keep"
                )
            out[mid] = {"heroSid": prior_hero, "factionSid": prior_faction}
            notes.append(f"{mid}: keep {prior_hero} (campaign-granted / no H3M concrete)")
    return out, notes


def _sync_policy(
    path: Path,
    *,
    dry_run: bool,
    hub_fallback: dict[str, dict[str, str]] | None = None,
) -> list[str]:
    policy = _load_json(path)
    if policy.get("schema") != "homm3.olden_campaign_continuity_carry_policy.v1":
        return [f"skip {path.name}: unsupported schema"]
    spawns, notes = _derive_chain_spawns(policy, hub_fallback=hub_fallback)
    chain = [str(mid) for mid in (policy.get("missionChain") or [])]
    first = spawns[chain[0]]
    campaign = policy.setdefault("campaign", {})
    campaign["defaultSpawn"] = {
        "factionSid": first["factionSid"],
        "heroSid": first["heroSid"],
    }
    campaign["missionSpawns"] = {mid: dict(spawns[mid]) for mid in chain}
    note = (
        "Spawn heroes are H3M-canon (map human hero / mainCustomHeroId / heroesNames). "
        "Narrative campaign titles are not spawn sources. Later protagonists unlock via "
        "StoryHub UnlockHero (delayed isAvailableAtStart)."
    )
    campaign["hubSidNote"] = note
    if not dry_run:
        _write_json(path, policy)
    return [f"{path.relative_to(ROOT)}: defaultSpawn={first['heroSid']}"] + [
        f"  {line}" for line in notes
    ]


def _sync_hub_index(spawns_by_hub_sid: dict[str, dict[str, str]], *, dry_run: bool) -> list[str]:
    index_path = ROOT / "scenarios" / "ab_sod_campaigns" / "hub_index.v1.json"
    if not index_path.is_file():
        return ["skip hub_index: missing"]
    index = _load_json(index_path)
    lines: list[str] = []
    for hub in index.get("hubs") or []:
        if not isinstance(hub, dict):
            continue
        hub_sid = str(hub.get("hubSid") or "")
        spawn = spawns_by_hub_sid.get(hub_sid)
        if not spawn:
            continue
        old = str(hub.get("heroSid") or "")
        hub["heroSid"] = spawn["heroSid"]
        hub["factionSid"] = spawn["factionSid"]
        lines.append(f"hub_index {hub.get('hub')}: {old} -> {spawn['heroSid']}")
    if not dry_run:
        _write_json(index_path, index)
    return lines


def _sync_roe_installer_campaign_heroes(
    spawns_by_hub_sid: dict[str, dict[str, str]], *, dry_run: bool
) -> list[str]:
    installer = ROOT / "tools" / "install_roe_castle_continuity_weave.py"
    text = installer.read_text(encoding="utf-8")
    lines: list[str] = []
    for hub_sid, spawn in spawns_by_hub_sid.items():
        pattern = re.compile(
            rf'(["\']hubSid["\']:\s*["\']{re.escape(hub_sid)}["\'],\s*\n\s*["\']campaignHeroSid["\']:\s*["\'])([^"\']+)(["\'])',
            re.MULTILINE,
        )
        match = pattern.search(text)
        if not match:
            continue
        prev = match.group(2)
        hero = spawn["heroSid"]
        if prev == hero:
            continue
        text = pattern.sub(rf"\g<1>{hero}\g<3>", text, count=1)
        lines.append(f"installer {hub_sid}: {prev} -> {hero}")
    if not dry_run and lines:
        installer.write_text(text, encoding="utf-8")
    return lines


def _patch_installer_ab_fragment(*, dry_run: bool) -> list[str]:
    """Replace inlined AB/SoD HUB_CONFIGS with the regenerated fragment."""
    fragment_path = ROOT / "scenarios" / "ab_sod_campaigns" / "installer_hub_configs.fragment.py"
    installer = ROOT / "tools" / "install_roe_castle_continuity_weave.py"
    if not fragment_path.is_file():
        return ["skip AB fragment patch: missing fragment"]
    fragment = fragment_path.read_text(encoding="utf-8")
    text = installer.read_text(encoding="utf-8")
    start = text.find("# --- BEGIN AB/SoD HUB_CONFIGS")
    end = text.find("# --- END AB/SoD HUB_CONFIGS ---")
    if start < 0 or end < 0:
        return ["skip AB fragment patch: markers missing in installer"]
    end_line = end + len("# --- END AB/SoD HUB_CONFIGS ---")
    # Fragment already includes BEGIN/END markers.
    new_text = text[:start] + fragment.rstrip() + "\n" + text[end_line:].lstrip("\n")
    if new_text == text:
        return ["AB fragment already synced into installer"]
    if not dry_run:
        installer.write_text(new_text, encoding="utf-8")
    return ["patched installer AB/SoD HUB_CONFIGS from fragment"]


def _sync_profiles(spawns_by_mission: dict[str, dict[str, str]], *, dry_run: bool) -> list[str]:
    lines: list[str] = []
    for profile_path in sorted(ROOT.glob("scenarios/*/raw_translation.profile.json")):
        doc = _load_json(profile_path)
        scenario_id = str(doc.get("scenarioId") or "")
        # scenarioId is usually "<missionId>_<packaging>"; missionId is the prefix
        # before the first packaging suffix we know. Prefer artifact folder name.
        mission_id = None
        artifact = str((doc.get("artifactRoot") or "")).replace("\\", "/")
        if artifact:
            mission_id = Path(artifact).name
            if mission_id.endswith("_poc"):
                mission_id = "homecoming"
            if mission_id == "homecoming_poc":
                mission_id = "homecoming"
        if mission_id is None:
            # Fall back: strip known packaging suffixes from scenarioId.
            for suffix in (
                "_roe_castle",
                "_roe_necropolis",
                "_roe_dungeon",
                "_roe_neutral",
                "_roe_inferno",
                "_ab_sod",
            ):
                if scenario_id.endswith(suffix):
                    mission_id = scenario_id[: -len(suffix)]
                    break
        if not mission_id or mission_id not in spawns_by_mission:
            continue
        spawn = spawns_by_mission[mission_id]
        block = doc.get("spawn") if isinstance(doc.get("spawn"), dict) else {}
        old = str(block.get("heroSid") or "")
        block["heroSid"] = spawn["heroSid"]
        block["factionSid"] = spawn["factionSid"]
        doc["spawn"] = block
        if old != spawn["heroSid"]:
            lines.append(
                f"profile {profile_path.relative_to(ROOT)}: {old} -> {spawn['heroSid']}"
            )
        if not dry_run:
            _write_json(profile_path, doc)
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--skip-profiles",
        action="store_true",
        help="Only update policies / hub index / installer campaignHeroSid",
    )
    parser.add_argument(
        "--skip-installer",
        action="store_true",
        help="Do not rewrite tools/install_roe_castle_continuity_weave.py",
    )
    args = parser.parse_args()

    all_notes: list[str] = []
    spawns_by_hub_sid: dict[str, dict[str, str]] = {}
    spawns_by_mission: dict[str, dict[str, str]] = {}
    hub_fallback = _hub_configs_spawn_by_hub_sid()

    for path in _iter_policy_paths():
        policy = _load_json(path)
        if policy.get("schema") != "homm3.olden_campaign_continuity_carry_policy.v1":
            continue
        spawns, _notes = _derive_chain_spawns(policy, hub_fallback=hub_fallback)
        campaign = policy.get("campaign") if isinstance(policy.get("campaign"), dict) else {}
        hub_sid = str(campaign.get("hubSid") or "")
        chain = [str(mid) for mid in (policy.get("missionChain") or [])]
        if hub_sid and chain:
            spawns_by_hub_sid[hub_sid] = dict(spawns[chain[0]])
        spawns_by_mission.update(spawns)
        all_notes.extend(_sync_policy(path, dry_run=args.dry_run, hub_fallback=hub_fallback))

    all_notes.extend(_sync_hub_index(spawns_by_hub_sid, dry_run=args.dry_run))
    if not args.skip_installer:
        all_notes.extend(
            _sync_roe_installer_campaign_heroes(spawns_by_hub_sid, dry_run=args.dry_run)
        )
    if not args.skip_profiles:
        all_notes.extend(_sync_profiles(spawns_by_mission, dry_run=args.dry_run))

    # Regenerate AB installer fragment from hub_index when not dry-run, then
    # splice it into the live installer HUB_CONFIGS block.
    if not args.dry_run and not args.skip_installer:
        gen = ROOT / "tools" / "generate_ab_sod_installer_hub_configs.py"
        if gen.is_file():
            import subprocess

            proc = subprocess.run(
                [sys.executable, str(gen)],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0:
                print(proc.stdout)
                print(proc.stderr, file=sys.stderr)
                return proc.returncode
            all_notes.append(proc.stdout.strip() or f"ran {gen.name}")
        all_notes.extend(_patch_installer_ab_fragment(dry_run=False))
    elif args.dry_run:
        all_notes.append("dry-run: skipped AB fragment regenerate/patch")

    print("\n".join(all_notes))
    print(
        json.dumps(
            {
                "ok": True,
                "dryRun": args.dry_run,
                "hubs": len(spawns_by_hub_sid),
                "missions": len(spawns_by_mission),
                "proofBoundary": "source/static H3M header + alignment map hero",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
