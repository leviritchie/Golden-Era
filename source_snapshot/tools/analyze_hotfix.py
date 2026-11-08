#!/usr/bin/env python3
"""
analyze_hotfix.py — Integrated post-hotfix analysis.
Runs the full pipeline and produces a single actionable report.

Usage:
    python tools/analyze_hotfix.py --old-dump tools/il2cpp_out_20260506/dump.cs
        --new-dump tools/il2cpp_out_live/dump.cs
        --source "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod"
        --output tools/hotfix_analysis.json

Produces:
    {
        "summary": { ... quick stats ... },
        "critical_patches": [ ... findings that WILL cause runtime failures ... ],
        "changed_signatures": [ ... methods with changed params/types ... ],
        "gone_types": [ ... types completely removed ... ],
        "renamed_obfuscated": [ ... key obfuscated type renames affecting patches ... ],
        "recommended_actions": [ ... step-by-step fix suggestions ... ]
    }
"""

import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Any


def load_dump_index(dump_path: str) -> Dict:
    """Load a dump.cs and return lightweight index."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from map_obfuscation import parse_dump

    classes = parse_dump(dump_path)
    index = {}
    for full_name, info in classes.items():
        entry = {
            'methods': {},
            'fields': {},
            'short_name': info.name,
        }
        for mname, params, ret in info.methods:
            entry['methods'][mname] = {'params': params, 'return': ret}
        for fname, ftype in info.fields:
            entry['fields'][fname] = ftype
        index[full_name] = entry
    return index


def find_method_alternatives(dump_index: Dict, type_name: str, old_method: str) -> List[str]:
    """Suggest alternative method names on a type for a missing method."""
    if type_name not in dump_index:
        return []
    methods = dump_index[type_name]['methods']
    # Return methods with similar parameter count (fuzzy)
    return sorted(methods.keys())


def analyze(hotfix_report: str) -> Dict[str, Any]:
    """Produce actionable analysis from a hotfix pipeline report."""
    if isinstance(hotfix_report, str):
        with open(hotfix_report, 'r') as f:
            report = json.load(f)
    else:
        report = hotfix_report

    findings = report.get('patch_findings', [])
    rename_map = report.get('rename_map', {})
    type_renames = rename_map.get('type_renames', {}) if isinstance(rename_map, dict) else {}

    analysis: Dict[str, Any] = {
        "summary": {},
        "critical_patches": [],
        "changed_signatures": [],
        "gone_types": [],
        "renamed_types_affecting_patches": {},
        "recommended_actions": [],
    }

    fatal = [f for f in findings if f.get('severity') == 'fatal']
    high = [f for f in findings if f.get('severity') == 'high']

    analysis["summary"] = {
        "total_findings": len(findings),
        "fatal": len(fatal),
        "high": len(high),
        "affected_source_files": sorted(set(
            loc.split(':')[0] for f in (fatal + high)
            for loc in f.get('source_locations', [])
        )),
    }

    # Clone rename map for augmentation
    analysis["renamed_types_affecting_patches"] = {}
    for f in findings:
        t = f.get('type', '')
        sn = t.split('.')[-1]
        if sn in type_renames:
            analysis["renamed_types_affecting_patches"][t] = type_renames[sn]

    for f in fatal:
        kind = f.get('kind', '?')
        typ = f.get('type', '?')
        member = f.get('member', '?')
        sources = f.get('source_locations', [])

        entry = {
            "type": typ,
            "member": member,
            "kind": kind,
            "sources": sources,
        }

        if kind == 'PATCH_ORPHAN':
            analysis["critical_patches"].append({
                **entry,
                "problem": f"Method '{member}' no longer exists on '{typ}'.",
                "suggested_action": f"Inspect current methods on '{typ}': find equivalent by parameter shape.",
            })
            analysis["recommended_actions"].append(
                f"[{typ}.{member}] ORPHANED — check dump.cs for replacement method on {typ}."
            )

        elif kind == 'PATCH_TYPE_GONE':
            analysis["gone_types"].append({
                **entry,
                "problem": f"Type '{typ}' not found in new build dump.",
                "suggested_action": "Check if type was renamed (structural match) or genuinely removed.",
            })
            sn = typ.split('.')[-1]
            if sn in type_renames:
                analysis["renamed_types_affecting_patches"][typ] = type_renames[sn]
                analysis["recommended_actions"].append(
                    f"[{typ}] RENAMED to '{type_renames[sn]}' — apply rename and verify method parity."
                )
            else:
                analysis["recommended_actions"].append(
                    f"[{typ}] GONE — no structural match found. Find replacement type or retire patch."
                )

        elif kind == 'PATCH_SIG_MISMATCH':
            analysis["changed_signatures"].append({
                **entry,
                "problem": f"Method '{member}' exists but signature changed.",
                "expected": f.get('expected_sig', '?'),
                "actual": f.get('actual_sig', '?'),
                "suggested_action": "Update Harmony patch parameter types to match new signature.",
            })
            analysis["recommended_actions"].append(
                f"[{typ}.{member}] SIGNATURE CHANGED — update patch params."
            )

    for f in high:
        kind = f.get('kind', '?')
        typ = f.get('type', '?')
        member = f.get('member', '?')
        sources = f.get('source_locations', [])

        if kind == 'PATCH_FIELD_TYPE':
            analysis["changed_signatures"].append({
                "type": typ, "member": member, "kind": kind, "sources": sources,
                "problem": f"Field '{member}' type changed: {f.get('expected_type','?')} -> {f.get('actual_type','?')}.",
                "suggested_action": "Update field access code for new type.",
            })
        elif kind == 'PATCH_MEMBER_MISSING':
            analysis["critical_patches"].append({
                "type": typ, "member": member, "kind": kind, "sources": sources,
                "problem": f"Property/field '{member}' no longer exists on '{typ}'.",
                "suggested_action": "Find equivalent property on the type.",
            })
        elif kind == 'PATCH_CTOR_SIG_MISMATCH':
            analysis["critical_patches"].append({
                "type": typ, "member": ".ctor", "kind": kind, "sources": sources,
                "problem": f"Constructor signature changed on '{typ}'.",
                "suggested_action": "Update AccessTools.Constructor parameter types.",
            })

    return analysis


def print_analysis(analysis: Dict[str, Any]):
    """Print a human-readable analysis report."""
    s = analysis["summary"]
    print(f"\n{'=' * 70}")
    print(f"HOTFIX ANALYSIS REPORT")
    print(f"{'=' * 70}")
    print(f"  Findings: {s['total_findings']} ({s['fatal']} fatal, {s['high']} high)")
    print(f"  Affected files: {len(s['affected_source_files'])}")

    if analysis["renamed_types_affecting_patches"]:
        print(f"\n--- RENAMED TYPES (structural matches) ---")
        for old, new in analysis["renamed_types_affecting_patches"].items():
            print(f"  {old}  →  {new}")

    if analysis["gone_types"]:
        print(f"\n--- GONE TYPES (no structural match) ---")
        for g in analysis["gone_types"]:
            print(f"  {g['type']}: {g['problem']}")

    if analysis["critical_patches"]:
        print(f"\n--- CRITICAL PATCH ISSUES ---")
        for c in analysis["critical_patches"]:
            print(f"  [{c['kind']}] {c['type']}.{c['member']}")
            print(f"    {c['problem']}")
            sources = c.get('sources', [])[:2]
            for s in sources:
                print(f"    Source: {s}")

    if analysis["changed_signatures"]:
        print(f"\n--- SIGNATURE CHANGES ---")
        for cs in analysis["changed_signatures"]:
            print(f"  [{cs['kind']}] {cs['type']}.{cs['member']}: {cs['problem']}")

    if analysis["recommended_actions"]:
        print(f"\n--- RECOMMENDED ACTIONS ---")
        for i, action in enumerate(analysis["recommended_actions"], 1):
            print(f"  {i}. {action}")

    print()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Analyze hotfix impact from verify_patch_surfaces report.")
    parser.add_argument("report", help="Path to verify_patch_surfaces JSON output")
    parser.add_argument("--dump", help="Path to new dump.cs (for method suggestions)")
    parser.add_argument("--output", "-o", help="Output JSON analysis path")
    args = parser.parse_args()

    with open(args.report, 'r') as f:
        report = json.load(f)

    analysis = analyze(report)

    if args.dump:
        print(f"Loading dump for method suggestions: {args.dump}")
        dump_index = load_dump_index(args.dump)
        # Augment orphan findings with alternative methods
        for i, finding in enumerate(analysis.get("critical_patches", [])):
            if finding["kind"] == "PATCH_ORPHAN":
                alts = find_method_alternatives(dump_index, finding["type"], finding["member"])
                if alts:
                    analysis["critical_patches"][i]["available_methods"] = alts[:10]

    print_analysis(analysis)

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(analysis, f, indent=2)
        print(f"Written to: {args.output}")


if __name__ == '__main__':
    main()
