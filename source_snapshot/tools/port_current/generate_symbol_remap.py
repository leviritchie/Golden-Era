#!/usr/bin/env python3
"""Generate game_symbols_remap_<buildid>.json from two port indexes (see docs/port_to_current_game_version.md).

  python tools/port_current/generate_symbol_remap.py \
      --golden artifacts/port_current/idx2_golden --live artifacts/port_current/idx2_live \
      --plugin-dir "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod" \
      --out tools/port_current/remap --artifacts artifacts/port_current/remap [--validate]

  python tools/port_current/generate_symbol_remap.py --check tools/port_current/remap/game_symbols_remap_<buildid>.json \n      --plugin-dir "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod"

--check prints STALE and exits 1, with the changed files, when a harvested plugin file
no longer has the sha256 recorded in the remap's `sources`, else FRESH (exit 0). Regenerate on STALE. It is deliberately
not wired into the build, because GameSymbols.cs changes constantly.

--golden/--live are `build_index.py generate` output dirs (inputs.json + port_index.tsv). Fails closed on a
missing or inconsistent input, a live build without a Steam build id, or a non-injective type map.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from symbol_remap import model, native_body, remap, validate  # noqa: E402


def load_side(d: Path, label: str):
    inp = d / 'inputs.json'
    idx = d / 'port_index.tsv'
    if not inp.is_file() or not idx.is_file():
        sys.exit(f'generate_symbol_remap: REFUSED: {d} lacks inputs.json/port_index.tsv (run build_index.py generate)')
    meta = json.loads(inp.read_text(encoding='utf-8'))
    if meta.get('schema') != 'port_index_inputs.v1':
        sys.exit(f'generate_symbol_remap: REFUSED: {inp} has schema {meta.get("schema")!r}')
    return model.load(str(idx)), {
        'label': meta['label'], 'steamBuildId': meta.get('steamBuildId'),
        'gameAssemblySha256': meta['gameAssemblySha256'], 'metadataSha256': meta['metadataSha256'],
        'unityVersion': meta['unityVersion'], 'portIndexSha256': remap.sha256(idx)}


def check(remap_path: Path, plugin: Path) -> int:
    doc = json.loads(remap_path.read_text(encoding='utf-8'))
    recorded = doc.get('sources', {})
    changed = []
    for f in remap.RESOLVER_FILES:
        cur = remap.sha256(plugin / f) if (plugin / f).is_file() else 'missing'
        if recorded.get(f) != cur:
            changed.append(f)
    if changed:
        print(f'STALE {remap_path}: changed since generation: {", ".join(changed)}')
        return 1
    else:
        print(f'FRESH {remap_path}')
    return 0


def load_native(gdir: Path, ldir: Path, gga: str | None, lga: str | None, G, L):
    sides = []
    meta = {}
    for d, ga, label in ((gdir, gga, 'golden'), (ldir, lga, 'live')):
        inp = json.loads((d / 'inputs.json').read_text(encoding='utf-8'))
        tsv = d / 'gen' / 'native_addresses.tsv'
        if not tsv.is_file():
            sys.exit(f'generate_symbol_remap: REFUSED: --native needs {tsv} (PortInterop native-addresses)')
        try:
            sides.append(native_body.NativeSide(tsv, Path(ga or inp['gameAssembly']), inp['gameAssemblySha256'],
                                                inp['metadataSha256']))
        except ValueError as e:
            sys.exit(f'generate_symbol_remap: REFUSED: {e}')
        meta[label + 'NativeAddressesSha256'] = remap.sha256(tsv)
    body = native_body.BodyEvidence(*sides)
    meta |= {'minScore': body.min_score, 'minMargin': body.min_margin, 'confidence': native_body.NATIVE_CONF,
             'weights': native_body.WEIGHTS}
    cal = native_body.calibrate(G, L, native_body.BodyEvidence(*sides), max_groups=100000)
    meta['calibration'] = cal
    print('native body calibration:', {k: cal[k] for k in ('groups', 'accepted', 'correct', 'wrong', 'precision', 'recall')})
    return body, meta


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--check', metavar='REMAP_JSON', help='only report STALE/FRESH against --plugin-dir')
    ap.add_argument('--golden')
    ap.add_argument('--live')
    ap.add_argument('--plugin-dir', required=True)
    ap.add_argument('--out', help='directory for the tracked remap + validation JSON')
    ap.add_argument('--artifacts', help='directory for the large full type map (gitignored)')
    ap.add_argument('--validate', action='store_true', help='also run the hidden-name validation trials')
    ap.add_argument('--native', action='store_true',
                    help='use native-body evidence for ambiguous same-signature member gaps (needs '
                         '<side>/gen/native_addresses.tsv from PortInterop native-addresses)')
    ap.add_argument('--golden-game-assembly', help='GameAssembly.dll for --native (default: golden inputs.json path)')
    ap.add_argument('--live-game-assembly', help='GameAssembly.dll for --native (e.g. the frozen mirror; sha256 must '
                         'equal the live inputs)')
    ap.add_argument('--cross-check-sample', type=int, default=3000,
                    help='owners sampled by the informational native-body order cross-check (recorded as '
                         'nativeBody.orderCrossCheck.sampleOwners; does not change any mapping). Lower it when RAM '
                         'is short: the check accounts for most of the --native run time and memory')
    a = ap.parse_args(argv)
    if a.check:
        return check(Path(a.check), Path(a.plugin_dir))
    missing = [n for n in ('golden', 'live', 'out', 'artifacts') if not getattr(a, n)]
    if missing:
        ap.error('generation needs ' + ', '.join('--' + n for n in missing))

    G, gmeta = load_side(Path(a.golden), 'golden')
    L, lmeta = load_side(Path(a.live), 'live')
    if not lmeta['steamBuildId']:
        sys.exit('generate_symbol_remap: REFUSED: live inputs carry no Steam build id')
    if gmeta['gameAssemblySha256'] == lmeta['gameAssemblySha256']:
        sys.exit('generate_symbol_remap: REFUSED: golden and live are the same GameAssembly.dll')
    plugin = Path(a.plugin_dir)
    for f in remap.RESOLVER_FILES:
        if not (plugin / f).is_file():
            sys.exit(f'generate_symbol_remap: REFUSED: {plugin / f} missing')
    groups, sources = remap.harvest(plugin, remap.RESOLVER_FILES)
    body, native_meta = None, None
    if a.native:
        body, native_meta = load_native(Path(a.golden), Path(a.live), a.golden_game_assembly, a.live_game_assembly, G, L)
    doc, tm = remap.build(G, L, groups, sources, {'source': gmeta, 'target': lmeta}, body, native_meta,
                         cross_check_sample=a.cross_check_sample)
    lives = [m.live for m in tm.matches.values()]
    if len(lives) != len(set(lives)):
        sys.exit('generate_symbol_remap: REFUSED: type map is not injective')

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    bid = lmeta['steamBuildId']
    p = out / f'game_symbols_remap_{bid}.json'
    p.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
    art = Path(a.artifacts)
    art.mkdir(parents=True, exist_ok=True)
    (art / f'type_map_{bid}.json').write_text(json.dumps(remap.type_map(tm, G, L), indent=1), encoding='utf-8')
    print(json.dumps(doc['summary'], indent=1))
    print('wrote', p)

    if a.validate:
        trials = []
        for frac in (0.25, 0.5, 1.0):
            for seed in (1, 2, 3):
                r = validate.run_trial(G, L, frac, seed)
                r.pop('member_error_samples', None)
                trials.append(r)
                print(frac, seed, r['types'], r['members'])
        vp = out / f'matcher_validation_{bid}.json'
        vp.write_text(json.dumps({'schema': 'matcher_validation.v1', 'source': gmeta, 'target': lmeta,
                                  'trials': trials}, indent=1) + '\n', encoding='utf-8', newline='\n')
        print('wrote', vp)


if __name__ == '__main__':
    sys.exit(main())
