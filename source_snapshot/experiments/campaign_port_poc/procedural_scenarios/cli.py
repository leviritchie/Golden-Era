"""Command-line surface for procedural scenario generation and delivery."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from .bundle import list_library
from .catalog import ContentCatalogSnapshot
from .service import (
    build_catalog,
    generate_bundle,
    install_generated_bundle,
    load_profile,
    uninstall_generated_scenario,
)
from .validator import validate_bundle


def _print(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True))



def _catalog_from_args(args: argparse.Namespace) -> ContentCatalogSnapshot:
    return build_catalog(
        args.core,
        game_root=args.game_root,
        custom_manifests=tuple(args.custom_manifest or ()),
        allowlist=tuple(args.allowlist or ()),
    )


def _catalog_payload(catalog: ContentCatalogSnapshot) -> dict[str, Any]:
    return {
        "schema": "olden.procedural-content-catalog.v1",
        "fingerprint": catalog.fingerprint,
        "coreHash": catalog.core_hash,
        "sourceHashes": dict(catalog.source_hashes),
        "allowlist": list(catalog.allowlist),
        "entries": [entry.to_dict() for entry in catalog.entries],
    }


def _command_catalog(args: argparse.Namespace) -> int:
    catalog = _catalog_from_args(args)
    payload = _catalog_payload(catalog)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    _print(
        {
            "ok": True,
            "fingerprint": catalog.fingerprint,
            "entryCount": len(catalog.entries),
            "eligibleCount": sum(entry.eligible for entry in catalog.entries),
            "output": str(args.output) if args.output else None,
        }
    )
    return 0


def _command_generate(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    result = generate_bundle(
        profile,
        core_zip=args.core,
        donor_map=args.donor,
        game_root=args.game_root,
        output_root=args.output,
        custom_manifests=tuple(args.custom_manifest or ()),
        allowlist=tuple(args.allowlist or ()),
        flavor_cache_root=args.flavor_cache,
    )
    _print(
        {
            "ok": True,
            "mapSid": result.bundle.map_sid,
            "bundle": str(result.bundle.root),
            "mechanicalFingerprint": result.bundle.emission.mechanical_fingerprint,
            "flavor": result.flavor.to_manifest_dict(),
            "checks": list(result.bundle_validation.checks),
            "warnings": list(result.warnings),
            "proofBoundary": "generated artifact validated; runtime unproven",
        }
    )
    return 0


def _command_validate(args: argparse.Namespace) -> int:
    report = validate_bundle(args.bundle, check_determinism=not args.cheap)
    _print(report.to_dict())
    return 0 if report.ok else 1


def _command_install(args: argparse.Namespace) -> int:
    result = install_generated_bundle(args.bundle, game_root=args.game_root)
    _print(
        {
            "ok": True,
            "mapSid": result.map_sid,
            "mapPath": str(result.map_path),
            "corePath": str(result.core_path),
            "hashes": result.installed_hashes,
            "preflightChecks": list(result.preflight_checks),
            "proofBoundary": "installed payload and map-load preflight proven; runtime unproven",
        }
    )
    return 0


def _command_uninstall(args: argparse.Namespace) -> int:
    result = uninstall_generated_scenario(args.map_sid, game_root=args.game_root)
    _print(
        {
            "ok": True,
            "mapSid": result.map_sid,
            "restored": list(result.restored),
        }
    )
    return 0


def _command_library(args: argparse.Namespace) -> int:
    _print({"ok": True, "scenarios": list_library(args.library_root)})
    return 0


def _add_game_root(
    parser: argparse.ArgumentParser,
    *,
    required: bool = False,
) -> None:
    parser.add_argument(
        "--game-root",
        type=Path,
        required=required,
        help=(
            "Explicit Golden Era root"
            if required
            else "Golden Era root; auto-detected from Steam when omitted"
        ),
    )


def _add_catalog_inputs(parser: argparse.ArgumentParser) -> None:
    _add_game_root(parser)
    parser.add_argument(
        "--core",
        type=Path,
        help="Advanced Core.zip override; do not combine with --game-root",
    )
    parser.add_argument(
        "--custom-manifest",
        type=Path,
        action="append",
        default=[],
        help="Validated custom-content manifest; repeatable",
    )
    parser.add_argument(
        "--allowlist",
        action="append",
        default=[],
        help="Explicit SID allowlist; repeatable",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="procedural-scenarios")
    subparsers = parser.add_subparsers(dest="command", required=True)

    catalog = subparsers.add_parser("catalog", help="Build an immutable content catalog")
    _add_catalog_inputs(catalog)
    catalog.add_argument("--output", type=Path)
    catalog.set_defaults(handler=_command_catalog)

    generate = subparsers.add_parser("generate", help="Generate and validate a bundle")
    generate.add_argument("--profile", type=Path, required=True)
    generate.add_argument(
        "--donor",
        type=Path,
        help="Advanced native schema-map override; requires --core",
    )
    generate.add_argument("--output", type=Path, required=True)
    generate.add_argument("--flavor-cache", type=Path)
    _add_catalog_inputs(generate)
    generate.set_defaults(handler=_command_generate)

    validate = subparsers.add_parser("validate", help="Validate an emitted bundle")
    validate.add_argument("bundle", type=Path)
    validate.add_argument(
        "--cheap",
        action="store_true",
        help="Skip byte-for-byte deterministic serialization audit",
    )
    validate.set_defaults(handler=_command_validate)

    install = subparsers.add_parser("install", help="Transactionally install a bundle")
    install.add_argument("bundle", type=Path)
    _add_game_root(install, required=True)

    install.set_defaults(handler=_command_install)

    uninstall = subparsers.add_parser("uninstall", help="Restore a scenario's backups")
    uninstall.add_argument("map_sid")
    _add_game_root(uninstall, required=True)
    uninstall.set_defaults(handler=_command_uninstall)

    library = subparsers.add_parser("library", help="List generated scenario bundles")
    library.add_argument("library_root", type=Path)
    library.set_defaults(handler=_command_library)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except Exception as exc:
        _print({"ok": False, "error": str(exc), "type": type(exc).__name__})
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
