"""Unit tests for the symbol remap matcher on small synthetic port indexes.

Run: python -m unittest tools/port_current/symbol_remap/test_symbol_remap.py   (from the repo root)
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from symbol_remap import match, model  # noqa: E402

ASM = 'Assembly-CSharp'
_tok = [100663296]


def T(full, ordv, *members, base='Il2CppSystem.Object', kind='class', ns=''):
    """A type row plus its members. `full` is also the native name (obfuscated when lowercase <= 4 chars)."""
    rows = [f'T\t{ASM}\t{full}\t{full}\t\t{ASM}.dll|{ns}|{full}\t{ordv}\t{base}\t{kind}\t\t0\t0\t0\t']
    for i, (cat, native, sig) in enumerate(members):
        if cat == 'f':      # field wrapper property
            rows.append(f'P\t{ASM}\t{full}\tfield_{native}\tfld:{native}\t{i}\t\t{sig}\t')
        elif cat == 'm':    # method with a metadata token and a native name
            _tok[0] += 1
            rows.append(f'M\t{ASM}\t{full}\tMethod_{native}_{i}\ttok:{_tok[0]}:{native}\t{i}\t\t{sig}\t')
    return rows


def load(*types) -> model.Index:
    fd, path = tempfile.mkstemp(suffix='.tsv')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write('#port_index.v2\n')
        for rows in types:
            f.write('\n'.join(rows) + '\n')
    try:
        return model.load(path)
    finally:
        os.remove(path)


def body(n_int=0, n_str=0, extra=()):
    return [('f', f'x{i}q', 'System.Int32') for i in range(n_int)] + \
           [('f', f'y{i}q', 'System.String') for i in range(n_str)] + list(extra)


# Stable (real-name) anchors that bound every gap in the type tests.
A0 = lambda: T('Anchor0', 0, ('m', 'Start', 'System.Void()'))
A9 = lambda o=100: T('Anchor9', o, ('m', 'Finish', 'System.Void()'))


class WeightedLisTest(unittest.TestCase):
    def test_prefers_heavier_chain(self):
        # (0,0) (1,1) (2,2) light chain vs one heavy crossing pair (1,5)... chain must be strictly increasing
        pairs = [(0, 0, 1.0, 'a'), (1, 1, 1.0, 'b'), (2, 2, 1.0, 'c'), (3, 0, 5.0, 'x')]
        self.assertEqual(match.weighted_lis(pairs), {'x'})
        pairs[-1] = (3, 0, 1.0, 'x')
        self.assertEqual(match.weighted_lis(pairs), {'a', 'b', 'c'})

    def test_equal_x_never_both(self):
        chain = match.weighted_lis([(1, 1, 1.0, 'a'), (1, 2, 1.0, 'b')])
        self.assertEqual(len(chain), 1)

    def test_empty(self):
        self.assertEqual(match.weighted_lis([]), set())


class TypeAlignmentTest(unittest.TestCase):
    def run_tm(self, G, L):
        tm = match.TypeMatcher(G, L)
        tm.run()
        return tm

    def test_stable_and_exact(self):
        G = load(A0(), T('ab', 1, *body(2, 1)), A9())
        L = load(A0(), T('qz', 1, *body(2, 1)), A9())
        tm = self.run_tm(G, L)
        self.assertEqual(tm.matches['Anchor0'].method, 'stable_name')
        self.assertEqual(tm.matches['ab'].live, 'qz')
        self.assertEqual(tm.matches['ab'].method, 'exact')

    def test_gap_alignment_is_order_preserving(self):
        # every golden type changed slightly (one extra field live), so nothing is exact; the DP must keep order
        kinds = ('System.Int32', 'System.String', 'System.Single')
        own = lambda i: [('f', f'k{j}q', kinds[i]) for j in range(4)] + [('m', 'mmq', f'{kinds[i]}()')]
        g = [T(n, i + 1, *own(i)) for i, n in enumerate(('aa', 'ab', 'ac'))]
        l = [T(n, i + 1, *own(i), ('f', 'zzq', 'System.Boolean')) for i, n in enumerate(('ra', 'rb', 'rc'))]
        tm = self.run_tm(load(A0(), *g, A9()), load(A0(), *l, A9()))
        self.assertEqual({k: tm.matches[k].live for k in ('aa', 'ab', 'ac')}, {'aa': 'ra', 'ab': 'rb', 'ac': 'rc'})
        for k in ('aa', 'ab', 'ac'):
            self.assertEqual(tm.matches[k].method, 'aligned')
            self.assertTrue(0.6 <= tm.matches[k].confidence <= 0.97)

    def test_fuzzy_never_crosses_an_anchor(self):
        # golden 'ab' sits before the middle anchor; its only structural twin live sits after it
        mid = lambda o: T('Middle', o, ('m', 'Mid', 'System.Void()'))
        G = load(A0(), T('ab', 1, *body(4, 2)), mid(2), A9())
        L = load(A0(), mid(1), T('rb', 2, *body(4, 2, [('f', 'zzq', 'System.Boolean')])), A9())
        tm = self.run_tm(G, L)
        self.assertNotIn('ab', tm.matches)
        self.assertIn('ab', tm.unmapped)

    def test_twins_pair_by_order(self):
        g = [T(n, i + 1, *body(2, 2, [('f', 'uuq', 'System.Single')])) for i, n in enumerate(('aa', 'ab'))]
        l = [T(n, i + 1, *body(2, 2, [('f', 'uuq', 'System.Single'), ('f', 'vvq', 'System.Byte')]))
             for i, n in enumerate(('ra', 'rb'))]
        tm = self.run_tm(load(A0(), *g, A9()), load(A0(), *l, A9()))
        self.assertEqual(tm.matches['aa'].live, 'ra')
        self.assertEqual(tm.matches['ab'].live, 'rb')
        self.assertEqual(tm.matches['aa'].method, 'aligned_twin_order')
        self.assertEqual(tm.matches['aa'].confidence, 0.8)

    def test_ambiguity_is_unmapped_not_forced(self):
        # one golden type, two indistinguishable live candidates in the same gap
        G = load(A0(), T('aa', 1, *body(2, 2)), A9())
        L = load(A0(), T('ra', 1, *body(2, 2, [('f', 'zzq', 'System.Byte')])),
                 T('rb', 2, *body(2, 2, [('f', 'zzq', 'System.Byte')])), A9())
        tm = self.run_tm(G, L)
        self.assertNotIn('aa', tm.matches)
        self.assertTrue(tm.unmapped['aa'].reason.startswith('ambiguous'))
        self.assertEqual(len(tm.unmapped['aa'].candidates), 2)


class MemberMatchTest(unittest.TestCase):
    def members(self, gmembers, lmembers):
        G = load(T('Owner', 0, *gmembers))
        L = load(T('Owner', 0, *lmembers))
        ng = match.Normalizer(G, {}, set())
        nl = match.Normalizer(L, {}, set())
        res = match.match_members(G.types['Owner'].cores, L.types['Owner'].cores, ng, nl)
        return {c.native_name: r for c, r in ((r.golden, r) for r in res.values())}

    def test_real_name_and_unique_signature(self):
        r = self.members([('m', 'Update', 'System.Void()'), ('m', 'ab', 'System.Int32(System.String)')],
                         [('m', 'Update', 'System.Void()'), ('m', 'kq', 'System.Int32(System.String)')])
        self.assertEqual((r['Update'].live.native_name, r['Update'].method), ('Update', 'real_name'))
        self.assertEqual((r['ab'].live.native_name, r['ab'].method), ('kq', 'unique_signature'))

    def test_obfuscated_members_pair_by_name_rank_not_declaration(self):
        # same-signature twins; live declaration order is shuffled, but the obfuscator's name order is kept
        g = [('m', 'ac', 'System.Void(System.Int32)'), ('m', 'ab', 'System.Void(System.Int32)')]
        l = [('m', 'ze', 'System.Void(System.Int32)'), ('m', 'zd', 'System.Void(System.Int32)')]
        r = self.members(g, [l[1], l[0]])
        self.assertEqual(r['ab'].live.native_name, 'zd')
        self.assertEqual(r['ac'].live.native_name, 'ze')
        self.assertEqual(r['ab'].method, 'gap_name_order')

    def test_name_rank_orders_length_first(self):
        self.assertLess(match.obf_rank('z'), match.obf_rank('aa'))
        self.assertLess(match.obf_rank('az'), match.obf_rank('ba'))
        self.assertEqual(match.order_key(load(T('O', 0, ('f', '<ab>k__BackingField', 'System.Int32')))
                                         .types['O'].cores[0]), ('A', match.obf_rank('ab')))

    def test_gap_is_bounded_by_anchors(self):
        # anchors 'ab'<->'pa' and 'ae'<->'pz' (unique signatures); inside, two int fields pair by order
        g = [('f', 'ab', 'System.String'), ('f', 'ac', 'System.Int32'), ('f', 'ad', 'System.Int32'),
             ('f', 'ae', 'System.Boolean')]
        l = [('f', 'pa', 'System.String'), ('f', 'pb', 'System.Int32'), ('f', 'pc', 'System.Int32'),
             ('f', 'pz', 'System.Boolean')]
        r = self.members(g, l)
        self.assertEqual([r[n].live.native_name for n in ('ab', 'ac', 'ad', 'ae')], ['pa', 'pb', 'pc', 'pz'])
        self.assertEqual(r['ac'].confidence, 0.85)

    def test_count_mismatch_in_gap_is_unmapped(self):
        g = [('m', 'ab', 'System.Int32()'), ('m', 'ac', 'System.Int32()')]
        l = [('m', 'pa', 'System.Int32()'), ('m', 'pb', 'System.Int32()'), ('m', 'pc', 'System.Int32()')]
        r = self.members(g, l)
        for n in ('ab', 'ac'):
            self.assertIsNone(r[n].live)
            self.assertTrue(r[n].reason.startswith('ambiguous'))
            self.assertEqual(len(r[n].candidates), 3)

    def test_removed_member_is_unmapped_with_reason(self):
        r = self.members([('m', 'ab', 'System.Int32(System.Single)')], [('m', 'pa', 'System.Void()')])
        self.assertIsNone(r['ab'].live)
        self.assertIn('no same-signature member', r['ab'].reason)


if __name__ == '__main__':
    unittest.main()
