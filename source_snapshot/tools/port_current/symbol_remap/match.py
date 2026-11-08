"""Golden Era -> live type and member matching over two port indexes.

Type matching (per assembly, iterated to a fixed point):
  1. stable-name seeds: a type whose whole native path is real (namespaced or real global names) is the same
     type when the other build has the same path. Confidence 1.0.
  2. exact fingerprints: kind, generic arity, base type, interfaces, parent and the multiset of core-member
     descriptors, with every obfuscated/generated type token replaced by its match id (or a placeholder).
     A fingerprint unique on both sides is a match.
  3. anchor + monotone order alignment: obfuscated names are assigned in declaration order, so the trusted
     matches form a (weighted) longest increasing chain over (golden typeOrd -> live typeOrd). Between two
     consecutive chain anchors, the unmatched golden and live types are aligned by an order-preserving DP over
     a fuzzy structural similarity. Fuzzy scoring never crosses an anchor.
  4. every fuzzy pair gets a margin against its best in-gap alternative (either side). Pairs below the score
     or margin floor are left UNMAPPED with the reason and candidates; nothing is forced.

Member matching (inside a matched owner pair, per category field/method/prop/const):
  real native names first, then signature descriptors unique within the owner, then a monotone chain over those
  anchors in each order domain (obfuscated native names by name rank - the obfuscator's assignment order, 99.97%
  stable across this update - and everything else by declaration order); inside each gap of a chain, members of
  one descriptor pair by order only when both sides hold the same count. Anything else is UNMAPPED with a reason.
"""
from __future__ import annotations

import bisect
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .model import BACKING, ORDINAL_GENERATED, Core, Index, TypeInfo, native_is_obfuscated

TOKEN = re.compile(r'[^\s,()<>\[\]&*]+')

# Acceptance floors (calibrated on the hidden-name validation, see docs/port_to_current_game_version.md).
TYPE_MIN_SCORE = 0.60
TYPE_MIN_MARGIN = 0.08
DP_PAIR_FLOOR = 0.35
MEMBER_MIN_CONF = 0.60


@dataclass
class TypeMatch:
    golden: str
    live: str | None
    method: str             # stable_name | exact | aligned | unmapped
    confidence: float
    score: float = 1.0
    margin: float = 1.0
    reason: str = ''
    candidates: list = field(default_factory=list)


@dataclass
class MemberMatch:
    golden: Core
    live: Core | None
    method: str
    confidence: float
    reason: str = ''
    candidates: list = field(default_factory=list)


class Normalizer:
    """Maps signature type tokens to comparable ids for one side."""

    def __init__(self, idx: Index, match_id: dict[str, str], hidden: set[str]):
        self.idx = idx
        self.match_id = match_id
        self.hidden = hidden
        self._cache: dict[str, str] = {}

    def token(self, tok: str) -> str:
        t = self.idx.types.get(tok)
        if t is None:
            return tok  # external type (System, UnityEngine, Il2CppSystem): stable by name
        mid = self.match_id.get(tok)
        if mid is not None:
            return '#' + mid
        return 'O'

    def sig(self, s: str) -> str:
        r = self._cache.get(s)
        if r is None:
            r = TOKEN.sub(lambda m: self.token(m.group(0)), s)
            self._cache[s] = r
        return r


def core_descriptor(c: Core, norm: Normalizer, hide_names: bool) -> tuple:
    name = None if hide_names else c.real_name
    if c.cat == 'const' and not hide_names:
        name = c.native_name
    return (c.cat, c.static, norm.sig(c.sig), name or '#')


def core_shape(c: Core) -> tuple:
    sig = c.sig
    if c.cat == 'method':
        inner = sig[sig.find('(') + 1:-1] if '(' in sig else ''
        depth = 0
        n = 1 if inner else 0
        for ch in inner:
            if ch == '<':
                depth += 1
            elif ch == '>':
                depth -= 1
            elif ch == ',' and depth == 0:
                n += 1
        return (c.cat, c.static, n)
    return (c.cat, c.static)


def dice(a: Counter, b: Counter) -> float:
    na, nb = sum(a.values()), sum(b.values())
    if na + nb == 0:
        return 1.0
    inter = sum((a & b).values())
    return 2.0 * inter / (na + nb)


def weighted_lis(pairs: list[tuple[int, int, float, object]]) -> set:
    """pairs: (x, y, weight, payload). Returns payloads of a max-weight strictly increasing chain in x and y."""
    pairs = sorted(pairs, key=lambda p: (p[0], -p[1]))
    ys = sorted({p[1] for p in pairs})
    rank = {y: i + 1 for i, y in enumerate(ys)}
    n = len(ys)
    tree = [(0.0, -1)] * (n + 1)

    def query(i):
        best = (0.0, -1)
        while i > 0:
            if tree[i][0] > best[0]:
                best = tree[i]
            i -= i & -i
        return best

    def update(i, val):
        while i <= n:
            if val[0] > tree[i][0]:
                tree[i] = val
            i += i & -i

    prev = [-1] * len(pairs)
    score = [0.0] * len(pairs)
    for k, (x, y, w, _) in enumerate(pairs):
        best = query(rank[y] - 1)
        score[k] = best[0] + w
        prev[k] = best[1]
        update(rank[y], (score[k], k))
    if not pairs:
        return set()
    k = max(range(len(pairs)), key=lambda i: score[i])
    out = set()
    while k != -1:
        out.add(pairs[k][3])
        k = prev[k]
    return out


class TypeMatcher:
    def __init__(self, G: Index, L: Index, *, hidden_golden: set[str] = frozenset(),
                 hidden_live: set[str] = frozenset(), use_stable_names: bool = True):
        self.G, self.L = G, L
        self.hg, self.hl = set(hidden_golden), set(hidden_live)
        self.use_stable = use_stable_names
        self.matches: dict[str, TypeMatch] = {}
        self.rev: dict[str, str] = {}
        self.unmapped: dict[str, TypeMatch] = {}
        self.rounds: list[dict] = []

    # ------------------------------------------------------------------ helpers
    def _add(self, m: TypeMatch):
        self.matches[m.golden] = m
        self.rev[m.live] = m.golden

    def _norms(self):
        gid = {g: g for g in self.matches}
        lid = {m.live: g for g, m in self.matches.items()}
        return Normalizer(self.G, gid, self.hg), Normalizer(self.L, lid, self.hl)

    def _hide(self, side: str, t: TypeInfo) -> bool:
        return t.full in (self.hg if side == 'g' else self.hl)

    def _parent_id(self, side: str, t: TypeInfo) -> str:
        if not t.parent:
            return '-'
        if side == 'g':
            return '#' + t.parent if t.parent in self.matches else 'O'
        g = self.rev.get(t.parent)
        return '#' + g if g else 'O'

    def _desc(self, side: str, t: TypeInfo, norm: Normalizer) -> Counter:
        hide = self._hide(side, t)
        return Counter(core_descriptor(c, norm, hide) for c in t.cores)

    def _stem(self, side: str, t: TypeInfo) -> str | None:
        """Real part of a compiler-generated ordinal name: <GetNickname>d__27 -> <GetNickname>d__#."""
        if self._hide(side, t):
            return None
        n = t.native_name or t.name
        if not ORDINAL_GENERATED.search(n):
            return None
        stem = ORDINAL_GENERATED.sub('__#', n)
        inner = re.findall(r'<([^>]*)>', stem)
        if any(native_is_obfuscated(x) for x in inner if x):
            return None
        return stem

    def _fingerprint(self, side, t, norm, desc) -> tuple:
        return (t.asm, t.kind, t.arity, norm.sig(t.base), tuple(sorted(norm.sig(i) for i in t.interfaces)),
                self._parent_id(side, t), self._stem(side, t), tuple(sorted(desc.items())))

    # ------------------------------------------------------------------ passes
    def seed_stable(self):
        if not self.use_stable:
            return 0
        lkeys = {}
        for t in self.L.types.values():
            if t.full not in self.hl and self.L.is_stable(t):
                lkeys.setdefault(self.L.stable_key(t), []).append(t.full)
        n = 0
        for t in self.G.types.values():
            if t.full in self.hg or not self.G.is_stable(t):
                continue
            ls = lkeys.get(self.G.stable_key(t))
            if ls and len(ls) == 1:
                self._add(TypeMatch(t.full, ls[0], 'stable_name', 1.0))
                n += 1
        return n

    def pass_exact(self, norms, descs):
        ng, nl = norms
        dg, dl = descs
        gfp, lfp = defaultdict(list), defaultdict(list)
        for t in self.G.types.values():
            if t.full not in self.matches:
                gfp[self._fingerprint('g', t, ng, dg[t.full])].append(t.full)
        for t in self.L.types.values():
            if t.full not in self.rev:
                lfp[self._fingerprint('l', t, nl, dl[t.full])].append(t.full)
        n = 0
        for fp, gs in gfp.items():
            ls = lfp.get(fp)
            if ls and len(gs) == 1 and len(ls) == 1:
                self._add(TypeMatch(gs[0], ls[0], 'exact', 0.99))
                n += 1
        return n

    def similarity(self, g: TypeInfo, l: TypeInfo, norms, descs, shapes) -> float:
        if g.asm != l.asm or g.kind != l.kind or g.arity != l.arity:
            return 0.0
        if self._parent_id('g', g) != self._parent_id('l', l) and not (
                self._parent_id('g', g) == 'O' and self._parent_id('l', l) == 'O'):
            return 0.0
        ng, nl = norms
        dg, dl = descs[0][g.full], descs[1][l.full]
        d = dice(dg, dl)
        sd = dice(shapes[0][g.full], shapes[1][l.full])
        b = 1.0 if ng.sig(g.base) == nl.sig(l.base) else 0.0
        ig = Counter(ng.sig(i) for i in g.interfaces)
        il = Counter(nl.sig(i) for i in l.interfaces)
        idc = dice(ig, il)
        a, c = sum(dg.values()), sum(dl.values())
        cnt = 1.0 if a == c else min(a, c) / max(a, c) if max(a, c) else 1.0
        score = 0.55 * d + 0.15 * sd + 0.15 * b + 0.05 * idc + 0.10 * cnt
        sg, sl = self._stem('g', g), self._stem('l', l)
        if sg and sl and sg != sl:
            score *= 0.7
        return score

    def pass_align(self, norms, descs, shapes, final: bool):
        """Anchor + monotone order alignment inside each gap. Returns #new matches."""
        new = 0
        for asm, gl in self.G.by_asm.items():
            ll = self.L.by_asm.get(asm, [])
            gpos = {t.full: i for i, t in enumerate(gl)}
            lpos = {t.full: i for i, t in enumerate(ll)}
            weight = {'stable_name': 4.0, 'exact': 2.0, 'aligned': 1.0, 'aligned_twin_order': 0.5}
            pairs = [(gpos[g], lpos[m.live], weight[m.method], g) for g, m in self.matches.items()
                     if g in gpos and m.live in lpos]
            chain = weighted_lis(pairs)
            for g, m in self.matches.items():
                if g in gpos and m.method == 'exact' and g not in chain and 'off-chain' not in m.reason:
                    m.confidence = 0.85
                    m.reason = 'exact fingerprint, off the monotone anchor chain'
            anchors = sorted((gpos[g], lpos[self.matches[g].live]) for g in chain)
            bounds = [(-1, -1)] + anchors + [(len(gl), len(ll))]
            for (g0, l0), (g1, l1) in zip(bounds, bounds[1:]):
                gs = [t for t in gl[g0 + 1:g1] if t.full not in self.matches]
                ls = [t for t in ll[l0 + 1:l1] if t.full not in self.rev]
                if not gs:
                    continue
                if not ls:
                    if final:
                        for t in gs:
                            self.unmapped[t.full] = TypeMatch(t.full, None, 'unmapped', 0.0, 0, 0,
                                                              'no unmatched live type between the surrounding anchors')
                    continue
                new += self._align_gap(gs, ls, norms, descs, shapes, final)
        return new

    def _align_gap(self, gs, ls, norms, descs, shapes, final) -> int:
        n, m = len(gs), len(ls)
        if n * m > 250000:
            if final:
                for t in gs:
                    self.unmapped[t.full] = TypeMatch(t.full, None, 'unmapped', 0.0, 0, 0,
                                                      f'gap too large for alignment ({n}x{m})')
            return 0
        S = [[self.similarity(g, l, norms, descs, shapes) for l in ls] for g in gs]
        # order-preserving DP maximising sum(score - floor) over accepted pairs
        dp = [[0.0] * (m + 1) for _ in range(n + 1)]
        bt = [[0] * (m + 1) for _ in range(n + 1)]
        for i in range(1, n + 1):
            for j in range(1, m + 1):
                best, how = dp[i - 1][j], 1
                if dp[i][j - 1] > best:
                    best, how = dp[i][j - 1], 2
                s = S[i - 1][j - 1]
                if s > DP_PAIR_FLOOR and dp[i - 1][j - 1] + s - DP_PAIR_FLOOR > best:
                    best, how = dp[i - 1][j - 1] + s - DP_PAIR_FLOOR, 3
                dp[i][j], bt[i][j] = best, how
        i, j, picked = n, m, []
        while i > 0 and j > 0:
            if bt[i][j] == 3:
                picked.append((i - 1, j - 1))
                i, j = i - 1, j - 1
            elif bt[i][j] == 1:
                i -= 1
            else:
                j -= 1
        picked_g = {a for a, _ in picked}
        # twin classes: types structurally identical within the gap (same fingerprint on each side)
        ng, nl = norms
        gfp = [self._fingerprint('g', t, ng, descs[0][t.full]) for t in gs]
        lfp = [self._fingerprint('l', t, nl, descs[1][t.full]) for t in ls]
        added = 0
        for a, b in picked:
            s = S[a][b]
            alt = max([S[a][k] for k in range(m) if k != b] + [S[k][b] for k in range(n) if k != a] + [0.0])
            margin = s - alt
            if s >= TYPE_MIN_SCORE and margin >= TYPE_MIN_MARGIN:
                conf = round(min(0.97, s * min(1.0, 0.6 + 2.0 * margin)), 4)
                self._add(TypeMatch(gs[a].full, ls[b].full, 'aligned', conf, round(s, 4), round(margin, 4)))
                added += 1
                continue
            # Every rival scoring as well is a structural twin of the pair itself (same fingerprint on
            # both sides, same twin count on both sides of the gap). Declaration order is then the only
            # evidence; take it at a capped confidence.
            rivals_l = [k for k in range(m) if k != b and S[a][k] >= s - TYPE_MIN_MARGIN]
            rivals_g = [k for k in range(n) if k != a and S[k][b] >= s - TYPE_MIN_MARGIN]
            twin_g = [k for k in range(n) if gfp[k] == gfp[a]]
            twin_l = [k for k in range(m) if lfp[k] == lfp[b]]
            if s >= 0.9 and len(twin_g) == len(twin_l) > 1                     and all(k in twin_l for k in rivals_l) and all(k in twin_g for k in rivals_g)                     and twin_g.index(a) == twin_l.index(b):
                self._add(TypeMatch(gs[a].full, ls[b].full, 'aligned_twin_order', 0.8, round(s, 4), round(margin, 4),
                                    f'{len(twin_g)} structural twins in the gap; paired by declaration order'))
                added += 1
            elif final:
                cands = sorted(((S[a][k], ls[k].full) for k in range(m)), reverse=True)[:3]
                why = 'ambiguous: best in-gap alternative within margin' if s >= TYPE_MIN_SCORE else 'best in-gap structural score below floor'
                self.unmapped[gs[a].full] = TypeMatch(gs[a].full, None, 'unmapped', 0.0, round(s, 4), round(margin, 4),
                                                      why, [{'live': c, 'score': round(v, 4)} for v, c in cands])
        if final:
            for a in range(n):
                if a not in picked_g and gs[a].full not in self.matches:
                    cands = sorted(((S[a][k], ls[k].full) for k in range(m)), reverse=True)[:3]
                    self.unmapped[gs[a].full] = TypeMatch(gs[a].full, None, 'unmapped', 0.0,
                                                          round(cands[0][0], 4) if cands else 0, 0,
                                                          'no order-consistent partner in its anchor gap',
                                                          [{'live': c, 'score': round(v, 4)} for v, c in cands])
        return added

    def run(self, max_rounds: int = 8) -> dict[str, TypeMatch]:
        self.rounds.append({'stable_seeds': self.seed_stable()})
        for r in range(max_rounds):
            norms = self._norms()
            descs = ({t.full: self._desc('g', t, norms[0]) for t in self.G.types.values()},
                     {t.full: self._desc('l', t, norms[1]) for t in self.L.types.values()})
            ex = self.pass_exact(norms, descs)
            norms = self._norms()
            descs = ({t.full: self._desc('g', t, norms[0]) for t in self.G.types.values()},
                     {t.full: self._desc('l', t, norms[1]) for t in self.L.types.values()})
            shapes = ({t.full: Counter(core_shape(c) for c in t.cores) for t in self.G.types.values()},
                      {t.full: Counter(core_shape(c) for c in t.cores) for t in self.L.types.values()})
            al = self.pass_align(norms, descs, shapes, final=False)
            self.rounds.append({'round': r, 'exact': ex, 'aligned': al, 'total': len(self.matches)})
            if ex == 0 and al == 0:
                break
        # final pass records the reasons for everything still unmatched
        norms = self._norms()
        descs = ({t.full: self._desc('g', t, norms[0]) for t in self.G.types.values()},
                 {t.full: self._desc('l', t, norms[1]) for t in self.L.types.values()})
        shapes = ({t.full: Counter(core_shape(c) for c in t.cores) for t in self.G.types.values()},
                  {t.full: Counter(core_shape(c) for c in t.cores) for t in self.L.types.values()})
        self.pass_align(norms, descs, shapes, final=True)
        for t in self.G.types.values():
            if t.full not in self.matches and t.full not in self.unmapped:
                self.unmapped[t.full] = TypeMatch(t.full, None, 'unmapped', 0.0, 0, 0, 'no candidate')
        return self.matches

    def normalizers(self):
        return self._norms()


# ---------------------------------------------------------------------- members
def obf_rank(name: str) -> int:
    """Order of an obfuscator-assigned name: shorter names first, then base-27 value (a=1 .. z=26)."""
    v = 0
    for ch in name:
        v = v * 27 + (ord(ch) - 96)
    return len(name) * 27 ** 4 + v


def order_key(c: Core) -> tuple[str, int]:
    """Order domain and position of a member inside its owner.

    Domain 'A': fields/methods whose native name is obfuscator-assigned, ordered by that name. The obfuscator
    hands names out in a stable order: 11,683 of 11,686 (99.97%) unique-signature member pairs between Golden
    Era and live keep it, while declaration order keeps only 88.6%. Domain 'B': everything else (real names,
    properties, enum literals), ordered by declaration."""
    n = c.native_name or ''
    m = BACKING.match(n)
    if m:
        n = m.group(1)
    if c.cat in ('field', 'method') and n and n.isalpha() and n.islower() and native_is_obfuscated(n):
        return ('A', obf_rank(n))
    return ('B', c.ord)


def match_members(gcores: list[Core], lcores: list[Core], ng: Normalizer, nl: Normalizer,
                  hide_golden_names: bool = False, hide_live_names: bool = False, body=None) -> dict[tuple, MemberMatch]:
    """Match the core members of one matched owner pair. Returns golden core key -> MemberMatch.

    Per category: (1) real native names; (2) signature descriptors unique within the owner on both sides;
    (3) a max-weight monotone chain over those anchors, computed separately in each order domain (see
    `order_key`); (4) inside each gap of a chain, members sharing one descriptor pair in order only when both
    sides hold the same count. Anything else is UNMAPPED with a reason - nothing is forced.

    `body` (optional, native_body._BoundPair for this owner pair) adds native-code evidence to step 4:
      * same-descriptor methods with unequal counts in a gap pair only as a mutual best body match above the
        calibrated floors (method 'gap_native_body');
      * equal-count order pairs are unchanged; the body assignment is only compared with them
        (`body.stats`, the order cross-check);
      * signature-changed candidates are never paired (the call sites' arguments would not fit); a body match
        is only named in the reason, for manual follow-up."""
    out: dict[tuple, MemberMatch] = {}
    for cat in ('field', 'method', 'prop', 'const'):
        G = [c for c in gcores if c.cat == cat]
        L = [c for c in lcores if c.cat == cat]
        if not G:
            continue
        gd = {c.key: core_descriptor(c, ng, hide_golden_names) for c in G}
        ld = {c.key: core_descriptor(c, nl, hide_live_names) for c in L}
        # descriptor without the name, for signature-level comparisons
        gs = {k: v[:3] for k, v in gd.items()}
        ls = {k: v[:3] for k, v in ld.items()}
        # the obfuscated-name order is an observable in production and in validation alike: only real names are
        # identities, and those are never in domain A
        gk = {c.key: order_key(c) for c in G}
        lk = {c.key: order_key(c) for c in L}
        used_l: set = set()
        anchors: list[tuple[Core, Core, str, float]] = []

        # 1. real names (per name; overloads resolved by signature)
        byname_g, byname_l = defaultdict(list), defaultdict(list)
        for c in G:
            if gd[c.key][3] != '#':
                byname_g[gd[c.key][3]].append(c)
        for c in L:
            if ld[c.key][3] != '#':
                byname_l[ld[c.key][3]].append(c)
        for name, gl in byname_g.items():
            ll = byname_l.get(name, [])
            if not ll:
                continue
            if len(gl) == 1 and len(ll) == 1:
                same = gs[gl[0].key] == ls[ll[0].key]
                anchors.append((gl[0], ll[0], 'real_name' if same else 'real_name_sig_changed', 0.99 if same else 0.9))
                used_l.add(ll[0].key)
                continue
            rest_l = list(ll)
            for c in gl:
                hits = [x for x in rest_l if ls[x.key] == gs[c.key]]
                if len(hits) == 1:
                    anchors.append((c, hits[0], 'real_name_overload_sig', 0.97))
                    rest_l.remove(hits[0])
                    used_l.add(hits[0].key)
        used_g = {a.key for a, _, _, _ in anchors}

        # 2. descriptors unique within the owner on both sides
        cg = Counter(gs[c.key] for c in G if c.key not in used_g)
        cl = Counter(ls[c.key] for c in L if c.key not in used_l)
        lby = {ls[c.key]: c for c in L if c.key not in used_l and cl[ls[c.key]] == 1}
        for c in G:
            d = gs[c.key]
            if c.key in used_g or cg[d] != 1 or cl.get(d) != 1:
                continue
            opaque = 'O' in TOKEN.findall(d[2])
            anchors.append((c, lby[d], 'unique_signature_opaque_types' if opaque else 'unique_signature',
                            0.9 if opaque else 0.95))
            used_g.add(c.key)
            used_l.add(lby[d].key)

        # 3. monotone chain per order domain; anchors whose two sides sit in different domains bound no gap
        chained: dict[str, list] = {'A': [], 'B': []}
        on_chain: set = set()
        for dom in ('A', 'B'):
            idx = [i for i, (a, b, _, _) in enumerate(anchors) if gk[a.key][0] == dom and lk[b.key][0] == dom]
            chain = weighted_lis([(gk[anchors[i][0].key][1], lk[anchors[i][1].key][1], anchors[i][3], i) for i in idx])
            on_chain |= chain
            chained[dom] = sorted((gk[anchors[i][0].key][1], lk[anchors[i][1].key][1]) for i in chain)
        for i, (a, b, how, conf) in enumerate(anchors):
            cross = gk[a.key][0] != lk[b.key][0]
            if i in on_chain or (cross and how.startswith('real_name')):
                out[a.key] = MemberMatch(a, b, how, conf)
            elif how.startswith('real_name'):
                out[a.key] = MemberMatch(a, b, how + '_reordered', min(conf, 0.9))
            else:
                out[a.key] = MemberMatch(a, b, how + '_off_chain', 0.7, 'unique signature but out of member order')

        # 4. gaps: same-descriptor members pair by order when both sides hold the same count
        for dom in ('A', 'B'):
            method = 'gap_name_order' if dom == 'A' else 'gap_ordinal'
            bounds = [(-1, -1)] + chained[dom] + [(10 ** 12, 10 ** 12)]
            for (g0, l0), (g1, l1) in zip(bounds, bounds[1:]):
                gg = sorted((c for c in G if gk[c.key][0] == dom and g0 < gk[c.key][1] < g1 and c.key not in out),
                            key=lambda c: gk[c.key][1])
                lg = sorted((c for c in L if lk[c.key][0] == dom and l0 < lk[c.key][1] < l1 and c.key not in used_l),
                            key=lambda c: lk[c.key][1])
                if not gg:
                    continue
                groups_g, groups_l = defaultdict(list), defaultdict(list)
                for c in gg:
                    groups_g[gs[c.key]].append(c)
                for c in lg:
                    groups_l[ls[c.key]].append(c)
                left_g = []
                for d, gl in groups_g.items():
                    ll = groups_l.get(d, [])
                    if len(gl) == len(ll):
                        conf = 0.9 if len(gl) == 1 else 0.85
                        if body is not None and cat == 'method' and len(gl) > 1:
                            body.cross_check(gl, ll)
                        for a, b in zip(gl, ll):
                            out[a.key] = MemberMatch(a, b, method, conf)
                            used_l.add(b.key)
                    elif ll:
                        why = f'ambiguous: {len(gl)} golden vs {len(ll)} live members with this signature in the order gap'
                        res = body.assign(gl, ll) if body is not None and cat == 'method' else {}
                        for a in gl:
                            r = res.get(a.key)
                            if r is not None:
                                out[a.key] = MemberMatch(a, r[0], 'gap_native_body', body.confidence,
                                                         f'{why}; native body score {r[1]:.3f} margin {r[2]:.3f}')
                                used_l.add(r[0].key)
                            else:
                                note = '; native body: no mutual best above the floors' if body is not None and cat == 'method' else ''
                                out[a.key] = MemberMatch(a, None, 'unmapped', 0.0, why + note,
                                                         [primary_name(x) for x in ll[:4]])
                    else:
                        left_g.extend(gl)
                left_l = [c for c in lg if c.key not in used_l]
                hint = {}
                if body is not None and cat == 'method':
                    for shp in {core_shape(a) for a in left_g}:
                        hint.update(body.assign([a for a in left_g if core_shape(a) == shp],
                                                [b for b in left_l if core_shape(b) == shp]))
                for a in left_g:
                    cands = [b for b in left_l if core_shape(b) == core_shape(a)]
                    if not cands:
                        why = 'no same-signature member in its order gap (removed, or signature changed)'
                    elif len(left_g) == 1 and len(cands) == 1:
                        why = 'signature changed; sole same-shape candidate in its order gap (below acceptance floor)'
                    else:
                        why = f'signature changed; {len(cands)} same-shape candidates in its order gap'
                    if a.key in hint:
                        b, s, m = hint[a.key]
                        why += f'; native body points to {primary_name(b)} (score {s:.3f} margin {m:.3f}), not applied: signature changed'
                    out[a.key] = MemberMatch(a, None, 'unmapped', 0.0, why, [primary_name(b) for b in cands[:4]])
        for c in G:
            if c.key not in out:
                out[c.key] = MemberMatch(c, None, 'unmapped', 0.0, 'no candidate')
    return out


ROLE_ORDER = ('prop', 'method', 'const', 'get', 'set', 'ptr', 'accessor')


def primary_name(c: Core) -> str:
    for r in ROLE_ORDER:
        if r in c.rows:
            return c.rows[r].name
    return c.native_name
