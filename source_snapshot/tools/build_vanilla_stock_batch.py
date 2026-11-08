#!/usr/bin/env python3
"""Build every scenario in scenarios/vanilla_stock/batch_manifest.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
POC = REPO / "experiments" / "campaign_port_poc"
if str(POC) not in sys.path:
    sys.path.insert(0, str(POC))

from vanilla_stock.emit_map import (  # noqa: E402
    DEFAULT_STOCK_CORE,
    DEFAULT_STOCK_MAPS_DIR,
    DEFAULT_STOCK_TEMPLATE_MAP,
    build_vanilla_stock_map,
)


DEFAULT_MANIFEST = REPO / "scenarios" / "vanilla_stock" / "batch_manifest.json"


def _resolve(path_value: str | Path, *, base: Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (base / path).resolve()


def load_batch_manifest(path: Path) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or doc.get("schema") != "homm3.vanilla_stock_batch_manifest.v1":
        raise SystemExit(f"unsupported or missing batch manifest schema: {path}")
    scenarios = doc.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise SystemExit(f"batch manifest scenarios list is empty: {path}")
    return doc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--repo-root", type=Path, default=REPO)
    parser.add_argument("--install", action="store_true", help="Also copy built maps into stock maps/")
    parser.add_argument("--only", action="append", default=[], help="Restrict to scenario id(s)")
    parser.add_argument(
        "--enable-scenery-canon-postpass",
        action="store_true",
        help="Opt-in stock-only scenery diversify post-pass",
    )
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    manifest_path = _resolve(args.manifest, base=repo_root)
    batch = load_batch_manifest(manifest_path)

    h3m_root = _resolve(batch.get("h3mRoot") or "HoMM 3 Complete/Maps", base=repo_root)
    artifact_root = _resolve(
        batch.get("artifactRoot") or "artifacts/campaign_port_poc/vanilla_stock",
        base=repo_root,
    )
    stock_core = _resolve(batch.get("stockCore") or DEFAULT_STOCK_CORE, base=repo_root)
    template_map = _resolve(batch.get("templateMap") or DEFAULT_STOCK_TEMPLATE_MAP, base=repo_root)
    install_dir = None
    if args.install:
        install_dir = _resolve(batch.get("installMapsDir") or DEFAULT_STOCK_MAPS_DIR, base=repo_root)

    only = {str(x) for x in args.only}
    results: list[dict[str, Any]] = []
    failures = 0
    for row in batch["scenarios"]:
        if not isinstance(row, dict):
            continue
        scenario_id = str(row.get("id") or "")
        if only and scenario_id not in only:
            continue
        h3m_name = str(row.get("h3m") or "")
        map_sid = str(row.get("mapSid") or "")
        if not scenario_id or not h3m_name or not map_sid:
            print(f"FAIL {scenario_id or '?'}: incomplete scenario row", file=sys.stderr)
            failures += 1
            continue
        h3m_path = h3m_root / h3m_name
        out_dir = artifact_root / scenario_id
        print(f"==== BUILD {scenario_id} ({h3m_name}) ====", flush=True)
        try:
            built = build_vanilla_stock_map(
                h3m_path=h3m_path,
                stock_core=stock_core,
                template_map=template_map,
                out_dir=out_dir,
                map_sid=map_sid,
                install_maps_dir=install_dir,
                enable_scenery_canon_postpass=bool(args.enable_scenery_canon_postpass),
            )
        except Exception as ex:  # noqa: BLE001 - batch must report each failure
            role = str(row.get("role") or "")
            optional = role == "fan_import" or bool(row.get("buildOptional"))
            if optional:
                print(
                    f"OPTIONAL FAIL {scenario_id}: {type(ex).__name__}: {ex}",
                    file=sys.stderr,
                    flush=True,
                )
                results.append(
                    {
                        "id": scenario_id,
                        "ok": False,
                        "optionalFailure": True,
                        "error": f"{type(ex).__name__}: {ex}",
                    }
                )
                continue
            failures += 1
            print(f"FAIL {scenario_id}: {type(ex).__name__}: {ex}", file=sys.stderr, flush=True)
            results.append({"id": scenario_id, "ok": False, "error": f"{type(ex).__name__}: {ex}"})
            continue
        print(
            json.dumps(
                {
                    "id": scenario_id,
                    "mapSid": built.get("mapSid"),
                    "outputMap": built.get("outputMap"),
                    "installedMap": built.get("installedMap"),
                    "victoryMode": (built.get("victory") or {}).get("mode"),
                },
                indent=2,
            ),
            flush=True,
        )
        results.append({"id": scenario_id, "ok": True, "mapSid": built.get("mapSid")})

    summary = {"built": sum(1 for r in results if r["ok"]), "failed": failures, "results": results}
    print(json.dumps(summary, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
