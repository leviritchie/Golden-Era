"""Emit C# skeletons from DiffableCs shells + IR Unresolved markers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from olden_cs_recovery.diffable_cs_scan import DiffableMethod, parse_diffable_cs_file
from olden_cs_recovery.lifter.isil_parse import parse_diffable_fields
from olden_cs_recovery.paths import PACKAGE_ROOT

RECOVERED_ROOT = PACKAGE_ROOT / "recovered"
CSPROJ_NAME = "OldenCsRecovery.Recovered.csproj"

_UNSAFE_TYPE = re.compile(r"[^\w.]+")


@dataclass(frozen=True)
class EmittedType:
    type_name: str
    namespace: str
    short_name: str
    relative_path: Path
    source: str


def recovered_domain_dir(domain: str) -> Path:
    if domain == "edb":
        return RECOVERED_ROOT / "edb"
    if domain.startswith("Hex.Session.Battle"):
        return RECOVERED_ROOT / "Hex.Session.Battle"
    # Direct State write-body partitions must not invent a second partial tree.
    if domain.startswith("DirectState.WriteBody"):
        return RECOVERED_ROOT
    safe = domain.replace(".", "/")
    return RECOVERED_ROOT / safe


def recovered_out_dir_for_type(type_name: str, domain: str) -> Path:
    """Prefer the type's natural recovered home so partial classes do not duplicate fields."""
    if type_name.startswith("Hex.Session.Battle."):
        return RECOVERED_ROOT / "Hex.Session.Battle"
    if type_name in {"edb", "eda", "edf", "eep", "een", "eeu", "ehh", "ejn", "ejr"}:
        return RECOVERED_ROOT
    if type_name.startswith("Hex."):
        parts = type_name.split(".")
        return RECOVERED_ROOT.joinpath(*parts[:-1])
    return recovered_domain_dir(domain)


def _split_type(type_name: str) -> tuple[str, str]:
    if "." not in type_name:
        return "", type_name
    ns, short = type_name.rsplit(".", 1)
    return ns, short


def _csharp_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _method_csharp_name(method_name: str) -> str:
    if method_name == ".ctor":
        return ".ctor"
    if method_name == ".cctor":
        return ".cctor"
    return method_name


def _parse_signature_for_emit(signature: str, short_type: str) -> tuple[str, str, str, bool, bool]:
    """Return (mods, return_type_or_empty, method_name, is_ctor, is_cctor)."""
    text = signature.strip()
    is_ctor = "Type:" in text
    mods_match = re.match(
        r"^(?P<mods>(?:(?:public|private|internal|protected|static|virtual|override|abstract|sealed|new|extern)\s+)*)",
        text,
    )
    mods = (mods_match.group("mods") if mods_match else "").strip()
    if is_ctor:
        is_cctor = "static" in mods.split()
        # Keep DiffableCs parameter list.
        params = text[text.find("(") : text.rfind(")") + 1] if "(" in text else "()"
        return mods or "public", "", short_type if not is_cctor else short_type, True, is_cctor

    # public static Ret name(args) { }
    rest = text[len(mods) :].strip() if mods else text
    m = re.match(r"^(?P<ret>[\w.<>,\[\]`]+)\s+(?P<name>\w+)\s*(?P<params>\([^)]*\))", rest)
    if not m:
        raise ValueError(f"Cannot parse DiffableCs signature for emit: {signature}")
    return mods or "public", m.group("ret"), m.group("name"), False, False


def _param_list(signature: str, *, namespace: str = "") -> str:
    if "(" not in signature or ")" not in signature:
        return "()"
    inside = signature[signature.find("(") + 1 : signature.rfind(")")].strip()
    if not inside:
        return "()"
    parts: list[str] = []
    for raw in inside.split(","):
        token = raw.strip()
        if not token:
            continue
        # Strip DiffableCs default values for compile-check skeletons.
        # Enum defaults like ``ETargetAllegiance c = 2`` are not convertible to empty
        # stub classes; defaults are not part of the unresolved body contract.
        if "=" in token:
            token = token.split("=", 1)[0].strip()
        bits = token.split()
        if len(bits) == 1:
            parts.append(_qualify_type_name(bits[0], namespace=namespace))
        else:
            type_bits = bits[:-1]
            name = bits[-1]
            qtype = _qualify_type_name(" ".join(type_bits), namespace=namespace)
            parts.append(f"{qtype} {name}")
    return "(" + ", ".join(parts) + ")"


def collect_referenced_simple_types(text: str) -> set[str]:
    """Collect simple type identifiers from declarations (ignore comments/strings)."""
    # Strip comments and string literals before scanning.
    cleaned = re.sub(r"//.*?$", "", text, flags=re.M)
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.S)
    cleaned = re.sub(r'"(?:\\.|[^"\\])*"', '""', cleaned)

    keywords = {
        "void",
        "int",
        "bool",
        "byte",
        "sbyte",
        "short",
        "ushort",
        "uint",
        "long",
        "ulong",
        "float",
        "double",
        "decimal",
        "char",
        "string",
        "object",
        "Object",
        "String",
        "Boolean",
        "Int32",
        "Int64",
        "Single",
        "Double",
        "public",
        "private",
        "protected",
        "internal",
        "static",
        "class",
        "namespace",
        "return",
        "throw",
        "new",
        "this",
        "base",
        "null",
        "true",
        "false",
        "var",
        "partial",
        "override",
        "virtual",
        "sealed",
        "abstract",
        "readonly",
        "const",
        "event",
        "using",
        "where",
        "get",
        "set",
        "add",
        "remove",
        "for",
        "foreach",
        "if",
        "else",
        "while",
        "do",
        "switch",
        "case",
        "break",
        "continue",
        "goto",
        "try",
        "catch",
        "finally",
        "typeof",
        "sizeof",
        "nameof",
        "is",
        "as",
        "in",
        "out",
        "ref",
        "params",
        "global",
        "disable",
        "enable",
        "restore",
        "warning",
        "nullable",
        "List",
        "HashSet",
        "Dictionary",
        "IEnumerable",
        "EventArgs",
        "EventHandler",
        "Exception",
        "Type",
        "Array",
        "Action",
        "Func",
        "Task",
        "UnresolvedLiftException",
        "System",
        "Collections",
        "Generic",
        "OldenCsRecovery",
        "Stubs",
        "Hex",
        "Session",
        "Battle",
    }

    # Prefer declaration sites: field types and method signatures.
    found: set[str] = set()
    for match in re.finditer(
        r"(?:public|private|protected|internal)\s+(?:static\s+)?"
        r"(?P<type>[A-Za-z_][\w]*(?:\[\])?)\s+[A-Za-z_][\w]*\s*[;=({]",
        cleaned,
    ):
        found.add(match.group("type").rstrip("[]"))
    for match in re.finditer(r":\s*(?P<base>[A-Za-z_][\w.]*)", cleaned):
        base = match.group("base").split(".")[-1]
        found.add(base)
    for match in re.finditer(r"\((?P<params>[^)]*)\)", cleaned):
        for part in match.group("params").split(","):
            bits = part.strip().split()
            if len(bits) >= 2:
                found.add(bits[0].strip("[]"))
    # Return types: public TypeName method(… / public TypeName[] method(
    for match in re.finditer(
        r"(?:public|private|protected|internal)\s+(?:static\s+)?"
        r"(?P<ret>[A-Za-z_][\w]*(?:\[\])?)\s+[A-Za-z_][\w]*\s*\(",
        cleaned,
    ):
        found.add(match.group("ret").rstrip("[]"))

    # Filter keywords and invalid identifiers.
    out: set[str] = set()
    for name in found:
        if name in keywords:
            continue
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
            continue
        # C# keyword safety.
        if name in {
            "for",
            "foreach",
            "if",
            "else",
            "while",
            "do",
            "switch",
            "case",
            "default",
            "try",
            "catch",
            "finally",
            "lock",
            "fixed",
            "checked",
            "unchecked",
            "unsafe",
            "operator",
            "implicit",
            "explicit",
            "extern",
            "delegate",
            "enum",
            "struct",
            "interface",
            "record",
        }:
            continue
        out.add(name)
    return out


_NAMESPACE_COLLISIONS = frozenset({"Hex", "Session", "Battle"})


def _qualify_type_name(type_name: str, *, namespace: str) -> str:
    """Rewrite DiffableCs type tokens that collide with enclosing namespace segments."""
    text = type_name.strip()
    if not text:
        return text
    # Keep arrays / generics wrappers simple for MVP stubs.
    if text.endswith("[]"):
        return _qualify_type_name(text[:-2], namespace=namespace) + "[]"
    if text in {"int", "bool", "byte", "sbyte", "short", "ushort", "uint", "long", "ulong", "float", "double", "decimal", "char", "string", "object", "void"}:
        return text
    if "." in text or "<" in text:
        return text
    ns_parts = {p for p in namespace.split(".") if p}
    if text in ns_parts or text in _NAMESPACE_COLLISIONS:
        # Hex.Map.Map (and similar): short name equals the last namespace segment.
        # Keep bare name so it binds to the recovered same-namespace type, not Extern.
        last_segment = namespace.rsplit(".", 1)[-1] if namespace else ""
        if text == last_segment:
            return text
        return f"global::OldenCsRecovery.Stubs.Extern.{text}"
    return text


def _synthetic_compgen_fields(
    methods: list[tuple[DiffableMethod, dict[str, Any]]],
    *,
    known_offsets: set[int],
    namespace: str,
) -> list[str]:
    """Declare field_0xN members proven by CompGen IR but absent from DiffableCs shells."""
    from olden_cs_recovery.replay import compgen_accessor_field

    lines: list[str] = []
    seen: set[str] = set()
    for method, ir in methods:
        info = compgen_accessor_field(ir)
        if info is None:
            continue
        offset_hex = str(info.get("offset_hex") or "")
        if not offset_hex.startswith("0x"):
            continue
        try:
            offset = int(offset_hex, 16)
        except ValueError:
            continue
        if offset in known_offsets:
            continue
        field_name = str(info.get("field_name") or "")
        if not field_name.startswith("field_0x") or field_name in seen:
            continue
        seen.add(field_name)
        mods, ret, _name, _is_ctor, _is_cctor = _parse_signature_for_emit(
            method.signature, method.type_name.rsplit(".", 1)[-1]
        )
        if info.get("kind") == "setter":
            # First parameter type from signature.
            params = method.signature[method.signature.find("(") + 1 : method.signature.rfind(")")]
            param0 = params.split(",")[0].strip() if params.strip() else "object"
            bits = param0.split()
            ftype = bits[0] if bits else "object"
        else:
            ftype = ret or "object"
        qtype = _qualify_type_name(ftype, namespace=namespace)
        lines.append(f"// Field offset: {offset_hex} (synthetic CompGen; DiffableCs base omitted)\npublic {qtype} {field_name};")
    return lines


def _method_names_in_source(source: str) -> set[str]:
    """Collect method names already present in a recovered partial.

    Return types may be globally qualified (``global::OldenCsRecovery.Stubs.Extern.Hex``),
    so the type token must allow ``:``. Without that, re-lift after a failed compile-check
    appends duplicate method skeletons (DestRecipe ``een.bdeo`` pollution).
    """
    names: set[str] = set()
    for match in re.finditer(
        r"(?:public|private|internal|protected)\s+(?:static\s+)?"
        r"(?:[\w.<>,\[\]:]+)\s+(\w+)\s*\(",
        source,
    ):
        names.add(match.group(1))
    return names


def _merge_methods_into_existing(existing: str, method_chunks: list[str], *, short: str) -> str:
    """Insert new method chunks before the closing brace of the primary partial class."""
    # Find the last closing of `partial class <short>`; insert before its final `}`.
    class_pat = re.compile(
        rf"public\s+partial\s+class\s+{re.escape(short)}\b[^{{]*\{{",
        re.M,
    )
    match = class_pat.search(existing)
    if match is None:
        raise ValueError(f"existing recovered file missing partial class {short}")
    # Walk braces from class open to matching close.
    start = match.end() - 1
    depth = 0
    end = None
    for i in range(start, len(existing)):
        ch = existing[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end is None:
        raise ValueError(f"unbalanced braces merging methods into {short}")
    insertion = "\n\n" + "\n\n".join(method_chunks) + "\n"
    return existing[:end] + insertion + existing[end:]


def emit_type_file(
    *,
    type_name: str,
    domain: str,
    diffable_path: Path,
    methods: list[tuple[DiffableMethod, dict[str, Any]]],
) -> EmittedType:
    """Emit one C# type file containing all lifted methods for that type in this batch."""
    namespace, short = _split_type(type_name)
    out_dir = recovered_out_dir_for_type(type_name, domain)
    out_dir.mkdir(parents=True, exist_ok=True)
    rel = out_dir.relative_to(RECOVERED_ROOT) / f"{short}.cs"
    path = RECOVERED_ROOT / rel

    method_chunks: list[str] = []
    for method, ir in methods:
        method_chunks.append(_emit_method(method, ir, short, namespace=namespace))

    # If a recovered skeleton already exists, merge new methods only (no field re-emit).
    if path.is_file():
        existing = path.read_text(encoding="utf-8-sig")
        present = _method_names_in_source(existing)
        fresh_chunks: list[str] = []
        for method, ir in methods:
            name = _method_csharp_name(method.method_name)
            if name in present:
                continue
            fresh_chunks.append(_emit_method(method, ir, short, namespace=namespace))
        if fresh_chunks:
            source = _merge_methods_into_existing(existing, fresh_chunks, short=short)
            path.write_text(source, encoding="utf-8", newline="\n")
        else:
            source = existing
        return EmittedType(
            type_name=type_name,
            namespace=namespace,
            short_name=short,
            relative_path=rel,
            source=source,
        )

    fields = parse_diffable_fields(diffable_path)
    field_lines = []
    for offset in sorted(fields):
        info = fields[offset]
        qtype = _qualify_type_name(info.type_name, namespace=namespace)
        field_lines.append(
            f"// Field offset: 0x{info.offset:X}\n"
            f"public {qtype} {info.name};"
        )
    field_lines.extend(
        _synthetic_compgen_fields(
            methods,
            known_offsets=set(fields.keys()),
            namespace=namespace,
        )
    )

    # Detect base type from DiffableCs if present.
    base = _detect_base_type(diffable_path)
    if base and base not in {"System.EventArgs"} and "." not in base:
        # Sibling types in the same namespace (e.g. BattleEventArgs) stay unqualified.
        base_clause = f" : {base}"
    elif base:
        base_clause = f" : {base}"
    else:
        base_clause = ""

    ns_open = f"namespace {namespace}\n{{\n" if namespace else ""
    ns_close = "}\n" if namespace else ""
    indent = "\t" if namespace else ""

    body_fields = "\n\n".join(field_lines)
    body_methods = "\n\n".join(method_chunks)
    parts = [p for p in (body_fields, body_methods) if p]
    class_body = ("\n\n".join(parts) + "\n") if parts else "\n"

    usings = "using System;\nusing System.Collections.Generic;\n\n"
    source = (
        "// <auto-generated>\n"
        "// Olden Era C# Recovery Phase 1 lifter skeleton.\n"
        "// Static-lifted only. Compile-check is a gate, never promotion.\n"
        "// </auto-generated>\n"
        "#nullable disable\n"
        f"{usings}"
        f"{ns_open}"
        f"{indent}public partial class {short}{base_clause}\n"
        f"{indent}{{\n"
        f"{_indent_block(class_body, indent + chr(9))}"
        f"{indent}}}\n"
        f"{ns_close}"
    )

    path.write_text(source, encoding="utf-8", newline="\n")
    return EmittedType(
        type_name=type_name,
        namespace=namespace,
        short_name=short,
        relative_path=rel,
        source=source,
    )


def _indent_block(text: str, prefix: str) -> str:
    lines = text.splitlines()
    if not lines:
        return ""
    return "\n".join((prefix + line if line.strip() else line) for line in lines) + "\n"


def _detect_base_type(diffable_path: Path) -> str | None:
    for line in diffable_path.read_text(encoding="utf-8-sig").splitlines():
        m = re.search(r"class\s+\w+\s*:\s*([A-Za-z_][\w.]*)", line)
        if m:
            base = m.group(1)
            # DiffableCs often writes unqualified EventArgs; qualify for compile-check.
            if base == "EventArgs":
                return "System.EventArgs"
            return base
    return None


def _ctor_param_names(signature: str) -> list[str]:
    if "(" not in signature or ")" not in signature:
        return []
    inside = signature[signature.find("(") + 1 : signature.rfind(")")].strip()
    if not inside:
        return []
    names: list[str] = []
    for part in inside.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        names.append(bits[-1] if len(bits) >= 2 else f"arg{len(names)}")
    return names


def _emit_nested_null_guarded_body(
    method_id: str,
    plan: list[dict],
    param_names: list[str],
) -> list[str]:
    """Emit honest C# for the two grounded nested-null-guarded EventArgs ctors."""
    if method_id == "Hex.Session.Battle.EnergyUpdateEventArgs::.ctor(eir,int)":
        side = param_names[0] if param_names else "side"
        delta = param_names[1] if len(param_names) > 1 else "energyDelta"
        return [
            f"\tthis.side = {side};",
            f"\tif ({side} == null) throw new System.NullReferenceException();",
            f"\tvar energyState = {side}.cglw;",
            "\tif (energyState == null) throw new System.NullReferenceException();",
            "\tthis.energy = energyState.cgnt;",
            "\tif (energyState == null) throw new System.NullReferenceException();",
            "\tthis.energyDistribution = energyState.cgnv;",
            f"\tthis.energyDelta = {delta};",
        ]
    if method_id.startswith("Hex.Session.Battle.UnitStartedMovementEventArgs::.ctor("):
        # Param order: moveTime, startTime, pathLength, unit, moveType, path, switchSoundToFly
        names = list(param_names) + [f"arg{i}" for i in range(max(0, 7 - len(param_names)))]
        mt, st, pl, unit, mty, path, ssf = names[:7]
        return [
            f"\tthis.moveTime = {mt};",
            f"\tthis.startTime = {st};",
            f"\tthis.pathLength = {pl};",
            f"\tthis.moveType = {mty};",
            f"\tthis.target = {unit};",
            f"\tif ({unit} == null) throw new System.NullReferenceException();",
            f"\tthis.path = {path};",
            f"\tthis.id = {unit}.id;",
            f"\tthis.switchSoundToFly = {ssf};",
        ]
    return []


def _emit_method(method: DiffableMethod, ir: dict[str, Any], short_type: str, *, namespace: str = "") -> str:
    # Late import avoids lifter↔replay cycle at module load.
    from olden_cs_recovery.replay import (
        bool_field_assigned_from_ctor,
        field_assign_plan_from_ir,
        is_base_only_parameterless_ctor,
        is_base_then_bool_field_assign_ctor,
        is_base_then_param_field_assign_ctor,
        is_compgen_field_getter,
        is_compgen_field_setter,
        is_nested_null_guarded_field_copy_ctor,
        nested_null_guarded_field_copy_plan,
        compgen_accessor_field,
    )

    mods, ret, name, is_ctor, is_cctor = _parse_signature_for_emit(method.signature, short_type)
    # Recovered skeletons inherit stub bases (ConfigElementBase, etc.) that do not declare
    # the DiffableCs virtuals. Emitting `override` against those stubs fails compile-check.
    mods = " ".join(tok for tok in mods.split() if tok not in {"override", "virtual", "abstract"})
    if not mods:
        mods = "public"
    params = _param_list(method.signature, namespace=namespace)
    unresolved = ir.get("unresolved") or []
    unresolved_codes = sorted({u.get("code", "?") for u in unresolved})
    field_writes = [
        t
        for t in (ir.get("field_touches") or [])
        if t.get("access") == "write" and t.get("field_name")
    ]
    # Deduplicate field names preserving order.
    seen: set[str] = set()
    ordered_fields: list[str] = []
    for touch in field_writes:
        fname = touch["field_name"]
        if fname in seen:
            continue
        seen.add(fname)
        ordered_fields.append(fname)

    lines: list[str] = []
    honest_body: list[str] | None = None
    if is_ctor and not is_cctor and is_base_only_parameterless_ctor(ir):
        honest_body = []
        summary = (
            f"/// Honest recovered body for <c>{_csharp_escape(method.method_id)}</c>.\n"
            "/// ISIL proves base EventArgs ctor only; no field writes. "
            "Grounded in DiffableCs/ISIL."
        )
    elif is_ctor and not is_cctor and is_base_then_bool_field_assign_ctor(ir):
        field_name = bool_field_assigned_from_ctor(ir)
        param_names = _ctor_param_names(method.signature)
        src = param_names[0] if param_names else "_value"
        honest_body = [f"\tthis.{field_name} = {src};"]
        summary = (
            f"/// Honest recovered body for <c>{_csharp_escape(method.method_id)}</c>.\n"
            "/// ISIL proves CallVoid BattleEventArgs::.ctor(), then one bool field assign. "
            "Grounded in DiffableCs/ISIL."
        )
    elif is_ctor and not is_cctor and is_base_then_param_field_assign_ctor(ir):
        plan = field_assign_plan_from_ir(ir)
        param_names = _ctor_param_names(method.signature)
        if plan is not None:
            body_lines: list[str] = []
            for field_name, _field_type, action in plan:
                kind, value = action
                if kind == "const":
                    body_lines.append(f"\tthis.{field_name} = {value};")
                elif kind == "arg":
                    idx = int(value)
                    src = param_names[idx] if 0 <= idx < len(param_names) else f"arg{idx}"
                    body_lines.append(f"\tthis.{field_name} = {src};")
                else:
                    body_lines = []
                    break
            if body_lines:
                honest_body = body_lines
                summary = (
                    f"/// Honest recovered body for <c>{_csharp_escape(method.method_id)}</c>.\n"
                    "/// ISIL proves base Object/EventArgs ctor, then field assigns from ctor params "
                    "(Il2Cpp write-barrier calls are non-semantic). Grounded in DiffableCs/ISIL."
                )
    elif is_ctor and not is_cctor and is_nested_null_guarded_field_copy_ctor(ir):
        nested_plan = nested_null_guarded_field_copy_plan(ir)
        param_names = _ctor_param_names(method.signature)
        if nested_plan is not None:
            body_lines = _emit_nested_null_guarded_body(method.method_id, nested_plan, param_names)
            if body_lines:
                honest_body = body_lines
                summary = (
                    f"/// Honest recovered body for <c>{_csharp_escape(method.method_id)}</c>.\n"
                    "/// ISIL+native disasm prove null-checks → 0x18048B100 and nested field copies. "
                    "Grounded in DiffableCs/ISIL/disasm."
                )
    elif (not is_ctor) and is_compgen_field_getter(ir):
        info = compgen_accessor_field(ir)
        if info is not None:
            honest_body = [f"\treturn this.{info['field_name']};"]
            summary = (
                f"/// Honest recovered CompGen getter for <c>{_csharp_escape(method.method_id)}</c>.\n"
                f"/// Native/ISIL proves field load at {info.get('offset_hex')} then return."
            )
    elif (not is_ctor) and is_compgen_field_setter(ir):
        info = compgen_accessor_field(ir)
        if info is not None:
            param_names = _ctor_param_names(method.signature)
            src = param_names[0] if param_names else "value"
            honest_body = [f"\tthis.{info['field_name']} = {src};"]
            summary = (
                f"/// Honest recovered CompGen setter for <c>{_csharp_escape(method.method_id)}</c>.\n"
                f"/// Native/ISIL proves field store at {info.get('offset_hex')} "
                "(optional Il2Cpp write barrier is non-semantic)."
            )

    if honest_body is not None:
        lines.append("/// <summary>")
        for summary_line in summary.splitlines():
            lines.append(summary_line)
        lines.append("/// </summary>")
    else:
        lines.append("/// <summary>")
        lines.append(f"/// Static-lifted skeleton for <c>{_csharp_escape(method.method_id)}</c>.")
        lines.append("/// Unresolved markers (fail-closed): " + ", ".join(unresolved_codes))
        lines.append("/// </summary>")

    if is_ctor and not is_cctor:
        lines.append(f"{mods} {short_type}{params}")
    elif is_cctor:
        lines.append(f"static {short_type}()")
    else:
        qret = _qualify_type_name(ret, namespace=namespace) if ret else ret
        lines.append(f"{mods} {qret} {name}{params}")

    lines.append("{")
    if honest_body is not None:
        lines.extend(honest_body)
    else:
        lines.append(
            f"\t// UNRESOLVED: opaque/control/native markers present; "
            f"see ir entry for {method.method_id}"
        )
        for fname in ordered_fields:
            lines.append(f"\t// FIELD_TOUCH write: {fname}")
        lines.append(
            f'\tthrow new global::OldenCsRecovery.Stubs.UnresolvedLiftException('
            f'"{_csharp_escape(method.method_id)}");'
        )
    lines.append("}")
    return "\n".join(lines)


def ensure_project_scaffold() -> Path:
    RECOVERED_ROOT.mkdir(parents=True, exist_ok=True)
    stubs = RECOVERED_ROOT / "Stubs"
    stubs.mkdir(parents=True, exist_ok=True)

    # Cross-namespace recovered types (Configs ↔ Session.Data) need shared usings so
    # compile-check does not require duplicate global stubs for promoted short names.
    # Keep this list narrow: broad Hex.Map / Hex.Session.Battle globals collide with stubs.
    global_usings = RECOVERED_ROOT / "GlobalUsings.cs"
    global_usings.write_text(
        """// <auto-generated>
// Shared usings for recovered Hex.Configs / Hex.Session.Data packages (compile-check gate).
// </auto-generated>
global using Hex.Configs;
global using Hex.Session.Data;
""",
        encoding="utf-8",
        newline="\n",
    )

    exception_path = stubs / "UnresolvedLiftException.cs"
    if not exception_path.is_file():
        exception_path.write_text(
            """// <auto-generated>
namespace OldenCsRecovery.Stubs
{
\t/// <summary>
\t/// Thrown by static-lifted skeletons. Presence of this throw is intentional:
\t/// inventing method bodies is forbidden until equivalence proof (bar C).
\t/// </summary>
\tpublic sealed class UnresolvedLiftException : System.Exception
\t{
\t\tpublic UnresolvedLiftException(string methodId)
\t\t\t: base("Unresolved static lift for " + methodId + ". Not equivalence-proven.")
\t\t{
\t\t\tMethodId = methodId;
\t\t}

\t\tpublic string MethodId { get; }
\t}
}
""",
            encoding="utf-8",
            newline="\n",
        )

    csproj = RECOVERED_ROOT / CSPROJ_NAME
    csproj.write_text(
        """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>netstandard2.1</TargetFramework>
    <LangVersion>latest</LangVersion>
    <Nullable>disable</Nullable>
    <ImplicitUsings>disable</ImplicitUsings>
    <RootNamespace>OldenCsRecovery.Recovered</RootNamespace>
    <AssemblyName>OldenCsRecovery.Recovered</AssemblyName>
    <GenerateDocumentationFile>false</GenerateDocumentationFile>
    <NoWarn>CS1591;CS0628</NoWarn>
  </PropertyGroup>
</Project>
""",
        encoding="utf-8",
        newline="\n",
    )
    return csproj


def collect_recovered_defined_types() -> set[str]:
    """Scan recovered C# for **global-namespace** type short names.

    Only global declarations suppress ExternalStubs entries. A namespaced
    ``Hex.Session.Battle.Unit`` must NOT suppress a global ``Unit`` stub needed by
    root-level recovered hubs (``eep``, ``eda``) that lack ``using Hex.Session.Battle``.
    """
    defined: set[str] = set()
    class_pat = re.compile(
        r"(?:public|internal|private|protected)\s+(?:partial\s+)?(?:class|struct|enum|interface)\s+(\w+)\b"
    )
    namespace_pat = re.compile(r"\bnamespace\s+[\w.]+")
    if not RECOVERED_ROOT.is_dir():
        return defined
    for path in RECOVERED_ROOT.rglob("*.cs"):
        if path.name == "ExternalStubs.cs":
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        # Track brace depth relative to namespace opens so nested types stay scoped.
        depth = 0
        in_namespace = False
        ns_depth = None
        i = 0
        while i < len(text):
            if text.startswith("//", i):
                nl = text.find("\n", i)
                i = len(text) if nl < 0 else nl + 1
                continue
            if text.startswith("/*", i):
                end = text.find("*/", i + 2)
                i = len(text) if end < 0 else end + 2
                continue
            ch = text[i]
            if ch == "{":
                depth += 1
                i += 1
                continue
            if ch == "}":
                depth -= 1
                if in_namespace and ns_depth is not None and depth < ns_depth:
                    in_namespace = False
                    ns_depth = None
                i += 1
                continue
            if text.startswith("namespace", i) and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] == "_")):
                m = namespace_pat.match(text, i)
                if m:
                    in_namespace = True
                    # namespace body opens at next '{'
                    ns_depth = depth + 1
                    i = m.end()
                    continue
            if not in_namespace:
                m = class_pat.match(text, i)
                if m:
                    defined.add(m.group(1))
                    i = m.end()
                    continue
            i += 1
    return defined


def write_external_stubs(type_names: set[str], known_defined: set[str]) -> Path:
    """Emit stub externals for unresolved referenced types (compile-check gate only)."""
    stubs_dir = RECOVERED_ROOT / "Stubs"
    stubs_dir.mkdir(parents=True, exist_ok=True)
    # Union batch-defined names with global recovered partials already on disk.
    known_defined = set(known_defined) | collect_recovered_defined_types()
    csharp_keywords = {
        "abstract",
        "as",
        "base",
        "bool",
        "break",
        "byte",
        "case",
        "catch",
        "char",
        "checked",
        "class",
        "const",
        "continue",
        "decimal",
        "default",
        "delegate",
        "do",
        "double",
        "else",
        "enum",
        "event",
        "explicit",
        "extern",
        "false",
        "finally",
        "fixed",
        "float",
        "for",
        "foreach",
        "goto",
        "if",
        "implicit",
        "in",
        "int",
        "interface",
        "internal",
        "is",
        "lock",
        "long",
        "namespace",
        "new",
        "null",
        "object",
        "operator",
        "out",
        "override",
        "params",
        "private",
        "protected",
        "public",
        "readonly",
        "ref",
        "return",
        "sbyte",
        "sealed",
        "short",
        "sizeof",
        "stackalloc",
        "static",
        "string",
        "struct",
        "switch",
        "this",
        "throw",
        "true",
        "try",
        "typeof",
        "uint",
        "ulong",
        "unchecked",
        "unsafe",
        "ushort",
        "using",
        "virtual",
        "void",
        "volatile",
        "while",
        "record",
        "global",
    }
    needed = sorted(
        t
        for t in type_names
        if t not in known_defined
        and t not in {"EventArgs", "List", "HashSet", "Dictionary", "EventHandler"}
        and t not in csharp_keywords
        and not t.startswith("System")
        and re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", t)
    )

    # Phase 5+: a few stubs need members for recovered EventArgs / edb compile-check.
    _STUB_BODIES = {
        "IntPtr": "\n\tpublic static readonly IntPtr Zero = null;\n",
        "FieldObject": "\n\tpublic int id;\n",
        "ede": " : FieldObject\n",
        "eix": "\n\tpublic int cgnt;\n\tpublic int[] cgnv;\n",
        "eir": "\n\tpublic eix cglw;\n",
    }

    lines = [
        "// <auto-generated>",
        "// Stub externals for compile-check gate. Not promoted game types.",
        "// </auto-generated>",
        "#nullable disable",
        "",
        "// Minimal stand-ins used by DiffableCs shells.",
        "public class List {}",
        "public class HashSet {}",
        "public class Dictionary {}",
        "public delegate void EventHandler();",
        "public delegate void EventHandler__1(object sender, object e);",
        "",
        "namespace System.Collections.Generic",
        "{",
        "\tpublic class List<T> {}",
        "\tpublic class HashSet<T> {}",
        "\tpublic class Dictionary<TKey, TValue> {}",
        "}",
        "",
        "// Global stubs for obfuscated / unrecovered symbols (non-colliding names).",
    ]
    # Ensure dependency order for stub bodies that reference each other.
    ordered_needed = sorted(needed)
    for prefer in ("FieldObject", "eix", "IntPtr", "ede", "eir"):
        if prefer in ordered_needed:
            ordered_needed.remove(prefer)
            ordered_needed.insert(0 if prefer != "eir" else len(ordered_needed), prefer)
    # Stable dependency order:
    force_order = [n for n in ("FieldObject", "IntPtr", "eix", "ede", "eir") if n in needed or n == "eix" and "eir" in needed]
    # Always emit eix when eir needs it.
    if "eir" in needed and "eix" not in needed:
        needed = set(needed)
        needed.add("eix")
        force_order = [n for n in ("FieldObject", "IntPtr", "eix", "ede", "eir") if n in needed]
    rest = [n for n in sorted(needed) if n not in force_order]
    for name in force_order + rest:
        if name in _NAMESPACE_COLLISIONS:
            continue
        body = _STUB_BODIES.get(name)
        if body is None:
            lines.append(f"public class {name} {{}}")
        elif body.startswith(" :"):
            lines.append(f"public class {name}{body}{{}}")
        else:
            lines.append(f"public class {name}\n{{{body}}}")

    lines.extend(
        [
            "",
            "namespace OldenCsRecovery.Stubs.Extern",
            "{",
            "\t// Simple names that collide with Hex.* namespace segments.",
        ]
    )
    for name in sorted(_NAMESPACE_COLLISIONS):
        lines.append(f"\tpublic class {name} {{}}")
    lines.append("}")

    path = stubs_dir / "ExternalStubs.cs"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path


def load_diffable_methods(path: Path) -> list[DiffableMethod]:
    return parse_diffable_cs_file(path)
