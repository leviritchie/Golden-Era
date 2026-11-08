#!/usr/bin/env python3
"""
decompile_surfaces.py — Decompile specific game types from the IL2CPP interop
Hex.dll using ILSpy, focused on types that verify_patch_surfaces flagged as broken.

Usage:
    python tools/decompile_surfaces.py <verify_report.json> --hex-dll <path/to/Hex.dll>
        --ilspy <path/to/ilspycmd.exe> [--output-dir tools/_tmp_patch_decomp/]

The output is a set of individual .cs files (one per type) plus an index.json
mapping each type to the findings that triggered the decompile.
"""

import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set


def load_verify_report(report_path: str) -> List[Dict]:
    """Load findings from a verify_patch_surfaces report."""
    with open(report_path, 'r') as f:
        report = json.load(f)
    return report.get("patch_findings", [])


def gather_types_to_decompile(findings: List[Dict]) -> Dict[str, List[Dict]]:
    """
    Extract unique types from FATAL/HIGH findings, grouped by type.
    Skips types that are clearly runtime-resolved or mod-internal.
    """
    type_findings = defaultdict(list)
    for f in findings:
        sev = f.get("severity", "")
        if sev not in ("fatal", "high"):
            continue

        type_name = f.get("type", "")
        # Skip runtime-resolved and mod-internal types
        if (
            type_name.startswith("<runtime:")
            or type_name in ("CanvasScaler", "VideoPlayer", "Image", "RawImage")
            or type_name.startswith("UnityEngine.")
            or type_name == "Homm3StrongholdCityMusic"
        ):
            continue

        type_findings[type_name].append(f)

    return type_findings


def decompile_types(
    type_names: List[str],
    hex_dll: str,
    ilspy_exe: str,
    output_dir: str,
) -> Dict[str, Optional[str]]:
    """
    Decompile specific types from Hex.dll using ILSpy.
    Returns {type_name: output_file_path or None if failed}.
    """
    results = {}

    for type_name in type_names:
        safe_name = type_name.replace('.', '_').replace('<', '_').replace('>', '_')
        out_file = os.path.join(output_dir, f"{safe_name}.cs")

        # Try exact type name first, then try with "Hex." prefix
        candidates = [type_name]
        if not type_name.startswith("Hex."):
            candidates.append(f"Hex.{type_name}")

        decompiled = False
        for candidate in candidates:
            cmd = [
                ilspy_exe,
                hex_dll,
                "-t", candidate,
                "-o", out_file,
            ]
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=30
                )
                if result.returncode == 0 and os.path.exists(out_file):
                    content = Path(out_file).read_text(encoding='utf-8', errors='replace')
                    if content.strip() and 'class ' in content:
                        decompiled = True
                        break
            except Exception:
                pass

        if decompiled:
            results[type_name] = out_file
            print(f"  Decompiled: {type_name} -> {out_file}")
        else:
            results[type_name] = None
            # Try list mode to find actual type name
            list_file = os.path.join(output_dir, f"_list_{safe_name}.txt")
            try:
                subprocess.run(
                    [ilspy_exe, hex_dll, "-l", "t", "-o", list_file],
                    capture_output=True, timeout=30
                )
                if os.path.exists(list_file):
                    with open(list_file, 'r') as lf:
                        matching = [ln.strip() for ln in lf if candidate.split('.')[-1] in ln]
                    if matching:
                        print(f"  NOT FOUND: {type_name} — try one of: {matching[:5]}")
                    else:
                        print(f"  NOT FOUND: {type_name} — no matching types in assembly")
            except Exception:
                print(f"  NOT FOUND: {type_name}")

    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Decompile patched types flagged by verify_patch_surfaces."
    )
    parser.add_argument("verify_report", help="verify_patch_surfaces JSON output")
    parser.add_argument("--hex-dll", default=r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\BepInEx\interop\Hex.dll",
                        help="Path to the live Hex.dll interop assembly")
    parser.add_argument("--ilspy", default=r"tools\dotnet-tools\ilspycmd.exe",
                        help="Path to ilspycmd.exe")
    parser.add_argument("--output-dir", "-o", default="tools/_tmp_patch_decomp",
                        help="Output directory for decompiled files")
    parser.add_argument("--severity", default="fatal,high",
                        help="Which severity levels to decompile (comma-separated)")
    args = parser.parse_args()

    sev_filter = set(s.strip() for s in args.severity.split(','))

    print(f"Loading verify report: {args.verify_report}")
    findings = load_verify_report(args.verify_report)
    print(f"  {len(findings)} findings total")

    # Filter by severity
    findings = [f for f in findings if f.get("severity", "") in sev_filter]
    print(f"  {len(findings)} findings at severity {sev_filter}")

    type_findings = gather_types_to_decompile(findings)

    if not type_findings:
        print("\nNo types to decompile.")
        return

    print(f"\nTypes flagged: {len(type_findings)}")
    for tname, tfindings in sorted(type_findings.items()):
        kinds = sorted(set(f["kind"] for f in tfindings))
        members = sorted(set(f.get("member", "?") for f in tfindings))
        sources = sorted(set(
            loc.split(':')[0] for f in tfindings
            for loc in f.get("source_locations", [])
        ))
        print(f"  {tname}")
        print(f"    Issues: {', '.join(kinds)}")
        print(f"    Members: {', '.join(members[:5])}")
        print(f"    Source: {', '.join(sources[:3])}")

    # Decompile
    os.makedirs(args.output_dir, exist_ok=True)
    print(f"\nDecompiling to {args.output_dir}...")
    results = decompile_types(
        list(type_findings.keys()),
        args.hex_dll,
        args.ilspy,
        args.output_dir,
    )

    # Write index
    index = {
        "hex_dll": os.path.abspath(args.hex_dll),
        "verify_report": os.path.abspath(args.verify_report),
        "decompiled": {
            tname: {
                "file": os.path.relpath(fpath, args.output_dir) if fpath else None,
                "findings": type_findings.get(tname, []),
            }
            for tname, fpath in results.items()
        },
    }
    index_path = os.path.join(args.output_dir, "index.json")
    with open(index_path, 'w') as f:
        json.dump(index, f, indent=2)

    success = sum(1 for v in results.values() if v)
    print(f"\nDone. {success}/{len(results)} types decompiled.")
    print(f"Index: {index_path}")
    print(f"Review each .cs file and compare with docs/il2cpp-semantic-map.md.")


if __name__ == '__main__':
    main()
