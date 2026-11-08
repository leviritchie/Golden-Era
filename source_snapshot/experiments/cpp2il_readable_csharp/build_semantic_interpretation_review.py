#!/usr/bin/env python3
"""Write a static semantic interpretation layer over post-native method reviews."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

INTERPRETATIONS: dict[str, dict[str, str]] = {
    "Hex.Session.UI.BhBattleTimers::yta": {
        "claim": "Battle timer side/UI update helper, not a reliable Map semantic alias.",
        "support": "Signature takes TransferSide, BhTimer, and bool; native body calls BhTimer.smd and GameObject.SetActive.",
        "outcome": "contradicts-mono-alias",
        "next": "Do not use the old Mono ordinal alias for map semantics. If needed, map this through battle timer UI callsites only.",
    },
    "Hex.Session.Data.DataTimerSide::bfvx": {
        "claim": "Tiny timer-side float mutation/accessor.",
        "support": "Signature is void(float); native body has one write-like move and no direct calls; inbound call from BhSoundMapObject::Awake exists.",
        "outcome": "static-exhausted-accessor",
        "next": "Static body cannot prove timer lifecycle semantics beyond a value write. Runtime/order proof is required for timing behavior.",
    },
    "Hex.Session.Battle.BhUnitWindowPartyView::Awake": {
        "claim": "Current-only battle/unit window party view Awake/init path, adjacent to city upgrade slot UI.",
        "support": "Native body has outbound calls including BhUpgradeUnitSlot.baoe and unit data access; no Mono alias was found.",
        "outcome": "current-only-static-body",
        "next": "Keep as current-only type. Do not force a Mono alias unless a neighboring readable type emerges.",
    },
    "Hex.ResManager::bmvo": {
        "claim": "Resource manager string asset lookup/load entrypoint.",
        "support": "Signature takes string and returns obfuscated asset type; inbound from config/map/timeline asset consumers; outbound to ResManager singleton and loader helpers.",
        "outcome": "supported-static-semantic",
        "next": "Strong static candidate for asset lookup identity. Runtime proof still needed before hook/invocation claims.",
    },
    "Hex.Session.Battle.BhUnitWindowMain::bevm": {
        "claim": "Battle unit-window main Set/update method for a Session.Data.Unit plus string key/name.",
        "support": "Signature takes Unit and string; outbound calls include Unit.bgkt, GameObject.SetActive, UI animation, and checkbox/HUD helpers.",
        "outcome": "supported-static-semantic",
        "next": "Good static identity for unit-window UI binding. Not gameplay state mutation proof.",
    },
    "Hex.Session.Battle.UnitData::bfda": {
        "claim": "Simple integer UnitData accessor used by battle unit-window UI.",
        "support": "Native body has no calls/branches/writes and returns int; inbound from BhUnitWindow and BhBattleUnitInfoView.",
        "outcome": "static-exhausted-accessor",
        "next": "Static disassembly cannot name the integer field. Use callsite context or runtime metadata/value probes if field semantics matter.",
    },
    "Hex.BhHireUnitAbilities::huo": {
        "claim": "Hire-unit ability UI row/item builder, not a constructor alias.",
        "support": "Signature returns int and takes ability logic/view configs; calls BhHireUnitAbilityItemView.banm, bzd.pna, IsNullOrEmpty, GameObject.SetActive.",
        "outcome": "contradicts-mono-alias",
        "next": "Reject noisy constructor/ordinal alias. Use as city hire ability UI evidence only.",
    },
    "Hex.Map.MapObjects::opo": {
        "claim": "Map object resource/visual setup path, not enough evidence for collection Contains semantics.",
        "support": "Native body calls ResManager.bmvo, String.Format, Object.op_Equality, and bve.ope; branch-heavy setup body.",
        "outcome": "weak-static-semantic",
        "next": "Use only as map-object visual/resource setup candidate. Do not treat as generic Contains without stronger callsite proof.",
    },
    "Hex.Session.Battle.BhUnitWindow::beut": {
        "claim": "Battle unit-window stat/subview update for a Unit parameter, not proven locale-change handling.",
        "support": "Signature takes Session.Data.Unit; outbound calls BhUnitWindowStats.bewg; no localization/text-anchor proof in native review.",
        "outcome": "contradicts-or-weakens-mono-alias",
        "next": "Do not rely on OnChangeLocale alias. Treat as unit-window update until localization callsites prove otherwise.",
    },
    "Hex.Session.Data.BuildingData::bgch": {
        "claim": "BuildingConfigBase getter/lookup from building data.",
        "support": "Signature returns BuildingConfigBase; calls ObjCityConfig.ryu and ObjectConfigs.rza; 23 inbound edges from building/city users.",
        "outcome": "contradicts-mono-alias",
        "next": "Reject OnCreateOverriden alias. Use as building config lookup only.",
    },
    "Hex.Session.Data.DataMagics::bfts": {
        "claim": "MagicData create/get-by-string-and-int helper, not Delete.",
        "support": "Signature returns MagicData, takes string/int, and native body calls a constructor-like target; no list remove/delete evidence.",
        "outcome": "contradicts-mono-alias",
        "next": "Reject Delete alias. Search neighboring DataMagics methods if actual delete/remove semantics are needed.",
    },
    "Hex.ResManager::bmvh": {
        "claim": "Resource manager singleton/accessor/init path.",
        "support": "Signature returns Hex.ResManager; inbound from ResManager loaders, SoundManager.Init, custom battle/map editor, and tools; outbound to GameObject construction/AddComponent.",
        "outcome": "supported-static-semantic",
        "next": "Strong static candidate for ResManager singleton identity. Runtime proof still needed for lifecycle timing.",
    },
    "Hex.Session.Hud.BhSideTimers::vwm": {
        "claim": "Side timer HUD helper involving side data and BhTimer, plausibly a timer-work check/update but not exact enough for CheckIsWorkTimer semantics.",
        "support": "Signature takes fda and BhTimer; calls BhTimer.sly, fda.bjbr/bjdf, HeroStat.bfyu; inbound/outbound native evidence exists.",
        "outcome": "weak-static-semantic",
        "next": "Use as timer HUD adjacency only. Runtime/order proof required for work-timer logic.",
    },
    "Hex.Session.Hud.BhHeroHUDPanel::vtz": {
        "claim": "Hero HUD panel update/binding helper using Hero and HeroConfig, not proven death check.",
        "support": "Native body calls Hero.bfwx, HeroConfig.rwv, and io.hmo; no death-state anchor appears in reviewed evidence.",
        "outcome": "contradicts-or-weakens-mono-alias",
        "next": "Do not rely on CheckOnDeath alias. Treat as hero HUD config/binding helper unless death callsites are proven.",
    },
    "Hex.Session.Hud.BhSideTimers::vwu": {
        "claim": "Side timer HUD day/start update adjacency, but exact UpdateStartDay semantics remain unproven.",
        "support": "Signature takes fda; native body has inbound/outbound edges, object equality checks, and timer/HUD-adjacent calls but no clear day-start anchor.",
        "outcome": "weak-static-semantic",
        "next": "Keep below exact semantic proof. Runtime day-start ordering or stronger caller labels needed.",
    },
    "Hex.Sound.SoundsManager::bmtu": {
        "claim": "SoundMixersManager accessor used by drag/drop UI sound paths.",
        "support": "Signature returns SoundMixersManager; native body is call-free; inbound from UnitSlot/Bags/HeroSlot OnDrop methods.",
        "outcome": "static-exhausted-accessor",
        "next": "Accessor identity is static; playback behavior and mixer side effects require caller/runtime evidence.",
    },
    "Hex.Session.Battle.Obstacle::bbcp": {
        "claim": "Simple Obstacle data accessor returning eac.",
        "support": "Native body has no calls/branches/writes; inbound from tactics/battle UI paths.",
        "outcome": "static-exhausted-accessor",
        "next": "Static disassembly cannot name eac semantics. Use caller context or runtime metadata if obstacle field meaning matters.",
    },
    "Hex.Session.UI.BhChimerologist::giz": {
        "claim": "Chimerologist screen OnInit/UI construction method.",
        "support": "Native body calls BhScreen.giz, BhGenericButton.Init, BuffData constructor, and multiple UI/config helpers.",
        "outcome": "supported-static-semantic",
        "next": "Good static OnInit candidate for UI initialization. Not gameplay behavior proof.",
    },
    "Hex.UI.City.BhCityUISession::uax": {
        "claim": "City UI session view/navigation update, plausibly hero/town view switching but not exact SetHeroesView proof.",
        "support": "Native body calls BhTownInput.banq, BhHUDSession.vvd, BhCityInfoGroup.OnHide, BhNavigationView.OnDeselect.",
        "outcome": "weak-static-semantic",
        "next": "Use as city UI navigation/session evidence. Runtime/UI state proof needed for exact SetHeroesView behavior.",
    },
    "Hex.UI.HeroView.BhSubClassView::tqm": {
        "claim": "Current-only hero subclass UI binder.",
        "support": "Existing dossier and native body show Hero/HeroConfig/sprite/UI binding calls; no Mono alias exists.",
        "outcome": "current-only-static-body",
        "next": "Keep as current-only semantic node in the map.",
    },
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def current_method(row: dict[str, Any]) -> str:
    if row.get("reviewedSide") == "target":
        return f"{row.get('targetType')}::{row.get('targetMethod')}"
    return f"{row.get('callerType')}::{row.get('callerMethod')}"


def load_native_reviews(root: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name in [
        "native_disasm_method_review_high_priority.json",
        "native_disasm_method_review_weak_static.json",
        "native_disasm_method_review_reject_remap.json",
        "native_disasm_method_review_current_only_types.json",
    ]:
        data = load_json(root / name)
        for row in data.get("rows") or []:
            item = dict(row)
            item["reviewFile"] = name
            out[row["method"]] = item
    return out


def build(queue: dict[str, Any], native_reviews: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows = []
    summary: dict[str, int] = {}
    missing = []
    for row in queue.get("rows") or []:
        method = current_method(row)
        interpretation = INTERPRETATIONS.get(method)
        native = native_reviews.get(method)
        if not interpretation or not native:
            missing.append({"method": method, "hasInterpretation": bool(interpretation), "hasNativeReview": bool(native)})
            continue
        out = {
            "path": row.get("path"),
            "current": method,
            "postReviewAction": row.get("postReviewAction"),
            "priorAction": row.get("action"),
            "reviewedSide": row.get("reviewedSide"),
            "monoCandidate": row.get("callerMonoMethodCandidate"),
            "claim": interpretation["claim"],
            "support": interpretation["support"],
            "outcome": interpretation["outcome"],
            "next": interpretation["next"],
            "nativeStatus": native.get("status"),
            "nativeReviewFile": native.get("reviewFile"),
            "bodyMatchCount": native.get("bodyMatchCount"),
            "inboundEdgeCount": native.get("inboundEdgeCount"),
            "outboundEdgeCount": native.get("outboundEdgeCount"),
        }
        rows.append(out)
        summary[out["outcome"]] = summary.get(out["outcome"], 0) + 1
    return {
        "schema": "static-semantic-interpretation-review.v1",
        "evidenceBoundary": "Static interpretation from post-review queue plus exact native disassembly reviews. Outcomes do not prove runtime order, reachability, hook safety, or gameplay behavior.",
        "summary": {
            "rows": len(rows),
            "missingInterpretations": len(missing),
            "outcomes": dict(sorted(summary.items())),
        },
        "rows": rows,
        "missing": missing,
    }


def write_md(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Static Semantic Interpretation Review",
        "",
        "Status: static-only. Runtime-unvalidated.",
        "",
        report["evidenceBoundary"],
        "",
        "## Summary",
        "",
        f"- Rows: `{report['summary']['rows']}`",
        f"- Missing interpretations: `{report['summary']['missingInterpretations']}`",
        f"- Outcomes: `{report['summary']['outcomes']}`",
        "",
        "## Rows",
        "",
        "| Outcome | Path | Current | Static claim | Static support | Next boundary |",
        "|---|---|---|---|---|---|",
    ]
    for row in report.get("rows") or []:
        claim = row["claim"].replace("|", "\\|")
        support = row["support"].replace("|", "\\|")
        nxt = row["next"].replace("|", "\\|")
        lines.append(f"| `{row['outcome']}` | `{row['path']}` | `{row['current']}` | {claim} | {support} | {nxt} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", type=Path, required=True)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--out-json", type=Path, required=True)
    ap.add_argument("--out-md", type=Path, required=True)
    args = ap.parse_args()
    report = build(load_json(args.queue), load_native_reviews(args.root))
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_md(report, args.out_md)
    print(json.dumps(report["summary"], indent=2))
    return 0 if not report["missing"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
