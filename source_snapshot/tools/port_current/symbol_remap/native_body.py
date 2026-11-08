"""Native-body evidence for member gaps the index alone cannot settle.

The P1 member matcher leaves a method UNMAPPED when its order gap holds several same-signature methods on one
side and a different number on the other ("ambiguous: 3 golden vs 1 live"), or when the signature changed and
more than one same-shape candidate remains. Those are exactly the cases where the metadata carries no identity.
The machine code does: IL2CPP compiles each method body to one function, and a body that survived the update
keeps its string literals, the metadata it touches, the real-named methods it calls, its float constants and
its instruction mix, while obfuscated names and addresses change.

Inputs per build (both read-only):
  * native_addresses.tsv from `PortInterop native-addresses` (method pointer per metadata token, and the
    methodDef / string-literal / type index tables); its header pins the GameAssembly.dll and metadata sha256.
  * GameAssembly.dll with that sha256 (function bounds from .pdata; capstone disassembly).

Features of one body (multisets, compared with Dice per class, weighted):
  S  string literals (decoded metadata-usage globals, kind 5)                               weight 4
  C  callees: real-named methods by name; obfuscated or helper callees by a hash of the
     callee's own first instructions                                                         weight 3
  M  metadata methods/types the body initialises (usage kinds 1-4, 6), obfuscated tokens
     replaced by a placeholder                                                               weight 2
  K  read-only constants loaded RIP-relative from .rdata (float/double literals)           weight 1.5
  I  immediates                                                                              weight 1
  D  memory displacements (field offsets; they shift when fields are added)                  weight 0.5
  N  mnemonic trigrams                                                                       weight 2
  Z  instruction-count ratio                                                                 weight 1

Acceptance (`assign`): a golden method takes a live candidate only as a *mutual* best - its score is at least
`MIN_SCORE`, beats the method's second-best live candidate by `MIN_MARGIN`, and beats every other golden
method's score on that live candidate by `MIN_MARGIN`. Nothing is forced; everything else stays UNMAPPED.
The floors are calibrated on real-named ground truth (`calibrate`), recorded next to the remap.
"""
from __future__ import annotations

import bisect
import hashlib
import random
import re
import struct
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

from .model import ORDINAL_GENERATED, Core, Index, native_is_obfuscated, type_name_is_identity

MIN_SCORE = 0.60
MIN_MARGIN = 0.10
NATIVE_CONF = 0.80          # MemberMatch confidence for an accepted native-body pair (>= match.MEMBER_MIN_CONF)
WEIGHTS = {'S': 4.0, 'C': 3.0, 'M': 2.0, 'K': 1.5, 'I': 1.0, 'D': 0.5, 'N': 2.0}
MAX_BODY = 1 << 16
# Body features are a pure function of the VA, so the cache is bounded (LRU): an unbounded cache grew past
# the machine's RAM on the 25509697 remap (MemoryError, 2026-09-30); a large method's entry is hundreds of KB,
# so even 15000 entries reached ~10 GB. Eviction only costs a re-disassembly.
FEATURE_CACHE_MAX = 2000
IDENT = re.compile(r'[A-Za-z_<>][\w<>`$]*')


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest().upper()


def _identity_name(name: str) -> bool:
    return bool(name) and not native_is_obfuscated(name) and not ORDINAL_GENERATED.search(name)


def _mask_type(s: str) -> str:
    """Replace every obfuscated identifier in a type spelling with 'O' (they differ between builds)."""
    return IDENT.sub(lambda m: m.group(0) if type_name_is_identity(m.group(0).split('`')[0]) else 'O', s)


def _dice(a: Counter, b: Counter) -> float:
    na, nb = sum(a.values()), sum(b.values())
    if na + nb == 0:
        return 1.0
    return 2.0 * sum((a & b).values()) / (na + nb)


class NativeSide:
    """One build's native code: method pointers by (assembly, token) and body fingerprints."""

    def __init__(self, tsv: Path, game_assembly: Path, expect_ga_sha: str, expect_md_sha: str | None = None):
        import capstone
        import pefile
        self._cs = capstone
        with open(tsv, encoding='utf-8') as f:
            head = f.readline().rstrip('\n').split('\t')
            if head[0] != '#native_addresses.v1':
                raise ValueError(f'{tsv}: not a native_addresses.v1 file')
            meta = dict(x.split('=', 1) for x in head[1:])
            if meta.get('gameAssemblySha256', '').upper() != expect_ga_sha.upper():
                raise ValueError(f'{tsv}: made from GameAssembly {meta.get("gameAssemblySha256")}, index expects {expect_ga_sha}')
            if expect_md_sha and meta.get('metadataSha256', '').upper() != expect_md_sha.upper():
                raise ValueError(f'{tsv}: made from metadata {meta.get("metadataSha256")}, index expects {expect_md_sha}')
            self.by_tok: dict[tuple[str, int], int] = {}
            self.at: dict[int, tuple[str, str, str]] = {}
            self.md: dict[int, str] = {}
            self.sl: dict[int, str] = {}
            self.ty: dict[int, str] = {}
            for line in f:
                p = line.rstrip('\n').split('\t')
                k = p[0]
                if k == 'MA':
                    asm = p[1][:-4] if p[1].endswith('.dll') else p[1]
                    va = int(p[5], 16)
                    self.by_tok[(asm, int(p[4]))] = va
                    self.at.setdefault(va, (asm, p[2], p[3]))
                elif k == 'MD':
                    t, n = p[2], p[3]
                    self.md[int(p[1])] = (t + '::' + n) if _identity_name(n) and all(
                        type_name_is_identity(x) for x in re.split(r'[./+]', t) if x) else 'O::' + ('n' if _identity_name(n) else 'O')
                elif k == 'SL':
                    self.sl[int(p[1])] = p[2] if len(p) > 2 else ''
                elif k == 'TY':
                    self.ty[int(p[1])] = _mask_type(p[2] if len(p) > 2 else '')
        actual = sha256_file(game_assembly)
        if actual != expect_ga_sha.upper():
            raise ValueError(f'{game_assembly}: sha256 {actual} is not the indexed GameAssembly {expect_ga_sha}')
        self.data = Path(game_assembly).read_bytes()
        pe = pefile.PE(data=self.data, fast_load=True)
        self.base = pe.OPTIONAL_HEADER.ImageBase
        self.sections = [(s.VirtualAddress, s.VirtualAddress + max(s.Misc_VirtualSize, s.SizeOfRawData), s.PointerToRawData,
                          s.SizeOfRawData, s.Name.rstrip(b'\0').decode('ascii', 'replace'), s.Characteristics)
                         for s in pe.sections]
        pd = next(s for s in self.sections if s[4] == '.pdata')
        raw = self.data[pd[2]:pd[2] + pd[3]]
        begins, ends = [], []
        for off in range(0, len(raw) - 11, 12):
            b, e, _u = struct.unpack_from('<III', raw, off)
            if b == 0 and e == 0:
                break
            begins.append(b)
            ends.append(e)
        order = sorted(range(len(begins)), key=begins.__getitem__)
        self.pbeg = [begins[i] for i in order]
        self.pend = [ends[i] for i in order]
        self._md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        self._md.detail = True
        self._feat: OrderedDict[int, dict] = OrderedDict()
        self._shape: dict[int, str] = {}

    # ------------------------------------------------------------------ raw access
    def _section(self, rva: int):
        for s in self.sections:
            if s[0] <= rva < s[1]:
                return s
        return None

    def _read(self, rva: int, n: int) -> bytes | None:
        s = self._section(rva)
        if s is None:
            return None
        off = rva - s[0]
        if off + n > s[3]:
            return None
        return self.data[s[2] + off:s[2] + off + n]

    def _bounds(self, rva: int) -> tuple[int, int]:
        i = bisect.bisect_right(self.pbeg, rva) - 1
        if i >= 0 and self.pbeg[i] <= rva < self.pend[i]:
            return rva, min(self.pend[i], rva + MAX_BODY)
        return rva, rva + 64        # no unwind entry (leaf stub): a short window

    def _insns(self, va: int, limit: int | None = None):
        b, e = self._bounds(va - self.base)
        code = self._read(b, e - b) or b''
        n = 0
        for insn in self._md.disasm(code, va):
            yield insn
            n += 1
            if limit and n >= limit:
                return

    # ------------------------------------------------------------------ fingerprints
    def shape_hash(self, va: int) -> str:
        """Hash of a callee's first instructions (mnemonics + small immediates): identifies runtime helpers and
        unchanged obfuscated callees across builds without their names or addresses."""
        h = self._shape.get(va)
        if h is None:
            toks = []
            for insn in self._insns(va, 48):
                toks.append(insn.mnemonic)
                if insn.mnemonic in ('ret', 'int3'):
                    break
            h = hashlib.sha1(' '.join(toks).encode()).hexdigest()[:12]
            self._shape[va] = h
        return h

    def _callee(self, tgt: int) -> str:
        who = self.at.get(tgt)
        if who is not None:
            _asm, t, n = who
            if _identity_name(n) and all(type_name_is_identity(x) for x in re.split(r'[./+]', t) if x):
                return 'n:' + t + '::' + n
            return 'h:' + self.shape_hash(tgt)
        return 'x:' + self.shape_hash(tgt)

    def _mem(self, feats: dict, addr: int, size: int) -> None:
        rva = addr - self.base
        s = self._section(rva)
        if s is None:
            return
        name, ch = s[4], s[5]
        writable = bool(ch & 0x80000000)
        if writable:
            raw = self._read(rva, 8)
            if raw is None:
                return
            q = struct.unpack('<Q', raw)[0]
            # metadata v31 usage slot before lazy init: (kind << 29) | (index << 1) | 1 in the low 32 bits
            if q & 1 and (1 << 29) <= q < (1 << 32):
                kind, idx = (q & 0xE0000000) >> 29, (q & 0x1FFFFFFE) >> 1
                if kind == 5:
                    feats['S'][self.sl.get(idx, '?')] += 1
                    return
                if kind == 3:
                    feats['M']['m:' + self.md.get(idx, '?')] += 1
                    return
                if kind in (1, 2):
                    feats['M']['t:' + self.ty.get(idx, '?')] += 1
                    return
                if kind in (4, 6, 7):
                    feats['M']['k' + str(kind)] += 1
                    return
            feats['M']['g'] += 1
        elif name in ('.rdata',) and 0 < size <= 16:
            raw = self._read(rva, size)
            if raw is not None:
                feats['K'][raw.hex()] += 1

    def features(self, va: int) -> dict:
        f = self._feat.get(va)
        if f is not None:
            self._feat.move_to_end(va)
            return f
        cs = self._cs
        x86 = cs.x86
        feats = {k: Counter() for k in WEIGHTS}
        mn = []
        b, e = self._bounds(va - self.base)
        lo, hi = self.base + b, self.base + e
        for insn in self._insns(va):
            mn.append(insn.mnemonic)
            ops = insn.operands
            is_call = insn.group(cs.CS_GRP_CALL)
            is_jump = insn.group(cs.CS_GRP_JUMP)
            if (is_call or is_jump) and ops and ops[0].type == x86.X86_OP_IMM:
                tgt = ops[0].imm
                if is_call or not (lo <= tgt < hi):       # calls and tail calls
                    feats['C'][self._callee(tgt)] += 1
                continue
            for op in ops:
                if op.type == x86.X86_OP_MEM:
                    if op.mem.base == x86.X86_REG_RIP:
                        self._mem(feats, insn.address + insn.size + op.mem.disp, op.size)
                    elif op.mem.disp and op.mem.base not in (x86.X86_REG_RSP, x86.X86_REG_RBP):
                        feats['D'][op.mem.disp] += 1
                elif op.type == x86.X86_OP_IMM and abs(op.imm) < (1 << 24):
                    feats['I'][op.imm] += 1
        for i in range(len(mn) - 2):
            feats['N'][(mn[i], mn[i + 1], mn[i + 2])] += 1
        feats['_n'] = len(mn)
        self._feat[va] = feats
        if len(self._feat) > FEATURE_CACHE_MAX:
            self._feat.popitem(last=False)
        return feats

    def va_of(self, asm: str, c: Core) -> int | None:
        if c.cat != 'method' or c.key[0] != 'm':
            return None
        return self.by_tok.get((asm, c.key[1]))


def similarity(fa: dict, fb: dict) -> float:
    num = den = 0.0
    for k, w in WEIGHTS.items():
        a, b = fa[k], fb[k]
        if not a and not b:
            continue
        num += w * _dice(a, b)
        den += w
    na, nb = fa['_n'], fb['_n']
    if na or nb:
        num += 1.0 * (min(na, nb) / max(na, nb))
        den += 1.0
    return num / den if den else 0.0


class BodyEvidence:
    """Golden + live native sides; `pair(gasm, lasm)` binds the assemblies of one owner pair."""

    def __init__(self, golden: NativeSide, live: NativeSide, min_score: float = MIN_SCORE, min_margin: float = MIN_MARGIN):
        self.g, self.l = golden, live
        self.min_score, self.min_margin = min_score, min_margin
        # order cross-check: equal-count gaps the matcher pairs by obfuscator order (99.97% stable), compared
        # with what the body evidence alone would pick there
        self.stats = Counter()
        self.disagreements: list[dict] = []

    def pair(self, gasm: str, lasm: str, owner: str = ''):
        return _BoundPair(self, gasm, lasm, owner)


class _BoundPair:
    confidence = NATIVE_CONF

    def __init__(self, ev: BodyEvidence, gasm: str, lasm: str, owner: str = ''):
        self.ev, self.gasm, self.lasm, self.owner = ev, gasm, lasm, owner

    def cross_check(self, gl: list[Core], ll: list[Core]) -> None:
        res = self.assign(gl, ll)
        for a, b in zip(gl, ll):
            r = res.get(a.key)
            if r is None:
                self.ev.stats['abstain'] += 1
            elif r[0].key == b.key:
                self.ev.stats['agree'] += 1
            else:
                self.ev.stats['disagree'] += 1
                if len(self.ev.disagreements) < 25:
                    from .match import primary_name
                    self.ev.disagreements.append({'owner': self.owner, 'golden': primary_name(a), 'byOrder': primary_name(b),
                                                  'byBody': primary_name(r[0]), 'score': round(r[1], 4), 'margin': round(r[2], 4)})

    def assign(self, A: list[Core], B: list[Core]) -> dict[tuple, tuple[Core, float, float]]:
        """Mutual-best assignment of golden cores A to live cores B; returns golden key -> (live, score, margin)."""
        ga = {a.key: self.ev.g.va_of(self.gasm, a) for a in A}
        lb = {b.key: self.ev.l.va_of(self.lasm, b) for b in B}
        A = [a for a in A if ga[a.key]]
        B = [b for b in B if lb[b.key]]
        if not A or not B:
            return {}
        fa = {a.key: self.ev.g.features(ga[a.key]) for a in A}
        fb = {b.key: self.ev.l.features(lb[b.key]) for b in B}
        S = {(a.key, b.key): similarity(fa[a.key], fb[b.key]) for a in A for b in B}
        out = {}
        for a in A:
            row = sorted(((S[a.key, b.key], i, b) for i, b in enumerate(B)), key=lambda x: (-x[0], x[1]))
            s1, _, b1 = row[0]
            s2 = row[1][0] if len(row) > 1 else 0.0
            col = max((S[x.key, b1.key] for x in A if x.key != a.key), default=0.0)
            margin = min(s1 - s2, s1 - col)
            if s1 >= self.ev.min_score and margin >= self.ev.min_margin:
                out[a.key] = (b1, s1, margin)
        return out


def calibrate(G: Index, L: Index, ev: BodyEvidence, max_groups: int = 4000, max_side: int = 8, seed: int = 7) -> dict:
    """Score `assign` on real-named ground truth: stable type pairs, their real-named methods grouped by shape
    (param count + static), names hidden from the scorer. Groups larger than `max_side` on either side are
    skipped (real order gaps are small). Precision = correct / accepted; recall = correct / answerable."""
    from .match import core_shape
    lkey = {}
    for t in L.types.values():
        if L.is_stable(t):
            lkey.setdefault(L.stable_key(t), []).append(t)
    groups = []
    for t in G.types.values():
        if not G.is_stable(t):
            continue
        ls = lkey.get(G.stable_key(t), [])
        if len(ls) != 1:
            continue
        lt = ls[0]
        gm = defaultdict(list)
        lm = defaultdict(list)
        for c in t.cores:
            if c.cat == 'method' and c.real_name:
                gm[core_shape(c)].append(c)
        for c in lt.cores:
            if c.cat == 'method' and c.real_name:
                lm[core_shape(c)].append(c)
        for shp, A in gm.items():
            B = lm.get(shp, [])
            if len(A) >= 2 and len(B) >= 2 and len(A) <= max_side and len(B) <= max_side:
                if len({c.real_name for c in A}) == len(A) and len({c.real_name for c in B}) == len(B):
                    groups.append((t, lt, A, B))
    rng = random.Random(seed)
    rng.shuffle(groups)
    groups = groups[:max_groups]
    tot = Counter()
    wrong_samples = []
    for t, lt, A, B in groups:
        names_b = {b.real_name for b in B}
        res = ev.pair(t.asm, lt.asm).assign(A, B)
        for a in A:
            answerable = a.real_name in names_b
            tot['answerable'] += answerable
            tot['golden'] += 1
            r = res.get(a.key)
            if r is None:
                continue
            tot['accepted'] += 1
            if r[0].real_name == a.real_name:
                tot['correct'] += 1
            else:
                tot['wrong'] += 1
                if len(wrong_samples) < 20:
                    wrong_samples.append({'owner': t.full, 'golden': a.real_name, 'picked': r[0].real_name,
                                          'score': round(r[1], 4), 'margin': round(r[2], 4)})
    acc = tot['accepted']
    return {'groups': len(groups), 'golden': tot['golden'], 'answerable': tot['answerable'], 'accepted': acc,
            'correct': tot['correct'], 'wrong': tot['wrong'],
            'precision': round(tot['correct'] / acc, 5) if acc else None,
            'recall': round(tot['correct'] / tot['answerable'], 5) if tot['answerable'] else None,
            'minScore': ev.min_score, 'minMargin': ev.min_margin, 'maxSide': max_side, 'seed': seed,
            'wrongSamples': wrong_samples}
