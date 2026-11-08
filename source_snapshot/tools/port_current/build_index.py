#!/usr/bin/env python3
"""Offline interop generation + port index for one game install (read-only on the install).

Commands
  generate   Cpp2IL + Il2CppInterop (BepInEx be.755 settings) from a game root into --out, then index it.
  index      Index an existing interop directory (for example an installed BepInEx/interop) into --out.
  calibrate  Compare two port indexes row by row; exit 1 on any difference.

Every path is explicit. The game roots are only read: --out must not be inside a game root (any ancestor
holding GameAssembly.dll), and generate re-hashes its game inputs afterwards to prove they did not change.
See docs/port_to_current_game_version.md, "Phase 1 status".
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOL_DIR = Path(__file__).resolve().parent
PROJECT = TOOL_DIR / 'PortInterop' / 'PortInterop.csproj'
DATA_DIR_NAME = 'HeroesOldenEra_Data'


class Refusal(SystemExit):
    def __init__(self, msg: str):
        super().__init__('build_index: REFUSED: ' + msg)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest().upper()


def game_root_of(path: Path) -> Path | None:
    """The nearest ancestor (or self) that looks like a game install."""
    p = path.resolve()
    for q in [p, *p.parents]:
        if (q / 'GameAssembly.dll').exists() or (q / DATA_DIR_NAME).exists():
            return q
    return None


def require_out_outside_game(out: Path, *roots: Path) -> None:
    out_r = out.resolve()
    for root in roots:
        r = root.resolve()
        if out_r == r or r in out_r.parents:
            raise Refusal(f'--out {out} is inside game root {root}')
    gr = game_root_of(out_r)
    if gr is not None:
        raise Refusal(f'--out {out} is inside a game install ({gr})')


def unity_version(game_root: Path) -> str:
    ggm = game_root / DATA_DIR_NAME / 'globalgamemanagers'
    if not ggm.exists():
        raise Refusal(f'cannot detect Unity version: {ggm} missing (pass --unity-version)')
    head = ggm.read_bytes()[:256]
    m = re.search(rb'(\d{4,}\.\d+\.\d+)[abfp]\d+', head)
    if not m:
        raise Refusal(f'cannot detect Unity version from {ggm} header (pass --unity-version)')
    return m.group(1).decode()


def steam_build_id(game_root: Path) -> str | None:
    """buildid from the Steam appmanifest whose installdir is this root; None for frozen copies."""
    steamapps = game_root.parent.parent
    for acf in steamapps.glob('appmanifest_*.acf'):
        txt = acf.read_text(encoding='utf-8', errors='replace')
        inst = re.search(r'"installdir"\s+"([^"]+)"', txt)
        bid = re.search(r'"buildid"\s+"(\d+)"', txt)
        if inst and bid and inst.group(1).lower() == game_root.name.lower():
            return bid.group(1)
    return None


def build_tool(bepinex_core: Path, bin_dir: Path) -> Path:
    if not (bepinex_core / 'Il2CppInterop.Generator.dll').exists():
        raise Refusal(f'{bepinex_core} is not a BepInEx core dir')
    cmd = ['dotnet', 'build', str(PROJECT), '-c', 'Release', '-o', str(bin_dir), '-nologo', '-v', 'q',
           f'-p:BepInExCore={bepinex_core}{os.sep}']
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise Refusal('PortInterop build failed:\n' + r.stdout[-4000:] + r.stderr[-2000:])
    return bin_dir / 'PortInterop.dll'


def run_tool(dll: Path, args: list[str], log: Path, cwd: Path) -> None:
    with open(log, 'w', encoding='utf-8') as lf:
        r = subprocess.run(['dotnet', str(dll), *args], stdout=lf, stderr=subprocess.STDOUT, cwd=cwd)
    if r.returncode != 0:
        raise Refusal(f'PortInterop {args[0]} failed (exit {r.returncode}); see {log}')


def cmd_generate(a) -> None:
    root = Path(a.game_root).resolve()
    out = Path(a.out).resolve()
    ga = root / 'GameAssembly.dll'
    md = Path(a.metadata).resolve() if a.metadata else root / DATA_DIR_NAME / 'il2cpp_data' / 'Metadata' / 'global-metadata.dat'
    for f in (ga, md):
        if not f.is_file():
            raise Refusal(f'missing game input {f}')
    bep = Path(a.bepinex_root).resolve()
    libs = bep / 'unity-libs'
    require_out_outside_game(out, root)
    if out.exists() and any(out.iterdir()):
        raise Refusal(f'--out {out} is not empty')
    uv = a.unity_version or unity_version(root)
    if not (libs / f'{uv}.zip').exists():
        raise Refusal(f'{libs} has no {uv}.zip; unity-libs must match the game Unity version')
    out.mkdir(parents=True, exist_ok=True)
    before = {str(ga): sha256(ga), str(md): sha256(md)}
    dll = build_tool(bep / 'core', out.parent / 'bin' / 'PortInterop')
    gen_dir = out / 'gen'
    run_tool(dll, ['generate', '--game-assembly', str(ga), '--metadata', str(md), '--unity-version', uv,
                   '--unity-libs', str(libs), '--out', str(gen_dir)], out / 'generate.log', cwd=out)
    run_tool(dll, ['index', '--interop', str(gen_dir / 'interop'), '--out', str(out / 'port_index.tsv'),
                   '--native-methods', str(gen_dir / 'native_methods.tsv')], out / 'index.log', cwd=out)
    after = {str(ga): sha256(ga), str(md): sha256(md)}
    if before != after:
        raise Refusal('game inputs changed during generation: ' + json.dumps({'before': before, 'after': after}))
    manifest = {
        'schema': 'port_index_inputs.v1',
        'label': a.label,
        'gameRoot': str(root),
        'gameAssembly': str(ga), 'gameAssemblySha256': before[str(ga)],
        'metadata': str(md), 'metadataSha256': before[str(md)],
        'steamBuildId': steam_build_id(root),
        'unityVersion': uv,
        'bepinexCore': str(bep / 'core'),
        'deobfuscationRegex': '^[a-z]{2}$|^[a-z]{3}$|^[a-c][a-z]{3}$',
        'index': str(out / 'port_index.tsv'),
    }
    (out / 'inputs.json').write_text(json.dumps(manifest, indent=1), encoding='utf-8')
    print(json.dumps(manifest, indent=1))


def cmd_index(a) -> None:
    interop = Path(a.interop).resolve()
    out = Path(a.out).resolve()
    require_out_outside_game(out)
    if out.exists():
        raise Refusal(f'{out} exists')
    out.parent.mkdir(parents=True, exist_ok=True)
    dll = build_tool(Path(a.bepinex_root) / 'core', out.parent / 'bin' / 'PortInterop')
    args = ['index', '--interop', str(interop), '--out', str(out)]
    if a.native_methods:
        args += ['--native-methods', str(Path(a.native_methods).resolve())]
    run_tool(dll, args, out.with_suffix('.log'), cwd=out.parent)
    print(out)


def cmd_calibrate(a) -> None:
    """Row-level identity of two indexes. Native method names (tok:N:name) are compared by token only,
    because an installed interop has no Cpp2IL side table."""
    def rows(p):
        out = []
        for line in open(p, encoding='utf-8'):
            if line.startswith('#'):
                continue
            f = line.rstrip('\n').split('\t')
            if f[0] in 'MFP' and f[4].startswith('tok:'):
                f[4] = ':'.join(f[4].split(':')[:2])
            out.append('\t'.join(f))
        return out
    x, y = rows(a.left), rows(a.right)
    diff = sum(1 for p, q in zip(x, y) if p != q) + abs(len(x) - len(y))
    report = {'left': a.left, 'right': a.right, 'rowsLeft': len(x), 'rowsRight': len(y), 'differingRows': diff,
              'identical': diff == 0}
    print(json.dumps(report, indent=1))
    if diff:
        for p, q in zip(x, y):
            if p != q:
                print('first diff:\n  ' + p + '\n  ' + q)
                break
        sys.exit(1)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    g = sub.add_parser('generate')
    g.add_argument('--game-root', required=True)
    g.add_argument('--out', required=True)
    g.add_argument('--bepinex-root', required=True, help='BepInEx be.755 dir providing core/ and unity-libs/ (read only)')
    g.add_argument('--label', required=True)
    g.add_argument('--metadata', help='override global-metadata.dat (e.g. a stock backup); read only')
    g.add_argument('--unity-version')
    i = sub.add_parser('index')
    i.add_argument('--interop', required=True)
    i.add_argument('--out', required=True)
    i.add_argument('--bepinex-root', required=True)
    i.add_argument('--native-methods')
    c = sub.add_parser('calibrate')
    c.add_argument('left')
    c.add_argument('right')
    a = ap.parse_args(argv)
    {'generate': cmd_generate, 'index': cmd_index, 'calibrate': cmd_calibrate}[a.cmd](a)


if __name__ == '__main__':
    main()
