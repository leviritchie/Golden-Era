"""Build the Ghidra label table for one Olden Era build from the port index.

Joins `native_addresses.tsv` MA rows (native type/method -> VA, keyed by assembly + metadata token) with
`port_index.tsv` M rows (same key -> interop type/member + signature), and decodes the IL2CPP metadata-usage
globals in GameAssembly's writable sections (metadata v31 slots hold `(kind << 29) | (index << 1) | 1` before lazy init)
into TypeInfo / MethodInfo / StringLiteral labels. Output is consumed by ImportOeSymbols.java.

Output `labels.tsv` (UTF-8, tab separated, no header besides the pin line):
  F  va  primary_name  alias|alias...  comment     function entry (first method at a VA names it)
  D  va  name          -               comment     metadata-usage global

Every string the metadata carries is labelled (StringLiteral_<index>_<text>), but the 25672315 string table holds
only ~16k mostly-framework strings: game literals such as "undead" are absent, so start from method VAs.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import struct
import sys
import time
from collections import defaultdict
from pathlib import Path

USAGE_KIND = {1: 'TypeInfo', 2: 'Il2CppType', 3: 'MethodInfo', 4: 'FieldInfo', 5: 'StringLiteral', 6: 'MethodRef'}
MAX_ALIASES = 8
_BAD = re.compile(r'[^A-Za-z0-9_.$@<>,`+\-\[\]]')


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest().upper()


def clean(name: str, limit: int = 180) -> str:
    return _BAD.sub('_', name)[:limit] or '_'


def comment_text(s: str) -> str:
    return s.replace('\t', ' ').replace('\r', ' ').replace('\n', ' ')[:300]


def read_native(tsv: Path):
    by_key: dict[tuple[str, int], tuple[int, str, str]] = {}
    md: dict[int, str] = {}
    sl: dict[int, str] = {}
    ty: dict[int, str] = {}
    with open(tsv, encoding='utf-8', errors='replace') as f:
        head = f.readline().rstrip('\n').split('\t')
        if head[0] != '#native_addresses.v1':
            sys.exit(f'{tsv}: not a native_addresses.v1 file')
        meta = dict(x.split('=', 1) for x in head[1:])
        for line in f:
            p = line.rstrip('\n').split('\t')
            k = p[0]
            if k == 'MA':
                asm = p[1][:-4] if p[1].endswith('.dll') else p[1]
                by_key[(asm, int(p[4]))] = (int(p[5], 16), p[2], p[3])
            elif k == 'MD':
                md[int(p[1])] = p[2] + '$$' + p[3]
            elif k == 'SL':
                sl[int(p[1])] = p[2] if len(p) > 2 else ''
            elif k == 'TY':
                ty[int(p[1])] = p[2] if len(p) > 2 else ''
    return meta, by_key, md, sl, ty


def read_interop(index: Path) -> dict[tuple[str, int], tuple[str, str, str]]:
    out = {}
    with open(index, encoding='utf-8', errors='replace') as f:
        for line in f:
            if not line.startswith('M\t'):
                continue
            p = line.rstrip('\n').split('\t')
            if len(p) < 8 or not p[4].startswith('tok:'):
                continue
            tok = int(p[4].split(':')[1])
            out[(p[1], tok)] = (p[2], p[3], p[7])
    return out


def usage_globals(ga: Path, md, sl, ty):
    import pefile
    data = ga.read_bytes()
    pe = pefile.PE(data=data, fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    sizes = {1: len(ty), 2: len(ty), 3: len(md), 5: len(sl)}
    for s in pe.sections:
        if not s.Characteristics & 0x80000000:        # writable only
            continue
        raw = data[s.PointerToRawData:s.PointerToRawData + s.SizeOfRawData]
        va0 = base + s.VirtualAddress
        for off in range(0, len(raw) - 7, 8):
            q = struct.unpack_from('<Q', raw, off)[0]
            # metadata v31: (kind << 29) | (index << 1) | 1 in the low 32 bits, upper 32 bits zero until init
            if not (q & 1) or q >= (1 << 32) or q < (1 << 29):
                continue
            kind, idx = (q & 0xE0000000) >> 29, (q & 0x1FFFFFFE) >> 1
            if kind not in USAGE_KIND:
                continue
            if kind in sizes and idx >= sizes[kind]:
                continue
            yield va0 + off, kind, idx
    return base


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--native', type=Path, required=True, help='native_addresses.tsv')
    ap.add_argument('--index', type=Path, required=True, help='port_index.tsv')
    ap.add_argument('--game-assembly', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()

    t0 = time.time()
    meta, by_key, md, sl, ty = read_native(a.native)
    want = meta.get('gameAssemblySha256', '').upper()
    have = sha256_file(a.game_assembly)
    if have != want:
        sys.exit(f'{a.game_assembly}: sha256 {have} is not the indexed GameAssembly {want}')
    interop = read_interop(a.index)

    at: dict[int, list[tuple[str, str]]] = defaultdict(list)   # va -> [(name, comment)]
    joined = 0
    for key, (va, ntype, nname) in by_key.items():
        primary = f'{ntype}$${nname}'
        it = interop.get(key)
        if it:
            joined += 1
            itype, imember, sig = it
            alias = f'{itype}$${imember}'
            at[va].append((primary, alias if alias != primary else '', f'{key[0]} {itype}.{imember} {sig} tok={key[1]}'))
        else:
            at[va].append((primary, '', f'{key[0]} tok={key[1]}'))

    n_f = n_d = 0
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, 'w', encoding='utf-8', newline='\n') as o:
        o.write(f'#oe_ghidra_labels.v1\tgameAssemblySha256={want}\tmetadataSha256={meta.get("metadataSha256", "")}\n')
        for va in sorted(at):
            rows = at[va]
            names = []
            for prim, alias, _c in rows:
                for n in (prim, alias):
                    if n and clean(n) not in names:
                        names.append(clean(n))
            more = f' (+{len(rows) - 1} folded)' if len(rows) > 1 else ''
            comment = comment_text(' | '.join(r[2] for r in rows[:4]) + more)
            o.write(f'F\t{va:X}\t{names[0]}\t{"|".join(names[1:1 + MAX_ALIASES])}\t{comment}\n')
            n_f += 1
        for va, kind, idx in usage_globals(a.game_assembly, md, sl, ty):
            if kind == 5:
                text = sl.get(idx, '')
                name = f'StringLiteral_{idx}_' + clean(text, 40)
                comment = comment_text(repr(text))
            elif kind in (1, 2):
                name = f'{USAGE_KIND[kind]}$${clean(ty.get(idx, str(idx)))}'
                comment = ty.get(idx, '')
            elif kind == 3:
                name = f'MethodInfo$${clean(md.get(idx, str(idx)))}'
                comment = md.get(idx, '')
            else:
                name = f'{USAGE_KIND[kind]}_{idx}'
                comment = ''
            o.write(f'D\t{va:X}\t{name}\t-\t{comment_text(comment)}\n')
            n_d += 1
    print(f'labels: {n_f} function VAs ({len(by_key)} methods, {joined} joined to interop names), '
          f'{n_d} metadata-usage globals -> {a.out} in {time.time() - t0:.1f}s')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
