"""Port index model (format port_index.v2, written by PortInterop `index`).

Row layout (tab separated, first line "#port_index.v2"):
  T asm fullName name obfAttr native typeOrd base kind flags genericArity nFields nMethods interfaces
  M asm owner name native ord static signature obfAttr
  F asm owner name native ord static fieldType obfAttr
  P asm owner name native ord static propertyType obfAttr

`native` on a type is "<image>|<namespace>|<name>" (top level) or "+|<name>" (nested), read from the
wrapper's static constructor (IL2CPP.GetIl2CppClass / GetIl2CppNestedType). On members it is
"tok:<metadata token>[:<native method name>]" (methods, NativeMethodInfoPtr_ fields) or
"fld:<native field name>" (field wrapper properties, their accessors, NativeFieldInfoPtr_ fields).

The model folds the interop plumbing into *core members*: one per native field ("f", name) and one per
native method ("m", token), plus plain C# properties ("p", name). Every interop row that exists because of a
core member (the wrapper property, get_/set_ accessors, the NativeFieldInfoPtr_/NativeMethodInfoPtr_ field)
is attached to that core with a role, so a remap of the core member carries every interop spelling.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

OBF_NATIVE = re.compile(r'^[a-z]{1,4}$')
BACKING = re.compile(r'^<([^>]+)>k__BackingField$')
ARITY = re.compile(r'`\d+$')
# compiler-generated names carrying a declaration ordinal (<Foo>d__74, <>c__DisplayClass12_0, <>c__3):
# the ordinal shifts when methods are added, so the name is not an identity across builds.
ORDINAL_GENERATED = re.compile(r'__\d+|DisplayClass\d+')


def native_is_obfuscated(name: str) -> bool:
    """True when a native (IL2CPP) identifier looks like an obfuscator-assigned name.

    Deliberately over-inclusive: real short lowercase names ("id", "hp", "sid") are classified as
    obfuscated too, which only hides information from the matcher; it never creates a false identity."""
    if not name:
        return True
    m = BACKING.match(name)
    if m:
        name = m.group(1)
    return bool(OBF_NATIVE.match(ARITY.sub('', name)))


def type_name_is_identity(name: str) -> bool:
    """A native type-name component that identifies the same type in another build."""
    return not native_is_obfuscated(name) and not ORDINAL_GENERATED.search(name)


@dataclass
class Row:
    kind: str       # M F P
    name: str       # interop name
    native: str     # raw native column
    ord: int
    static: bool
    sig: str        # signature (M) or member type (F/P)
    obf: str


@dataclass
class Core:
    key: tuple                  # ("f", nativeName) | ("m", token) | ("p", name) | ("c", name)
    cat: str                    # "field" | "method" | "prop" | "const"
    native_name: str            # native identifier ("" when unknown)
    sig: str                    # representative signature (method sig or field type)
    static: bool
    ord: int                    # declaration ordinal within its category
    rows: dict = field(default_factory=dict)   # role -> interop Row

    @property
    def real_name(self) -> str | None:
        """Native name usable as a stable identity, or None when it is obfuscated/unknown."""
        n = self.native_name
        return None if native_is_obfuscated(n) or ORDINAL_GENERATED.search(n) else n


@dataclass
class TypeInfo:
    full: str           # interop full name (Cecil form, '/' for nesting)
    asm: str
    name: str
    obf: str
    native_ns: str
    native_name: str
    parent: str | None
    ord: int
    base: str
    kind: str
    flags: str
    arity: int
    interfaces: list
    rows: list = field(default_factory=list)
    cores: list = field(default_factory=list)

    @property
    def runtime_full(self) -> str:
        """Reflection Type.FullName spelling of the interop type ('+' for nesting)."""
        return self.full.replace('/', '+')

    @property
    def native_path(self) -> str:
        return (self.native_ns + '.' if self.native_ns else '') + self.native_name


class Index:
    def __init__(self, types: dict[str, TypeInfo]):
        self.types = types
        self.by_asm: dict[str, list[TypeInfo]] = {}
        for t in types.values():
            self.by_asm.setdefault(t.asm, []).append(t)
        for lst in self.by_asm.values():
            lst.sort(key=lambda t: t.ord)
        self._finish()

    def _finish(self):
        for t in self.types.values():
            if t.parent and t.parent in self.types:
                p = self.types[t.parent]
                t.native_ns = p.native_ns
            t.cores = build_cores(t.rows)
        # native namespace/name chains for nested types
        for t in self.types.values():
            chain = []
            cur = t
            while cur is not None:
                chain.append(cur.native_name or cur.name)
                cur = self.types.get(cur.parent) if cur.parent else None
            t.native_chain = list(reversed(chain))

    def is_stable(self, t: TypeInfo) -> bool:
        """Every component of the native path is a real (non-obfuscated) name."""
        cur = t
        while cur is not None:
            if not type_name_is_identity(cur.native_name or cur.name):
                return False
            cur = self.types.get(cur.parent) if cur.parent else None
        return True

    def stable_key(self, t: TypeInfo) -> str:
        return t.asm + '::' + (t.native_ns + '.' if t.native_ns else '') + '/'.join(t.native_chain)


def build_cores(rows: list[Row]) -> list[Core]:
    cores: dict[tuple, Core] = {}
    counters = {'field': 0, 'method': 0, 'prop': 0, 'const': 0}

    def get(key, cat, native_name, sig, static):
        c = cores.get(key)
        if c is None:
            c = Core(key, cat, native_name, sig, static, counters[cat])
            counters[cat] += 1
            cores[key] = c
        return c

    for r in rows:
        nat = r.native
        if r.kind == 'P' and nat.startswith('fld:'):
            c = get(('f', nat[4:]), 'field', nat[4:], r.sig, r.static)
            c.sig, c.static = r.sig, r.static
            c.rows['prop'] = r
        elif r.kind == 'P':
            c = get(('p', r.name), 'prop', r.name, r.sig, r.static)
            c.rows['prop'] = r
    for r in rows:
        nat = r.native
        if r.kind == 'M' and nat.startswith('tok:'):
            parts = nat.split(':', 2)
            c = get(('m', int(parts[1])), 'method', parts[2] if len(parts) > 2 else '', r.sig, r.static)
            c.sig, c.static = r.sig, r.static
            c.rows['method'] = r
        elif r.kind == 'M' and nat.startswith('fld:'):
            c = get(('f', nat[4:]), 'field', nat[4:], '', r.static)
            role = 'get' if r.name.startswith('get_') else 'set' if r.name.startswith('set_') else 'accessor'
            c.rows[role] = r
        elif r.kind == 'F' and nat.startswith('fld:'):
            c = get(('f', nat[4:]), 'field', nat[4:], '', r.static)
            c.rows['ptr'] = r
        elif r.kind == 'F' and nat.startswith('tok:'):
            c = get(('m', int(nat.split(':')[1])), 'method', '', '', r.static)
            c.rows['ptr'] = r
        elif r.kind == 'F' and not nat and not r.name.startswith(('NativeFieldInfoPtr_', 'NativeMethodInfoPtr_')):
            # enum literals / value__ : interop keeps the native name
            c = get(('c', r.name), 'const', r.name, r.sig, r.static)
            c.rows['const'] = r
    # a plain C# property is identified by its accessor's native method name (get_Foo -> Foo); the interop
    # property name itself may be generated from obfuscated tokens (prop_ObjectPublic..._0)
    mnative = {r.name: r.native.split(':', 2)[2] for r in rows
               if r.kind == 'M' and r.native.startswith('tok:') and r.native.count(':') >= 2}
    for c in cores.values():
        if c.cat != 'prop':
            continue
        pname = c.rows['prop'].name
        nat = mnative.get('get_' + pname) or mnative.get('set_' + pname) or ''
        c.native_name = nat[4:] if nat.startswith(('get_', 'set_')) else ''
    out = list(cores.values())
    # ordinals by declaration order of the defining row per category
    for cat in ('field', 'method', 'prop', 'const'):
        lst = [c for c in out if c.cat == cat]
        lst.sort(key=lambda c: (c.rows.get('prop') or c.rows.get('method') or next(iter(c.rows.values()))).ord)
        for i, c in enumerate(lst):
            c.ord = i
    return out


def load(path: str) -> Index:
    types: dict[str, TypeInfo] = {}
    with open(path, encoding='utf-8') as f:
        head = f.readline()
        if not head.startswith('#port_index.v2'):
            raise ValueError(f'{path}: not a port_index.v2 file')
        for line in f:
            p = line.rstrip('\n').split('\t')
            if p[0] == 'T':
                asm, full, name, obf, native, ordv, base, kind, flags, arity, _nf, _nm, ifaces = p[1:14]
                if native.startswith('+|'):
                    ns, nname = '', native[2:]
                elif native:
                    _img, ns, nname = native.split('|', 2)
                else:  # no static constructor (enums, some interfaces): the interop name is the native name
                    ns, nname = (full.rsplit('.', 1)[0] if '.' in full.split('/')[0] else ''), (obf.split('+')[-1] if obf else name)
                parent = full.rsplit('/', 1)[0] if '/' in full else None
                if not native and kind != 'enum' and (name == '<Module>' or name.startswith('MethodInfoStoreGeneric_')):
                    continue  # interop plumbing with no native counterpart
                types[full] = TypeInfo(full, asm, name, obf, ns, nname, parent, int(ordv), base, kind, flags,
                                       int(arity), [x for x in ifaces.split(';') if x])
            else:
                kind, asm, owner, name, native, ordv, static, sig = p[:8]
                obf = p[8] if len(p) > 8 else ''
                if owner not in types:
                    continue
                types[owner].rows.append(Row(kind, name, native, int(ordv), static == 's', sig, obf))
    return Index(types)
