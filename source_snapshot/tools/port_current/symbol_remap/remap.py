"""Emit game_symbols_remap_<buildid>.json (schema game_symbols_remap.v1).

Every hint literal harvested from GameSymbols.cs and the resolver layer is bound to what it names on Golden
Era (types by interop short/full name, ObfuscatedName or native name; members by any interop spelling of a
core member or its native name), carried across by the type and member matchers, and written back in the
same spelling on the live build. Anything the matchers could not carry with confidence is UNMAPPED with a
reason. Nothing is forced.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from . import match
from .literals import harvest  # noqa: F401  (re-exported for the CLI)
from .model import Core, Index, TypeInfo

SCHEMA = 'game_symbols_remap.v1'
RESOLVER_FILES = ['GameSymbols.cs', 'GameMember.cs', 'DeobfInteropCompat.cs']
MAX_BINDINGS = 25


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest().upper()


class Remapper:
    def __init__(self, G: Index, L: Index, tm: match.TypeMatcher, body=None):
        self.G, self.L, self.tm = G, L, tm
        self.body = body            # native_body.BodyEvidence or None
        self.ng, self.nl = tm.normalizers()
        self._members: dict[str, dict] = {}
        self.type_forms: dict[str, list] = defaultdict(list)
        self.member_forms: dict[str, list] = defaultdict(list)
        for t in G.types.values():
            if 'PrivateImplementationDetails' in t.full or 'PrivateImplementationDetails' in t.native_path:
                continue  # compiler data blobs: thousands of short native field names that only collide with hints
            forms = {'short': t.name, 'full': t.full, 'runtime': t.runtime_full, 'obf': t.obf, 'native': t.native_name,
                     'native_full': t.native_path if t.native_ns else ''}
            seen = set()
            for form, v in forms.items():
                if v and v not in seen:
                    seen.add(v)
                    self.type_forms[v].append((t, form))
            for c in t.cores:
                seen = set()
                for role, r in c.rows.items():
                    if r.name not in seen:
                        seen.add(r.name)
                        self.member_forms[r.name].append((t, c, 'role:' + role))
                if c.cat in ('field', 'method') and c.native_name and c.native_name not in seen:
                    self.member_forms[c.native_name].append((t, c, 'native'))

    # ---------------------------------------------------------------- types
    def type_status(self, g: str) -> dict:
        m = self.tm.matches.get(g)
        if m is None:
            u = self.tm.unmapped.get(g)
            return {'status': 'UNMAPPED', 'live': None, 'confidence': 0.0,
                    'reason': 'type: ' + (u.reason if u else 'no candidate'),
                    'candidates': (u.candidates if u else [])}
        return {'status': 'MAPPED', 'live': m.live, 'confidence': m.confidence, 'method': m.method}

    def map_type_binding(self, t: TypeInfo, form: str, literal: str) -> dict:
        ts = self.type_status(t.full)
        out = {'goldenOwner': t.full, 'form': 'type:' + form}
        if ts['status'] != 'MAPPED':
            return out | {'status': 'UNMAPPED', 'live': None, 'confidence': 0.0, 'reason': ts['reason'],
                          'candidates': ts.get('candidates', [])}
        lt = self.L.types[ts['live']]
        live = {'short': lt.name, 'full': lt.full, 'runtime': lt.runtime_full, 'obf': lt.obf or '',
                'native': lt.native_name, 'native_full': lt.native_path}[form]
        note = ''
        if form == 'obf' and not lt.obf:
            live = lt.name
            note = 'live type carries no ObfuscatedName attribute; interop name given'
        res = out | {'status': 'UNCHANGED' if live == literal else 'MAPPED', 'live': live,
                     'confidence': ts['confidence'], 'liveOwner': lt.full, 'liveRuntimeFullName': lt.runtime_full,
                     'method': ts['method']}
        if note:
            res['note'] = note
        return res

    # ---------------------------------------------------------------- members
    def members_of(self, g: str) -> dict | None:
        if g not in self._members:
            m = self.tm.matches.get(g)
            if m is None:
                self._members[g] = None
            else:
                gt, lt = self.G.types[g], self.L.types[m.live]
                bound = self.body.pair(gt.asm, lt.asm, g) if self.body is not None else None
                self._members[g] = match.match_members(gt.cores, lt.cores, self.ng, self.nl, body=bound)
        return self._members[g]

    def map_member_binding(self, t: TypeInfo, c: Core, form: str, literal: str) -> dict:
        out = {'goldenOwner': t.full, 'goldenCoreKey': list(c.key), 'form': form, 'memberCategory': c.cat}
        ts = self.type_status(t.full)
        if ts['status'] != 'MAPPED':
            return out | {'status': 'UNMAPPED', 'live': None, 'confidence': 0.0, 'reason': 'owner ' + ts['reason']}
        mm = self.members_of(t.full).get(c.key)
        out['liveOwner'] = ts['live']
        out['liveOwnerRuntimeFullName'] = self.L.types[ts['live']].runtime_full
        if mm is None or mm.live is None:
            return out | {'status': 'UNMAPPED', 'live': None, 'confidence': 0.0,
                          'reason': 'member: ' + (mm.reason if mm else 'not matched'),
                          'candidates': (mm.candidates if mm else [])}
        conf = round(min(ts['confidence'], mm.confidence), 4)
        if form == 'native':
            live = mm.live.native_name
        else:
            r = mm.live.rows.get(form[5:])
            live = r.name if r else None
        if not live:
            return out | {'status': 'UNMAPPED', 'live': None, 'confidence': 0.0,
                          'reason': f'matched live member has no {form} spelling'}
        if conf < match.MEMBER_MIN_CONF:
            return out | {'status': 'UNMAPPED', 'live': None, 'confidence': conf,
                          'reason': f'confidence {conf} below floor {match.MEMBER_MIN_CONF}',
                          'candidates': [live]}
        return out | {'status': 'UNCHANGED' if live == literal else 'MAPPED', 'live': live, 'confidence': conf,
                      'method': mm.method, 'ownerConfidence': ts['confidence']}

    def bindings(self, literal: str) -> list[dict]:
        tf = self.type_forms.get(literal, [])
        # Exact spellings first: the resolvers look types up by full name (Assembly.GetType) or by
        # ObfuscatedName; a short-name/native-name hit is only used when no exact spelling binds.
        exact = [(t, f) for t, f in tf if f in ('full', 'runtime', 'obf', 'native_full') or
                 (f == 'short' and '.' not in t.full and '/' not in t.full)]
        tf = exact or tf
        out = [self.map_type_binding(t, f, literal) | {'kind': 'type'} for t, f in tf]
        out += [self.map_member_binding(t, c, f, literal) | {'kind': 'member'}
                for t, c, f in self.member_forms.get(literal, [])]
        return out

    # ---------------------------------------------------------------- aggregation
    @staticmethod
    def aggregate(literal: str, bs: list[dict]) -> dict:
        if not bs:
            return {'status': 'NOT_IN_GOLDEN', 'live': None, 'confidence': 0.0,
                    'reason': 'the literal names no type or member in the Golden Era interop index'}
        ok = [b for b in bs if b['status'] in ('MAPPED', 'UNCHANGED')]
        lives = {b['live'] for b in ok}
        if len(ok) == len(bs) and len(lives) == 1:
            live = lives.pop()
            return {'status': 'UNCHANGED' if live == literal else 'MAPPED', 'live': live,
                    'confidence': min(b['confidence'] for b in ok)}
        if len(lives) > 1:
            return {'status': 'UNMAPPED', 'live': None, 'confidence': 0.0,
                    'reason': f'owner-dependent: {len(bs)} Golden Era bindings map to {len(lives)} different live names; use groups'}
        if ok:
            return {'status': 'UNMAPPED', 'live': None, 'confidence': 0.0,
                    'reason': f'partially mapped: {len(ok)} of {len(bs)} Golden Era bindings map; use groups'}
        reasons = Counter(b['reason'] for b in bs)
        return {'status': 'UNMAPPED', 'live': None, 'confidence': 0.0, 'reason': reasons.most_common(1)[0][0]}

    def base_chain(self, g: str) -> list[str]:
        out, cur = [], self.G.types.get(g)
        while cur is not None:
            out.append(cur.full)
            cur = self.G.types.get(cur.base)
        return out


TYPE_ROLE = re.compile(r'Type(Hint|Name)?s?$|TypeHints?|Types$')
MEMBER_ROLE = re.compile(r'(Members?|Fields?|Methods?|Getters?|Setters?|Properties|Property|Arrays?)$')


def group_role(g, type_lits, mem_lits) -> str:
    """'type' | 'member' | 'mixed' | 'none' for one hint group: the declaration kind and name decide first,
    then which kind of Golden Era binding its literals have."""
    name = g.symbol.split('@')[0].split('.')[-1]
    if g.decl_type in ('MethodSymbol', 'FieldSymbol') or MEMBER_ROLE.search(name):
        return 'member' if mem_lits or not type_lits else 'mixed'
    if TYPE_ROLE.search(name):
        return 'type' if type_lits or not mem_lits else 'mixed'
    if not type_lits and not mem_lits:
        return 'none'
    only_t = sum(1 for h in type_lits if h not in mem_lits)
    only_m = sum(1 for h in mem_lits if h not in type_lits)
    if only_t > only_m:
        return 'type'
    if only_m > only_t:
        return 'member'
    return 'mixed'


def class_path(symbol: str) -> str:
    head = symbol.split('@')[0]
    return head.rsplit('.', 1)[0] if '.' in head else ''


def build(G: Index, L: Index, groups, sources: dict, meta: dict, body=None,
          native_meta: dict | None = None, cross_check_sample: int = 3000) -> tuple[dict, match.TypeMatcher]:
    tm = match.TypeMatcher(G, L)
    tm.run()
    rm = Remapper(G, L, tm, body)

    lit_bindings: dict[str, list] = {}
    for g in groups:
        for h in g.hints:
            if h not in lit_bindings:
                lit_bindings[h] = rm.bindings(h)

    # context: golden types named by type-kind literals, per class path
    ctx: dict[str, set] = defaultdict(set)
    for g in groups:
        for h in g.hints:
            for b in lit_bindings[h]:
                if b['kind'] == 'type':
                    ctx[class_path(g.symbol)].add(b['goldenOwner'])

    out_groups = []
    gstat = Counter()
    for g in groups:
        hints = g.hints
        if not hints:
            continue
        entries = []
        type_lits = [h for h in hints if any(b['kind'] == 'type' for b in lit_bindings[h])]
        mem_lits = [h for h in hints if any(b['kind'] == 'member' for b in lit_bindings[h])]
        kind = group_role(g, type_lits, mem_lits)
        if kind == 'type':
            mem_lits = []
        elif kind == 'member':
            type_lits = []
        owner_info = {} if kind == 'type' else {'ownerHint': None, 'ownerBasis': 'none', 'ownerStatus': 'UNMAPPED',
                                                'ownerConfidence': 0.0}
        owners: list[str] = []
        if mem_lits:
            hits = Counter()
            for h in mem_lits:
                for o in {b['goldenOwner'] for b in lit_bindings[h] if b['kind'] == 'member'}:
                    hits[o] += 1
            cp = class_path(g.symbol)
            context = set()
            while True:
                context |= ctx.get(cp, set())
                if context or not cp:
                    break
                cp = cp.rsplit('.', 1)[0] if '.' in cp else ''
            context_exp = {x for c in context for x in rm.base_chain(c)}
            inter = [o for o in hits if o in context_exp]
            basis = ''
            if inter:
                top = max(hits[o] for o in inter)
                owners = [o for o in inter if hits[o] == top]
                basis = 'class_type_hint'
            elif len(hits) == 1:
                owners = list(hits)
                basis = 'only_owner'
            else:
                ranked = hits.most_common(2)
                if ranked[0][1] >= 2 and ranked[0][1] > ranked[1][1]:
                    owners = [ranked[0][0]]
                    basis = 'most_hits'
            if len(owners) == 1:
                ts = rm.type_status(owners[0])
                lt = L.types[ts['live']] if ts['live'] else None
                owner_info = {'ownerHint': owners[0], 'ownerBasis': basis,
                              'ownerStatus': ts['status'], 'ownerConfidence': ts['confidence'],
                              'ownerLive': lt.full if lt else None,
                              'ownerLiveRuntimeFullName': lt.runtime_full if lt else None}
                if ts['status'] != 'MAPPED':
                    owner_info['ownerReason'] = ts['reason']
            else:
                owner_info = {'ownerHint': None, 'ownerBasis': 'ambiguous' if hits else 'none',
                              'ownerStatus': 'UNMAPPED', 'ownerConfidence': 0.0,
                              'ownerCandidates': sorted(hits, key=lambda o: (-hits[o], o))[:6],
                              'ownerCandidateCount': len(hits)}
        for h in hints:
            bs = lit_bindings[h]
            e = {'golden': h}
            tb = [b for b in bs if b['kind'] == 'type']
            mb = [b for b in bs if b['kind'] == 'member']
            if kind == 'type' and h not in type_lits:
                e |= {'kind': 'type', 'status': 'NOT_IN_GOLDEN', 'live': None, 'confidence': 0.0,
                      'reason': 'type hint names no Golden Era type'}
            elif kind == 'member' and h not in mem_lits:
                e |= {'kind': 'member', 'status': 'NOT_IN_GOLDEN', 'live': None, 'confidence': 0.0,
                      'reason': 'member hint names no Golden Era member'}
            elif h in type_lits and (kind in ('type', 'mixed') or not mb):
                agg = rm.aggregate(h, tb)
                e |= {'kind': 'type'} | agg
                if agg['status'] in ('MAPPED', 'UNCHANGED'):
                    e['liveRuntimeFullName'] = sorted({b['liveRuntimeFullName'] for b in tb})[0] \
                        if len({b['liveRuntimeFullName'] for b in tb}) == 1 else None
                    e['goldenOwner'] = tb[0]['goldenOwner'] if len(tb) == 1 else None
                else:
                    e['candidates'] = [c for b in tb for c in b.get('candidates', [])][:3]
            elif mb:
                sel = [b for b in mb if owners and (b['goldenOwner'] in owners or
                                                    b['goldenOwner'] in {x for o in owners for x in rm.base_chain(o)})]
                mb_owners = {b['goldenOwner'] for b in mb}
                if not owners and len(mb_owners) == 1:
                    # the group names no owner, but the literal exists on exactly one Golden Era type
                    sel = mb
                    e['ownerBasis'] = 'unique_binding'
                agree = rm.aggregate(h, mb) if not owners and not sel else None
                if agree is not None and agree['status'] in ('MAPPED', 'UNCHANGED'):
                    # the owner is undetermined, but every Golden Era type carrying the literal maps it to the
                    # same live name: the substitution does not depend on which owner the resolver ends up with
                    e |= {'kind': 'member'} | agree
                    e['ownerBasis'] = 'agreeing_owners'
                    e['ownerCandidates'] = [{'golden': b['goldenOwner'], 'live': b.get('liveOwner'),
                                             'status': rm.type_status(b['goldenOwner'])['status'],
                                             'confidence': rm.type_status(b['goldenOwner'])['confidence']}
                                            for b in mb][:MAX_BINDINGS]
                    e['ownerStatus'] = 'MAPPED' if all(c['status'] == 'MAPPED' for c in e['ownerCandidates']) \
                        else 'UNMAPPED'
                    e['ownerConfidence'] = min(c['confidence'] for c in e['ownerCandidates'])
                elif not owners and not sel:
                    e |= {'kind': 'member', 'status': 'UNMAPPED', 'live': None, 'confidence': 0.0,
                          'reason': f"owner ambiguous: literal binds on {len(mb_owners)} Golden Era types that map it "
                                    f"differently ({agree['reason']}) and the group names no single owner type"}
                elif not sel:
                    e |= {'kind': 'member', 'status': 'NOT_IN_GOLDEN', 'live': None, 'confidence': 0.0,
                          'reason': 'not a member of the group owner (or its bases) on Golden Era'}
                else:
                    e |= {'kind': 'member'} | rm.aggregate(h, sel)
                    e['goldenOwner'] = sel[0]['goldenOwner']
                    ts = rm.type_status(sel[0]['goldenOwner'])
                    e['ownerStatus'], e['ownerConfidence'] = ts['status'], ts['confidence']
                    if sel[0].get('liveOwner'):
                        e['liveOwner'] = sel[0]['liveOwner']
                    if e['status'] == 'UNMAPPED':
                        e['candidates'] = [c for b in sel for c in b.get('candidates', [])][:4]
                        if len(sel) == 1:
                            e['reason'] = sel[0].get('reason', e.get('reason'))
            else:
                e |= {'kind': 'unresolved', 'status': 'NOT_IN_GOLDEN', 'live': None, 'confidence': 0.0,
                      'reason': 'the literal names no type or member in the Golden Era interop index'}
            entries.append(e)
        if mem_lits and owner_info.get('ownerHint') is None:
            uo = {e.get('goldenOwner') for e in entries if e.get('ownerBasis') == 'unique_binding'}
            if len(uo) == 1:
                o = uo.pop()
                ts = rm.type_status(o)
                lt = L.types[ts['live']] if ts['live'] else None
                owner_info = {'ownerHint': o, 'ownerBasis': 'unique_binding', 'ownerStatus': ts['status'],
                              'ownerConfidence': ts['confidence'], 'ownerLive': lt.full if lt else None,
                              'ownerLiveRuntimeFullName': lt.runtime_full if lt else None}
        live = []
        for e in entries:
            if e['status'] in ('MAPPED', 'UNCHANGED') and e['live'] not in live:
                live.append(e['live'])
        unm = [{'golden': e['golden'], 'reason': e.get('reason', '')} for e in entries if e['status'] == 'UNMAPPED']
        resolvable = [e for e in entries if e['status'] != 'NOT_IN_GOLDEN']
        state = ('no_golden_binding' if not resolvable else
                 'all_mapped' if all(e['status'] in ('MAPPED', 'UNCHANGED') for e in resolvable) else
                 'partially_mapped' if live else 'unmapped')
        gstat[state] += 1
        out_groups.append({'file': g.file, 'line': g.line, 'symbol': g.symbol, 'kind': kind,
                           'resolution': state, 'literals': hints} | owner_info |
                          {'live': live, 'unmapped': unm, 'entries': entries})

    literals_out = {}
    sites = defaultdict(list)
    for g in groups:
        for h in g.hints:
            sites[h].append({'file': g.file, 'line': g.line, 'symbol': g.symbol})
    lstat = Counter()
    kstat = Counter()
    used_roles = defaultdict(set)
    for og in out_groups:
        for e in og['entries']:
            used_roles[e['golden']].add(e['kind'])
    for h, bs in sorted(lit_bindings.items()):
        roles = used_roles.get(h, set())
        if roles == {'type'}:
            bs = [b for b in bs if b['kind'] == 'type']
        elif roles == {'member'}:
            bs = [b for b in bs if b['kind'] == 'member']
        agg = rm.aggregate(h, bs)
        kinds = sorted({('type' if b['kind'] == 'type' else b['form'].replace('role:', '') if b['form'] != 'native'
                         else 'native_' + b['memberCategory']) for b in bs}) or ['unresolved']
        rec = {'kinds': kinds} | agg | {'bindingCount': len(bs), 'bindings': bs[:MAX_BINDINGS], 'sites': sites[h]}
        if agg['status'] == 'UNMAPPED':
            cands = [c for b in bs for c in b.get('candidates', [])]
            if cands:
                rec['candidates'] = cands[:5]
        literals_out[h] = rec
        lstat[agg['status']] += 1
        for k in kinds:
            kstat[(k, agg['status'])] += 1

    tstat = Counter(m.method for m in tm.matches.values())
    summary = {
        'literals': dict(lstat),
        'literalsByKind': {f'{k}:{s}': n for (k, s), n in sorted(kstat.items())},
        'groups': dict(gstat),
        'groupsByKind': dict(Counter(g['kind'] for g in out_groups)),
        'goldenTypes': len(G.types), 'liveTypes': len(L.types),
        'typeMatches': dict(tstat), 'typesUnmapped': len(tm.unmapped),
        'typeUnmappedReasons': dict(Counter(u.reason for u in tm.unmapped.values())),
        'matcherRounds': tm.rounds,
    }
    if body is not None:
        native_meta = dict(native_meta or {})
        native_meta['orderCrossCheck'] = order_cross_check(rm, body, sample=cross_check_sample)
        meta = meta | {'nativeBody': native_meta}
    doc = {'schema': SCHEMA} | meta | {'sources': sources, 'summary': summary,
                                       'literals': literals_out, 'groups': out_groups}
    return doc, tm


def order_cross_check(rm: Remapper, body, sample: int = 3000, seed: int = 11) -> dict:
    """Independent precision estimate for native-body picks on the obfuscated population: in equal-count gaps
    the matcher pairs by obfuscator order (99.97% stable across this update); compare what the body evidence
    alone picks there. Runs over the owners the plugin binds plus a fixed-seed sample of matched owners."""
    import random
    keys = sorted(g for g in rm.tm.matches if not rm.G.is_stable(rm.G.types[g]))
    random.Random(seed).shuffle(keys)
    for g in keys[:sample]:
        rm.members_of(g)
    st = body.stats
    decided = st['agree'] + st['disagree']
    return {'sampleOwners': min(sample, len(keys)), 'seed': seed, 'agree': st['agree'], 'disagree': st['disagree'],
            'abstain': st['abstain'], 'agreement': round(st['agree'] / decided, 5) if decided else None,
            'disagreements': body.disagreements}


def type_map(tm: match.TypeMatcher, G: Index, L: Index) -> dict:
    out = {}
    for g, t in G.types.items():
        m = tm.matches.get(g)
        if m:
            out[g] = {'live': m.live, 'liveRuntimeFullName': L.types[m.live].runtime_full, 'method': m.method,
                      'confidence': m.confidence, 'score': m.score, 'margin': m.margin,
                      'goldenNative': t.native_path, 'liveNative': L.types[m.live].native_path}
        else:
            u = tm.unmapped.get(g)
            out[g] = {'live': None, 'status': 'UNMAPPED', 'reason': u.reason if u else 'no candidate',
                      'candidates': u.candidates if u else [], 'goldenNative': t.native_path}
    return out
