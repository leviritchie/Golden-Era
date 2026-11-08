#!/usr/bin/env python3
"""
verify_patch_surfaces.py — Cross-reference all Harmony patches and GameMember
lookups in the OfflineUnlockMod C# source against an Il2CppDumper dump.cs to
detect orphaned patches, signature mismatches, and field type changes.

Usage:
    python tools/verify_patch_surfaces.py <dump.cs> [--source <OfflineUnlockMod/>]
        [--rename-map rename_map.json] [--output report.json] [--verbose]

Produces a report:
    {
        "patch_findings": [
            {
                "kind": "PATCH_ORPHAN",     # method/type completely gone
                "type": "...",
                "member": "...",
                "expected_sig": "...",
                "source_locations": ["file.cs:123"],
                "severity": "fatal"
            }, ...
        ],
        "summary": { ... }
    }

Run this immediately after generating a new dump.cs from a Steam hotfix. Feed report.json to tools/decompile_surfaces.py to decompile the flagged types from Hex.dll via ILSpy; the two scripts are a pipeline (verify, then decompile), not overlapping implementations.
"""

import re
import json
import os
import sys
from collections import defaultdict, OrderedDict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any


# ─── dump.cs reading (lightweight, reuses map_obfuscation parser) ────────────

def _load_dump_index(dump_path: str) -> Dict[str, Dict]:
    """
    Parse dump.cs into a lightweight index: {type_full_name -> {methods, fields, properties}}.
    Returns dict where each value has:
        'methods': {name: (params_str, return_type)}
        'fields': {name: field_type}
        'props': {name: prop_type}
        'kind': 'class'|'struct'|'enum'|'interface'
        'short_name': 'ecd'
        'namespace': '...'
    """
    # Reuse the parser from map_obfuscation
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from map_obfuscation import parse_dump

    classes = parse_dump(dump_path)

    index = {}
    for full_name, info in classes.items():
        entry = {
            'methods': OrderedDict(),
            'fields': OrderedDict(),
            'props': OrderedDict(),
            'kind': info.kind,
            'short_name': info.name,
            'namespace': info.namespace,
        }
        for mname, params, ret in info.methods:
            entry['methods'][mname] = (params, ret)
        for fname, ftype in info.fields:
            entry['fields'][fname] = ftype
        for pname, ptype in info.properties:
            entry['props'][pname] = ptype
        index[full_name] = entry

    return index


# ─── C# source parsing ───────────────────────────────────────────────────────

# Pattern 1: [HarmonyPatch(typeof(X), nameof(X.M), new[] { typeof(P1), ... })]
HARMONY_3ARG_RE = re.compile(
    r'\[HarmonyPatch\s*\(\s*typeof\s*\(\s*([^)]+)\s*\)\s*,\s*'
    r'nameof\s*\(\s*\1\s*\.\s*(\w+)\s*\)\s*,\s*'
    r'new\s*\[\s*\]\s*\{\s*typeof\s*\(([^}]+)\)\s*\}\s*\)\s*\]',
    re.DOTALL
)

# Pattern 2: [HarmonyPatch(typeof(X), nameof(X.M))]
HARMONY_2ARG_RE = re.compile(
    r'\[HarmonyPatch\s*\(\s*typeof\s*\(\s*([^)]+)\s*\)\s*,\s*'
    r'nameof\s*\(\s*\1\s*\.\s*(\w+)\s*\)\s*\)\s*\]'
)

# Pattern 3: [HarmonyPatch] with TargetMethod()
HARMONY_TARGETLESS_RE = re.compile(
    r'\[HarmonyPatch\s*\]\s*\n\s*(?:\[[\w]+\]\s*\n\s*)*'
    r'(?:internal|public|private|static)\s+class\s+(\w+)',
    re.DOTALL
)

# For GameMember and AccessTools calls, use a line-based approach since
# these calls can span multiple lines with complex nesting.
GM_FINDMETHODS_START = re.compile(r'GameMember\s*\.\s*FindMethods\s*\(')
GM_FINDMETHODSBYNAMES_START = re.compile(r'GameMember\s*\.\s*FindMethodsByNames\s*\(')
GM_FINDFIELDS_START = re.compile(r'GameMember\s*\.\s*FindFields\s*\(')
GM_FINDTYPE_START = re.compile(r'GameMember\s*\.\s*FindType\s*\(')
GM_FINDPARAMLESS_START = re.compile(r'GameMember\s*\.\s*FindParameterlessReturning\s*\(')
ACC_CTOR_START = re.compile(r'AccessTools\s*\.\s*Constructor\s*\(')
ACC_PROP_START = re.compile(r'AccessTools\s*\.\s*Property(?:Setter)?\s*\(')
ACC_FIELD_START = re.compile(r'AccessTools\s*\.\s*Field\s*\(')

# Extract typeof(...) anywhere
TYPEOF_RE = re.compile(r'typeof\s*\(\s*([^)]+)\s*\)')
# Extract "string literal" args
STRING_ARG_RE = re.compile(r'"([^"]*)"')
CONST_STRING_RE = re.compile(r'\bconst\s+string\s+(\w+)\s*=\s*"([^"]*)"')
CLASS_DECL_RE = re.compile(r'\b(?:internal|public|private|protected)?\s*(?:static\s+)?(?:readonly\s+)?(?:class|struct)\s+(\w+)')
# Extract nameof(X.M)
NAMEOF_RE = re.compile(r'nameof\s*\(\s*[\w.]+\s*\.\s*(\w+)\s*\)')
# Extract paramCount: N
PARAMCOUNT_RE = re.compile(r'paramCount\s*:\s*(-?\d+)')
# Extract Type.EmptyTypes
EMPTYTYPES_RE = re.compile(r'Type\s*\.\s*EmptyTypes')
# Extract null (standalone arg)
NULL_ARG_RE = re.compile(r'\bnull\b')
# Extract GetType()
GETTYPE_RE = re.compile(r'([\w.]+)\s*\.\s*GetType\s*\(\s*\)')


def _extract_typeof(expr: str) -> str:
    """Clean a typeof(...) expression to a type name."""
    expr = expr.strip()
    # Remove global:: prefix
    expr = re.sub(r'^global\s*::\s*', '', expr)
    # Remove namespace prefixes for simple names (keep Hex.Session.Battle.Unit etc)
    return expr


def _extract_type_names(type_list_str: str) -> List[str]:
    """Extract type names from a comma-separated typeof(...) list."""
    types = []
    for part in type_list_str.split(','):
        part = part.strip()
        m = re.search(r'typeof\s*\(\s*([^)]+)\s*\)', part)
        if m:
            types.append(_extract_typeof(m.group(1)))
        elif part:
            types.append(part.strip())
    return types


def _resolve_type_name(typeof_expr: str, short_name_map: Dict[str, str]) -> str:
    """
    Resolve a type name from source code to a dump.cs full name.
    Handles: typeof(Hex.Session.Battle.BhTurnView), typeof(ecd), typeof(global::ejz)
    Uses the short_name_map (short name -> full name from dump) for obfuscated types.
    """
    name = _extract_typeof(typeof_expr)
    # If it's a short obfuscated name, look up in dump
    if len(name) <= 4 and name.islower() and name.isalpha():
        if name in short_name_map:
            return short_name_map[name]
        # Try with various namespace prefixes
        for candidate in short_name_map:
            if short_name_map[candidate] == name:
                return short_name_map[candidate]
            if candidate.endswith('.' + name):
                return candidate
    # Named types with full namespace
    return name


def _resolve_type_name_from_gettype(expr: str) -> str:
    """Resolve a GetType() or typeof expression from the source code."""
    expr = expr.strip()
    # typeof(...)
    m = re.search(r'typeof\s*\(\s*([^)]+)\s*\)', expr)
    if m:
        return _extract_typeof(m.group(1))
    # variable.GetType()
    m = re.search(r'(\w+)\s*\.\s*GetType\s*\(\s*\)', expr)
    if m:
        return f"<runtime:{m.group(1)}>"
    return expr


def _extract_call_args(text: str, start_pos: int) -> List[str]:
    """
    Extract comma-separated top-level arguments from a C# call starting at start_pos.
    Handles nested parentheses, generics, strings, and brackets.
    Returns list of raw argument strings.
    """
    depth = 0
    bracket_depth = 0
    in_string = False
    in_char = False
    args = []
    current = []
    i = start_pos

    # find opening paren
    while i < len(text) and text[i] != '(':
        i += 1
    if i >= len(text):
        return args
    i += 1  # skip '('
    depth = 1

    while i < len(text) and depth > 0:
        ch = text[i]
        if in_string:
            current.append(ch)
            if ch == '\\' and i + 1 < len(text):
                i += 1
                current.append(text[i])
            elif ch == '"':
                in_string = False
        elif in_char:
            current.append(ch)
            if ch == '\\' and i + 1 < len(text):
                i += 1
                current.append(text[i])
            elif ch == "'":
                in_char = False
        elif ch == '"':
            in_string = True
            current.append(ch)
        elif ch == "'":
            in_char = True
            current.append(ch)
        elif ch == '(':
            depth += 1
            current.append(ch)
        elif ch == ')':
            depth -= 1
            if depth == 0:
                if current:
                    args.append(''.join(current).strip())
                break
            current.append(ch)
        elif ch == '<':
            bracket_depth += 1
            current.append(ch)
        elif ch == '>':
            bracket_depth -= 1
            current.append(ch)
        elif ch == ',' and depth == 1 and bracket_depth == 0:
            args.append(''.join(current).strip())
            current = []
        else:
            current.append(ch)
        i += 1

    return args


def _collect_string_constants(source_dir: str) -> Dict[str, str]:
    """Collect simple C# const string values keyed by their containing type path."""
    source_path = Path(source_dir)
    consts: Dict[str, str] = {}
    skip_dirs = {'obj', 'bin', 'tools', '.git', 'Properties', '_decompiled_shipped'}
    cs_files = [f for f in source_path.rglob("*.cs") if not any(p in skip_dirs for p in f.parts)]

    for cs_file in cs_files:
        try:
            lines = cs_file.read_text(encoding='utf-8', errors='replace').splitlines()
        except Exception:
            continue

        type_stack: List[Tuple[str, int]] = []
        pending_types: List[str] = []
        brace_depth = 0
        for line in lines:
            for match in CLASS_DECL_RE.finditer(line):
                pending_types.append(match.group(1))

            open_count = line.count('{')
            for _ in range(open_count):
                brace_depth += 1
                if pending_types:
                    type_stack.append((pending_types.pop(0), brace_depth))

            const_match = CONST_STRING_RE.search(line)
            if const_match and type_stack:
                name, value = const_match.group(1), const_match.group(2)
                path = '.'.join(t[0] for t in type_stack)
                consts[path + '.' + name] = value
                if type_stack[0][0] == 'GameSymbols':
                    consts['GameSymbols.' + '.'.join(t[0] for t in type_stack[1:]) + '.' + name] = value

            close_count = line.count('}')
            for _ in range(close_count):
                while type_stack and type_stack[-1][1] >= brace_depth:
                    type_stack.pop()
                brace_depth = max(0, brace_depth - 1)

    return consts


def _resolve_string_arg(arg: str, constants: Dict[str, str]) -> Optional[str]:
    """Resolve a quoted string or simple const-string reference. Return None for dynamic expressions."""
    arg = arg.strip()
    if len(arg) >= 2 and arg[0] == '"' and arg[-1] == '"':
        return arg[1:-1]
    if arg in constants:
        return constants[arg]
    return None


def _extract_typeof_from_arg(arg: str) -> Optional[str]:
    """Extract type name from a typeof(...) expression."""
    m = TYPEOF_RE.search(arg)
    if m:
        name = m.group(1).strip()
        return re.sub(r'^global\s*::\s*', '', name)
    return None


def _extract_nameof_from_arg(arg: str) -> Optional[str]:
    """Extract member name from a nameof(X.M) expression."""
    m = NAMEOF_RE.search(arg)
    if m:
        return m.group(1)
    return None


def _classify_gm_call(first_arg: str) -> Optional[str]:
    """Determine what kind of GameMember call this is from the first arg (the type arg)."""
    # The arg could be typeof(...), variable.GetType(), or a variable
    if 'typeof' in first_arg or 'GetType' in first_arg or first_arg.strip():
        return "type"
    return None


def parse_patches(source_dir: str, skip_probes: bool = False) -> List[Dict[str, Any]]:
    """
    Scan all .cs files and extract patch targets.
    Returns list of findings with source_locations.
    If skip_probes is True, skip files matching *Probe*.
    """
    findings = []
    source_path = Path(source_dir)
    cs_files = list(source_path.rglob("*.cs"))
    string_constants = _collect_string_constants(source_dir)

    # Prevent scanning generated/output files
    skip_dirs = {'obj', 'bin', 'tools', '.git', 'Properties', '_decompiled_shipped'}
    cs_files = [f for f in cs_files if not any(p in skip_dirs for p in f.parts)]

    if skip_probes:
        cs_files = [f for f in cs_files if 'Probe' not in f.name]

    for cs_file in cs_files:
        try:
            content = cs_file.read_text(encoding='utf-8', errors='replace')
        except Exception:
            continue

        rel_path = str(cs_file.relative_to(source_path))
        lines = content.split('\n')

        for line_no, line in enumerate(lines, 1):
            stripped = line.strip()

            # ── HarmonyPatch attributes ──

            if stripped.startswith('[HarmonyPatch'):
                # 3-arg form
                m3 = HARMONY_3ARG_RE.search(line + ' '.join(lines[line_no:line_no+5]))
                if m3:
                    type_name = _extract_typeof(m3.group(1))
                    method_name = m3.group(2)
                    param_types = _extract_type_names(m3.group(3))
                    findings.append({
                        "kind": "harmony_patch",
                        "type": type_name,
                        "member": method_name,
                        "params": param_types,
                        "source_file": rel_path,
                        "source_line": line_no,
                    })
                    continue

                # 2-arg form
                m2 = HARMONY_2ARG_RE.search(line + ' '.join(lines[line_no:line_no+3]))
                if m2:
                    type_name = _extract_typeof(m2.group(1))
                    method_name = m2.group(2)
                    findings.append({
                        "kind": "harmony_patch",
                        "type": type_name,
                        "member": method_name,
                        "params": None,
                        "source_file": rel_path,
                        "source_line": line_no,
                    })
                    continue

            # ── GameMember.FindMethods ──
            if 'GameMember.FindMethods(' in stripped or 'GameMember.FindMethods (' in stripped:
                # Collect multi-line call
                call_text = _collect_call_text(lines, line_no - 1)
                idx = call_text.find('GameMember.FindMethods(')
                if idx == -1:
                    idx = call_text.find('GameMember.FindMethods (')
                if idx >= 0:
                    args = _extract_call_args(call_text, idx + len('GameMember.FindMethods'))
                    if len(args) >= 4:
                        type_arg = args[0].strip()
                        ret_arg = args[1].strip()
                        param_arg = args[2].strip()
                        id_arg = args[3].strip().strip('"')

                        type_name = _extract_typeof_from_arg(type_arg)
                        if not type_name:
                            gm = GETTYPE_RE.search(type_arg)
                            if gm:
                                type_name = f"<runtime:{gm.group(1)}>"
                            else:
                                type_name = type_arg

                        param_types = []
                        is_empty_types = EMPTYTYPES_RE.search(param_arg)
                        is_null = (not is_empty_types and (param_arg.strip() == 'null' or NULL_ARG_RE.match(param_arg)))
                        if not is_empty_types and not is_null:
                            # Extract typeof list
                            param_types = [m.group(1).strip() for m in TYPEOF_RE.finditer(param_arg)]
                            param_types = [re.sub(r'^global\s*::\s*', '', t) for t in param_types]

                        findings.append({
                            "kind": "gamemember_findmethods",
                            "type": type_name,
                            "member_hints": [id_arg.rsplit('.', 1)[-1]],
                            "id": id_arg,
                            "params": param_types if (param_types or is_empty_types) else None,
                            "return_type": ret_arg if ret_arg and ret_arg not in ('null', '') else None,
                            "source_file": rel_path,
                            "source_line": line_no,
                        })

            # ── GameMember.FindMethodsByNames ──
            if 'GameMember.FindMethodsByNames(' in stripped:
                call_text = _collect_call_text(lines, line_no - 1)
                idx = call_text.find('GameMember.FindMethodsByNames(')
                if idx >= 0:
                    args = _extract_call_args(call_text, idx + len('GameMember.FindMethodsByNames'))
                    if len(args) >= 3:
                        type_arg = args[0].strip()
                        filter_arg = args[1].strip()
                        id_arg = args[2].strip().strip('"')

                        type_name = _extract_typeof_from_arg(type_arg)
                        if not type_name:
                            gm = GETTYPE_RE.search(type_arg)
                            if gm:
                                type_name = f"<runtime:{gm.group(1)}>"
                            else:
                                type_name = type_arg.split('.')[0] if '.' in type_arg else type_arg

                        # Check for paramCount:
                        pcm = PARAMCOUNT_RE.search(filter_arg)
                        is_empty = EMPTYTYPES_RE.search(filter_arg)
                        is_null = NULL_ARG_RE.match(filter_arg)

                        if pcm:
                            findings.append({
                                "kind": "gamemember_findmethods_bynames",
                                "type": type_name,
                                "param_count": int(pcm.group(1)),
                                "id": id_arg,
                                "source_file": rel_path,
                                "source_line": line_no,
                            })
                        elif is_empty or is_null or 'typeof' in filter_arg:
                            param_types = [m.group(1).strip() for m in TYPEOF_RE.finditer(filter_arg)]
                            param_types = [re.sub(r'^global\s*::\s*', '', t) for t in param_types]
                            findings.append({
                                "kind": "gamemember_findmethods_bynames_typed",
                                "type": type_name,
                                "params": param_types if param_types else [],
                                "id": id_arg,
                                "source_file": rel_path,
                                "source_line": line_no,
                            })

            # ── GameMember.FindParameterlessReturning ──
            if 'GameMember.FindParameterlessReturning(' in stripped:
                call_text = _collect_call_text(lines, line_no - 1)
                idx = call_text.find('GameMember.FindParameterlessReturning(')
                if idx >= 0:
                    args = _extract_call_args(call_text, idx + len('GameMember.FindParameterlessReturning'))
                    if len(args) >= 3:
                        type_arg = args[0].strip()
                        ret_arg = args[1].strip()
                        id_arg = args[2].strip().strip('"')

                        type_name = _extract_typeof_from_arg(type_arg)
                        if not type_name:
                            gm = GETTYPE_RE.search(type_arg)
                            if gm:
                                type_name = f"<runtime:{gm.group(1)}>"
                            else:
                                type_name = type_arg

                        ret_type = _extract_typeof_from_arg(ret_arg)
                        findings.append({
                            "kind": "gamemember_findmethods",
                            "type": type_name,
                            "member_hints": [id_arg.rsplit('.', 1)[-1]],
                            "id": id_arg,
                            "params": [],  # parameterless
                            "return_type": ret_type,
                            "source_file": rel_path,
                            "source_line": line_no,
                        })

            # ── GameMember.FindFields ──
            if 'GameMember.FindFields(' in stripped:
                call_text = _collect_call_text(lines, line_no - 1)
                idx = call_text.find('GameMember.FindFields(')
                if idx >= 0:
                    args = _extract_call_args(call_text, idx + len('GameMember.FindFields'))
                    if len(args) >= 3:
                        type_arg = args[0].strip()
                        field_type_arg = args[1].strip()
                        id_arg = args[2].strip().strip('"')

                        type_name = _extract_typeof_from_arg(type_arg)
                        if not type_name:
                            gm = GETTYPE_RE.search(type_arg)
                            if gm:
                                type_name = f"<runtime:{gm.group(1)}>"
                            else:
                                type_name = type_arg

                        field_type = _extract_typeof_from_arg(field_type_arg)

                        findings.append({
                            "kind": "gamemember_findfields",
                            "type": type_name,
                            "member": id_arg.rsplit('.', 1)[-1],
                            "field_type": field_type,
                            "id": id_arg,
                            "source_file": rel_path,
                            "source_line": line_no,
                        })

            # ── GameMember.FindType ──
            if 'GameMember.FindType(' in stripped:
                call_text = _collect_call_text(lines, line_no - 1)
                idx = call_text.find('GameMember.FindType(')
                if idx >= 0:
                    args = _extract_call_args(call_text, idx + len('GameMember.FindType'))
                    if len(args) >= 2:
                        id_arg = _resolve_string_arg(args[0], string_constants)
                        hint_arg = _resolve_string_arg(args[1], string_constants)
                        if not hint_arg:
                            continue
                        findings.append({
                            "kind": "gamemember_findtype",
                            "type": hint_arg,  # The nameHint is often the type short name
                            "id": id_arg or args[0].strip(),
                            "source_file": rel_path,
                            "source_line": line_no,
                        })

            # ── AccessTools.Constructor ──
            if 'AccessTools.Constructor(' in stripped:
                call_text = _collect_call_text(lines, line_no - 1)
                idx = call_text.find('AccessTools.Constructor(')
                if idx >= 0:
                    args = _extract_call_args(call_text, idx + len('AccessTools.Constructor'))
                    if len(args) >= 2:
                        type_name = _extract_typeof_from_arg(args[0])
                        param_types = [m.group(1).strip() for m in TYPEOF_RE.finditer(args[1])]
                        param_types = [re.sub(r'^global\s*::\s*', '', t) for t in param_types]
                        if type_name:
                            findings.append({
                                "kind": "accesstools_constructor",
                                "type": type_name,
                                "member": ".ctor",
                                "params": param_types,
                                "source_file": rel_path,
                                "source_line": line_no,
                            })

            # ── AccessTools.Property / PropertySetter ──
            if 'AccessTools.Property(' in stripped or 'AccessTools.PropertySetter(' in stripped:
                call_text = _collect_call_text(lines, line_no - 1)
                idx = max(
                    call_text.find('AccessTools.PropertySetter('),
                    call_text.find('AccessTools.Property('),
                )
                if idx >= 0:
                    start = idx + len('AccessTools.PropertySetter(') if 'Setter' in call_text[idx:idx+30] else idx + len('AccessTools.Property(')
                    args = _extract_call_args(call_text, start - 1)
                    if len(args) >= 2:
                        type_name = _extract_typeof_from_arg(args[0])
                        if not type_name:
                            gm = GETTYPE_RE.search(args[0])
                            type_name = f"<runtime:{gm.group(1)}>" if gm else args[0].strip()
                        prop_name = _extract_nameof_from_arg(args[1])
                        if not prop_name:
                            sm = STRING_ARG_RE.search(args[1])
                            if sm:
                                prop_name = sm.group(1)

                        if type_name and not type_name.startswith('<runtime'):
                            findings.append({
                                "kind": "accesstools_property",
                                "type": type_name,
                                "member": prop_name or args[1].strip().strip('"'),
                                "source_file": rel_path,
                                "source_line": line_no,
                            })

            # ── AccessTools.Field ──
            if 'AccessTools.Field(' in stripped and 'AccessTools.FieldRef' not in stripped:
                call_text = _collect_call_text(lines, line_no - 1)
                idx = call_text.find('AccessTools.Field(')
                if idx >= 0:
                    args = _extract_call_args(call_text, idx + len('AccessTools.Field'))
                    if len(args) >= 2:
                        type_name = _extract_typeof_from_arg(args[0])
                        if not type_name:
                            gm = GETTYPE_RE.search(args[0])
                            type_name = f"<runtime:{gm.group(1)}>" if gm else args[0].strip()
                        field_name = _extract_nameof_from_arg(args[1])
                        if not field_name:
                            sm = STRING_ARG_RE.search(args[1])
                            if sm:
                                field_name = sm.group(1)

                        if type_name and not type_name.startswith('<runtime'):
                            findings.append({
                                "kind": "accesstools_field",
                                "type": type_name,
                                "member": field_name or args[1].strip().strip('"'),
                                "source_file": rel_path,
                                "source_line": line_no,
                            })

    return findings


def _collect_call_text(lines: List[str], start_idx: int) -> str:
    """Collect text from start_idx forward until parentheses balance."""
    text = lines[start_idx]
    if '(' not in text:
        return text
    depth = text.count('(') - text.count(')')
    idx = start_idx + 1
    while depth > 0 and idx < len(lines):
        line = lines[idx]
        depth += line.count('(') - line.count(')')
        text += ' ' + line
        idx += 1
    return text


# ─── Cross-reference against dump ────────────────────────────────────────────

def _find_type_in_dump(type_name: str, dump_index: Dict[str, Dict],
                       short_name_map: Dict[str, str]) -> Optional[str]:
    """Find the matching dump type key for a source-level type name."""
    # Exact match
    if type_name in dump_index:
        return type_name
    # Try by short name
    sn = type_name.split('.')[-1]
    if sn in short_name_map:
        return short_name_map[sn]
    # Try suffix matching
    for full in dump_index:
        if full.endswith('.' + type_name) or full == type_name:
            return full
    return None


def verify_against_dump(findings: List[Dict], dump_index: Dict[str, Dict],
                        rename_map: Optional[Dict] = None) -> List[Dict]:
    """
    Cross-reference each finding against the dump index.
    Returns a list of patch_findings with status.
    Skips runtime-resolved types (<runtime:...>) and Unity engine types.
    """
    results = []

    # Build maps
    short_name_map = {}
    for full in dump_index:
        sn = full.split('.')[-1]
        if sn not in short_name_map:
            short_name_map[sn] = full

    type_renames = {}
    method_renames = {}
    field_renames = {}
    if rename_map:
        type_renames = rename_map.get("type_renames", {})
        method_renames = rename_map.get("method_renames", {})
        field_renames = rename_map.get("field_renames", {})

    # Unity engine types to skip (not in IL2CPP dump)
    UNITY_TYPES = {
        'CanvasScaler', 'VideoPlayer', 'Canvas', 'Camera', 'RectTransform',
        'Image', 'RawImage', 'SpriteRenderer', 'TextMeshProUGUI', 'GameObject',
        'Transform', 'MonoBehaviour', 'Component', 'Object', 'Behaviour',
        'Rect', 'Vector3', 'Vector2', 'Color', 'Material', 'Shader',
    }

    # Group findings by (type, member) for dedup
    grouped: Dict[Tuple[str, str], List[Dict]] = defaultdict(list)
    for f in findings:
        key = (f["type"], f.get("member", f.get("id", "")))
        grouped[key].append(f)

    for (type_name, member_key), group in grouped.items():
        # Skip runtime-resolved types
        if type_name.startswith('<runtime:'):
            continue

        # Skip Unity engine types
        if type_name in UNITY_TYPES or type_name.startswith('UnityEngine.'):
            continue

        # Skip local variable types (single letters, or names ending in "Type" not in dump)
        # These come from `var t = GetHexType(...); ... FindMethods(t, ...)`
        # Also skip 'type' which is System.Type variable name
        if (len(type_name) <= 1
            or type_name == 'type'
            or (type_name.endswith('Type') and type_name not in dump_index
                and type_name not in short_name_map)):
            continue

        # Apply rename map
        resolved_type = type_name
        sn = type_name.split('.')[-1]
        if sn in type_renames:
            resolved_type = type_renames[sn]

        dump_key = _find_type_in_dump(resolved_type, dump_index, short_name_map)

        if dump_key is None:
            # Try the short name as a last resort
            sn = resolved_type.split('.')[-1]
            if sn in short_name_map:
                dump_key = short_name_map[sn]

        if dump_key is None:
            results.append({
                "kind": "PATCH_TYPE_GONE",
                "type": type_name,
                "member": member_key,
                "source_locations": sorted(set(
                    f"{f['source_file']}:{f['source_line']}" for f in group
                )),
                "severity": "fatal",
                "detail": f"Type '{type_name}' not found in dump. Rename or removal?",
            })
            continue

        dump_entry = dump_index[dump_key]
        representative = group[0]
        patch_kind = representative.get("kind", "?")

        # Handle different patch kinds
        if patch_kind == "harmony_patch":
            method_name = representative.get("member", "")
            param_types = representative.get("params")

            # Apply method rename map (try short and full type names)
            method_renames_lookup = {}
            if rename_map:
                method_renames_lookup = rename_map.get("method_renames", {})
            type_sn = type_name.split('.')[-1] if '.' in type_name else type_name
            for lookup_key in (f"{type_sn}.{method_name}", f"{type_name}.{method_name}"):
                if lookup_key in method_renames_lookup:
                    method_name = method_renames_lookup[lookup_key]
                    break

            if method_name not in dump_entry['methods']:
                # Try common obfuscated aliases
                found = False
                if param_types is not None:
                    # Search by param count and types
                    for mname, (mparams, _) in dump_entry['methods'].items():
                        dump_params = [p.strip() for p in mparams.split(',') if p.strip()]
                        if len(dump_params) == len(param_types):
                            found = True
                            break

                results.append({
                    "kind": "PATCH_ORPHAN" if not found else "PATCH_SIG_MISMATCH",
                    "type": dump_key,
                    "member": method_name,
                    "expected_params": param_types,
                    "source_locations": sorted(set(
                        f"{f['source_file']}:{f['source_line']}" for f in group
                    )),
                    "severity": "fatal" if not found else "high",
                    "detail": (f"Method '{method_name}' not found in {dump_key}."
                               if not found else
                               f"Method '{method_name}' exists but with different parameters."),
                })
            else:
                # Method found — check param compatibility
                actual_params, actual_ret = dump_entry['methods'][method_name]
                if param_types is not None:
                    actual_param_list = [p.strip() for p in actual_params.split(',') if p.strip()]
                    if len(actual_param_list) != len(param_types):
                        results.append({
                            "kind": "PATCH_SIG_MISMATCH",
                            "type": dump_key,
                            "member": method_name,
                            "expected_sig": f"({', '.join(param_types)})",
                            "actual_sig": f"({actual_params})",
                            "source_locations": sorted(set(
                                f"{f['source_file']}:{f['source_line']}" for f in group
                            )),
                            "severity": "high",
                            "detail": f"Param count mismatch: expected {len(param_types)}, got {len(actual_param_list)}.",
                        })

        elif patch_kind in ("gamemember_findfields",):
            field_name = representative.get("member", "")
            # Apply field rename map (try short and full type names)
            type_sn_f = type_name.split('.')[-1] if '.' in type_name else type_name
            for lookup_key in (f"{type_sn_f}.{field_name}", f"{type_name}.{field_name}"):
                if lookup_key in field_renames:
                    field_name = field_renames[lookup_key]
                    break
            if field_name and field_name not in dump_entry['fields']:
                results.append({
                    "kind": "PATCH_FIELD_MISSING",
                    "type": dump_key,
                    "member": field_name,
                    "source_locations": sorted(set(
                        f"{f['source_file']}:{f['source_line']}" for f in group
                    )),
                    "severity": "high",
                    "detail": f"Field '{field_name}' not found in {dump_key}. Available: {sorted(dump_entry['fields'].keys())[:20]}...",
                })
            elif field_name and field_name in dump_entry['fields']:
                actual_type = dump_entry['fields'][field_name]
                expected_type = representative.get("field_type", "")
                if expected_type and expected_type != actual_type:
                    results.append({
                        "kind": "PATCH_FIELD_TYPE",
                        "type": dump_key,
                        "member": field_name,
                        "expected_type": expected_type,
                        "actual_type": actual_type,
                        "source_locations": sorted(set(
                            f"{f['source_file']}:{f['source_line']}" for f in group
                        )),
                        "severity": "high",
                        "detail": f"Field type changed: {expected_type} -> {actual_type}.",
                    })

        elif patch_kind in ("accesstools_constructor",):
            method_name = ".ctor"
            param_types = representative.get("params", [])
            if method_name in dump_entry['methods']:
                actual_params, _ = dump_entry['methods'][method_name]
                actual_param_list = [p.strip() for p in actual_params.split(',') if p.strip()]
                if len(actual_param_list) != len(param_types):
                    results.append({
                        "kind": "PATCH_CTOR_SIG_MISMATCH",
                        "type": dump_key,
                        "member": ".ctor",
                        "expected_sig": f"({', '.join(param_types)})",
                        "actual_sig": f"({actual_params})",
                        "source_locations": sorted(set(
                            f"{f['source_file']}:{f['source_line']}" for f in group
                        )),
                        "severity": "high",
                        "detail": f"Constructor param count mismatch.",
                    })

        elif patch_kind in ("accesstools_property", "accesstools_field"):
            member_name = representative.get("member", "")
            # Apply field rename map (try short and full type names)
            type_sn_m = type_name.split('.')[-1] if '.' in type_name else type_name
            for lookup_key in (f"{type_sn_m}.{member_name}", f"{type_name}.{member_name}"):
                if lookup_key in field_renames:
                    member_name = field_renames[lookup_key]
                    break
            lookup = dump_entry['props'] if patch_kind == "accesstools_property" else dump_entry['fields']
            if member_name and member_name not in lookup:
                results.append({
                    "kind": "PATCH_MEMBER_MISSING",
                    "type": dump_key,
                    "member": member_name,
                    "source_locations": sorted(set(
                        f"{f['source_file']}:{f['source_line']}" for f in group
                    )),
                    "severity": "high",
                    "detail": f"{'Property' if 'property' in patch_kind else 'Field'} '{member_name}' not found in {dump_key}.",
                })

    # Sort by severity then type
    sev_order = {"fatal": 0, "high": 1, "medium": 2, "low": 3}
    results.sort(key=lambda r: (sev_order.get(r.get("severity", "low"), 3), r.get("type", ""), r.get("member", "")))

    return results


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Cross-reference Harmony patches and GameMember calls against a dump.cs."
    )
    parser.add_argument("dump", help="Path to Il2CppDumper dump.cs")
    parser.add_argument("--source", "-s",
                        default="Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod",
                        help="Path to OfflineUnlockMod source directory")
    parser.add_argument("--rename-map", "-r", help="Path to rename_map.json from map_obfuscation.py")
    parser.add_argument("--output", "-o", help="Output JSON report path")
    parser.add_argument("--no-probes", action="store_true",
                        help="Skip diagnostic probe files (*Probe.cs)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    print(f"Loading dump index from: {args.dump}")
    dump_index = _load_dump_index(args.dump)
    print(f"  Indexed {len(dump_index)} types")

    rename_map = None
    if args.rename_map:
        with open(args.rename_map, 'r') as f:
            rename_map = json.load(f)
        print(f"  Loaded rename map with {len(rename_map.get('type_renames', {}))} type renames")

    print(f"\nScanning source: {args.source}")
    findings = parse_patches(args.source, skip_probes=args.no_probes)
    print(f"  Found {len(findings)} patch targets")

    print(f"\nVerifying against dump...")
    results = verify_against_dump(findings, dump_index, rename_map)

    # Print report
    fatal_count = sum(1 for r in results if r.get("severity") == "fatal")
    high_count = sum(1 for r in results if r.get("severity") == "high")
    medium_count = sum(1 for r in results if r.get("severity") == "medium")

    print(f"\n{'=' * 70}")
    print(f"VERIFICATION REPORT")
    print(f"{'=' * 70}")
    print(f"  Total patch targets scanned: {len(findings)}")
    print(f"  Issues found: {len(results)}")
    print(f"    FATAL: {fatal_count} (type or method completely gone)")
    print(f"    HIGH:  {high_count} (signature mismatch, field type change)")
    print(f"    MEDIUM: {medium_count}")

    if results:
        print(f"\n{'=' * 70}")
        print(f"ISSUES (sorted by severity)")
        print(f"{'=' * 70}")
        for r in results:
            sev = r["severity"].upper()
            kind = r["kind"]
            typ = r.get("type", "?")
            member = r.get("member", "?")
            detail = r.get("detail", "")
            sources = ", ".join(r.get("source_locations", [])[:3])
            print(f"\n[{sev}] {kind}: {typ}.{member}")
            if detail:
                print(f"  {detail}")
            if sources:
                print(f"  Source: {sources}")
    else:
        print(f"\n  No issues found. All patch surfaces verified.")

    # Output JSON if requested
    if args.output:
        report = OrderedDict()
        report["patch_findings"] = results
        report["summary"] = OrderedDict([
            ("dump_path", os.path.abspath(args.dump)),
            ("source_dir", os.path.abspath(args.source)),
            ("types_indexed", len(dump_index)),
            ("patch_targets_scanned", len(findings)),
            ("issues_total", len(results)),
            ("issues_fatal", fatal_count),
            ("issues_high", high_count),
            ("issues_medium", medium_count),
        ])
        with open(args.output, 'w') as f:
            json.dump(report, f, indent=2)
        print(f"\nReport written to: {args.output}")

    # Exit with non-zero if fatal issues
    if fatal_count > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()
