"""Lifter role orchestration: claim batch → IR → C# → compile-check → ledger/queue."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from olden_cs_recovery.lifter.address_map import (
    find_method_address,
    load_address_map,
    load_native_disasm_index,
    normalize_address,
)
from olden_cs_recovery.lifter.compile_check import CompileCheckError, compile_check
from olden_cs_recovery.lifter.emit_csharp import (
    RECOVERED_ROOT,
    emit_type_file,
    ensure_project_scaffold,
    load_diffable_methods,
)
from olden_cs_recovery.lifter.ir_build import build_ir
from olden_cs_recovery.lifter.isil_parse import (
    match_isil_method,
    parse_diffable_fields_with_bases,
    parse_isil_file,
)
from olden_cs_recovery.lifter.limits import EDB_MAX_ISIL_INSTRUCTIONS, PARTITION_PRIORITY
from olden_cs_recovery.paths import (
    ALLOWED_STAGE_TRANSITIONS,
    PACKAGE_ROOT,
    PROOF_LEDGER_ENTRIES_DIR,
    REPO_ROOT,
)
from olden_cs_recovery.queue_store import (
    method_id_to_filename,
    release_item,
    to_iso,
    utc_now,
    write_queue_item,
)
from olden_cs_recovery.schema_validate import validate_instance

IR_ROOT = PACKAGE_ROOT / "ir"
NATIVE_DISASM_BATTLE = (
    REPO_ROOT
    / "experiments"
    / "cpp2il_readable_csharp"
    / "samples"
    / "latest_refresh"
    / "native_disasm_hex_session_battle.json"
)


class LiftError(RuntimeError):
    """Fail-closed lift failure for a single method."""


def _repo_path(rel_or_abs: str) -> Path:
    path = Path(rel_or_abs)
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def _evidence(item: dict[str, Any], kind: str) -> dict[str, Any] | None:
    for ref in item.get("evidence_refs") or []:
        if ref.get("kind") == kind:
            return ref
    return None


def _require_evidence_file(item: dict[str, Any], kind: str) -> Path:
    ref = _evidence(item, kind)
    if ref is None:
        raise LiftError(f"Queue item missing evidence_refs kind={kind!r}")
    path = _repo_path(ref["path"])
    required = ref.get("required", True)
    if not path.is_file():
        if required:
            raise LiftError(f"Required {kind} evidence missing: {path}")
        raise LiftError(f"{kind} evidence path not found (required=false still needed for lift): {path}")
    return path


def claim_sort_key(item: dict[str, Any]) -> tuple[int, str]:
    """Prefer EventArgs partitions before edb within a claim batch."""
    partition = str(item.get("partition") or "")
    domain = str(item.get("domain") or "")
    for idx, prefix in enumerate(PARTITION_PRIORITY):
        if partition.startswith(prefix) or domain.startswith(prefix):
            return (idx, item["method_id"])
    return (len(PARTITION_PRIORITY), item["method_id"])


def ir_path_for(method_id: str) -> Path:
    return IR_ROOT / method_id_to_filename(method_id).replace(".json", ".ir.json")


def ledger_path_for(method_id: str) -> Path:
    return PROOF_LEDGER_ENTRIES_DIR / method_id_to_filename(method_id)


def write_ir(ir: dict[str, Any]) -> Path:
    validate_instance("ir_method.schema.json", ir, ir["method_id"])
    path = ir_path_for(ir["method_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(ir, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def write_ledger_static_lifted(item: dict[str, Any], ir_path: Path, csharp_paths: list[str]) -> Path:
    PROOF_LEDGER_ENTRIES_DIR.mkdir(parents=True, exist_ok=True)
    evidence = [
        {"kind": "ir", "path": _rel_repo(ir_path), "notes": "Phase 1 IR"},
    ]
    for p in csharp_paths:
        evidence.append({"kind": "recovered_csharp", "path": p, "notes": "Compile-check gate passed"})
    for ref in item.get("evidence_refs") or []:
        cleaned = {"kind": str(ref.get("kind")), "path": str(ref.get("path"))}
        if ref.get("notes"):
            cleaned["notes"] = str(ref["notes"])
        evidence.append(cleaned)
    entry = {
        "schema_version": 1,
        "method_id": item["method_id"],
        "status": "static-lifted",
        "previous_status": item.get("proof_status"),
        "blocked_reason": None,
        "evidence_refs": evidence,
        "updated_at": to_iso(utc_now()),
        "notes": (
            "static-lifted after IR+C# emission and recovered project compile-check. "
            "Not promotion. Bar C still requires equivalence-proven."
        ),
    }
    validate_instance("proof_ledger_entry.schema.json", entry, item["method_id"])
    path = ledger_path_for(item["method_id"])
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(entry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def _advance_to_rename(item: dict[str, Any], holder: str) -> dict[str, Any]:
    current = item["stage"]
    if current != "lift":
        raise LiftError(f"Cannot advance non-lift stage {current!r} for {item['method_id']}")
    if "rename" not in ALLOWED_STAGE_TRANSITIONS["lift"]:
        raise LiftError("Internal error: lift→rename not allowed")
    updated = dict(item)
    updated["stage"] = "rename"
    updated["proof_status"] = "static-lifted"
    updated["blocked_reason"] = None
    updated["updated_at"] = to_iso(utc_now())
    # Keep lease until release by orchestrator.
    return updated


def _mark_blocked(item: dict[str, Any], reason: str) -> dict[str, Any]:
    updated = dict(item)
    updated["stage"] = "blocked"
    updated["proof_status"] = "blocked"
    updated["blocked_reason"] = reason
    updated["updated_at"] = to_iso(utc_now())
    return updated


def _rel_repo(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _try_write_body_asm_ir(
    item: dict[str, Any],
    *,
    method_id: str,
    type_name: str,
    method_name: str,
    diffable_path: Path,
    addr_path: Path | None,
    native_entry: Any,
) -> dict[str, Any] | None:
    """Capstone-annotated write-body stub when ISIL/CompGen cannot lift (Direct State)."""
    from olden_cs_recovery.lifter.write_body_asm import build_write_body_ir_from_asm

    asm_path: Path | None = None
    for ref in item.get("evidence_refs") or []:
        notes = str(ref.get("notes") or "").lower()
        path_text = str(ref.get("path") or "").replace("\\", "/")
        if "capstone" in notes or "direct_state_movement_trace" in path_text and path_text.endswith(".asm.txt"):
            candidate = _repo_path(str(ref["path"]))
            if candidate.is_file():
                asm_path = candidate
                break
    if asm_path is None:
        return None
    sources = {
        "diffable_cs": _rel_repo(diffable_path),
        "address_map": _rel_repo(addr_path) if addr_path else None,
        "native_disasm": None,
        "capstone_asm": _rel_repo(asm_path),
    }
    native_address = None
    if native_entry is not None and getattr(native_entry, "address", None):
        native_address = str(native_entry.address)
    return build_write_body_ir_from_asm(
        method_id=method_id,
        type_name=type_name,
        method_name=method_name,
        signature=str(item.get("signature") or method_id),
        asm_path=asm_path,
        sources=sources,
        native_address=native_address,
    )


def lift_one(
    item: dict[str, Any],
    *,
    address_map_cache: dict[str, Any],
    native_disasm_cache: dict[str, Any] | None,
    native_by_type_method: dict[tuple[str, str], list] | None = None,
) -> dict[str, Any]:
    """Lift a single queue item to IR dict. Raises LiftError on fail-closed conditions."""
    from olden_cs_recovery.lifter.compgen_synthesize import (
        CompGenSynthesizeError,
        find_native_method,
        synthesize_compgen_isil_from_native,
    )
    from olden_cs_recovery.lifter.address_map import AddressEntry

    method_id = item["method_id"]
    type_name = item.get("type_name") or method_id.split("::", 1)[0]
    method_name = item.get("method_name") or ""
    domain = item.get("domain") or ""

    diffable_path = _require_evidence_file(item, "diffable_cs")

    addr_ref = _evidence(item, "address_map")
    address_map = None
    addr_path: Path | None = None
    if addr_ref is not None:
        addr_path = _repo_path(addr_ref["path"])
        if addr_ref.get("required", True) and not addr_path.is_file():
            raise LiftError(f"Required address_map missing: {addr_path}")
        if addr_path.is_file():
            key = str(addr_path)
            if key not in address_map_cache:
                address_map_cache[key] = load_address_map(addr_path)
            address_map = address_map_cache[key]
        elif addr_ref.get("required", True):
            raise LiftError(f"Required address_map missing: {addr_path}")

    fields = parse_diffable_fields_with_bases(diffable_path)
    native_entry = None
    if address_map is not None:
        native_entry = find_method_address(
            address_map,
            type_name=type_name,
            method_name=method_name,
            method_id=method_id,
        )

    # Fall back to native disasm pack for address when DummyDLL map omits CompGen getters.
    native_method_hit = None
    if native_by_type_method is not None:
        native_method_hit = find_native_method(
            native_by_type_method,
            type_name=type_name,
            method_name=method_name,
            method_id=method_id,
        )
        if native_entry is None and native_method_hit is not None:
            addr = native_method_hit.get("address")
            if isinstance(addr, str) and addr:
                native_entry = AddressEntry(
                    address=normalize_address(addr),
                    kind="native_disasm",
                    label=str(native_method_hit.get("signature") or method_id),
                    signature=native_method_hit.get("signature")
                    if isinstance(native_method_hit.get("signature"), str)
                    else None,
                    confidence="native_disasm_pack",
                    raw=native_method_hit,
                )

    isil_ref = _evidence(item, "isil")
    isil_path: Path | None = None
    isil_method = None
    synthesized = False
    if isil_ref is not None:
        isil_path = _repo_path(str(isil_ref["path"]))
        if isil_path.is_file():
            isil_methods = parse_isil_file(isil_path)
            try:
                isil_method = match_isil_method(
                    isil_methods,
                    type_name=type_name,
                    method_name=method_name,
                    method_id=method_id,
                )
            except LookupError as exc:
                raise LiftError(str(exc)) from exc
        elif isil_ref.get("required", True):
            raise LiftError(f"Required isil evidence missing: {isil_path}")

    if isil_method is None:
        if native_method_hit is None:
            # Capstone write-body fallback (Direct State M1): asm evidence only.
            asm_ir = _try_write_body_asm_ir(
                item,
                method_id=method_id,
                type_name=type_name,
                method_name=method_name,
                diffable_path=diffable_path,
                addr_path=addr_path,
                native_entry=native_entry,
            )
            if asm_ir is not None:
                return asm_ir
            raise LiftError(
                f"ISIL missing for {method_id} and native disasm method not found; "
                "cannot lift. Fail closed."
            )
        try:
            isil_method = synthesize_compgen_isil_from_native(
                type_name=type_name,
                method_name=method_name,
                method_id=method_id,
                native_method=native_method_hit,
                fields=fields,
            )
            synthesized = True
        except CompGenSynthesizeError as exc:
            asm_ir = _try_write_body_asm_ir(
                item,
                method_id=method_id,
                type_name=type_name,
                method_name=method_name,
                diffable_path=diffable_path,
                addr_path=addr_path,
                native_entry=native_entry,
            )
            if asm_ir is not None:
                return asm_ir
            raise LiftError(f"{exc.code}: {exc.message}") from exc

    if domain == "edb" and len(isil_method.instructions) > EDB_MAX_ISIL_INSTRUCTIONS:
        raise LiftError(
            f"edb method exceeds Phase 1 MVP ISIL bound "
            f"({len(isil_method.instructions)} > {EDB_MAX_ISIL_INSTRUCTIONS}). "
            "Left claimable for a later bounded lift; inventing a body is forbidden."
        )

    native_disasm_path: Path | None = None
    native_disasm_present = False
    if native_disasm_cache is not None and NATIVE_DISASM_BATTLE.is_file():
        native_disasm_path = NATIVE_DISASM_BATTLE
        if native_entry is not None:
            addr = normalize_address(native_entry.address)
            native_disasm_present = addr in native_disasm_cache

    sources = {
        "diffable_cs": _rel_repo(diffable_path),
        "isil": (
            "synthesized:native_disasm_compgen"
            if synthesized
            else (_rel_repo(isil_path) if isil_path else None)
        ),
        "address_map": _rel_repo(addr_path) if addr_path else None,
        "native_disasm": _rel_repo(native_disasm_path) if native_disasm_path else None,
    }

    return build_ir(
        method_id=method_id,
        type_name=type_name,
        method_name=method_name,
        isil_method=isil_method,
        fields=fields,
        address_map=address_map,
        sources=sources,
        native_address=native_entry.address if native_entry else None,
        native_disasm_present=native_disasm_present,
    )


def lift_claimed_items(
    claimed: list[tuple[Path, dict[str, Any]]],
    *,
    holder: str,
) -> dict[str, Any]:
    """
    Lift claimed queue items.

    Recommended claim order: EventArgs first (`--partition Hex.Session.Battle`), then edb.
    Within a mixed claim batch, EventArgs are processed before edb.

    Compile-check is a batch gate over the recovered project after successful IR+C#
    emission for this claim set. proof_status becomes static-lifted only after that gate.
    Oversized edb methods are blocked with an honest reason (still visible; not invented).
    """
    if not claimed:
        return {"ok": True, "lifted": [], "blocked": [], "compile_check": None}

    ordered = sorted(claimed, key=lambda pair: claim_sort_key(pair[1]))
    address_map_cache: dict[str, Any] = {}
    from olden_cs_recovery.lifter.address_map import load_native_disasm_methods
    from olden_cs_recovery.lifter.compgen_synthesize import index_native_disasm_by_type_method

    # Merge native_disasm packs from claimed evidence (City UI / Hud / Battle).
    native_pack_paths: list[Path] = []
    if NATIVE_DISASM_BATTLE.is_file():
        native_pack_paths.append(NATIVE_DISASM_BATTLE)
    for _path, claimed_item in ordered:
        for ref in claimed_item.get("evidence_refs") or []:
            if not isinstance(ref, dict):
                continue
            path_text = str(ref.get("path") or "")
            if "native_disasm" not in path_text.replace("\\", "/"):
                continue
            candidate = Path(path_text)
            if not candidate.is_absolute():
                candidate = REPO_ROOT / candidate
            if candidate.is_file() and candidate not in native_pack_paths:
                native_pack_paths.append(candidate)

    native_disasm_cache: dict[str, Any] | None = None
    native_by_type_method: dict[tuple[str, str], list] | None = None
    if native_pack_paths:
        merged_methods: list[dict[str, Any]] = []
        native_disasm_cache = {}
        for pack in native_pack_paths:
            native_disasm_cache.update(load_native_disasm_index(pack))
            merged_methods.extend(load_native_disasm_methods(pack))
        # Type/method index must use the raw methods list so CompGen VA aliases
        # (identical thunks shared across types) are not collapsed away.
        native_by_type_method = index_native_disasm_by_type_method(merged_methods)

    ensure_project_scaffold()
    IR_ROOT.mkdir(parents=True, exist_ok=True)

    lifted_irs: list[dict[str, Any]] = []
    lifted_meta: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    # group successful lifts by (domain, type_name, diffable_path)
    emit_groups: dict[tuple[str, str, str], list[tuple[dict[str, Any], dict[str, Any], Path]]] = defaultdict(list)

    for path, item in ordered:
        try:
            ir = lift_one(
                item,
                address_map_cache=address_map_cache,
                native_disasm_cache=native_disasm_cache,
                native_by_type_method=native_by_type_method,
            )
            ir_path = write_ir(ir)
            diffable = _require_evidence_file(item, "diffable_cs")
            emit_groups[(item["domain"], item["type_name"], str(diffable))].append((item, ir, path))
            lifted_irs.append(ir)
            lifted_meta.append(
                {
                    "method_id": item["method_id"],
                    "ir_path": _rel_repo(ir_path),
                    "isil_instruction_count": ir["isil_instruction_count"],
                    "unresolved_count": len(ir["unresolved"]),
                }
            )
        except LiftError as exc:
            reason = str(exc)
            # MVP size refusals stay claimable (not permanently blocked).
            if "exceeds Phase 1 MVP ISIL bound" in reason:
                updated = release_item(dict(item), holder=holder)
                # Keep stage=lift, proof_status unchanged.
                write_queue_item(updated, path=path)
                skipped.append({"method_id": item["method_id"], "reason": reason})
            else:
                updated = _mark_blocked(item, reason)
                updated = release_item(updated, holder=holder)
                write_queue_item(updated, path=path)
                blocked.append({"method_id": item["method_id"], "reason": reason})

    if not emit_groups:
        return {
            "ok": False,
            "lifted": [],
            "blocked": blocked,
            "skipped": skipped,
            "compile_check": None,
            "note": "No methods lifted; claimed items blocked, skipped (MVP bound), or failed closed.",
        }

    # Emit C# per type, then compile-check once for the batch package.
    defined_types: set[str] = set()
    csharp_by_method: dict[str, list[str]] = defaultdict(list)
    emitted_files: list[str] = []

    for (domain, type_name, diffable_str), group in emit_groups.items():
        diffable_path = Path(diffable_str)
        # Match DiffableMethod objects for signatures.
        diffable_methods = {m.method_id: m for m in load_diffable_methods(diffable_path)}
        pairs = []
        for item, ir, _queue_path in group:
            dm = diffable_methods.get(item["method_id"])
            if dm is None:
                # Fall back: synthesize minimal DiffableMethod-like via queue fields.
                from olden_cs_recovery.diffable_cs_scan import DiffableMethod

                dm = DiffableMethod(
                    type_name=type_name,
                    method_name=item["method_name"],
                    signature=item.get("signature") or f"public void {item['method_name']}() {{ }}",
                    method_id=item["method_id"],
                    source_path=diffable_path,
                    source_line=item.get("source_line") or 1,
                    raw_line=item.get("signature") or "",
                )
            pairs.append((dm, ir))

        # For edb, avoid dumping thousands of fields into skeletons.
        if domain == "edb":
            emitted_list = _emit_edb_methods(type_name=type_name, methods=pairs)
            for emitted in emitted_list:
                defined_types.add(emitted.short_name)
                rel = emitted.relative_path.as_posix()
                emitted_files.append(f"experiments/olden_cs_recovery/recovered/{rel}")
                # Map each method to its own file when possible.
            for (item, _ir, _qp), emitted in zip(group, emitted_list):
                csharp_by_method[item["method_id"]].append(
                    f"experiments/olden_cs_recovery/recovered/{emitted.relative_path.as_posix()}"
                )
        else:
            emitted = emit_type_file(
                type_name=type_name,
                domain=domain,
                diffable_path=diffable_path,
                methods=pairs,
            )
            defined_types.add(emitted.short_name)
            if emitted.namespace:
                defined_types.add(emitted.type_name.split(".")[-1])
            rel = emitted.relative_path.as_posix()
            emitted_files.append(f"experiments/olden_cs_recovery/recovered/{rel}")
            for item, _ir, _qp in group:
                csharp_by_method[item["method_id"]].append(
                    f"experiments/olden_cs_recovery/recovered/{rel}"
                )

    try:
        build_result = compile_check(defined_types=defined_types)
    except CompileCheckError as exc:
        # Fail closed: do not mark static-lifted / do not advance stage.
        for _domain_key, group in emit_groups.items():
            for item, _ir, queue_path in group:
                updated = dict(item)
                updated["notes"] = (
                    (item.get("notes") or "")
                    + f" | Lift IR/C# emitted but compile-check FAILED: {exc}"
                ).strip(" |")
                # Leave stage=lift so the method remains claimable after fix.
                updated = release_item(updated, holder=holder)
                write_queue_item(updated, path=queue_path)
        raise SystemExit(f"FAIL: compile-check gate failed after lift emission.\n{exc}") from exc

    # Compile-check passed → ledger + stage advance + release.
    for _domain_key, group in emit_groups.items():
        for item, _ir, queue_path in group:
            ir_file = ir_path_for(item["method_id"])
            write_ledger_static_lifted(item, ir_file, csharp_by_method[item["method_id"]])
            updated = _advance_to_rename(item, holder=holder)
            updated = release_item(updated, holder=holder)
            write_queue_item(updated, path=queue_path)

    return {
        "ok": True,
        "lifted": lifted_meta,
        "blocked": blocked,
        "skipped": skipped,
        "emitted_csharp": emitted_files,
        "compile_check": {
            "ok": True,
            "csproj": build_result["csproj"],
            "note": "Batch package compile-check passed. Gate only — not promotion.",
        },
        "proof_status": "static-lifted",
        "next_stage": "rename",
        "limits": {
            "edb_max_isil_instructions": EDB_MAX_ISIL_INSTRUCTIONS,
            "recommended_claim_order": [
                "python -m olden_cs_recovery.worker --role lifter --claim N --partition Hex.Session.Battle",
                "python -m olden_cs_recovery.worker --role lifter --claim N --partition edb",
            ],
            "note": (
                f"edb methods with more than {EDB_MAX_ISIL_INSTRUCTIONS} ISIL instructions are "
                "skipped (remain stage=lift / claimable). They are not permanently blocked."
            ),
        },
    }


def _emit_edb_methods(*, type_name: str, methods: list) -> list:
    """Emit one partial file per lifted edb method (no field dump; MVP size bound)."""
    from olden_cs_recovery.lifter.emit_csharp import EmittedType, _emit_method, recovered_domain_dir
    from olden_cs_recovery.queue_store import method_id_to_filename

    short = type_name.rsplit(".", 1)[-1]
    out_dir = recovered_domain_dir("edb")
    out_dir.mkdir(parents=True, exist_ok=True)

    emitted_list = []
    for method, ir in methods:
        chunk = _emit_method(method, ir, short, namespace="")
        indented = "\n".join(("\t" + ln if ln.strip() else ln) for ln in chunk.splitlines())
        source = (
            "// <auto-generated>\n"
            "// Olden Era C# Recovery Phase 1 lifter skeleton (edb partial).\n"
            "// Fields omitted intentionally for MVP size; method stubs only.\n"
            "// Static-lifted only. Compile-check is a gate, never promotion.\n"
            "// </auto-generated>\n"
            "#nullable disable\n"
            "using System;\n"
            "using System.Collections.Generic;\n"
            "\n"
            f"public partial class {short}\n"
            "{\n"
            f"{indented}\n"
            "}\n"
        )
        safe = method_id_to_filename(method.method_id).replace(".json", ".cs")
        rel = Path("edb") / safe
        path = RECOVERED_ROOT / rel
        path.write_text(source, encoding="utf-8", newline="\n")
        emitted_list.append(
            EmittedType(
                type_name=type_name,
                namespace="",
                short_name=short,
                relative_path=rel,
                source=source,
            )
        )
    if not emitted_list:
        raise LiftError("edb emit received zero methods")
    return emitted_list
