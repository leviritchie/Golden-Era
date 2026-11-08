"""Shared headless Ghidra project for one Olden Era build (docs/ghidra_oe.md).

  setup   copy-free: imports the pinned GameAssembly.dll with -noanalysis and labels it (ImportOeSymbols.java)
  query   read-only decomp / callers / callees / find against the labelled program (OeQuery.java)

Targets are absolute VAs (0x18...) or symbol names, e.g. `Hex.Session.Battle.BhBattleEnd$$bhlq` or the interop
alias `Hex.Session.Battle.BhBattleEnd$$Method_Public_Void_PDM_0`; a trailing * matches a prefix.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BUILD = '25672315'
WORK = Path(r'V:\olden_port_work\ghidra')
GHIDRA = Path(r'V:\Tools\ghidra\ghidra_12.1.4_PUBLIC')
JDK = Path(r'V:\Tools\jdk\jdk-21.0.12.1+1')
INDEX = REPO / 'artifacts' / 'port_current' / f'idx2_live_{BUILD}'
GA_SHA = 'D9972B0E7F7DD1C17758808E2F1B80E0A728946416D9A41DEAA99BAD744DE53A'
PROJECT = f'OE_{BUILD}'
PROGRAM = 'GameAssembly.dll'


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest().upper()


def headless(args: list[str], maxmem: str) -> int:
    env = dict(os.environ, JAVA_HOME=str(JDK), GHIDRA_HEADLESS_MAXMEM=maxmem)
    cmd = [str(GHIDRA / 'support' / 'analyzeHeadless.bat'), str(WORK / 'project'), PROJECT, *args]
    return subprocess.call(cmd, env=env)


def setup(a) -> int:
    ga = WORK / f'inputs_{BUILD}' / PROGRAM
    if sha256_file(ga) != GA_SHA:
        sys.exit(f'{ga}: sha256 is not the pinned {GA_SHA}')
    if (WORK / 'project' / f'{PROJECT}.rep').exists() and not a.force:
        sys.exit(f'project {PROJECT} already exists under {WORK / "project"}; pass --force to re-import')
    labels = WORK / f'labels_{BUILD}.tsv'
    rc = subprocess.call([sys.executable, str(HERE / 'make_labels.py'),
                          '--native', str(INDEX / 'gen' / 'native_addresses.tsv'), '--index', str(INDEX / 'port_index.tsv'),
                          '--game-assembly', str(ga), '--out', str(labels)])
    if rc:
        return rc
    (WORK / 'project').mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with project_turn(a.wait):
        rc = headless(['-import', str(ga), '-noanalysis', '-overwrite', '-scriptPath', str(HERE / 'scripts'),
                       '-postScript', 'ImportOeSymbols.java', str(labels), '-log', str(WORK / 'setup.log')], a.maxmem)
    print(f'setup exit {rc} in {time.time() - t0:.0f}s; log {WORK / "setup.log"}')
    return rc


@contextmanager
def project_turn(wait_s: int):
    """Ghidra locks a project per process, so queries and setup take turns on one OS file lock (blocking wait in
    10 s slices up to `wait_s`, then fail with a diagnostic instead of hitting Ghidra's LockException)."""
    import msvcrt
    WORK.mkdir(parents=True, exist_ok=True)
    f = open(WORK / 'project.turn.lock', 'a+b')
    deadline = time.time() + wait_s
    while True:
        try:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)    # blocks up to ~10 s per call
            break
        except OSError:
            if time.time() >= deadline:
                f.close()
                sys.exit(f'another Ghidra query/setup held the project for {wait_s}s; retry later or raise --wait')
    try:
        yield
    finally:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        f.close()


def query(a) -> int:
    out = Path(a.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text('', encoding='utf-8')
    with project_turn(a.wait):
        rc = headless(['-process', PROGRAM, '-readOnly', '-noanalysis', '-scriptPath', str(HERE / 'scripts'),
                       '-postScript', 'OeQuery.java', str(out), a.cmd, *a.targets], a.maxmem)
    text = out.read_text(encoding='utf-8', errors='replace')
    if rc == 0 and not text.rstrip().endswith('// OeQuery done'):
        print(f'query failed: OeQuery did not finish (analyzeHeadless exits 0 on script errors); see console output', file=sys.stderr)
        rc = 2
    if not a.quiet:
        sys.stdout.write(text)
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest='op', required=True)
    s = sub.add_parser('setup')
    s.add_argument('--force', action='store_true')
    s.add_argument('--maxmem', default='12G')
    s.add_argument('--wait', type=int, default=1800)
    s.set_defaults(fn=setup)
    q = sub.add_parser('query')
    q.add_argument('cmd', choices=['decomp', 'callers', 'callees', 'find'])
    q.add_argument('targets', nargs='+')
    q.add_argument('--out', default=str(WORK / 'queries' / f'q_{os.getpid()}.txt'))
    q.add_argument('--maxmem', default='6G')
    q.add_argument('--quiet', action='store_true')
    q.add_argument('--wait', type=int, default=900, help='seconds to wait for the project turn')
    q.set_defaults(fn=query)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == '__main__':
    raise SystemExit(main())
