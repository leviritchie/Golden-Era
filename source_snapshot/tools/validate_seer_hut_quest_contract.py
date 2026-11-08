#!/usr/bin/env python3
"""Fail-closed gate for the confirmed HoMM3 Seer's Hut QuestScript FSM shape.

Pins the user-proven stage machine in ``seer_hut_quest.compile_seer_quest_subquests``.
Does not prove runtime behavior on maps other than the documented Steadwick proof.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
POC = ROOT / "experiments" / "campaign_port_poc"
DOC = ROOT / "docs" / "homm3_seer_hut_questscript.md"


def _fail(message: str) -> None:
    raise SystemExit(f"FAIL validate_seer_hut_quest_contract: {message}")


def _require(cond: bool, message: str) -> None:
    if not cond:
        _fail(message)


def _condition_ops(trigger: dict[str, Any]) -> list[str]:
    return [str(row.get("c") or "") for row in (trigger.get("conditions") or []) if isinstance(row, dict)]


def _action_ops(trigger: dict[str, Any]) -> list[tuple[str, list[Any]]]:
    out: list[tuple[str, list[Any]]] = []
    for row in trigger.get("actions") or []:
        if isinstance(row, dict) and row.get("a"):
            params = row.get("p") if isinstance(row.get("p"), list) else []
            out.append((str(row["a"]), list(params)))
    return out


def validate_compile_shape() -> dict[str, Any]:
    if str(POC) not in sys.path:
        sys.path.insert(0, str(POC))
    from seer_hut_quest import (  # noqa: WPS433
        SeerMissionBringArtifacts,
        SeerQuestPlan,
        SeerQuestTexts,
        SeerRewardExperience,
        compile_seer_quest_subquests,
    )

    plan = SeerQuestPlan(
        quest_id="contract_seer",
        hut_entity_sid="contract_hut",
        state_counter_sid="contract_seer_state",
        mission=SeerMissionBringArtifacts(item_sids=("contract_item",)),
        reward=SeerRewardExperience(amount=100),
        texts=SeerQuestTexts("first", "next", "done"),
    )
    stages = compile_seer_quest_subquests(plan)
    expected_sids = [
        "contract_seer_offer",
        "contract_seer_incomplete",
        "contract_seer_ready",
        "contract_seer_complete",
    ]
    _require(len(stages) == 4, f"expected 4 stages, got {len(stages)}")
    _require(
        [row["sid"] for row in stages] == expected_sids,
        f"stage SIDs drifted: {[row['sid'] for row in stages]}",
    )
    _require(stages[0]["activeOnStart"] is True, "offer must be activeOnStart")
    _require(
        all(row["activeOnStart"] is False for row in stages[1:]),
        "only offer may be activeOnStart",
    )

    offer, incomplete, ready, complete = (row["triggers"][0] for row in stages)
    _require(_condition_ops(offer) == ["ObjectInteractionBefore"], "offer must be visit-only")
    _require(
        _condition_ops(incomplete) == ["ObjectInteractionBefore"],
        "incomplete must be visit-only",
    )
    _require(incomplete.get("repeat") is True, "incomplete must repeat")
    _require(_condition_ops(ready) == ["ItemOwnSide"], "ready must be item-own only")
    _require(
        _condition_ops(complete) == ["ObjectInteractionBefore"],
        "complete must be visit-only",
    )

    forbidden_and = {"Counter", "CounterEqualityInDays", "ItemOwnSide", "ResCounter", "UnitOwnSide"}
    for label, trigger in (
        ("offer", offer),
        ("incomplete", incomplete),
        ("complete", complete),
    ):
        ops = set(_condition_ops(trigger))
        mixed = ops & forbidden_and
        _require(
            not mixed,
            f"{label} illegally ANDs visit with {sorted(mixed)}",
        )

    offer_actions = _action_ops(offer)
    _require(
        ("SubQuestDeactivate", ["contract_seer", "contract_seer_offer"]) in offer_actions,
        "offer must SubQuestDeactivate itself",
    )
    _require(
        ("SubQuestActivate", ["contract_seer", "contract_seer_incomplete"]) in offer_actions,
        "offer must activate incomplete",
    )
    _require(
        ("SubQuestActivate", ["contract_seer", "contract_seer_ready"]) in offer_actions,
        "offer must activate ready",
    )
    ready_actions = _action_ops(ready)
    _require(
        ("SubQuestActivate", ["contract_seer", "contract_seer_complete"]) in ready_actions,
        "ready must activate complete",
    )
    _require(
        ("SubQuestDeactivate", ["contract_seer", "contract_seer_incomplete"]) in ready_actions,
        "ready must deactivate incomplete",
    )
    return {
        "stageSids": expected_sids,
        "proofBoundary": "source_static_compile_shape; steadwick_user_visible_gameplay_proven_separately",
    }


def validate_docs(repo: Path) -> None:
    _require(DOC.is_file(), f"missing {DOC.relative_to(repo)}")
    text = DOC.read_text(encoding="utf-8-sig")
    for needle in (
        "Confirmed FSM",
        "SubQuestDeactivate",
        "ObjectInteractionBefore",
        "propEntities.sid",
        "validate_seer_hut_quest_contract.py",
        "user-visible gameplay proven",
    ):
        _require(needle in text, f"docs/homm3_seer_hut_questscript.md missing {needle!r}")
    agents = (repo / "AGENTS.md").read_text(encoding="utf-8-sig")
    _require(
        "docs/homm3_seer_hut_questscript.md" in agents,
        "AGENTS.md must point at the Seer Hut QuestScript contract",
    )
    docs_readme = (repo / "docs" / "README.md").read_text(encoding="utf-8-sig")
    _require(
        "homm3_seer_hut_questscript.md" in docs_readme,
        "docs/README.md must index the Seer Hut QuestScript contract",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    validate_docs(repo)
    shape = validate_compile_shape()
    print(
        json.dumps(
            {
                "ok": True,
                "schema": "homm3.seer_hut_quest_contract.v1",
                "shape": shape,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
