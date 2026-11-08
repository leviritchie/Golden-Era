"""Select a Meshy 7.1 regeneration only when it beats the unit's source bind.

Regeneration is intentionally a routed repair, not a default for every unit.  This selector compares
the candidate and source through the same canonical-T-pose owned-bind audit and also checks welded
surface health.  A reference problem may keep both reports ``audit.ok == false``; that is recorded as
an upstream blocker and is not silently converted into a pass.  The selector only answers whether the
candidate is the better geometry candidate for the next reference-repair step.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


SCHEMA = "meshy71.candidate_selection.v1"
MAX_GEOMETRY_RATIO = 1.25
MAX_ESCAPE_RATIO = 0.90


def load(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"fail-closed: cannot read JSON report {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"fail-closed: report is not an object: {path}")
    return value


def finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SystemExit(f"fail-closed: {label} is not numeric")
    number = float(value)
    if not math.isfinite(number):
        raise SystemExit(f"fail-closed: {label} is not finite")
    return number


def select(args: argparse.Namespace) -> int:
    baseline_bind = load(Path(args.baseline_bind))
    candidate_bind = load(Path(args.candidate_bind))
    baseline_geometry = load(Path(args.baseline_geometry))
    candidate_geometry = load(Path(args.candidate_geometry))

    required_bind = (
        "maxEscapedFraction",
        "tearing",
    )
    for report, label in ((baseline_bind, "baseline bind"), (candidate_bind, "candidate bind")):
        audit = report.get("audit")
        if not isinstance(audit, dict):
            raise SystemExit(f"fail-closed: {label} has no audit object")
        for key in required_bind:
            if key not in audit:
                raise SystemExit(f"fail-closed: {label} audit has no {key}")
        if not isinstance(audit["tearing"], dict):
            raise SystemExit(f"fail-closed: {label} audit tearing is not an object")

    for report, label in ((baseline_geometry, "baseline geometry"), (candidate_geometry, "candidate geometry")):
        welded = report.get("welded")
        if not isinstance(welded, dict):
            raise SystemExit(f"fail-closed: {label} has no welded preflight")
        for key in ("boundaryEdges", "nonManifoldEdges", "componentCount"):
            if key not in welded:
                raise SystemExit(f"fail-closed: {label} welded preflight has no {key}")

    base_audit = baseline_bind["audit"]
    cand_audit = candidate_bind["audit"]
    base_geom = baseline_geometry["welded"]
    cand_geom = candidate_geometry["welded"]

    base_escape = finite_number(base_audit["maxEscapedFraction"], "baseline maxEscapedFraction")
    cand_escape = finite_number(cand_audit["maxEscapedFraction"], "candidate maxEscapedFraction")
    base_torn = finite_number(
        base_audit["tearing"]["edgesPastReviewLimit"], "baseline edgesPastReviewLimit"
    )
    cand_torn = finite_number(
        cand_audit["tearing"]["edgesPastReviewLimit"], "candidate edgesPastReviewLimit"
    )
    base_stretch = finite_number(base_audit["tearing"]["max"], "baseline max stretch")
    cand_stretch = finite_number(cand_audit["tearing"]["max"], "candidate max stretch")

    reasons: list[str] = []
    if int(cand_geom["componentCount"]) != 1:
        reasons.append("candidate welded surface is not one connected component")
    for key in ("boundaryEdges", "nonManifoldEdges"):
        base = max(1.0, finite_number(base_geom[key], f"baseline {key}"))
        candidate = finite_number(cand_geom[key], f"candidate {key}")
        if candidate > base * MAX_GEOMETRY_RATIO:
            reasons.append(f"candidate {key} grows beyond {MAX_GEOMETRY_RATIO:.2f}x source")

    if cand_escape > base_escape * MAX_ESCAPE_RATIO:
        reasons.append(
            f"candidate escape {cand_escape:.4%} is not at least {1.0 - MAX_ESCAPE_RATIO:.0%} below "
            f"source {base_escape:.4%}"
        )
    if cand_torn > base_torn:
        reasons.append(f"candidate reviewed stretch edges {cand_torn:.0f} exceed source {base_torn:.0f}")
    if cand_stretch > base_stretch:
        reasons.append(f"candidate worst stretch {cand_stretch:.3f} exceeds source {base_stretch:.3f}")

    selected = not reasons
    report = {
        "schema": SCHEMA,
        "proof": "generated-artifact",
        "unit": args.unit,
        "selected": selected,
        "route": "meshy71_canonical_tpose_candidate" if selected else "retain_source_owned_bind",
        "source": {
            "bind": str(Path(args.baseline_bind).resolve()).replace("\\", "/"),
            "geometry": str(Path(args.baseline_geometry).resolve()).replace("\\", "/"),
            "auditOk": bool(baseline_bind["audit"].get("ok")),
            "maxEscapedFraction": base_escape,
            "edgesPastReviewLimit": base_torn,
            "maxStretch": base_stretch,
            "welded": base_geom,
        },
        "candidate": {
            "bind": str(Path(args.candidate_bind).resolve()).replace("\\", "/"),
            "geometry": str(Path(args.candidate_geometry).resolve()).replace("\\", "/"),
            "variant": candidate_bind.get("candidateVariant"),
            "auditOk": bool(candidate_bind["audit"].get("ok")),
            "maxEscapedFraction": cand_escape,
            "edgesPastReviewLimit": cand_torn,
            "maxStretch": cand_stretch,
            "welded": cand_geom,
        },
        "policy": {
            "maxGeometryRatio": MAX_GEOMETRY_RATIO,
            "maxEscapeRatio": MAX_ESCAPE_RATIO,
            "reviewedStretchEdgesMustNotIncrease": True,
            "worstStretchMustNotIncrease": True,
            "auditOkIsNotOverridden": True,
        },
        "reasons": reasons,
        "upstreamReferenceBlockers": list(candidate_bind["audit"].get("issues", [])),
    }
    output = Path(args.out).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if selected else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", required=True)
    parser.add_argument("--baseline-bind", required=True)
    parser.add_argument("--candidate-bind", required=True)
    parser.add_argument("--baseline-geometry", required=True)
    parser.add_argument("--candidate-geometry", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    return select(args)


if __name__ == "__main__":
    raise SystemExit(main())
