#!/usr/bin/env python3
"""Fail-closed contract for RoE Castle Good1 continuity weave + hero carry policy.

Validates the generated StoryHub weave against the carry policy and batch manifest.
When Core.zip contains the hub, also validates the installed payload.

Installed-payload checks include the shared map-load preflight
(``tools/map_load_preflight.py``): Meta logic ↔ ObjectConfig integrity, orphan
``homm3_xfp_*`` scrub, camp_fire aliases, StoryHub owner/ai.script coverage,
map SID resolution, and Story_maps-only dual-install refusal.

Does not require Plugin playable-shell CampaignInfo changes.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

SCHEMA_WEAVE = "homm3.olden_campaign_continuity_weave.v1"
SCHEMA_POLICY = "homm3.olden_campaign_continuity_carry_policy.v1"
BONUS_DIFFICULTY_POLICY = (
    Path("scenarios") / "roe_castle_campaign" / "continuity_bonus_difficulty.v1.json"
)
RESOURCE_FIELD_KEYS: tuple[str, ...] = (
    "gold",
    "wood",
    "ore",
    "gemstones",
    "crystals",
    "mercury",
    "alchemicalDust",
)
HUB_SID = "homm3_01_roe_castle_good1"
DEFAULT_GAME_ROOT = Path(
    r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
)
CORE_ZIP_REL = Path("HeroesOldenEra_Data") / "StreamingAssets" / "Core.zip"
# Campaign StartInfo loads mapSid from maps/Story_maps/<sid>.map (not maps/ root).
MAPS_REL = Path("HeroesOldenEra_Data") / "StreamingAssets" / "maps" / "Story_maps"


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def load_json(path: Path) -> Any:
    if not path.is_file():
        raise SystemExit(f"missing required JSON: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def expected_starting_resources_table(repo_root: Path) -> dict[int, dict[str, dict[str, int]]]:
    policy = load_json(repo_root / BONUS_DIFFICULTY_POLICY)
    block = policy.get("startingResources")
    if not isinstance(block, dict):
        raise SystemExit(f"{BONUS_DIFFICULTY_POLICY} must declare startingResources")
    rows = block.get("rows")
    if not isinstance(rows, list) or not rows:
        raise SystemExit(f"{BONUS_DIFFICULTY_POLICY} startingResources.rows must be non-empty")
    out: dict[int, dict[str, dict[str, int]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise SystemExit("startingResources.rows entries must be objects")
        index = row.get("index")
        if not isinstance(index, int) or index < 0 or index > 3:
            raise SystemExit(f"startingResources row has invalid index {index!r}")
        economic: dict[str, dict[str, int]] = {}
        for field in ("playerStartResources", "aiStartResources"):
            resources = row.get(field)
            if not isinstance(resources, dict):
                raise SystemExit(f"startingResources[{index}] missing {field}")
            economic[field] = {
                key: int(resources[key])
                for key in RESOURCE_FIELD_KEYS
                if isinstance(resources.get(key), int)
            }
            if set(economic[field]) != set(RESOURCE_FIELD_KEYS):
                raise SystemExit(
                    f"startingResources[{index}].{field} must include all resource keys"
                )
        out[index] = economic
    if set(out) != {0, 1, 2, 3}:
        raise SystemExit("startingResources must cover indices 0-3")
    return out


def require_economic_resources(
    *,
    actual: Any,
    expected: dict[str, int],
    label: str,
    errors: list[str],
) -> None:
    if not isinstance(actual, dict):
        require(False, f"{label} must be an object", errors)
        return
    for key in RESOURCE_FIELD_KEYS:
        require(
            actual.get(key) == expected.get(key),
            f"{label}.{key} must be {expected.get(key)}; got {actual.get(key)!r}",
            errors,
        )


def regenerate(repo_root: Path, game_root: Path) -> None:
    script = repo_root / "experiments" / "campaign_port_poc" / "build_roe_castle_continuity_weave.py"
    if not script.is_file():
        raise SystemExit(f"missing weave builder: {script}")
    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--repo-root",
            str(repo_root),
            "--game-root",
            str(game_root),
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(
            "continuity weave regeneration failed:\n"
            + (proc.stdout or "")
            + (proc.stderr or "")
        )


def expected_map_sid(mission_id: str, batch_row: dict[str, Any], policy: dict[str, Any]) -> str:
    overrides = policy.get("storyHubMapSidOverrides") or {}
    override = overrides.get(mission_id)
    if isinstance(override, str) and override.strip():
        return override.strip()
    return str(batch_row["mapSid"])


def validate_plugin_untouched(plugin_cs: Path, errors: list[str]) -> None:
    text = plugin_cs.read_text(encoding="utf-8-sig", errors="replace")
    require(
        "private static CampaignInfo CreateHomecomingPlayableShellCampaignInfo()" in text,
        "Plugin.cs must still expose CreateHomecomingPlayableShellCampaignInfo",
        errors,
    )
    marker = "private static CampaignInfo CreateHomecomingPlayableShellCampaignInfo()"
    body = text.split(marker, 1)[1].split("private static SideTimerSettings CreateSideTimerSettings", 1)[0]
    require(
        "return new CampaignInfo();" in body,
        "Homecoming playable shell must keep empty CampaignInfo() so raw_translation playtest stays single-map",
        errors,
    )
    require(
        "transferHeroProgressFromSession_" not in body,
        "do not silently enable CampaignInfo transfer on the Homecoming playable-shell path",
        errors,
    )


def validate_csharp_contract(
    cs_path: Path,
    policy: dict[str, Any],
    *,
    expect_installed: bool,
    errors: list[str],
) -> None:
    require(cs_path.is_file(), f"missing C# continuity contract: {cs_path}", errors)
    if not cs_path.is_file():
        return
    text = cs_path.read_text(encoding="utf-8-sig", errors="replace")
    require(
        f'HubSid = "{HUB_SID}"' in text or f'public const string HubSid = "{HUB_SID}"' in text,
        f"C# contract must pin HubSid {HUB_SID}",
        errors,
    )
    require(
        "TransferHeroProgressFromSession = true" in text
        or "TransferHeroProgressFromSessionRequired = true" in text,
        "C# contract must require transferHeroProgressFromSession true",
        errors,
    )
    require(
        "AvailableDifficultyCount = 4" in text,
        "C# contract must pin AvailableDifficultyCount = 4",
        errors,
    )
    require(
        "ImpossibleDifficultyAvailable = false" in text,
        "C# contract must keep ImpossibleDifficultyAvailable false",
        errors,
    )
    require(
        "StartingBonusSelectionImplemented = false" in text,
        "C# contract must keep StartingBonusSelectionImplemented false until bonuses are safe",
        errors,
    )
    handoff = policy["handoffs"][0]
    require(
        f"StrongestHeroesCarryCount = {handoff['strongestHeroesCarryCount']}" in text,
        "C# contract must pin Homecoming strongest-heroes carry count",
        errors,
    )
    require(
        f"HomecomingLevelCap = {handoff['levelCap']}" in text,
        "C# contract must pin Homecoming level cap",
        errors,
    )
    homecoming_sid = expected_map_sid(
        "homecoming",
        {"mapSid": "h3_roe_castle_homecoming_raw_translation"},
        policy,
    )
    require(
        f'FirstMapSid = "{homecoming_sid}"' in text,
        f"C# contract must pin FirstMapSid {homecoming_sid}",
        errors,
    )
    if expect_installed:
        require(
            "InstalledIntoCoreZip = true" in text,
            "C# contract must set InstalledIntoCoreZip true after deploy",
            errors,
        )
    else:
        require(
            "InstalledIntoCoreZip = false" in text or "InstalledIntoCoreZip = true" in text,
            "C# contract must declare InstalledIntoCoreZip",
            errors,
        )


def validate_game_symbols(symbols_path: Path, errors: list[str]) -> None:
    require(symbols_path.is_file(), f"missing GameSymbols.cs: {symbols_path}", errors)
    if not symbols_path.is_file():
        return
    text = symbols_path.read_text(encoding="utf-8-sig", errors="replace")
    require(
        re.search(r"internal static (?:partial )?class CampaignContinuity\b", text) is not None,
        "GameSymbols must centralize CampaignContinuity symbols",
        errors,
    )
    for needle in [
        "transferHeroProgressFromSession",
        "transferHeroProgressFromSession_",
        "heroesSaves",
        "CampaignInfo",
        "StoryHubSave",
    ]:
        require(needle in text, f"GameSymbols.CampaignContinuity must mention {needle}", errors)


def validate_weave(
    weave: dict[str, Any],
    policy: dict[str, Any],
    batch: dict[str, Any],
    *,
    repo_root: Path,
    expect_installed: bool,
    starting_resources: dict[int, dict[str, dict[str, int]]],
    errors: list[str],
) -> None:
    require(weave.get("schema") == SCHEMA_WEAVE, f"weave schema must be {SCHEMA_WEAVE}", errors)
    require(weave.get("hubSid") == HUB_SID, f"hubSid must be {HUB_SID}", errors)
    require(
        weave.get("transferHeroProgressFromSession") is True,
        "weave must enable transferHeroProgressFromSession",
        errors,
    )
    install_status = weave.get("coreZipLayout", {}).get("installStatus")
    if expect_installed:
        require(
            install_status == "installed",
            "weave must report installStatus=installed after Core.zip deploy",
            errors,
        )
    else:
        require(
            install_status in {"not_installed", "installed"},
            "weave installStatus must be not_installed or installed",
            errors,
        )

    story_hub = weave.get("payloads", {}).get("storyHub", {})
    require(
        story_hub.get("transferHeroProgressFromSession") is True,
        "storyHub.json payload must set transferHeroProgressFromSession true",
        errors,
    )
    require(story_hub.get("sid") == HUB_SID, "storyHub.sid must match hubSid", errors)
    require(
        story_hub.get("mainIconSid") == "main_icon",
        "storyHub.mainIconSid must be main_icon (native campaign selection image)",
        errors,
    )

    video_policy = (
        policy.get("videoContract") if isinstance(policy.get("videoContract"), dict) else {}
    )
    if video_policy.get("hubFirstShowPlayVideo") is False:
        first_show = story_hub.get("firstShowActions") or []
        require(
            not any(
                isinstance(a, dict) and a.get("type") == "PlayVideo" for a in first_show
            ),
            "Good1 firstShowActions must omit PlayVideo when hubFirstShowPlayVideo is false "
            "(Cgood1 is selection-still only; mission pins keep Good1a/b/c)",
            errors,
        )
        wiring = weave.get("videoWiring") or {}
        require(
            wiring.get("status") == "omitted_selection_still_only",
            "videoWiring.status must be omitted_selection_still_only when hub PlayVideo "
            "is policy-disabled",
            errors,
        )
        sel = video_policy.get("selectionIcon") if isinstance(video_policy.get("selectionIcon"), dict) else {}
        require(
            sel.get("storyHubField") == "mainIconSid" and sel.get("iconSid") == "main_icon",
            "carry policy selectionIcon must map mainIconSid → main_icon",
            errors,
        )

    chain = policy.get("missionChain") or []
    require(weave.get("missionChain") == chain, "weave missionChain must match carry policy", errors)

    # VCMI good1 region pixels fitted into Olden StoryHub localPosition envelope
    # (see build_roe_castle_continuity_weave.map_good1_region_to_storyhub_pos).
    expected_node_positions = {
        "homecoming": (-358.1, -120.0),
        "guardian_angels": (-100.0, -113.4),
        "griffin_cliff": (-400.0, 80.0),
    }

    nodes = story_hub.get("nodes") or []
    require(len(nodes) == len(chain), "storyHub nodes must cover missionChain", errors)
    for index, mission_id in enumerate(chain):
        node = nodes[index] if index < len(nodes) else {}
        expected_sid = f"homm3_roe_castle_node_{mission_id}"
        require(node.get("sid") == expected_sid, f"node[{index}] sid must be {expected_sid}", errors)
        if mission_id in expected_node_positions:
            exp_x, exp_y = expected_node_positions[mission_id]
            require(
                abs(float(node.get("posX", 0)) - exp_x) < 0.05
                and abs(float(node.get("posY", 0)) - exp_y) < 0.05,
                f"node {expected_sid} must use HoMM3-mapped StoryHub pos "
                f"({exp_x}, {exp_y}); got ({node.get('posX')}, {node.get('posY')})",
                errors,
            )
        actions = node.get("interactionActions") or []
        require(
            any(
                a.get("type") == "OpenMissionsPrologue"
                and a.get("values") == [f"homm3_roe_castle_{mission_id}"]
                for a in actions
            ),
            f"node {expected_sid} must OpenMissionsPrologue for mission config",
            errors,
        )
        clip_map = (
            (policy.get("videoContract") or {}).get("missionClipKeys")
            if isinstance((policy.get("videoContract") or {}).get("missionClipKeys"), dict)
            else {}
        )
        expected_clip = clip_map.get(mission_id)
        require(
            isinstance(expected_clip, str) and expected_clip.strip(),
            f"carry policy missionClipKeys must map {mission_id} to a clip key",
            errors,
        )
        validate_mission_pin_action_order(
            expected_sid,
            actions,
            mission_id=mission_id,
            expected_clip=expected_clip if isinstance(expected_clip, str) else None,
            errors=errors,
        )
        pin_reports = (weave.get("videoWiring") or {}).get("missionPins") or []
        pin_report = next(
            (
                row
                for row in pin_reports
                if isinstance(row, dict) and row.get("missionId") == mission_id
            ),
            None,
        )
        if isinstance(pin_report, dict) and pin_report.get("playVideoStatus") == "wired_playvideo":
            require(
                len(actions) >= 2
                and isinstance(actions[0], dict)
                and actions[0].get("type") == "PlayVideo"
                and actions[0].get("values") == [expected_clip],
                f"node {expected_sid} videoWiring wired_playvideo but interactionActions "
                f"missing leading PlayVideo[{expected_clip}]",
                errors,
            )
        if index + 1 < len(chain):
            next_sid = f"homm3_roe_castle_node_{chain[index + 1]}"
            on_done = node.get("onDoneActions") or []
            require(
                any(
                    a.get("type") == "changeNodeState" and a.get("values") == [next_sid, "Activated"]
                    for a in on_done
                ),
                f"node {expected_sid} must activate {next_sid} onDone",
                errors,
            )

    handoff = policy["handoffs"][0]
    weave_handoff = (weave.get("handoffs") or [None])[0]
    require(weave_handoff == handoff, "weave handoffs[0] must match carry policy", errors)
    require(handoff["fromMissionId"] == "homecoming", "first handoff fromMissionId must be homecoming", errors)
    require(
        handoff["toMissionId"] == "guardian_angels",
        "first handoff toMissionId must be guardian_angels",
        errors,
    )
    require(handoff["levelCap"] == 6, "Homecoming levelCap must be 6", errors)
    require(
        handoff["strongestHeroesCarryCount"] == 4,
        "Homecoming strongestHeroesCarryCount must be 4",
        errors,
    )
    require(
        "4 strongest" in handoff.get("sourceTextProven", ""),
        "handoff must retain source text proving 4 strongest heroes carry",
        errors,
    )
    poc_dir = str(repo_root / "experiments" / "campaign_port_poc")
    if poc_dir not in sys.path:
        sys.path.insert(0, poc_dir)
    import campaign_hero_level_cap

    for issue in campaign_hero_level_cap.validate_handoff_level_cap(
        handoff, repo_root=repo_root
    ):
        errors.append(issue)

    require(
        (weave.get("minimumFaithfulSubset") or {}).get("dimensions")
        == policy["minimumFaithfulSubset"]["dimensions"],
        "minimumFaithfulSubset must stay pinned",
        errors,
    )
    require(
        "keepCreatures" in (weave.get("deferredExplicitLoss") or {}).get("dimensions", []),
        "army/creature carry must be explicit deferred loss, not silent",
        errors,
    )

    batch_by_id = {
        row["missionId"]: row
        for row in batch.get("missions", [])
        if isinstance(row, dict) and "missionId" in row
    }
    missions_payload = weave.get("payloads", {}).get("missions") or {}
    for mission_id in chain:
        key = f"homm3_roe_castle_{mission_id}"
        require(key in missions_payload, f"missing mission payload {key}", errors)
        if key not in missions_payload:
            continue
        rows = missions_payload[key].get("array") or []
        require(len(rows) == 1, f"{key} must have exactly one mission row", errors)
        if not rows:
            continue
        variant = (rows[0].get("variants") or [{}])[0]
        expected_map = expected_map_sid(mission_id, batch_by_id[mission_id], policy)
        require(
            variant.get("mapSid") == expected_map,
            f"{key} mapSid must be {expected_map}",
            errors,
        )
        if mission_id == "homecoming":
            sides = variant.get("sides") or []
            bot_sides = [
                side
                for side in sides
                if isinstance(side, dict) and side.get("type") == "Bot"
            ]
            # Compact owner scheme from homecoming raw_translation install_manifest:
            # human=1, AI Castle towns=2, Terraneus/Dungeon=3 (not legacy 3/4).
            require(
                any(
                    side.get("spawns") == [2] and side.get("fractionSid") == "homm3_castle"
                    for side in bot_sides
                ),
                f"{key} must declare Bot side spawns[2] fractionSid=homm3_castle "
                "for surface AI Castle towns (missing Bot leaves propCities unbound and "
                "Session.Loader retries forever)",
                errors,
            )
            require(
                any(
                    side.get("spawns") == [3] and side.get("fractionSid") == "homm3_dungeon"
                    for side in bot_sides
                ),
                f"{key} must declare Bot side spawns[3] fractionSid=homm3_dungeon "
                "for Terraneus (city faction; Inferno Bot paints Terraneus Inferno; "
                "Xyron still binds via propHeroes + campaign spawn parity hook)",
                errors,
            )
        continuity = rows[0].get("_continuity") or {}
        require(
            continuity.get("mapReadyForRuntime") is True,
            f"{key} must be mapReadyForRuntime true for campaign install/test",
            errors,
        )
        require(
            rows[0].get("requiredHeroesCount") == 1,
            f"{key} requiredHeroesCount must be 1 so a single carried hero can start",
            errors,
        )
        params = rows[0].get("difficultiesParameters") or []
        require(len(params) == 5, f"{key} must declare 5 difficultiesParameters rows", errors)
        for index, row in enumerate(params):
            expect_available = index < 4
            require(
                row.get("index") == index,
                f"{key} difficultiesParameters[{index}].index must be {index}",
                errors,
            )
            require(
                row.get("isAvailable") is expect_available,
                f"{key} difficultiesParameters[{index}].isAvailable must be {expect_available} "
                "(Easy..Expert open; Impossible locked)",
                errors,
            )
        difficulties = variant.get("difficulties") or []
        require(
            len(difficulties) == 4,
            f"{key} variant must ship difficulties indices 0-3 (not only Easy)",
            errors,
        )
        for index, diff in enumerate(difficulties):
            require(
                diff.get("index") == index,
                f"{key} difficulties[{index}].index must be {index}",
                errors,
            )
            require(
                isinstance(diff.get("neutralPowerMultiplier"), (int, float)),
                f"{key} difficulties[{index}] must set neutralPowerMultiplier",
                errors,
            )
            require(
                diff.get("heroesArmies") == [],
                f"{key} difficulties[{index}].heroesArmies must stay empty until additive "
                "army-bonus apply is proven (czr.vhk replaces map spawn armies)",
                errors,
            )
            ai = diff.get("ai") if isinstance(diff.get("ai"), dict) else {}
            script = ai.get("script")
            require(
                isinstance(script, str) and script.strip() != "",
                f"{key} difficulties[{index}].ai.script must be a non-empty AiConfig id "
                "(empty script → Config id \"\" not found → fjl NRE → Session.Loader leak)",
                errors,
            )
            require(
                script == "campaign_M1",
                f"{key} difficulties[{index}].ai.script must be campaign_M1 "
                f"(Start Phase Mission 1 mirror); got {script!r}",
                errors,
            )
            economic = diff.get("economic") if isinstance(diff.get("economic"), dict) else {}
            expected_economic = starting_resources.get(index)
            require(
                isinstance(expected_economic, dict),
                f"validator missing expected starting resources for difficulty index {index}",
                errors,
            )
            require_economic_resources(
                actual=(economic.get("playerStartResources") if economic else None),
                expected=expected_economic["playerStartResources"],
                label=f"{key} difficulties[{index}].economic.playerStartResources",
                errors=errors,
            )
            require_economic_resources(
                actual=(economic.get("aiStartResources") if economic else None),
                expected=expected_economic["aiStartResources"],
                label=f"{key} difficulties[{index}].economic.aiStartResources",
                errors=errors,
            )
        require(
            len(rows[0].get("variants") or []) == 1,
            f"{key} must keep a single MissionVariant until starting-bonus effects are safe",
            errors,
        )

    homecoming_choice = weave.get("homecomingMapSidChoice") or {}
    require(
        homecoming_choice.get("mapSid") == "h3_roe_castle_homecoming_raw_translation",
        "weave must document Homecoming raw_translation mapSid choice",
        errors,
    )
    require(
        bool(homecoming_choice.get("reason")),
        "homecomingMapSidChoice.reason must document why raw_translation was chosen",
        errors,
    )

    recipe = weave.get("campaignInfoLaunchRecipe") or {}
    require(
        recipe.get("fields", {}).get("transferHeroProgressFromSession_") is True,
        "CampaignInfo launch recipe must require transferHeroProgressFromSession_ true",
        errors,
    )
    require(
        recipe.get("doNotApplyTo") == "Plugin.CreateHomecomingPlayableShellCampaignInfo",
        "launch recipe must explicitly exclude the current playable-shell path",
        errors,
    )
    proof_path = recipe.get("levelPersistenceProofPath") or []
    require(len(proof_path) >= 5, "level persistence proof path must be documented", errors)
    ui_path = recipe.get("uiClickPath") or []
    require(len(ui_path) >= 4, "uiClickPath must document how to open the hub", errors)

    open_gaps = {g.get("id"): g for g in weave.get("openGaps") or [] if isinstance(g, dict)}
    for required_gap in [
        "strongest_n_selection",
        "session_to_hub_writeback",
        "sequel_maps",
        "army_carry",
        "starting_bonus_selection",
        "difficulty_runtime_scaling",
    ]:
        require(required_gap in open_gaps, f"openGaps must include {required_gap}", errors)
    require(
        open_gaps.get("starting_bonus_selection", {}).get("status")
        == "not_shipped_fail_closed",
        "starting_bonus_selection must remain fail-closed until additive grant surfaces exist",
        errors,
    )
    require(
        weave.get("startingBonusSelection", {}).get("implementedInWeave") is False,
        "weave startingBonusSelection.implementedInWeave must be false while bonuses are blocked",
        errors,
    )
    require(
        (weave.get("difficultySelection") or {}).get("oldenImpossibleIndex4", {}).get(
            "isAvailable"
        )
        is False,
        "difficultySelection must keep Impossible locked",
        errors,
    )
    require(
        open_gaps.get("sequel_maps", {}).get("status")
        in {"maps_present_campaign_ready", "generation_incomplete"},
        "sequel_maps gap status must be explicit",
        errors,
    )


def validate_split_payloads(out_dir: Path, weave: dict[str, Any], errors: list[str]) -> None:
    story_hub_path = out_dir / "campaign_payload" / "storyHub.json"
    require(story_hub_path.is_file(), f"missing split payload {story_hub_path}", errors)
    if story_hub_path.is_file():
        split = load_json(story_hub_path)
        require(
            split.get("transferHeroProgressFromSession") is True,
            "split storyHub.json must enable transfer",
            errors,
        )
        require(split == weave["payloads"]["storyHub"], "split storyHub.json must match weave payload", errors)
        require(
            not any(
                isinstance(a, dict) and a.get("type") == "PlayVideo"
                for a in (split.get("firstShowActions") or [])
            ),
            "split Good1 storyHub.json firstShowActions must omit PlayVideo (selection still)",
            errors,
        )
    for mission_id in weave.get("missionChain") or []:
        path = out_dir / "campaign_payload" / "missions" / f"homm3_roe_castle_{mission_id}.json"
        require(path.is_file(), f"missing mission payload file {path}", errors)
    require(
        (out_dir / "campaign_payload" / "perks.json").is_file(),
        "missing split perks.json",
        errors,
    )
    main_icon = out_dir / "campaign_payload" / "icons" / "main_icon.png"
    require(main_icon.is_file(), f"missing selection icon {main_icon}", errors)
    if main_icon.is_file():
        try:
            from PIL import Image

            with Image.open(main_icon) as im:
                require(
                    im.size == (378, 693),
                    f"Good1 main_icon.png must be native 378x693; got {im.size}",
                    errors,
                )
        except Exception as exc:  # noqa: BLE001 — surface decode failures as contract errors
            errors.append(f"Good1 main_icon.png unreadable: {exc}")
        require(
            len(main_icon.read_bytes()) > 1024,
            "Good1 main_icon.png looks empty/truncated",
            errors,
        )
    lang_path = out_dir / "campaign_payload" / "lang_tokens.json"
    require(lang_path.is_file(), "missing split lang_tokens.json", errors)
    if lang_path.is_file():
        lang = load_json(lang_path)
        token_sids = {
            row.get("sid")
            for row in (lang.get("array") or [])
            if isinstance(row, dict)
        }
        require(
            f"campaign_{HUB_SID}" in token_sids,
            "lang_tokens must include BhCampaign LocKit SID campaign_" + HUB_SID,
            errors,
        )
        for mission_id in weave.get("missionChain") or []:
            cfg = f"homm3_roe_castle_{mission_id}"
            require(f"{cfg}_title" in token_sids, f"lang_tokens missing {cfg}_title", errors)
            require(
                f"{cfg}_description" in token_sids,
                f"lang_tokens missing {cfg}_description",
                errors,
            )

    fractions_path = out_dir / "campaign_payload" / "fractions.json"
    counters_path = out_dir / "campaign_payload" / "storyCounters.json"
    require(fractions_path.is_file(), "missing split fractions.json", errors)
    require(counters_path.is_file(), "missing split storyCounters.json", errors)
    if fractions_path.is_file() and counters_path.is_file():
        fractions = load_json(fractions_path).get("array") or []
        expected_fractions = [
            ("human", "fractionReputation_Human"),
            ("undead", "fractionReputation_Undead"),
            ("unfrozen", "fractionReputation_Unfrozen"),
            ("nature", "fractionReputation_Nature"),
            ("dungeon", "fractionReputation_Dungeon"),
            ("demon", "fractionReputation_Demon"),
        ]
        require(
            len(fractions) == 6,
            "fractions.json must list the native six StoryHub faction UI slots "
            f"(got {len(fractions)}); mismatch crashes BhFractionsReputation.Init",
            errors,
        )
        actual_pairs = [
            (row.get("sid"), row.get("counterSid"))
            for row in fractions
            if isinstance(row, dict)
        ]
        require(
            actual_pairs == expected_fractions,
            "fractions.json must match native tutorial/mainStory faction SIDs+counters "
            f"(got {actual_pairs})",
            errors,
        )
        counter_sids = {
            row.get("sid")
            for row in (load_json(counters_path).get("array") or [])
            if isinstance(row, dict)
        }
        for _sid, counter_sid in expected_fractions:
            require(
                counter_sid in counter_sids,
                f"storyCounters.json missing reputation counter {counter_sid}",
                errors,
            )


def detect_core_installed(game_root: Path) -> bool:
    core_zip = game_root / CORE_ZIP_REL
    if not core_zip.is_file():
        return False
    with zipfile.ZipFile(core_zip, "r") as source:
        return f"campaigns/{HUB_SID}/storyHub.json" in source.namelist()


def validate_mission_pin_action_order(
    node_sid: str,
    actions: list[Any],
    *,
    mission_id: str,
    expected_clip: str | None,
    errors: list[str],
) -> None:
    """Pin serial order: optional PlayVideo(clip), then OpenMissionsPrologue(mission)."""
    typed = [a for a in actions if isinstance(a, dict)]
    prologue = [
        a
        for a in typed
        if a.get("type") == "OpenMissionsPrologue"
        and a.get("values") == [f"homm3_roe_castle_{mission_id}"]
    ]
    require(len(prologue) == 1, f"{node_sid} must have exactly one OpenMissionsPrologue", errors)
    play = [a for a in typed if a.get("type") == "PlayVideo"]
    if not expected_clip:
        require(
            not play,
            f"{node_sid} must not PlayVideo when policy has no missionClipKeys entry",
            errors,
        )
        return
    # Weave may omit PlayVideo when MP4 is missing/undersized (fail-closed). When present,
    # it must be immediately before OpenMissionsPrologue with the policy clip key.
    if not play:
        return
    require(len(play) == 1, f"{node_sid} must have at most one PlayVideo", errors)
    require(
        play[0].get("values") == [expected_clip],
        f"{node_sid} PlayVideo must use clip key {expected_clip!r}",
        errors,
    )
    require(
        len(typed) >= 2
        and typed[0].get("type") == "PlayVideo"
        and typed[1].get("type") == "OpenMissionsPrologue",
        f"{node_sid} interactionActions must be PlayVideo then OpenMissionsPrologue "
        f"(got {[a.get('type') for a in typed]})",
        errors,
    )


def _clips_info_rows(clips: dict[str, Any]) -> list[dict[str, Any]]:
    rows = (
        clips.get("array", {}).get("data")
        if isinstance(clips.get("array"), dict)
        else clips.get("array")
    )
    return [row for row in (rows or []) if isinstance(row, dict)]


def _clips_info_keys(clips: dict[str, Any]) -> set[str]:
    return {
        row.get("key")
        for row in _clips_info_rows(clips)
        if isinstance(row.get("key"), str)
    }


def _clips_info_have_subtitles(clips: dict[str, Any]) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for row in _clips_info_rows(clips):
        key = row.get("key")
        val = row.get("val") if isinstance(row.get("val"), dict) else {}
        if isinstance(key, str):
            out[key] = bool(val.get("haveSubtitles"))
    return out


def validate_playvideo_mp4_and_registry(
    game_root: Path,
    clip_key: str,
    *,
    clips_keys: set[str] | None,
    context: str,
    errors: list[str],
    video_contract: dict[str, Any] | None = None,
    clips_have_subtitles: dict[str, bool] | None = None,
) -> None:
    """When PlayVideo is wired, require native-canvas MP4 + clips_info registration."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "campaign_port_poc"))
    from campaign_video_clip import MIN_ACCEPT_HEIGHT, MIN_ACCEPT_WIDTH, mp4_meets_native_canvas, probe_mp4
    from campaign_video_compose import composed_mp4_meets_contract, ensure_composed_recipe

    mp4 = (
        game_root
        / "HeroesOldenEra_Data"
        / "StreamingAssets"
        / "video"
        / f"{clip_key}.mp4"
    )
    require(mp4.is_file(), f"{context}: PlayVideo {clip_key} wired but {mp4} missing", errors)
    contract = video_contract if isinstance(video_contract, dict) else {}
    recipe = ensure_composed_recipe(clip_key)
    if mp4.is_file():
        probe = probe_mp4(mp4)
        ok, reason = mp4_meets_native_canvas(probe)
        require(
            ok,
            f"{context}: PlayVideo {clip_key} MP4 must be >={MIN_ACCEPT_WIDTH}x{MIN_ACCEPT_HEIGHT} "
            f"(Campaign_Intro canvas parity); {reason}",
            errors,
        )
        if contract.get("requireComposedAudio") and recipe is not None and recipe.is_composable:
            composed_ok, composed_reason = composed_mp4_meets_contract(probe, recipe)
            require(
                composed_ok,
                f"{context}: PlayVideo {clip_key} must be a composed cutscene "
                f"(audio + narration-length duration); {composed_reason}",
                errors,
            )
            sidecar = mp4.with_suffix(mp4.suffix + ".json")
            require(
                sidecar.is_file(),
                f"{context}: PlayVideo {clip_key} softsub sidecar missing: {sidecar}",
                errors,
            )
    if clips_keys is not None:
        require(
            clip_key in clips_keys,
            f"{context}: clips_info must register {clip_key} when PlayVideo is wired",
            errors,
        )
    if (
        contract.get("subtitleMode") == "softsub_sidecar_and_lockit"
        and recipe is not None
        and recipe.is_composable
        and clips_have_subtitles is not None
        and clip_key in (clips_keys or set())
    ):
        require(
            clips_have_subtitles.get(clip_key) is True,
            f"{context}: clips_info {clip_key} must set haveSubtitles true for softsub compose",
            errors,
        )
        if recipe.prolog_text and mp4.is_file():
            sidecar = mp4.with_suffix(mp4.suffix + ".json")
            if sidecar.is_file():
                try:
                    from extract_h3c_prolog_texts import normalize_prolog

                    opening = normalize_prolog(recipe.prolog_text)[:48]
                    # Sidecar only stores SIDs; LocKit holds text. Pin recipe to H3C prolog,
                    # not region blurb (known failure: NeutralA / Good1b).
                    if opening.startswith(normalize_prolog("You are offered a mercenary")[:24]):
                        errors.append(
                            f"{context}: {clip_key} recipe softsub source looks like regionText"
                        )
                    if opening.startswith(normalize_prolog("Reports of Angels near the town")[:24]):
                        errors.append(
                            f"{context}: {clip_key} recipe softsub source looks like regionText"
                        )
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{context}: {clip_key} softsub prologue check failed: {exc}")


def _validate_composed_softsub_prolog_contract(errors: list[str]) -> None:
    """Fail closed if COMPOSED_CLIP_RECIPES drift from H3C prologText transcripts."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "campaign_port_poc"))
    try:
        from campaign_video_compose import assert_recipe_prolog_matches_h3c_transcripts

        assert_recipe_prolog_matches_h3c_transcripts()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"H3C prolog softsub contract: {exc}")


def _validate_cinematic_softsub_lockit_contract(
    game_root: Path,
    source: zipfile.ZipFile,
    errors: list[str],
) -> None:
    """LocKit resolves PlayVideo softsubs from cinematic.json tokens, not array.

    A prior multilingual scrub misclassified ``homm3_*_video_N`` SIDs and left
    them only in ``array``, which still showed ``LOC:`` placeholders in-game.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "release_port"))
    try:
        from multilingual_custom_lang import (  # type: ignore
            CAMPAIGN_VIDEO_SOFTSUB_SID_RE,
            canonical_custom_text_files_for_sid,
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"cinematic softsub allowlist import failed: {exc}")
        return

    sample = "homm3_roe_good1a_video_1"
    require(
        canonical_custom_text_files_for_sid(sample) == {"cinematic.json"},
        "canonical_custom_text_files_for_sid must keep campaign softsub SIDs in "
        f"cinematic.json (got {canonical_custom_text_files_for_sid(sample)!r})",
        errors,
    )

    video_dir = (
        game_root / "HeroesOldenEra_Data" / "StreamingAssets" / "video"
    )
    if not video_dir.is_dir():
        return
    needed: set[str] = set()
    for path in sorted(video_dir.glob("*.mp4.json")):
        if path.name.startswith("Campaign_"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append(f"softsub sidecar unreadable {path.name}: {exc}")
            continue
        for cue in data.get("subtitles") or []:
            if not isinstance(cue, dict):
                continue
            sid = cue.get("sid")
            if isinstance(sid, str) and CAMPAIGN_VIDEO_SOFTSUB_SID_RE.match(sid):
                needed.add(sid)
    if not needed:
        return

    member = "Lang/english/texts/cinematic.json"
    require(member in source.namelist(), f"Core.zip missing {member}", errors)
    if member not in source.namelist():
        return
    cin = json.loads(source.read(member).decode("utf-8-sig"))
    token_sids = {
        row.get("sid")
        for row in (cin.get("tokens") or [])
        if isinstance(row, dict)
    }
    missing = sorted(sid for sid in needed if sid not in token_sids)
    require(
        not missing,
        "english cinematic.json tokens must localize PlayVideo softsub SIDs "
        "(avoids LOC: placeholders); missing "
        f"{len(missing)} e.g. {missing[:8]}. "
        "Run tools/repair_cinematic_softsub_loc_tokens.py",
        errors,
    )




def validate_hub_video_contract(
    game_root: Path,
    story: dict[str, Any],
    *,
    policy: dict[str, Any] | None,
    clips_keys: set[str] | None,
    errors: list[str],
    clips_have_subtitles: dict[str, bool] | None = None,
) -> None:
    """Pin PlayVideo↔MP4 canvas parity for hub firstShow and mission pin actions."""
    video = {}
    if isinstance(policy, dict):
        video = policy.get("videoContract") if isinstance(policy.get("videoContract"), dict) else {}
    actions = story.get("firstShowActions") or []
    if video.get("hubFirstShowPlayVideo") is False:
        require(
            not any(
                isinstance(action, dict) and action.get("type") == "PlayVideo"
                for action in actions
            ),
            "hub firstShowActions must not PlayVideo when hubFirstShowPlayVideo is false",
            errors,
        )
    for action in actions:
        if not isinstance(action, dict) or action.get("type") != "PlayVideo":
            continue
        values = action.get("values") or []
        if not values or not isinstance(values[0], str):
            errors.append("firstShowActions PlayVideo must carry a string clip key")
            continue
        validate_playvideo_mp4_and_registry(
            game_root,
            values[0],
            clips_keys=clips_keys,
            context="hub firstShowActions",
            errors=errors,
            video_contract=video,
            clips_have_subtitles=clips_have_subtitles,
        )

    clip_map: dict[str, Any] = {}
    if isinstance(policy, dict):
        clip_map = (
            video.get("missionClipKeys") if isinstance(video.get("missionClipKeys"), dict) else {}
        )

    for node in story.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        node_sid = str(node.get("sid") or "?")
        mission_id = None
        if node_sid.startswith("homm3_roe_castle_node_"):
            mission_id = node_sid[len("homm3_roe_castle_node_") :]
        expected_clip = clip_map.get(mission_id) if mission_id else None
        pin_actions = node.get("interactionActions") or []
        if mission_id:
            validate_mission_pin_action_order(
                node_sid,
                pin_actions,
                mission_id=mission_id,
                expected_clip=expected_clip if isinstance(expected_clip, str) else None,
                errors=errors,
            )
        for action in pin_actions:
            if not isinstance(action, dict) or action.get("type") != "PlayVideo":
                continue
            values = action.get("values") or []
            if not values or not isinstance(values[0], str):
                errors.append(f"{node_sid}: PlayVideo must carry a string clip key")
                continue
            validate_playvideo_mp4_and_registry(
                game_root,
                values[0],
                clips_keys=clips_keys,
                context=f"node {node_sid}",
                errors=errors,
                video_contract=video,
                clips_have_subtitles=clips_have_subtitles,
            )


def validate_intro_skip_publisher_only(plugin_root: Path, errors: list[str]) -> None:
    patch = plugin_root / "IntroVideoSkipPatch.cs"
    require(patch.is_file(), f"missing {patch}", errors)
    if not patch.is_file():
        return
    text = patch.read_text(encoding="utf-8-sig", errors="replace")
    require(
        "PublisherIntroNameNeedles" in text and "IsPublisherBootIntro" in text,
        "IntroVideoSkipPatch must allowlist publisher intros only (not all menu videos)",
        errors,
    )
    require(
        "Cgood1" in text or "Campaign clips are not skipped" in text,
        "IntroVideoSkipPatch must document that campaign clips are not skipped",
        errors,
    )
    for needle in ("Ubisoft", "Unfrozen", "Hooded_Horse", "Trailer"):
        require(needle in text, f"IntroVideoSkipPatch must include publisher needle {needle}", errors)


def validate_installed_core(game_root: Path, weave: dict[str, Any], errors: list[str]) -> None:
    core_zip = game_root / CORE_ZIP_REL
    require(core_zip.is_file(), f"missing Core.zip: {core_zip}", errors)
    if not core_zip.is_file():
        return
    with zipfile.ZipFile(core_zip, "r") as source:
        story_name = f"campaigns/{HUB_SID}/storyHub.json"
        require(story_name in source.namelist(), f"Core.zip missing {story_name}", errors)
        if story_name not in source.namelist():
            return
        story = json.loads(source.read(story_name).decode("utf-8-sig"))
        require(
            story.get("transferHeroProgressFromSession") is True,
            "installed storyHub must enable transferHeroProgressFromSession",
            errors,
        )
        require(
            story.get("mainIconSid") == "main_icon",
            "installed storyHub.mainIconSid must be main_icon",
            errors,
        )
        require(
            not any(
                isinstance(a, dict) and a.get("type") == "PlayVideo"
                for a in (story.get("firstShowActions") or [])
            ),
            "installed Good1 firstShowActions must omit PlayVideo (Cgood1 selection still)",
            errors,
        )
        icon_member = f"campaigns/{HUB_SID}/icons/main_icon.png"
        require(icon_member in source.namelist(), f"Core.zip missing {icon_member}", errors)
        if icon_member in source.namelist():
            installed_icon = source.read(icon_member)
            payload_icon = (
                Path(__file__).resolve().parents[1]
                / "artifacts"
                / "campaign_port_poc"
                / "roe_castle_campaign"
                / "continuity_weave"
                / "campaign_payload"
                / "icons"
                / "main_icon.png"
            )
            if payload_icon.is_file():
                require(
                    installed_icon == payload_icon.read_bytes(),
                    "installed Good1 main_icon.png must match weave campaign_payload icon",
                    errors,
                )
            if "campaigns/mainStory/icons/main_icon.png" in source.namelist():
                require(
                    installed_icon != source.read("campaigns/mainStory/icons/main_icon.png"),
                    "installed Good1 main_icon.png must not be the mainStory clone",
                    errors,
                )
        clips_keys: set[str] | None = None
        clips_have_subtitles: dict[str, bool] | None = None
        clips_member = "DB/clips_info.json"
        if clips_member in source.namelist():
            clips = json.loads(source.read(clips_member).decode("utf-8-sig"))
            clips_keys = _clips_info_keys(clips)
            clips_have_subtitles = _clips_info_have_subtitles(clips)
        policy_path = (
            Path(__file__).resolve().parents[1]
            / "scenarios"
            / "roe_castle_campaign"
            / "continuity_carry_policy.v1.json"
        )
        policy = load_json(policy_path) if policy_path.is_file() else {}
        validate_hub_video_contract(
            game_root,
            story,
            policy=policy,
            clips_keys=clips_keys,
            clips_have_subtitles=clips_have_subtitles,
            errors=errors,
        )
        good2_story_name = "campaigns/homm3_02_roe_castle_good2/storyHub.json"
        if good2_story_name in source.namelist():
            good2_policy_path = (
                Path(__file__).resolve().parents[1]
                / "scenarios"
                / "roe_castle_campaign"
                / "continuity_carry_policy_good2.v1.json"
            )
            good2_policy = load_json(good2_policy_path) if good2_policy_path.is_file() else {}
            good2_story = json.loads(source.read(good2_story_name).decode("utf-8-sig"))
            validate_hub_video_contract(
                game_root,
                good2_story,
                policy=good2_policy,
                clips_keys=clips_keys,
                clips_have_subtitles=clips_have_subtitles,
                errors=errors,
            )
        for mission_id in weave.get("missionChain") or []:
            member = f"campaigns/{HUB_SID}/missions/homm3_roe_castle_{mission_id}.json"
            require(member in source.namelist(), f"Core.zip missing {member}", errors)
            if member not in source.namelist():
                continue
            mission = json.loads(source.read(member).decode("utf-8-sig"))
            expected = (
                ((weave.get("payloads") or {}).get("missions") or {})
                .get(f"homm3_roe_castle_{mission_id}", {})
                .get("array", [{}])[0]
                .get("variants", [{}])[0]
                .get("mapSid")
            )
            actual = mission["array"][0]["variants"][0]["mapSid"]
            require(actual == expected, f"installed {member} mapSid drift: {actual} != {expected}", errors)
            if mission_id == "homecoming":
                installed_sides = (mission["array"][0].get("variants") or [{}])[0].get("sides") or []
                require(
                    any(
                        isinstance(side, dict)
                        and side.get("type") == "Bot"
                        and side.get("spawns") == [2]
                        and side.get("fractionSid") == "homm3_castle"
                        for side in installed_sides
                    ),
                    f"installed {member} Bot spawns[2] must be fractionSid=homm3_castle "
                    "(surface AI towns; re-run tools/install_roe_castle_continuity_weave.py)",
                    errors,
                )
                require(
                    any(
                        isinstance(side, dict)
                        and side.get("type") == "Bot"
                        and side.get("spawns") == [3]
                        and side.get("fractionSid") == "homm3_dungeon"
                        for side in installed_sides
                    ),
                    f"installed {member} Bot spawns[3] must be fractionSid=homm3_dungeon "
                    "(Terraneus city; re-run tools/install_roe_castle_continuity_weave.py)",
                    errors,
                )
            installed_row = mission["array"][0]
            params = installed_row.get("difficultiesParameters") or []
            require(
                len(params) == 5
                and all(params[i].get("isAvailable") is (i < 4) for i in range(5)),
                f"installed {member} must expose Easy..Expert (re-run "
                "tools/install_roe_castle_continuity_weave.py after weave regen)",
                errors,
            )
            installed_diffs = (installed_row.get("variants") or [{}])[0].get("difficulties") or []
            require(
                len(installed_diffs) == 4,
                f"installed {member} must include difficulties indices 0-3 "
                "(re-install continuity weave)",
                errors,
            )
            for diff in installed_diffs:
                if not isinstance(diff, dict):
                    continue
                script = ((diff.get("ai") or {}) if isinstance(diff.get("ai"), dict) else {}).get(
                    "script"
                )
                require(
                    isinstance(script, str) and script.strip() != "",
                    f"installed {member} difficulties[{diff.get('index')}].ai.script must be "
                    "non-empty (empty → fjl/Loader memory leak)",
                    errors,
                )
                require(
                    script == "campaign_M1",
                    f"installed {member} difficulties[{diff.get('index')}].ai.script must be "
                    f"campaign_M1; got {script!r}",
                    errors,
                )
        data = json.loads(source.read("DB/data.json").decode("utf-8-sig"))
        require(
            "DB/heroes/homm3_castle/homm3_castle_hero_7.json" in source.namelist(),
            "installed Core must keep roster hero DB/heroes/homm3_castle/homm3_castle_hero_7.json",
            errors,
        )
        roster_sids = {
            match.group(2)
            for name in source.namelist()
            for match in [re.match(r"^DB/heroes/(homm3_[^/]+)/(homm3_.+_hero_\d+)\.json$", name.replace("\\", "/"))]
            if match
        }
        leaked = sorted(
            sid for sid in (data.get("campaignHeroes") or []) if sid in roster_sids
        )
        require(
            not leaked,
            "installed DB/data.json campaignHeroes must not list shared town-roster SIDs "
            "(native Quick Play hides them): " + ", ".join(leaked),
            errors,
        )
        english = "Lang/english/texts/campaign.json"
        require(english in source.namelist(), f"missing {english}", errors)
        if english in source.namelist():
            camp = json.loads(source.read(english).decode("utf-8-sig"))
            # LocKit resolves BhCampaign titles from ``tokens``. A prior multilingual
            # scrub left titles only in ``array``, which still showed LOC: placeholders.
            token_sids = {
                row.get("sid")
                for row in (camp.get("tokens") or [])
                if isinstance(row, dict)
            }
            array_sids = {
                row.get("sid")
                for row in (camp.get("array") or [])
                if isinstance(row, dict)
            }
            for label, sids in (("tokens", token_sids), ("array", array_sids)):
                require(
                    f"campaign_{HUB_SID}" in sids,
                    f"english campaign.json {label} must localize BhCampaign SID "
                    f"campaign_{HUB_SID} (avoids LOC: placeholder)",
                    errors,
                )
                require(
                    HUB_SID in sids,
                    f"english campaign.json {label} must localize hub sid",
                    errors,
                )
                require(
                    "homm3_roe_castle_homecoming_title" in sids,
                    f"english campaign.json {label} must localize Homecoming title",
                    errors,
                )
                require(
                    "homm3_roe_castle_homecoming_description" in sids,
                    f"english campaign.json {label} must localize Homecoming description",
                    errors,
                )

        _validate_cinematic_softsub_lockit_contract(game_root, source, errors)

        fractions_member = f"campaigns/{HUB_SID}/fractions.json"
        require(fractions_member in source.namelist(), f"Core.zip missing {fractions_member}", errors)
        if fractions_member in source.namelist():
            fractions = json.loads(source.read(fractions_member).decode("utf-8-sig")).get("array") or []
            require(
                len(fractions) == 6,
                "installed fractions.json must have 6 native StoryHub faction slots "
                f"(got {len(fractions)})",
                errors,
            )
            require(
                [row.get("sid") for row in fractions if isinstance(row, dict)]
                == ["human", "undead", "unfrozen", "nature", "dungeon", "demon"],
                "installed fractions.json must use native faction SIDs",
                errors,
            )

        resources_member = "DB/objects_logic/res/resources.json"
        require(resources_member in source.namelist(), f"Core.zip missing {resources_member}", errors)
        if resources_member in source.namelist():
            resource_rows = json.loads(source.read(resources_member).decode("utf-8-sig")).get(
                "array"
            ) or []
            xfp_ids = sorted(
                str(row.get("id") or "")
                for row in resource_rows
                if isinstance(row, dict) and str(row.get("id") or "").startswith("homm3_xfp_")
            )
            require(
                not xfp_ids,
                "Core.zip resources.json must not contain orphan homm3_xfp_* logic ids "
                f"(Loader Meta map object hang); found {xfp_ids[:8]}",
                errors,
            )
            require(
                [str(row.get("id") or "") for row in resource_rows if isinstance(row, dict)]
                == [
                    "resource_gold",
                    "resource_dust",
                    "resource_wood",
                    "resource_ore",
                    "resource_crystals",
                    "resource_mercury",
                    "resource_gemstones",
                ],
                "Core.zip resources.json must be the native seven resource_* logic rows only",
                errors,
            )

        camp_alias_member = "DB/map/objects/homm3_camp_fire_meta_aliases.json"
        resources_object_member = "DB/map/objects/3_resources.json"
        # Liberation load fix: aliases live in 3_resources.json; legacy side-file stays empty.
        if camp_alias_member in source.namelist():
            alias_rows = json.loads(source.read(camp_alias_member).decode("utf-8-sig")).get(
                "array"
            ) or []
            require(
                alias_rows == [],
                "Core.zip homm3_camp_fire_meta_aliases.json must be cleared "
                f"(aliases belong in 3_resources.json); got {len(alias_rows)} rows",
                errors,
            )
        require(
            resources_object_member in source.namelist(),
            f"Core.zip missing {resources_object_member} (camp_fire ObjectConfig)",
            errors,
        )
        if resources_object_member in source.namelist():
            resource_object_rows = (
                json.loads(source.read(resources_object_member).decode("utf-8-sig")).get(
                    "array"
                )
                or []
            )
            resource_object_ids = {
                str(row.get("id") or "")
                for row in resource_object_rows
                if isinstance(row, dict)
            }
            for camp_id in ("camp_fire_1", "camp_fire_2", "camp_fire_3"):
                require(
                    camp_id in resource_object_ids,
                    f"Core.zip {resources_object_member} must include ObjectConfig {camp_id}",
                    errors,
                )

        good2_steadwick = (
            "campaigns/homm3_02_roe_castle_good2/missions/"
            "homm3_roe_castle_steadwick_liberation.json"
        )
        if good2_steadwick in source.namelist():
            steadwick = json.loads(source.read(good2_steadwick).decode("utf-8-sig"))
            variant = ((steadwick.get("array") or [{}])[0].get("variants") or [{}])[0]
            sides = variant.get("sides") or []
            bot_spawns = {
                int(spawn)
                for side in sides
                if isinstance(side, dict) and side.get("type") == "Bot"
                for spawn in (side.get("spawns") or [])
                if isinstance(spawn, int)
            }
            require(
                bot_spawns == {2, 3, 4, 5},
                "Good2 Steadwick mission must declare Bot spawns [2,3,4,5] for "
                f"Tower/Castle/Dungeon/Inferno AI owners (got {sorted(bot_spawns)})",
                errors,
            )
            require(
                any(
                    side.get("type") == "Bot"
                    and side.get("spawns") == [2]
                    and side.get("fractionSid") == "homm3_tower"
                    for side in sides
                    if isinstance(side, dict)
                ),
                "Good2 Steadwick must Bot-bind Tower minority city on spawns[2]",
                errors,
            )

    maps_dir = game_root / MAPS_REL
    maps_root = game_root / Path("HeroesOldenEra_Data") / "StreamingAssets" / "maps"
    for mission_id, row in (weave.get("mapReadiness") or {}).items():
        map_sid = row.get("mapSid")
        path = maps_dir / f"{map_sid}.map"
        require(
            path.is_file(),
            f"installed Story_maps missing {map_sid}.map for {mission_id} "
            f"(StoryHub StartInfo requires maps/Story_maps/, not maps/ root)",
            errors,
        )
        root_map = maps_root / f"{map_sid}.map"
        root_json = maps_root / f"{map_sid}.json"
        require(
            not ((root_map.is_file() or root_json.is_file()) and path.is_file()),
            (
                f"dual mapSid install forbidden for {map_sid}: exists under both maps/ and "
                f"maps/Story_maps/ (QuestScript Dialogs play twice; "
                f"re-run tools/install_roe_castle_continuity_weave.py)"
            ),
            errors,
        )

    # Shared Loader hang preflight (Meta/ObjectConfig, owners, dual install, xfp).
    tools_dir = Path(__file__).resolve().parent
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    from map_load_preflight import run_installed_campaign_preflight

    map_checks: list[dict[str, Any]] = []
    with zipfile.ZipFile(core_zip, "r") as source:
        for mission_id, row in (weave.get("mapReadiness") or {}).items():
            map_sid = row.get("mapSid")
            if not isinstance(map_sid, str) or not map_sid:
                continue
            member = f"campaigns/{HUB_SID}/missions/homm3_roe_castle_{mission_id}.json"
            mission = None
            if member in source.namelist():
                mission = json.loads(source.read(member).decode("utf-8-sig"))
            map_checks.append(
                {
                    "mapSid": map_sid,
                    "mapPath": maps_dir / f"{map_sid}.map",
                    "mission": mission,
                    "missionLabel": member,
                    "missionId": mission_id,
                }
            )
        # When Good2 is also installed, include its missions so LocKit gaps fail closed.
        good2_hub = "campaigns/homm3_02_roe_castle_good2/storyHub.json"
        if good2_hub in source.namelist():
            for mission_id in (
                "steadwick_liberation",
                "deal_with_the_devil",
                "neutral_affairs",
                "tunnels_and_troglodytes",
            ):
                member = (
                    "campaigns/homm3_02_roe_castle_good2/missions/"
                    f"homm3_roe_castle_{mission_id}.json"
                )
                if member not in source.namelist():
                    continue
                mission = json.loads(source.read(member).decode("utf-8-sig"))
                variant = ((mission.get("array") or [{}])[0].get("variants") or [{}])[0]
                map_sid = variant.get("mapSid")
                if not isinstance(map_sid, str) or not map_sid:
                    continue
                map_checks.append(
                    {
                        "mapSid": map_sid,
                        "mapPath": maps_dir / f"{map_sid}.map",
                        "mission": mission,
                        "missionLabel": member,
                        "missionId": mission_id,
                    }
                )
    for issue in run_installed_campaign_preflight(
        game_root=game_root,
        core_zip=core_zip,
        map_checks=map_checks,
    ):
        errors.append(issue.format())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--game-root", type=Path, default=DEFAULT_GAME_ROOT)
    parser.add_argument("--skip-regenerate", action="store_true")
    parser.add_argument(
        "--require-installed",
        action="store_true",
        help="Fail unless Core.zip already contains the hub (post-install CI mode).",
    )
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    game_root = args.game_root.resolve()

    policy_path = repo_root / "scenarios" / "roe_castle_campaign" / "continuity_carry_policy.v1.json"
    batch_path = repo_root / "scenarios" / "roe_castle_campaign" / "batch_manifest.json"
    out_dir = (
        repo_root
        / "artifacts"
        / "campaign_port_poc"
        / "roe_castle_campaign"
        / "continuity_weave"
    )
    weave_path = out_dir / "continuity.weave.v1.json"
    plugin_cs = (
        repo_root
        / "Heroes of Might & Magic Olden Era Playtest"
        / "OfflineUnlockMod"
        / "Plugin.cs"
    )
    contract_cs = (
        repo_root
        / "Heroes of Might & Magic Olden Era Playtest"
        / "OfflineUnlockMod"
        / "Homm3CampaignContinuityContract.cs"
    )
    symbols_cs = (
        repo_root
        / "Heroes of Might & Magic Olden Era Playtest"
        / "OfflineUnlockMod"
        / "GameSymbols.cs"
    )

    policy = load_json(policy_path)
    batch = load_json(batch_path)
    errors: list[str] = []
    _validate_composed_softsub_prolog_contract(errors)

    require(policy.get("schema") == SCHEMA_POLICY, f"carry policy schema must be {SCHEMA_POLICY}", errors)
    require(policy["nativeTransfer"]["requiredValue"] is True, "policy must require transfer true", errors)
    require(
        (policy.get("storyHubMapSidOverrides") or {}).get("homecoming")
        == "h3_roe_castle_homecoming_raw_translation",
        "carry policy must override Homecoming StoryHub mapSid to raw_translation",
        errors,
    )

    if not args.skip_regenerate:
        regenerate(repo_root, game_root)

    weave = load_json(weave_path)
    core_installed = detect_core_installed(game_root)
    # Installed Story_maps / Core SID checks are opt-in. A partial Golden Era hub marker
    # must not auto-promote this gate — that forced SkipRoeCastleContinuityContract on
    # every plugin build while AGENTS.md still marks the payload unproven.
    expect_installed = bool(args.require_installed)

    # Regenerating wipe installStatus back to not_installed; if Core already has the hub,
    # re-mark the weave artifact so validators and docs stay coherent.
    if core_installed and weave.get("coreZipLayout", {}).get("installStatus") != "installed":
        weave["coreZipLayout"]["installStatus"] = "installed"
        weave_path.write_text(
            json.dumps(weave, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    if core_installed and not expect_installed:
        print(
            "RoE Castle continuity: Core hub markers detected but installed-payload checks "
            "are skipped (pass --require-installed after continuity installer readiness)."
        )

    validate_weave(
        weave,
        policy,
        batch,
        repo_root=repo_root,
        expect_installed=expect_installed,
        starting_resources=expected_starting_resources_table(repo_root),
        errors=errors,
    )
    validate_split_payloads(out_dir, weave, errors)
    validate_plugin_untouched(plugin_cs, errors)
    validate_intro_skip_publisher_only(
        repo_root
        / "Heroes of Might & Magic Olden Era Playtest"
        / "OfflineUnlockMod",
        errors,
    )
    validate_csharp_contract(
        contract_cs,
        policy,
        expect_installed=expect_installed,
        errors=errors,
    )
    validate_game_symbols(symbols_cs, errors)

    if expect_installed:
        if not core_installed:
            errors.append(
                "--require-installed set but Core.zip lacks campaigns/homm3_01_roe_castle_good1/"
            )
        else:
            validate_installed_core(game_root, weave, errors)

    if errors:
        print("RoE Castle continuity contract FAILED:", file=sys.stderr)
        for err in errors:
            print(f"- {err}", file=sys.stderr)
        return 1

    print("RoE Castle campaign continuity contract OK")
    print(f"  hub={HUB_SID}")
    print("  transferHeroProgressFromSession=true")
    print("  handoff=homecoming->guardian_angels (levelCap=6, strongest=4)")
    print(f"  homecomingMapSid={weave['homecomingMapSidChoice']['mapSid']}")
    print(f"  installStatus={weave.get('coreZipLayout', {}).get('installStatus')}")
    print(f"  coreInstalled={core_installed}")
    print("  playable-shell CampaignInfo remains empty")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
