#!/usr/bin/env python3
"""
Refresh the readable-C# static pipeline from Cpp2IL outputs.

This orchestrates the existing standalone tools so a new game patch can be
processed from fresh Cpp2IL DiffableCs/ISIL dumps without touching mod code.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from annotate_isil import (
    DEFAULT_DIFFABLE_ROOT,
    DEFAULT_ISIL_ROOT,
    assert_experiment_safe_output,
)


EXPERIMENT_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class CommandRecord:
    name: str
    command: list[str]


def render_command(command: list[str]) -> str:
    return " ".join(command)


def portable_command(command: list[str]) -> list[str]:
    result: list[str] = []
    cwd = Path.cwd().resolve()
    for index, item in enumerate(command):
        path = Path(item)
        if index == 0 and path.resolve() == Path(sys.executable).resolve():
            result.append("python")
            continue
        try:
            resolved = path.resolve()
        except OSError:
            result.append(item)
            continue
        if resolved == cwd or cwd in resolved.parents:
            result.append(str(resolved.relative_to(cwd)))
        else:
            result.append(item)
    return result


def script_path(name: str) -> Path:
    return EXPERIMENT_DIR / name


def build_address_map_command(
    isil_root: Path,
    address_map: Path,
    import_maps: list[Path],
    min_helper_observations: int,
    type_prefix: str | None,
    timeout_seconds: int,
    use_known_helper_seed: bool,
    allow_outside_experiment: bool,
) -> list[str]:
    command = [
        sys.executable,
        str(script_path("build_address_map.py")),
        "--isil-root",
        str(isil_root),
        "--out",
        str(address_map),
        "--min-helper-observations",
        str(min_helper_observations),
        "--timeout-seconds",
        str(timeout_seconds),
    ]
    if type_prefix:
        command.extend(["--type-prefix", type_prefix])
    for import_map in import_maps:
        command.extend(["--import-map", str(import_map)])
    if not use_known_helper_seed:
        command.append("--no-known-helper-seed")
    if allow_outside_experiment:
        command.append("--allow-outside-experiment")
    return command


def build_review_pack_command(
    diffable_root: Path,
    isil_root: Path,
    address_map: Path,
    out_dir: Path,
    type_prefix: str | None,
    top: int,
    corpus_top: int,
    max_body_lines: int,
    timeout_seconds: int,
    summary_only: bool,
    include_constructors: bool,
    allow_outside_experiment: bool,
) -> list[str]:
    command = [
        sys.executable,
        str(script_path("build_review_pack.py")),
        "--diffable-root",
        str(diffable_root),
        "--isil-root",
        str(isil_root),
        "--address-map",
        str(address_map),
        "--out-dir",
        str(out_dir),
        "--top",
        str(top),
        "--corpus-top",
        str(corpus_top),
        "--max-body-lines",
        str(max_body_lines),
        "--timeout-seconds",
        str(timeout_seconds),
    ]
    if type_prefix:
        command.extend(["--type-prefix", type_prefix])
    if summary_only:
        command.append("--summary-only")
    if include_constructors:
        command.append("--include-constructors")
    if allow_outside_experiment:
        command.append("--allow-outside-experiment")
    return command


def parse_dossier_target(value: str) -> tuple[str, str | None]:
    if "::" in value:
        type_name, method = value.split("::", 1)
        method = method.strip() or None
    else:
        type_name, method = value, None
    type_name = type_name.strip()
    if not type_name:
        raise ValueError("--dossier values must include a type name")
    return type_name, method


def dossier_output_stem(type_name: str, method: str | None) -> str:
    text = type_name if method is None else f"{type_name}_{method}"
    text = re.sub(r"[^A-Za-z0-9_.+-]+", "_", text).strip("_")
    return text[:120].rstrip("_") or "dossier"


def build_method_dossier_command(
    diffable_root: Path,
    isil_root: Path,
    address_map: Path,
    out_md: Path,
    out_json: Path,
    type_name: str,
    method: str | None,
    max_body_lines: int,
    timeout_seconds: int,
    summary_only: bool,
    allow_outside_experiment: bool,
) -> list[str]:
    command = [
        sys.executable,
        str(script_path("build_method_dossier.py")),
        "--diffable-root",
        str(diffable_root),
        "--isil-root",
        str(isil_root),
        "--address-map",
        str(address_map),
        "--type",
        type_name,
        "--out",
        str(out_md),
        "--out-json",
        str(out_json),
        "--max-body-lines",
        str(max_body_lines),
        "--timeout-seconds",
        str(timeout_seconds),
        "--include-static-initializers",
    ]
    if method:
        command.extend(["--method", method])
    if summary_only:
        command.append("--summary-only")
    if allow_outside_experiment:
        command.append("--allow-outside-experiment")
    return command


def build_symbol_map_command(
    diffable_root: Path,
    isil_root: Path,
    address_map: Path,
    out_json: Path,
    out_md: Path,
    runtime_source_root: Path | None,
    runtime_map_json: Path | None,
    type_prefix: str | None,
    game_symbols_types: Path | None,
    max_files: int,
    candidate_limit: int,
    call_limit: int,
    timeout_seconds: int,
    allow_outside_experiment: bool,
) -> list[str]:
    command = [
        sys.executable,
        str(script_path("build_symbol_map.py")),
        "--diffable-root",
        str(diffable_root),
        "--isil-root",
        str(isil_root),
        "--address-map",
        str(address_map),
        "--out-json",
        str(out_json),
        "--out-md",
        str(out_md),
        "--max-files",
        str(max_files),
        "--candidate-limit",
        str(candidate_limit),
        "--call-limit",
        str(call_limit),
        "--timeout-seconds",
        str(timeout_seconds),
    ]
    if runtime_source_root:
        command.extend(["--runtime-source-root", str(runtime_source_root)])
    if runtime_map_json:
        command.extend(["--runtime-map-json", str(runtime_map_json)])
    if game_symbols_types:
        command.extend(["--game-symbols-types", str(game_symbols_types)])
    if type_prefix:
        command.extend(["--type-prefix", type_prefix])
    if allow_outside_experiment:
        command.append("--allow-outside-experiment")
    return command


def build_runtime_interop_map_command(
    runtime_assembly: Path,
    cecil_dll: Path,
    out_json: Path,
    type_prefix: str | None,
    max_types: int,
) -> list[str]:
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path("build_runtime_interop_map.ps1")),
        "-Assembly",
        str(runtime_assembly),
        "-Cecil",
        str(cecil_dll),
        "-OutJson",
        str(out_json),
    ]
    if type_prefix:
        command.extend(["-TypePrefix", type_prefix])
    if max_types > 0:
        command.extend(["-MaxTypes", str(max_types)])
    return command


def build_semantic_index_command(
    isil_root: Path,
    address_map: Path,
    out_json: Path,
    out_md: Path,
    type_prefix: str | None,
    anchors: list[str],
    targets: list[str],
    type_targets: list[str],
    game_symbols_targets: Path | None,
    max_files: int,
    timeout_seconds: int,
    allow_outside_experiment: bool,
) -> list[str]:
    command = [
        sys.executable,
        str(script_path("build_semantic_index.py")),
        "--isil-root",
        str(isil_root),
        "--address-map",
        str(address_map),
        "--out-json",
        str(out_json),
        "--out-md",
        str(out_md),
        "--max-files",
        str(max_files),
        "--timeout-seconds",
        str(timeout_seconds),
    ]
    if type_prefix:
        command.extend(["--type-prefix", type_prefix])
    for anchor in anchors:
        command.extend(["--anchor", anchor])
    for target in targets:
        command.extend(["--target", target])
    for type_target in type_targets:
        command.extend(["--type-target", type_target])
    if game_symbols_targets:
        command.extend(["--game-symbols-targets", str(game_symbols_targets)])
    if allow_outside_experiment:
        command.append("--allow-outside-experiment")
    return command


def build_law_surface_dossiers_command(
    game_symbols: Path,
    source_root: Path | None,
    diffable_root: Path,
    isil_root: Path,
    address_map: Path,
    symbol_map: Path,
    runtime_map_json: Path | None,
    semantic_index: Path,
    out_json: Path,
    out_md: Path,
    allow_outside_experiment: bool,
) -> list[str]:
    command = [
        sys.executable,
        str(script_path("build_law_surface_dossiers.py")),
        "--game-symbols",
        str(game_symbols),
        "--diffable-root",
        str(diffable_root),
        "--isil-root",
        str(isil_root),
        "--address-map",
        str(address_map),
        "--symbol-map",
        str(symbol_map),
        "--semantic-index",
        str(semantic_index),
        "--out-json",
        str(out_json),
        "--out-md",
        str(out_md),
    ]
    if runtime_map_json:
        command.extend(["--runtime-map-json", str(runtime_map_json)])
    if source_root:
        command.extend(["--source-root", str(source_root)])
    if allow_outside_experiment:
        command.append("--allow-outside-experiment")
    return command


def run_command(record: CommandRecord, dry_run: bool, timeout_seconds: int) -> int:
    print(f"[{record.name}] {render_command(record.command)}")
    if dry_run:
        return 0
    try:
        completed = subprocess.run(record.command, check=False, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        print(
            f"error: {record.name} exceeded timeout of {timeout_seconds} seconds",
            file=sys.stderr,
        )
        return 124
    return completed.returncode


def require_input_dir(path: Path, label: str) -> None:
    if not path.exists() or not path.is_dir():
        raise FileNotFoundError(f"{label} does not exist or is not a directory: {path}")


def write_manifest(
    path: Path,
    args: argparse.Namespace,
    address_map: Path,
    review_pack: Path,
    records: list[CommandRecord],
    dry_run: bool,
) -> None:
    assert_experiment_safe_output(path, args.allow_outside_experiment)
    document = {
        "schema": 1,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "inputs": {
            "diffable_root": str(args.diffable_root),
            "isil_root": str(args.isil_root),
            "import_maps": [str(path) for path in args.import_map],
        },
        "outputs": {
            "address_map": str(address_map),
            "runtime_interop_map": str(args.out_dir / "runtime_interop_map.json") if args.runtime_assembly else None,
            "symbol_map": str(args.out_dir / "symbol_map.json"),
            "symbol_map_markdown": str(args.out_dir / "symbol_map.md"),
            "semantic_index": str(args.out_dir / "semantic_index.json"),
            "semantic_index_markdown": str(args.out_dir / "semantic_index.md"),
            "law_surface_dossiers": (
                str(args.out_dir / "law_surface_dossiers.json") if args.game_symbols else None
            ),
            "law_surface_dossiers_markdown": (
                str(args.out_dir / "law_surface_dossiers.md") if args.game_symbols else None
            ),
            "review_pack": str(review_pack),
            "dossiers": [
                str(args.out_dir / "dossiers" / f"{dossier_output_stem(*parse_dossier_target(value))}.md")
                for value in args.dossier
            ],
        },
        "options": {
            "type_prefix": args.type_prefix,
            "top": args.top,
            "corpus_top": args.corpus_top,
            "max_body_lines": args.max_body_lines,
            "summary_only": args.summary_only,
            "include_constructors": args.include_constructors,
            "runtime_source_root": str(args.runtime_source_root) if args.runtime_source_root else None,
            "runtime_assembly": str(args.runtime_assembly) if args.runtime_assembly else None,
            "cecil_dll": str(args.cecil_dll) if args.cecil_dll else None,
            "runtime_map_type_prefix": args.runtime_map_type_prefix,
            "runtime_map_max_types": args.runtime_map_max_types,
            "symbol_map_max_files": args.symbol_map_max_files,
            "symbol_map_candidate_limit": args.symbol_map_candidate_limit,
            "symbol_map_call_limit": args.symbol_map_call_limit,
            "semantic_index_max_files": args.semantic_index_max_files,
            "semantic_anchors": args.semantic_anchor,
            "semantic_targets": args.semantic_target,
            "semantic_type_targets": args.semantic_type_target,
            "game_symbols": str(args.game_symbols) if args.game_symbols else None,
            "mod_source_root": str(args.mod_source_root) if args.mod_source_root else None,
            "min_helper_observations": args.min_helper_observations,
            "use_known_helper_seed": args.use_known_helper_seed,
            "command_timeout_seconds": args.command_timeout_seconds,
            "dossiers": args.dossier,
        },
        "commands": [
            {"name": record.name, "command": portable_command(record.command)}
            for record in records
        ],
        "patch_reuse_notes": [
            "Regenerate this manifest, address map, and review pack after every game patch.",
            "Imported exact method-pointer maps are preferred over inferred helper labels.",
            "Symbol-map runtime candidates require generated C# source or generated interop assembly metadata and are not runtime proof.",
            "Semantic-index call edges and LOC anchors are triage evidence, not reconstructed control flow.",
            "Law-surface dossiers are generated from GameSymbols and optional static evidence; proof status remains explicit per surface.",
            "Known helper seed addresses are build-specific and require --use-known-helper-seed.",
            "This manifest covers only the configured type prefix and focused-note count.",
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh readable Cpp2IL address maps and static review packs."
    )
    parser.add_argument("--diffable-root", type=Path, default=DEFAULT_DIFFABLE_ROOT)
    parser.add_argument("--isil-root", type=Path, default=DEFAULT_ISIL_ROOT)
    parser.add_argument(
        "--import-map",
        type=Path,
        action="append",
        default=[],
        help="Optional exact managed method-pointer JSON/CSV export.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("experiments/cpp2il_readable_csharp/samples/latest_refresh"),
    )
    parser.add_argument("--type-prefix", help="Only scan types whose inferred name starts with this prefix.")
    parser.add_argument("--top", type=int, default=8)
    parser.add_argument("--corpus-top", type=int, default=25)
    parser.add_argument("--max-body-lines", type=int, default=300)
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--include-constructors", action="store_true")
    parser.add_argument(
        "--runtime-source-root",
        type=Path,
        help="Optional generated C# interop source root for symbol-map candidate matching.",
    )
    parser.add_argument(
        "--runtime-assembly",
        type=Path,
        help="Optional generated Il2CppInterop assembly such as BepInEx/interop/Hex.dll.",
    )
    parser.add_argument(
        "--cecil-dll",
        type=Path,
        help="Mono.Cecil.dll used to read --runtime-assembly metadata.",
    )
    parser.add_argument(
        "--runtime-map-type-prefix",
        help="Optional runtime-map type prefix filter. Usually leave unset for obfuscated interop assemblies.",
    )
    parser.add_argument(
        "--runtime-map-max-types",
        type=int,
        default=0,
        help="Optional cap for runtime assembly metadata export; 0 means no cap.",
    )
    parser.add_argument("--symbol-map-max-files", type=int, default=200)
    parser.add_argument("--symbol-map-candidate-limit", type=int, default=8)
    parser.add_argument("--symbol-map-call-limit", type=int, default=8)
    parser.add_argument("--semantic-index-max-files", type=int, default=200)
    parser.add_argument(
        "--semantic-anchor",
        action="append",
        default=[],
        help="Optional string/LOC anchor substring to highlight in semantic_index outputs.",
    )
    parser.add_argument(
        "--semantic-target",
        action="append",
        default=[],
        help="Optional call target/address substring for semantic_index focus tables.",
    )
    parser.add_argument(
        "--semantic-type-target",
        action="append",
        default=[],
        help="Optional type-reference substring for semantic_index focus tables.",
    )
    parser.add_argument(
        "--dossier",
        action="append",
        default=[],
        metavar="TYPE[::METHOD]",
        help="Also build a method evidence dossier, for example beh::jwp.",
    )
    parser.add_argument(
        "--game-symbols",
        type=Path,
        help="Optional GameSymbols.cs path. When provided, refresh also writes law_surface_dossiers.json/md.",
    )
    parser.add_argument(
        "--mod-source-root",
        type=Path,
        help="Optional OfflineUnlockMod source root for static law-surface registration evidence.",
    )
    parser.add_argument("--min-helper-observations", type=int, default=3)
    parser.add_argument(
        "--command-timeout-seconds",
        type=int,
        default=1800,
        help="Maximum runtime for each child pipeline command.",
    )
    parser.add_argument(
        "--use-known-helper-seed",
        action="store_true",
        help="Include built-in build-specific helper seeds for the currently reviewed build.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without executing the pipeline or writing outputs.",
    )
    parser.add_argument(
        "--allow-outside-experiment",
        action="store_true",
        help="Allow writing outside the experiment/tmp Cpp2IL areas.",
    )
    args = parser.parse_args()

    if args.top < 1:
        raise ValueError("--top must be positive")
    if args.corpus_top < 1:
        raise ValueError("--corpus-top must be positive")
    if args.max_body_lines < 1:
        raise ValueError("--max-body-lines must be positive")
    if args.min_helper_observations < 1:
        raise ValueError("--min-helper-observations must be positive")
    if args.symbol_map_max_files < 1:
        raise ValueError("--symbol-map-max-files must be positive")
    if args.runtime_map_max_types < 0:
        raise ValueError("--runtime-map-max-types must be zero or positive")
    if args.symbol_map_candidate_limit < 1:
        raise ValueError("--symbol-map-candidate-limit must be positive")
    if args.symbol_map_call_limit < 1:
        raise ValueError("--symbol-map-call-limit must be positive")
    if args.semantic_index_max_files < 1:
        raise ValueError("--semantic-index-max-files must be positive")
    if args.command_timeout_seconds < 1:
        raise ValueError("--command-timeout-seconds must be positive")

    require_input_dir(args.diffable_root, "DiffableCs root")
    require_input_dir(args.isil_root, "ISIL root")
    for import_map in args.import_map:
        if not import_map.exists():
            raise FileNotFoundError(f"Import map does not exist: {import_map}")
    if args.runtime_source_root and not args.runtime_source_root.is_dir():
        raise FileNotFoundError(f"Runtime source root does not exist: {args.runtime_source_root}")
    if args.runtime_assembly and not args.runtime_assembly.is_file():
        raise FileNotFoundError(f"Runtime assembly does not exist: {args.runtime_assembly}")
    if args.runtime_assembly and not args.cecil_dll:
        raise ValueError("--runtime-assembly requires --cecil-dll")
    if args.cecil_dll and not args.cecil_dll.is_file():
        raise FileNotFoundError(f"Mono.Cecil.dll does not exist: {args.cecil_dll}")
    if args.game_symbols and not args.game_symbols.is_file():
        raise FileNotFoundError(f"GameSymbols file does not exist: {args.game_symbols}")
    if args.mod_source_root and not args.mod_source_root.is_dir():
        raise FileNotFoundError(f"Mod source root does not exist: {args.mod_source_root}")

    address_map = args.out_dir / "address_map.json"
    runtime_interop_map = args.out_dir / "runtime_interop_map.json"
    symbol_map = args.out_dir / "symbol_map.json"
    symbol_map_md = args.out_dir / "symbol_map.md"
    semantic_index = args.out_dir / "semantic_index.json"
    semantic_index_md = args.out_dir / "semantic_index.md"
    law_surface_dossiers = args.out_dir / "law_surface_dossiers.json"
    law_surface_dossiers_md = args.out_dir / "law_surface_dossiers.md"
    review_pack = args.out_dir / "review_pack"
    manifest = args.out_dir / "refresh_manifest.json"
    if not args.dry_run:
        assert_experiment_safe_output(address_map, args.allow_outside_experiment)
        if args.runtime_assembly:
            assert_experiment_safe_output(runtime_interop_map, args.allow_outside_experiment)
        assert_experiment_safe_output(symbol_map, args.allow_outside_experiment)
        assert_experiment_safe_output(symbol_map_md, args.allow_outside_experiment)
        assert_experiment_safe_output(semantic_index, args.allow_outside_experiment)
        assert_experiment_safe_output(semantic_index_md, args.allow_outside_experiment)
        if args.game_symbols:
            assert_experiment_safe_output(law_surface_dossiers, args.allow_outside_experiment)
            assert_experiment_safe_output(law_surface_dossiers_md, args.allow_outside_experiment)
        assert_experiment_safe_output(review_pack / "index.md", args.allow_outside_experiment)
        assert_experiment_safe_output(manifest, args.allow_outside_experiment)

    records = [
        CommandRecord(
            "address-map",
            build_address_map_command(
                args.isil_root,
                address_map,
                args.import_map,
                args.min_helper_observations,
                args.type_prefix,
                args.command_timeout_seconds,
                args.use_known_helper_seed,
                args.allow_outside_experiment,
            ),
        ),
    ]
    if args.runtime_assembly:
        records.append(
            CommandRecord(
                "runtime-interop-map",
                build_runtime_interop_map_command(
                    args.runtime_assembly,
                    args.cecil_dll,
                    runtime_interop_map,
                    args.runtime_map_type_prefix,
                    args.runtime_map_max_types,
                ),
            )
        )
    records.extend(
        [
        CommandRecord(
            "symbol-map",
            build_symbol_map_command(
                args.diffable_root,
                args.isil_root,
                address_map,
                symbol_map,
                symbol_map_md,
                args.runtime_source_root,
                runtime_interop_map if args.runtime_assembly else None,
                args.type_prefix,
                args.game_symbols,
                args.symbol_map_max_files,
                args.symbol_map_candidate_limit,
                args.symbol_map_call_limit,
                args.command_timeout_seconds,
                args.allow_outside_experiment,
            ),
        ),
        CommandRecord(
            "semantic-index",
            build_semantic_index_command(
                args.isil_root,
                address_map,
                semantic_index,
                semantic_index_md,
                args.type_prefix,
                args.semantic_anchor,
                args.semantic_target,
                args.semantic_type_target,
                args.game_symbols,
                args.semantic_index_max_files,
                args.command_timeout_seconds,
                args.allow_outside_experiment,
            ),
        ),
        CommandRecord(
            "review-pack",
            build_review_pack_command(
                args.diffable_root,
                args.isil_root,
                address_map,
                review_pack,
                args.type_prefix,
                args.top,
                args.corpus_top,
                args.max_body_lines,
                args.command_timeout_seconds,
                args.summary_only,
                args.include_constructors,
                args.allow_outside_experiment,
            ),
        ),
        ]
    )

    if args.game_symbols:
        records.append(
            CommandRecord(
                "law-surface-dossiers",
                build_law_surface_dossiers_command(
                    args.game_symbols,
                    args.mod_source_root,
                    args.diffable_root,
                    args.isil_root,
                    address_map,
                    symbol_map,
                    runtime_interop_map if args.runtime_assembly else None,
                    semantic_index,
                    law_surface_dossiers,
                    law_surface_dossiers_md,
                    args.allow_outside_experiment,
                ),
            )
        )

    for dossier in args.dossier:
        dossier_type, dossier_method = parse_dossier_target(dossier)
        stem = dossier_output_stem(dossier_type, dossier_method)
        out_md = args.out_dir / "dossiers" / f"{stem}.md"
        out_json = args.out_dir / "dossiers" / f"{stem}.json"
        if not args.dry_run:
            assert_experiment_safe_output(out_md, args.allow_outside_experiment)
            assert_experiment_safe_output(out_json, args.allow_outside_experiment)
        records.append(
            CommandRecord(
                f"dossier:{dossier}",
                build_method_dossier_command(
                    args.diffable_root,
                    args.isil_root,
                    address_map,
                    out_md,
                    out_json,
                    dossier_type,
                    dossier_method,
                    args.max_body_lines,
                    args.command_timeout_seconds,
                    args.summary_only,
                    args.allow_outside_experiment,
                ),
            )
        )

    for record in records:
        code = run_command(record, args.dry_run, args.command_timeout_seconds)
        if code != 0:
            return code

    if args.dry_run:
        print("Dry run complete; no outputs were written.")
    else:
        write_manifest(manifest, args, address_map, review_pack, records, args.dry_run)
        print(f"Wrote refresh manifest to {manifest}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
