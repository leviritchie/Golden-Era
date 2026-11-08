"""Harvest symbol-hint string literals from GameSymbols.cs and the resolver layer.

A *group* is one statement: a member declaration (hint array, const, MethodSymbol, FieldSymbol[] ...) or one
statement of a method body. Its symbol is `<nested class path>.<declared name>` (or `<class>.<method>@<line>`
inside method bodies). Literals that are not hints are kept in the group but marked `skip`:
  * symbol ids: the first argument of `new(...)` in MethodSymbol/FieldSymbol declarations, consts named *Id(s);
  * TypeShape arguments (`new TypeShape("base", f, m)`) and TypeHintGroup declarations themselves;
  * arrays referenced as the `current:` scope of a TypeHintGroup (they already hold live names);
  * anything that is not identifier-like.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

IDENT = re.compile(r'^[A-Za-z_<][A-Za-z0-9_<>`.+/]*$')
TOKEN = re.compile(r'''
    (?P<comment>//[^\n]*|/\*.*?\*/)
  | (?P<vstr>@"(?:[^"]|"")*")
  | (?P<istr>\$@?"(?:[^"\\\n]|\\.)*")
  | (?P<str>"(?:[^"\\\n]|\\.)*")
  | (?P<chr>'(?:[^'\\\n]|\\.)+')
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<punct>[{}();=,\[\]:])
  | (?P<nl>\n)
  | (?P<ws>[ \t\r]+)
  | (?P<other>.)
''', re.S | re.X)
MODIFIERS = {'internal', 'public', 'private', 'protected', 'static', 'readonly', 'const', 'sealed', 'override', 'new'}
SYMBOL_TYPES = {'MethodSymbol', 'FieldSymbol'}


@dataclass
class Lit:
    value: str
    line: int
    skip: str = ''


@dataclass
class Group:
    file: str
    line: int
    symbol: str
    decl_type: str = ''
    literals: list = field(default_factory=list)
    scope_refs: dict = field(default_factory=dict)     # TypeHintGroup: {'golden': [...idents], 'current': [...]}

    @property
    def hints(self) -> list[str]:
        return [l.value for l in self.literals if not l.skip]


def tokenize(text: str):
    line = 1
    for m in TOKEN.finditer(text):
        kind, val = m.lastgroup, m.group(0)
        start = line
        line += val.count('\n')
        if kind in ('comment', 'nl', 'ws', 'other', 'chr'):
            continue
        yield kind, val, start


def _unescape(raw: str) -> str:
    out, i = [], 0
    simple = {'n': '\n', 't': '\t', 'r': '\r', '0': '\0', '\\': '\\', '"': '"', "'": "'"}
    while i < len(raw):
        c = raw[i]
        if c == '\\' and i + 1 < len(raw):
            out.append(simple.get(raw[i + 1], raw[i + 1]))
            i += 2
        else:
            out.append(c)
            i += 1
    return ''.join(out)


class _Stmt:
    def __init__(self, line):
        self.line = line
        self.toks: list = []
        self.has_eq = False
        self.paren = 0
        self.calls: list = []       # stack of [callee, argIndex]
        self.lits: list[Lit] = []
        self.scope = None
        self.scope_refs: dict = {}


def harvest_file(path: Path, rel: str) -> list[Group]:
    groups: list[Group] = []
    braces: list[tuple[str, str]] = []      # (kind 'class'|'method'|'block'|'init', name)
    st: _Stmt | None = None

    def class_path():
        return '.'.join(n for k, n in braces if k == 'class')

    def method_name():
        for k, n in reversed(braces):
            if k == 'method':
                return n
        return None

    def close():
        nonlocal st
        if st is None:
            return
        idents = [v for k, v, _ in st.toks if k == 'ident']
        decl = [v for v in idents if v not in MODIFIERS]
        decl_type = decl[0] if decl and idents and idents[0] in MODIFIERS else ''
        name = ''
        for j, (k, v, _) in enumerate(st.toks):
            if k == 'punct' and v == '=':
                if j and st.toks[j - 1][0] == 'ident':
                    name = st.toks[j - 1][1]
                break
        cp = class_path()
        # drop the outermost class (GameSymbols / file class) from the label
        cp = '.'.join(cp.split('.')[1:]) if '.' in cp else ('' if rel.endswith('GameSymbols.cs') else cp)
        m = method_name()
        if m:
            sym = f'{cp + "." if cp else ""}{m}@{st.line}'
        else:
            sym = f'{cp + "." if cp else ""}{name or "@" + str(st.line)}'
        if st.lits:
            g = Group(rel, st.line, sym, decl_type, st.lits, st.scope_refs)
            if not m and name and re.search(r'Ids?$', name) and decl_type in ('string', 'string[]'):
                for l in g.literals:
                    l.skip = l.skip or 'symbol id const'
            if decl_type == 'TypeHintGroup':
                for l in g.literals:
                    l.skip = l.skip or 'TypeHintGroup declaration'
            groups.append(g)
        elif decl_type == 'TypeHintGroup':
            groups.append(Group(rel, st.line, sym, decl_type, [], st.scope_refs))
        st = None

    toks = list(tokenize(path.read_text(encoding='utf-8-sig')))
    for i, (kind, val, line) in enumerate(toks):
        if kind == 'punct' and val == '{':
            if st is not None and st.has_eq:
                braces.append(('init', ''))
                st.toks.append((kind, val, line))
                continue
            idents = [v for k, v, _ in (st.toks if st else []) if k == 'ident']
            if any(v in ('class', 'struct', 'interface', 'enum') for v in idents):
                kw = next(j for j, v in enumerate(idents) if v in ('class', 'struct', 'interface', 'enum'))
                braces.append(('class', idents[kw + 1] if kw + 1 < len(idents) else '?'))
            elif st is not None and any(v == '(' for k, v, _ in st.toks) and method_name() is None:
                j = next(j for j, (k, v, _) in enumerate(st.toks) if v == '(')
                braces.append(('method', st.toks[j - 1][1] if j else '?'))
            else:
                braces.append(('block', ''))
            close()
            continue
        if kind == 'punct' and val == '}':
            k = braces.pop()[0] if braces else 'block'
            if k == 'init' and st is not None:
                st.toks.append((kind, val, line))
                continue
            close()
            continue
        if st is None:
            st = _Stmt(line)
        st.toks.append((kind, val, line))
        if kind == 'punct':
            if val == '=':
                st.has_eq = True
            elif val == '(':
                prev = st.toks[-2][1] if len(st.toks) >= 2 else ''
                prev2 = st.toks[-3][1] if len(st.toks) >= 3 else ''
                callee = 'new' if prev == 'new' else ('new ' + prev if prev2 == 'new' else prev)
                st.calls.append([callee, 0])
                st.paren += 1
            elif val == ')':
                if st.calls:
                    st.calls.pop()
                st.paren -= 1
            elif val == ',' and st.calls:
                st.calls[-1][1] += 1
            elif val == ':' and len(st.toks) >= 2 and st.toks[-2][1] in ('golden', 'current'):
                st.scope = st.toks[-2][1]
                st.scope_refs.setdefault(st.scope, [])
            elif val == ';' and st.paren <= 0:
                close()
            continue
        if kind == 'ident' and st.scope and val not in ('new', 'TypeShape', 'TypeHintScope', 'None'):
            st.scope_refs[st.scope].append(val)
        if kind in ('str', 'vstr'):
            s = val[2:-1].replace('""', '"') if kind == 'vstr' else _unescape(val[1:-1])
            skip = ''
            idents = [v for k, v, _ in st.toks if k == 'ident']
            decl_type = next((v for v in idents if v not in MODIFIERS), '') if idents and idents[0] in MODIFIERS else ''
            if not IDENT.match(s) or s.isdigit():
                skip = 'not identifier-like'
            elif any(c[0] == 'new TypeShape' for c in st.calls):
                skip = 'TypeShape argument'
            elif st.calls and st.calls[-1][0] in ('new', 'new MethodSymbol', 'new FieldSymbol') and st.calls[-1][1] == 0 \
                    and decl_type in SYMBOL_TYPES:
                skip = 'symbol id'
            st.lits.append(Lit(s, line, skip))
    close()
    return groups


def harvest(plugin_dir: Path, files: list[str]) -> tuple[list[Group], dict]:
    groups: list[Group] = []
    sources = {}
    for rel in files:
        p = plugin_dir / rel
        sources[rel] = hashlib.sha256(p.read_bytes()).hexdigest().upper()
        groups.extend(harvest_file(p, rel))
    # arrays used as the `current:` scope of a TypeHintGroup already hold live names
    current_refs = {r for g in groups if g.decl_type == 'TypeHintGroup' for r in g.scope_refs.get('current', [])}
    for g in groups:
        if g.symbol.split('.')[-1] in current_refs:
            for l in g.literals:
                l.skip = l.skip or 'TypeHintGroup current scope (live names)'
    return [g for g in groups if g.literals], sources
