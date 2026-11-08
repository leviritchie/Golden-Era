"""Honest matcher validation on real-name ground truth.

Namespaced / real-named ("stable") types keep their names across the update, so the pair (golden stable type,
live type with the same native path) is ground truth. The harness hides a random fraction of those names on
both sides - no stable-name seeding, member names hidden, references to them in signatures opaque exactly like
obfuscated tokens - runs the full matcher, and scores only the hidden golden types:

  precision = correct / mapped          (mapped = matcher produced a live type)
  recall    = correct / answerable      (answerable = hidden golden types whose name exists live)
  a hidden golden type whose name is gone live is answered correctly only by UNMAPPED.

Members: for every hidden type pair the matcher got right, the owner's cores with real (non-obfuscated) native
names are ground truth; their names are hidden from the member matcher, which is then scored the same way.
"""
from __future__ import annotations

import random
from collections import Counter, defaultdict

from . import match
from .model import Index


def bucket(conf: float) -> str:
    for lo in (0.95, 0.9, 0.8, 0.7, 0.6):
        if conf >= lo:
            return f'>={lo:.2f}'
    return '<0.60'


def run_trial(G: Index, L: Index, fraction: float, seed: int) -> dict:
    rng = random.Random(seed)
    lkey = {}
    for t in L.types.values():
        if L.is_stable(t):
            lkey.setdefault(L.stable_key(t), []).append(t.full)
    stable_g = sorted(t.full for t in G.types.values() if G.is_stable(t))
    hidden_g = set(rng.sample(stable_g, int(round(len(stable_g) * fraction))))
    # hide whole subtrees: a visible nested type would otherwise carry its hidden parent's name
    hidden_g |= {t for t in stable_g if any(t.startswith(h + '/') for h in hidden_g)}
    truth, hidden_l = {}, set()
    for g in hidden_g:
        ls = lkey.get(G.stable_key(G.types[g]), [])
        truth[g] = ls[0] if len(ls) == 1 else None
        hidden_l.update(ls)
    # live stable types with no golden counterpart are hidden at the same rate (they are candidates too)
    gkeys = {G.stable_key(G.types[g]) for g in stable_g}
    for k, ls in lkey.items():
        if k not in gkeys and rng.random() < fraction:
            hidden_l.update(ls)

    tm = match.TypeMatcher(G, L, hidden_golden=hidden_g, hidden_live=hidden_l)
    tm.run()

    by_method = defaultdict(Counter)
    by_conf = defaultdict(Counter)
    tot = Counter()
    for g in hidden_g:
        m = tm.matches.get(g)
        t = truth[g]
        tot['hidden'] += 1
        if t is not None:
            tot['answerable'] += 1
        if m is None:
            tot['unmapped'] += 1
            if t is None:
                tot['correct_unmapped'] += 1
            continue
        ok = m.live == t
        tot['mapped'] += 1
        tot['correct'] += ok
        by_method[m.method]['mapped'] += 1
        by_method[m.method]['correct'] += ok
        by_conf[bucket(m.confidence)]['mapped'] += 1
        by_conf[bucket(m.confidence)]['correct'] += ok

    # members of correctly matched hidden pairs
    ng, nl = tm.normalizers()
    mem = Counter()
    mem_by = defaultdict(Counter)
    errors = []
    for g in hidden_g:
        m = tm.matches.get(g)
        if m is None or m.live != truth[g]:
            continue
        gt, lt = G.types[g], L.types[m.live]
        lname = defaultdict(list)
        for c in lt.cores:
            if c.real_name:
                lname[(c.cat, c.real_name)].append(c)
        res = match.match_members(gt.cores, lt.cores, ng, nl, hide_golden_names=True, hide_live_names=True)
        for c in gt.cores:
            # enum literals are never obfuscated (no enum in either build carries an ObfuscatedName), so
            # production matches them by name; hiding their names would score a path production never takes
            if not c.real_name or c.cat == 'const':
                continue
            cand = lname.get((c.cat, c.real_name), [])
            # overloads: the truth is the same-name core with the identical raw signature, when unique
            if len(cand) > 1:
                cand = [x for x in cand if x.sig == c.sig]
            want = cand[0] if len(cand) == 1 else None
            if want is None and lname.get((c.cat, c.real_name)):
                continue  # truth itself ambiguous (changed overload set); not scored
            r = res.get(c.key)
            mem['scored'] += 1
            if want is not None:
                mem['answerable'] += 1
            if r is None or r.live is None:
                mem['unmapped'] += 1
                mem['correct_unmapped'] += want is None
                continue
            ok = want is not None and r.live.key == want.key
            mem['mapped'] += 1
            mem['correct'] += ok
            mem_by[r.method]['mapped'] += 1
            mem_by[r.method]['correct'] += ok
            mem_by['cat:' + c.cat]['mapped'] += 1
            mem_by['cat:' + c.cat]['correct'] += ok
            if not ok and len(errors) < 400:
                errors.append((g, c.cat, c.real_name, r.live.native_name, r.method))

    def pr(c):
        p = c['correct'] / c['mapped'] if c['mapped'] else None
        r = c['correct'] / c['answerable'] if c.get('answerable') else None
        return {k: v for k, v in c.items()} | {'precision': round(p, 4) if p is not None else None,
                                               'recall': round(r, 4) if r is not None else None}

    return {
        'fraction_hidden': fraction, 'seed': seed,
        'types': pr(tot),
        'types_by_method': {k: pr(v) for k, v in sorted(by_method.items())},
        'types_by_confidence': {k: pr(v) for k, v in sorted(by_conf.items(), reverse=True)},
        'members': pr(mem),
        'members_by_method': {k: pr(v) for k, v in sorted(mem_by.items())},
        'member_error_samples': errors,
    }
