#!/usr/bin/env python3
"""Validate the fail-closed semantic coverage gate used by scenario emission."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--expect-current-incomplete",
        action="store_true",
        help="legacy pin: require the committed Homecoming substitution artifact to fail coverage",
    )
    parser.add_argument(
        "--expect-current-complete",
        action="store_true",
        help="require the committed Homecoming substitution artifact to pass coverage",
    )
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    sys.path.insert(0, str(repo_root / "experiments" / "campaign_port_poc"))

    import scenario_semantic_coverage as coverage

    errors: list[str] = []
    direct = {
        "invalidEntitySubstitutions": [{
            "sourceSignature": "direct",
            "replacementSid": "native-object",
            "lossiness": "direct_or_family_substitution",
            "count": 1,
        }],
    }
    direct_report = coverage.semantic_coverage_report(direct)
    require(direct_report["complete"], "direct substitution should pass coverage", errors)

    unsafe = {
        "invalidEntitySubstitutions": [{
            "sourceSignature": "fallback",
            "replacementSid": "pinetree_1",
            "lossiness": "lossy_placeholder",
            "ruleName": "universal_scenery_fallback",
            "count": 2,
        }],
    }
    unsafe_report = coverage.semantic_coverage_report(
        unsafe,
        emission_stats={"deferredNonStartHeroSpawnerCount": 1},
    )
    require(not unsafe_report["complete"], "placeholder/deferred sample must fail coverage", errors)
    require(unsafe_report["substitutionUnsafeInstanceCount"] == 2, "unsafe sample count mismatch", errors)
    try:
        coverage.require_complete_semantic_coverage(unsafe, scenario_id="fixture")
    except coverage.ScenarioSemanticCoverageError:
        pass
    else:
        errors.append("unsafe sample did not raise ScenarioSemanticCoverageError")

    blocked = {
        "invalidEntitySubstitutions": [{
            "sourceSignature": "blocked-contract",
            "replacementSid": None,
            "lossiness": "blocked",
            "ruleName": "explicit_block_contract",
            "count": 3,
        }],
    }
    blocked_report = coverage.semantic_coverage_report(blocked)
    require(not blocked_report["complete"], "blocked substitution contract must fail coverage", errors)
    require(blocked_report["substitutionUnsafeInstanceCount"] == 3, "blocked sample count mismatch", errors)
    try:
        coverage.require_complete_semantic_coverage(blocked, scenario_id="fixture-blocked")
    except coverage.ScenarioSemanticCoverageError:
        pass
    else:
        errors.append("blocked sample did not raise ScenarioSemanticCoverageError")

    deferred_blocked_emission = {
        "invalidEntitySubstitutions": [{
            "sourceSignature": "direct",
            "replacementSid": "native-object",
            "lossiness": "direct_or_family_substitution",
            "count": 1,
        }],
    }
    deferred_blocked_report = coverage.semantic_coverage_report(
        deferred_blocked_emission,
        emission_stats={"deferredBlockedEntityCount": 2},
    )
    require(not deferred_blocked_report["complete"], "deferred blocked emission must fail coverage", errors)

    artifact_path = (
        repo_root
        / "artifacts"
        / "campaign_port_poc"
        / "homecoming_poc"
        / "entity_substitutions"
        / "homecoming.olden_entity_substitution_map.json"
    )
    if args.expect_current_incomplete or args.expect_current_complete:
        require(artifact_path.is_file(), f"missing Homecoming substitution artifact: {artifact_path}", errors)
        if artifact_path.is_file():
            artifact = json.loads(artifact_path.read_text(encoding="utf-8-sig"))
            artifact_report = coverage.semantic_coverage_report(artifact)
            if args.expect_current_incomplete:
                require(
                    not artifact_report["complete"],
                    "current Homecoming substitution artifact must be classified incomplete",
                    errors,
                )
            if args.expect_current_complete:
                require(
                    artifact_report["complete"],
                    "current Homecoming substitution artifact must be classified complete",
                    errors,
                )
                blocked_entries = [
                    entry for entry in (artifact.get("invalidEntitySubstitutions") or [])
                    if isinstance(entry, dict)
                    and (entry.get("replacementSid") is None or entry.get("lossiness") == "blocked")
                ]
                require(
                    not blocked_entries,
                    f"current Homecoming substitution artifact must have zero blocked signatures, found {len(blocked_entries)}",
                    errors,
                )

    if errors:
        print("Scenario semantic coverage contract FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Scenario semantic coverage contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
